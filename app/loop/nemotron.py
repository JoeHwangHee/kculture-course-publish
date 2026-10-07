"""Nemotron chat for the loop: the existing NimClient (unchanged) plus a counting transport that reads usage.

NimClient's ChatResult has no usage, so the transport wraps the HTTP layer and keeps the `usage` of the last 200
response (resent failures are not counted). NimClient errors (ConfigError, ModelCallError) propagate unchanged.
A client passed in has its `transport` replaced by the counting transport (which wraps the old one).
"""

from __future__ import annotations

import json
import time

from agent.nim_client import NimClient, default_transport


DEFAULT_MAX_TOKENS = 2048  # (조정값) NimClient default, left as is for every other purpose
ORGANIZE_NAMES_MAX_TOKENS = 6144  # (조정값) 0025: organize_names answers were cut at 2048
ORGANIZE_NAMES_PURPOSE = "organize_names"


def max_tokens_for(purpose) -> int | None:
    """Body max_tokens override for a purpose (None = keep NimClient's). Matches loosely: the real tools' purpose
    string may only contain "organize_names"."""
    if isinstance(purpose, str) and ORGANIZE_NAMES_PURPOSE in purpose:
        return ORGANIZE_NAMES_MAX_TOKENS
    return None


def _set_max_tokens(req, max_tokens: int) -> None:
    try:
        body = json.loads(req.data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        return
    if isinstance(body, dict):
        body["max_tokens"] = max_tokens
        req.data = json.dumps(body, ensure_ascii=False).encode("utf-8")  # urllib recomputes Content-Length


def _read_usage(raw: bytes) -> dict | None:
    try:
        usage = json.loads(raw.decode("utf-8")).get("usage")
        i, o = usage.get("prompt_tokens"), usage.get("completion_tokens")
    except (ValueError, UnicodeDecodeError, AttributeError, TypeError):
        return None
    if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (i, o)):
        return {"input": i, "output": o}
    return None


class NemotronChat:
    def __init__(self, client=None, *, transport=None, sleep=None, clock=time.monotonic):
        self._clock = clock
        self._last_usage: dict | None = None
        self._max_tokens: int | None = None
        if client is None:
            self._inner = transport or default_transport
            self.client = NimClient.from_env(transport=self._counting, sleep=sleep)
        else:
            # Wrap the given client's transport too, so usage is counted on this path as well.
            self._inner = transport or client.transport
            client.transport = self._counting
            self.client = client

    def __repr__(self) -> str:
        return f"NemotronChat({self.client!r})"

    def _counting(self, req, timeout):
        if self._max_tokens is not None:
            _set_max_tokens(req, self._max_tokens)
        status, headers, raw = self._inner(req, timeout)
        if status == 200:
            self._last_usage = _read_usage(raw)
        return status, headers, raw

    def __call__(self, messages: list[dict], purpose: str, response_format: dict | None = None) -> dict:
        """One logical call -> {"text", "usage", "model", "latency_ms", "finish_reason"}. `purpose` picks the
        max_tokens override (max_tokens_for) and goes to the records."""
        self._last_usage = None
        self._max_tokens = max_tokens_for(purpose)
        started = self._clock()
        try:
            result = self.client.chat(messages, response_format=response_format)
        finally:
            self._max_tokens = None
        return {
            "text": result.text,
            "usage": self._last_usage,
            "model": result.model,
            "latency_ms": float((self._clock() - started) * 1000),
            "finish_reason": result.finish_reason,  # "length" = cut at max_tokens
        }
