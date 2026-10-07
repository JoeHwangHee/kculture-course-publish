import json
import urllib.error
import urllib.request

import pytest

from agent.errors import ConfigError, ModelCallError
from agent.nim_client import DEFAULT_BASE_URL, DEFAULT_MODEL, NimClient

FAKE_KEY = "test-placeholder-key-0123456789"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access in tests")

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _blocked)


def ok_body(content="{}", model="nvidia/test-model"):
    return json.dumps({"model": model, "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode()


class FakeTransport:
    """Returns queued (status, headers, body) tuples and records each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append((req, timeout))
        return self.responses.pop(0)


def make_client(responses):
    sleeps = []
    t = FakeTransport(responses)
    c = NimClient("http://nim.test/v1", "nvidia/test-model", FAKE_KEY, transport=t, sleep=sleeps.append)
    return c, t, sleeps


def test_request_body_shape():
    c, t, _ = make_client([(200, {}, ok_body())])
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    res = c.chat(msgs, response_format={"type": "json_object"})
    assert res.text == "{}"
    req, timeout = t.requests[0]
    assert req.full_url == "http://nim.test/v1/chat/completions"
    assert req.get_method() == "POST"
    assert timeout == 60
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "nvidia/test-model"
    assert body["messages"] == msgs
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.95
    assert body["max_tokens"] == 2048
    assert body["response_format"] == {"type": "json_object"}
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "tools" not in body
    assert body.get("stream") in (None, False)


def test_authorization_header_is_unredirected():
    c, t, _ = make_client([(200, {}, ok_body())])
    c.chat([{"role": "user", "content": "u"}])
    req, _ = t.requests[0]
    assert req.unredirected_hdrs.get("Authorization") == f"Bearer {FAKE_KEY}"
    assert "Authorization" not in req.headers


def test_retry_5xx_twice_then_success():
    c, t, sleeps = make_client([(500, {}, b""), (503, {}, b""), (200, {}, ok_body("hi"))])
    res = c.chat([{"role": "user", "content": "u"}])
    assert res.text == "hi"
    assert sleeps == [5, 10]
    assert len(t.requests) == 3
    assert res.attempts == 3
    assert c.http_attempts == 3


def test_retry_gives_up_after_three_resends():
    c, t, sleeps = make_client([(502, {}, b"")] * 4)
    with pytest.raises(ModelCallError) as ei:
        c.chat([{"role": "user", "content": "u"}])
    assert sleeps == [5, 10, 20]
    assert len(t.requests) == 4
    assert "502" in str(ei.value)
    assert FAKE_KEY not in str(ei.value)


@pytest.mark.parametrize(
    "retry_after,expected",
    [("30", 30), ("120", 60), ("2", 5), ("Wed, 21 Oct 2015 07:28:00 GMT", 5), ("abc", 5)],
)
def test_429_with_retry_after(retry_after, expected):
    c, t, sleeps = make_client([(429, {"retry-after": retry_after}, b""), (200, {}, ok_body())])
    c.chat([{"role": "user", "content": "u"}])
    assert sleeps == [expected]
    assert len(t.requests) == 2


def test_retry_after_on_later_attempt_uses_max_of_backoff():
    c, _, sleeps = make_client([(500, {}, b""), (429, {"Retry-After": "7"}, b""), (200, {}, ok_body())])
    c.chat([{"role": "user", "content": "u"}])
    assert sleeps == [5, 10]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 302])
def test_4xx_and_3xx_not_retried(status):
    c, t, sleeps = make_client([(status, {}, b"secret body " + FAKE_KEY.encode())])
    with pytest.raises(ModelCallError) as ei:
        c.chat([{"role": "user", "content": "u"}])
    assert sleeps == []
    assert len(t.requests) == 1
    msg = str(ei.value)
    assert str(status) in msg
    assert FAKE_KEY not in msg and "secret body" not in msg


def test_connection_error_not_retried_and_no_key_in_message():
    calls = []

    def transport(req, timeout):
        calls.append(req)
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    c = NimClient("http://nim.test/v1", "m", FAKE_KEY, transport=transport, sleep=lambda s: None)
    with pytest.raises(ModelCallError) as ei:
        c.chat([{"role": "user", "content": "u"}])
    assert len(calls) == 1
    assert FAKE_KEY not in str(ei.value)


def test_timeout_not_retried():
    calls = []

    def transport(req, timeout):
        calls.append(req)
        raise TimeoutError("timed out")

    c = NimClient("http://nim.test/v1", "m", FAKE_KEY, transport=transport, sleep=lambda s: None)
    with pytest.raises(ModelCallError):
        c.chat([{"role": "user", "content": "u"}])
    assert len(calls) == 1


def test_bad_json_response_is_model_call_error():
    c, _, _ = make_client([(200, {}, b"not json")])
    with pytest.raises(ModelCallError):
        c.chat([{"role": "user", "content": "u"}])


def test_empty_content_returns_empty_text():
    body = json.dumps({"model": "m", "choices": [{"message": {"content": None}, "finish_reason": "length"}]}).encode()
    c, _, _ = make_client([(200, {}, body)])
    res = c.chat([{"role": "user", "content": "u"}])
    assert res.text == ""
    assert res.finish_reason == "length"


def test_from_env_defaults(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    monkeypatch.delenv("NIM_BASE_URL", raising=False)
    monkeypatch.delenv("NIM_MODEL", raising=False)
    c = NimClient.from_env()
    assert c.base_url == DEFAULT_BASE_URL == "https://integrate.api.nvidia.com/v1"
    assert c.model == DEFAULT_MODEL == "nvidia/nemotron-3-super-120b-a12b"
    assert FAKE_KEY not in repr(c)


def test_from_env_overrides(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    monkeypatch.setenv("NIM_BASE_URL", "http://proxy.test/v1/")
    monkeypatch.setenv("NIM_MODEL", "nvidia/other")
    c = NimClient.from_env()
    assert c.base_url == "http://proxy.test/v1"
    assert c.model == "nvidia/other"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_from_env_missing_key_is_config_error(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    else:
        monkeypatch.setenv("NVIDIA_API_KEY", value)
    with pytest.raises(ConfigError) as ei:
        NimClient.from_env()
    assert "NVIDIA_API_KEY" in str(ei.value)


def test_bad_base_url_is_config_error(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    monkeypatch.setenv("NIM_BASE_URL", "file:///etc")
    with pytest.raises(ConfigError):
        NimClient.from_env()


def test_default_transport_does_not_follow_redirects():
    from agent.nim_client import _NoRedirect

    h = _NoRedirect()
    req = urllib.request.Request("http://nim.test/v1/chat/completions", data=b"{}", method="POST")
    assert h.redirect_request(req, None, 302, "Found", {}, "http://evil.test/") is None


def test_from_env_key_variable_name_can_be_switched(monkeypatch):
    """NIM_API_KEY_ENV names the variable that holds the key (self-hosted vLLM: VLLM_API_KEY)."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NIM_API_KEY_ENV", "VLLM_API_KEY")
    monkeypatch.setenv("VLLM_API_KEY", FAKE_KEY)
    monkeypatch.setenv("NIM_BASE_URL", "https://vllm.test/v1")
    monkeypatch.setenv("NIM_MODEL", "nemotron")
    t = FakeTransport([(200, {}, ok_body())])
    c = NimClient.from_env(transport=t, sleep=lambda s: None)
    c.chat([{"role": "user", "content": "u"}])
    req, _ = t.requests[0]
    assert req.full_url == "https://vllm.test/v1/chat/completions"
    assert req.unredirected_hdrs.get("Authorization") == f"Bearer {FAKE_KEY}"
    assert json.loads(req.data.decode("utf-8"))["model"] == "nemotron"


def test_from_env_switched_key_variable_missing_is_config_error(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)  # the default variable must not be used once switched
    monkeypatch.setenv("NIM_API_KEY_ENV", "VLLM_API_KEY")
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    with pytest.raises(ConfigError) as ei:
        NimClient.from_env()
    assert "VLLM_API_KEY" in str(ei.value)


@pytest.mark.parametrize("name", ["vllm_api_key", "VLLM-KEY", "1KEY", "A" * 65, "KEY;rm", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "PATH"])
def test_from_env_bad_key_variable_name_is_config_error(monkeypatch, name):
    monkeypatch.setenv("NIM_API_KEY_ENV", name)
    with pytest.raises(ConfigError) as ei:
        NimClient.from_env()
    assert "NIM_API_KEY_ENV" in str(ei.value)


def test_requests_carry_a_named_user_agent():
    c, t, _ = make_client([(200, {}, ok_body())])
    c.chat([{"role": "user", "content": "u"}])
    req, _ = t.requests[0]
    assert req.get_header("User-agent") == "kculture-agent/1.0"
