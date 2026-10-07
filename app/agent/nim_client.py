"""OpenAI-compatible chat completions client for NIM (urllib only).

Configuration (environment):
- NVIDIA_API_KEY  required unless NIM_API_KEY_ENV names VLLM_API_KEY. Sent as-is in the Bearer header. Inside the sandbox this is a placeholder that the
                  egress proxy replaces with the real key, so the code never needs (or sees) the real value.
- NIM_API_KEY_ENV optional. Which variable holds the key: NVIDIA_API_KEY (default) or VLLM_API_KEY (the team's
                  self-hosted vLLM). Any other name is a ConfigError. The value is still a sandbox placeholder.
- NIM_BASE_URL    default https://integrate.api.nvidia.com/v1
- NIM_MODEL       default nvidia/nemotron-3-super-120b-a12b

Behaviour:
- Authorization is an unredirected header and redirects are not followed (a 3xx is an error, not retried).
- Retries only HTTP 5xx and 429: at most 3 resends per request, waiting 5, 10, 20 s. With Retry-After (seconds),
  the wait is max(backoff, min(Retry-After, 60)). Connection errors and timeouts are not retried.
- Per-request timeout 60 s.
- Error messages carry the HTTP status or exception type only: never the key or the response body.
- `transport(req, timeout) -> (status, headers, body_bytes)` and `sleep(seconds)` are injectable for tests.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from agent.errors import ConfigError, ModelCallError

API_KEY_ENV = "NVIDIA_API_KEY"
API_KEY_ENV_NAME_ENV = "NIM_API_KEY_ENV"  # names the key variable; default API_KEY_ENV
# Only model keys may be named: never another provider's placeholder (e.g. GITHUB_TOKEN) in a model request.
ALLOWED_KEY_ENVS = ("NVIDIA_API_KEY", "VLLM_API_KEY")
# A named client. Cloudflare-fronted endpoints (the team's Brev vLLM tunnel) reject the default urllib agent
# with error 1010 (browser signature check); measured 2026-10-07.
USER_AGENT = "kculture-agent/1.0"
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
TIMEOUT_S = 60
RETRY_WAITS = (5, 10, 20)
RETRY_AFTER_CAP_S = 60
DEFAULT_PARAMS = {
    "temperature": 0.2,
    "top_p": 0.95,
    "max_tokens": 2048,
    "chat_template_kwargs": {"enable_thinking": False},
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect; urllib then raises HTTPError with the 3xx status."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Default ProxyHandler stays in (inside the sandbox the proxy is what injects the real key).
_OPENER = urllib.request.build_opener(_NoRedirect)


def default_transport(req: urllib.request.Request, timeout: float):
    """Send `req`; return (status, headers, body). HTTP error bodies are dropped, never surfaced."""
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        headers = e.headers
        e.close()
        return e.code, headers, b""


def _header(headers, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is not None:
        v = getter(name)
        if v is not None:
            return v
    try:
        items = headers.items()
    except AttributeError:
        return None
    for k, v in items:
        if str(k).lower() == name.lower():
            return v
    return None


def _retry_after_seconds(headers) -> float | None:
    """Retry-After as a number of seconds; HTTP-date and malformed values are ignored."""
    raw = _header(headers, "Retry-After")
    if raw is None:
        return None
    try:
        v = float(str(raw).strip())
    except ValueError:
        return None
    if v != v or v < 0:  # NaN or negative
        return None
    return v


@dataclass
class ChatResult:
    text: str
    model: str
    finish_reason: str | None
    attempts: int


class NimClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        *,
        transport=None,
        sleep=None,
        timeout: float = TIMEOUT_S,
        waits: tuple = RETRY_WAITS,
    ):
        base_url = (base_url or "").strip().rstrip("/")
        if urllib.parse.urlparse(base_url).scheme not in ("http", "https"):
            raise ConfigError(f"NIM_BASE_URL은 http(s) 주소여야 합니다: {base_url!r}")
        if not model or not model.strip():
            raise ConfigError("NIM_MODEL이 비어 있습니다")
        if not api_key or not api_key.strip():
            raise ConfigError(f"환경변수 {API_KEY_ENV}가 없거나 비어 있습니다")
        self.base_url = base_url
        self.model = model.strip()
        self._api_key = api_key.strip()
        self.transport = transport or default_transport
        self.sleep = sleep or time.sleep
        self.timeout = timeout
        self.waits = tuple(waits)
        self.http_attempts = 0  # cumulative over the client's life (includes retries)

    def __repr__(self) -> str:
        return f"NimClient(base_url={self.base_url!r}, model={self.model!r})"

    @classmethod
    def from_env(cls, *, transport=None, sleep=None) -> "NimClient":
        key_env = (os.environ.get(API_KEY_ENV_NAME_ENV) or API_KEY_ENV).strip()
        if key_env not in ALLOWED_KEY_ENVS:
            raise ConfigError(f"{API_KEY_ENV_NAME_ENV}는 {', '.join(ALLOWED_KEY_ENVS)} 가운데 하나여야 합니다")
        key = os.environ.get(key_env, "")
        if not key.strip():
            raise ConfigError(f"환경변수 {key_env}가 없거나 비어 있습니다(키 래퍼 아래에서 실행하세요)")
        base = os.environ.get("NIM_BASE_URL") or DEFAULT_BASE_URL
        model = os.environ.get("NIM_MODEL") or DEFAULT_MODEL
        return cls(base, model, key, transport=transport, sleep=sleep)

    def build_body(self, messages: list[dict], response_format: dict | None = None) -> dict:
        body = {"model": self.model, "messages": messages, **DEFAULT_PARAMS}
        body["chat_template_kwargs"] = dict(DEFAULT_PARAMS["chat_template_kwargs"])
        if response_format is not None:
            body["response_format"] = response_format
        return body

    def _request(self, data: bytes) -> urllib.request.Request:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        # Not forwarded if a redirect ever were followed.
        req.add_unredirected_header("Authorization", f"Bearer {self._api_key}")
        return req

    def _wait_for(self, attempt_index: int, headers) -> float:
        backoff = self.waits[attempt_index]
        ra = _retry_after_seconds(headers)
        if ra is None:
            return backoff
        return max(backoff, min(ra, RETRY_AFTER_CAP_S))

    def chat(self, messages: list[dict], response_format: dict | None = None) -> ChatResult:
        data = json.dumps(self.build_body(messages, response_format), ensure_ascii=False).encode("utf-8")
        attempts = 0
        while True:
            attempts += 1
            self.http_attempts += 1
            try:
                status, headers, raw = self.transport(self._request(data), self.timeout)
            except urllib.error.URLError as e:
                reason = getattr(e, "reason", e)
                raise ModelCallError(f"모델 서버에 연결하지 못했습니다: {type(reason).__name__}") from None
            except (TimeoutError, OSError) as e:
                raise ModelCallError(f"모델 요청이 실패했습니다: {type(e).__name__}") from None

            if status == 200:
                return self._parse(raw, attempts)
            retryable = status == 429 or 500 <= status <= 599
            if retryable and attempts <= len(self.waits):
                self.sleep(self._wait_for(attempts - 1, headers))
                continue
            suffix = f" ({attempts}회 시도)" if retryable else ""
            raise ModelCallError(f"모델 요청 실패: HTTP {status}{suffix}")

    def _parse(self, raw: bytes, attempts: int) -> ChatResult:
        try:
            payload = json.loads(raw.decode("utf-8"))
            choice = payload["choices"][0]
            content = (choice.get("message") or {}).get("content")
        except (ValueError, UnicodeDecodeError, KeyError, IndexError, TypeError, AttributeError):
            raise ModelCallError("모델 응답 형식을 읽지 못했습니다(choices[0].message 없음)") from None
        model = payload.get("model") if isinstance(payload.get("model"), str) else self.model
        return ChatResult(
            text=content if isinstance(content, str) else "",
            model=model or self.model,
            finish_reason=choice.get("finish_reason"),
            attempts=attempts,
        )
