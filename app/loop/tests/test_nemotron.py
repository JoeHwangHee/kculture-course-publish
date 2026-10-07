"""NemotronChat: NimClient with a counting transport that reads usage (no network)."""

from __future__ import annotations

import json

import pytest

from agent.errors import ConfigError, ModelCallError
from agent.nim_client import NimClient
from loop.nemotron import NemotronChat

FAKE_KEY = "placeholder-not-a-key"


def nim_body(text="답", usage=(30, 7), model="nvidia/nemotron-x"):
    payload = {"model": model, "choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
    if usage is not None:
        payload["usage"] = {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}
    return json.dumps(payload).encode("utf-8")


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append(req)
        return self.responses.pop(0)


class Ticks:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.5
        return self.t


@pytest.fixture
def nim_env(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    monkeypatch.delenv("NIM_BASE_URL", raising=False)
    monkeypatch.delenv("NIM_MODEL", raising=False)


def test_reads_usage(nim_env):
    transport = FakeTransport([(200, {}, nim_body())])
    chat = NemotronChat(transport=transport, sleep=lambda s: None, clock=Ticks())
    out = chat([{"role": "user", "content": "q"}], "plan", response_format={"type": "json_object"})
    assert out == {"text": "답", "usage": {"input": 30, "output": 7}, "model": "nvidia/nemotron-x",
                   "latency_ms": 500.0, "finish_reason": "stop"}
    body = json.loads(transport.requests[0].data.decode("utf-8"))
    assert body["response_format"] == {"type": "json_object"}
    assert "purpose" not in body and "plan" not in json.dumps(body)


def test_usage_missing_is_none(nim_env):
    transport = FakeTransport([(200, {}, nim_body(usage=(30, 7))), (200, {}, nim_body(usage=None))])
    chat = NemotronChat(transport=transport, sleep=lambda s: None)
    assert chat([], "plan")["usage"] == {"input": 30, "output": 7}
    assert chat([], "plan")["usage"] is None  # previous call's usage is cleared


def test_retry_counts_only_the_200(nim_env):
    sleeps = []
    transport = FakeTransport([(500, {}, b'{"usage": {"prompt_tokens": 999, "completion_tokens": 999}}'),
                               (200, {}, nim_body(usage=(11, 2)))])
    chat = NemotronChat(transport=transport, sleep=sleeps.append)
    out = chat([], "plan")
    assert sleeps == [5]
    assert out["usage"] == {"input": 11, "output": 2}


def test_errors_pass_through(nim_env):
    transport = FakeTransport([(400, {}, b"")])
    chat = NemotronChat(transport=transport, sleep=lambda s: None)
    with pytest.raises(ModelCallError):
        chat([], "plan")


def test_from_env_without_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        NemotronChat(transport=FakeTransport([]), sleep=lambda s: None)


def test_client_passed_directly():
    transport = FakeTransport([(200, {}, nim_body(usage=(4, 5), model="m-direct"))])
    client = NimClient("https://nim.example/v1", "m-direct", FAKE_KEY, transport=transport, sleep=lambda s: None)
    chat = NemotronChat(client)
    out = chat([], "light")
    assert out["text"] == "답" and out["model"] == "m-direct"
    assert out["usage"] == {"input": 4, "output": 5}
    assert len(transport.requests) == 1


def test_bad_usage_values_are_none(nim_env):
    raw = json.dumps({"model": "m", "choices": [{"message": {"content": "x"}}],
                      "usage": {"prompt_tokens": "a", "completion_tokens": 1}}).encode()
    chat = NemotronChat(transport=FakeTransport([(200, {}, raw)]), sleep=lambda s: None)
    assert chat([], "plan")["usage"] is None



@pytest.mark.parametrize("purpose, expected", [
    ("organize_names", 6144), ("organize_names:p1", 6144), ("tool organize_names", 6144),
    ("plan", 2048), ("route", 2048), ("select_places", 2048),
])
def test_max_tokens_by_purpose_in_the_sent_body(nim_env, purpose, expected):
    transport = FakeTransport([(200, {}, nim_body())])
    chat = NemotronChat(transport=transport, sleep=lambda s: None)
    chat([{"role": "user", "content": "q"}], purpose)
    body = json.loads(transport.requests[0].data.decode("utf-8"))
    assert body["max_tokens"] == expected


def test_finish_reason_length_is_returned(nim_env):
    payload = {"model": "m", "choices": [{"message": {"content": "{"}, "finish_reason": "length"}],
               "usage": {"prompt_tokens": 1, "completion_tokens": 2}}
    transport = FakeTransport([(200, {}, json.dumps(payload).encode("utf-8"))])
    out = NemotronChat(transport=transport, sleep=lambda s: None)([], "organize_names")
    assert out["finish_reason"] == "length"
