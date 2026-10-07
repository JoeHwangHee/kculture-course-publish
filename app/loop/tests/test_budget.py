"""Budget: logical call counts, token sums, run time without the approval wait, tool steps (spec 4.10)."""

from __future__ import annotations

import pytest

from common import limits
from loop.budget import LIMIT_NAMES, Budget, LimitHit


class FakeClock:
    def __init__(self, t: float = 100.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def fake_chat(usage=None, model="fake-model", latency_ms=12.5, text="ok"):
    calls = []

    def chat(messages, purpose, **kw):
        calls.append((messages, purpose, kw))
        return {"text": text, "usage": usage, "model": model, "latency_ms": latency_ms}

    chat.calls = calls
    return chat


def test_limit_names_and_limithit():
    assert LIMIT_NAMES == ("router_calls", "nemotron_calls", "tokens", "run_seconds", "tool_steps")
    e = LimitHit("tokens")
    assert e.name == "tokens"
    assert isinstance(e, Exception)


def test_defaults_come_from_limits():
    b = Budget(clock=FakeClock())
    assert b.model_calls == {"router": 0, "nemotron": 0}
    assert b.tokens == {"router": {"input": 0, "output": 0}, "nemotron": {"input": 0, "output": 0}}
    assert b.limits_hit == [] and b.warnings == [] and b.call_log == []
    # tokens attribute is the usage sum, not the limit number
    assert b.tokens["router"]["input"] == 0
    b2 = Budget(clock=FakeClock(), tool_steps=limits.TOOL_STEPS)
    for _ in range(limits.TOOL_STEPS):
        b2.count_step()
    with pytest.raises(LimitHit):
        b2.count_step()


def test_wrap_counts_calls_tokens_and_log():
    b = Budget(clock=FakeClock())
    chat = fake_chat(usage={"input": 10, "output": 3}, model="nemo")
    wrapped = b.wrap(chat, "nemotron")
    out = wrapped([{"role": "user", "content": "hi"}], "plan", response_format={"type": "json_object"})
    assert out["text"] == "ok"
    assert chat.calls[0][1] == "plan"
    assert chat.calls[0][2] == {"response_format": {"type": "json_object"}}
    assert b.model_calls == {"router": 0, "nemotron": 1}
    assert b.tokens["nemotron"] == {"input": 10, "output": 3}
    assert b.call_log == [{"name": "nemo", "purpose": "plan", "latency_ms": 12.5,
                           "usage": {"input": 10, "output": 3}}]
    assert b.warnings == []


def test_missing_usage_counts_zero_and_warns():
    b = Budget(clock=FakeClock())
    wrapped = b.wrap(fake_chat(usage=None, model="router-x"), "router")
    wrapped([], "route")
    assert b.model_calls["router"] == 1
    assert b.tokens["router"] == {"input": 0, "output": 0}
    assert b.warnings == ["router-x 응답에 usage가 없어 0으로 셈"]
    assert b.call_log[0]["usage"] is None
    assert set(b.call_log[0]) == {"name", "purpose", "latency_ms", "usage"}


def test_call_limit_blocks_before_call():
    b = Budget(clock=FakeClock(), router_calls=2)
    chat = fake_chat(usage={"input": 1, "output": 1})
    wrapped = b.wrap(chat, "router")
    wrapped([], "route")
    wrapped([], "route")
    with pytest.raises(LimitHit) as ei:
        wrapped([], "route")
    assert ei.value.name == "router_calls"
    assert len(chat.calls) == 2
    assert b.model_calls["router"] == 2
    with pytest.raises(LimitHit):
        wrapped([], "route")
    assert b.limits_hit == ["router_calls"]


def test_nemotron_call_limit_name():
    b = Budget(clock=FakeClock(), nemotron_calls=1)
    wrapped = b.wrap(fake_chat(usage={"input": 1, "output": 1}), "nemotron")
    wrapped([], "plan")
    with pytest.raises(LimitHit) as ei:
        wrapped([], "plan")
    assert ei.value.name == "nemotron_calls"
    assert b.limits_hit == ["nemotron_calls"]


def test_token_limit_over_both_counters():
    b = Budget(clock=FakeClock(), tokens=100)
    b.wrap(fake_chat(usage={"input": 40, "output": 10}), "router")([], "route")
    with pytest.raises(LimitHit) as ei:
        b.wrap(fake_chat(usage={"input": 40, "output": 11}), "nemotron")([], "plan")
    assert ei.value.name == "tokens"
    assert b.model_calls["nemotron"] == 1
    assert b.tokens["nemotron"]["output"] == 11
    assert b.limits_hit == ["tokens"]


def test_token_limit_exact_is_fine():
    b = Budget(clock=FakeClock(), tokens=100)
    b.wrap(fake_chat(usage={"input": 50, "output": 50}), "router")([], "route")
    assert b.limits_hit == []


def test_exception_counts_one_call_and_reraises():
    b = Budget(clock=FakeClock())

    def boom(messages, purpose, **kw):
        raise RuntimeError("down")

    wrapped = b.wrap(boom, "router")
    with pytest.raises(RuntimeError):
        wrapped([], "route")
    assert b.model_calls["router"] == 1
    assert b.warnings == []
    assert len(b.call_log) == 1
    assert b.call_log[0]["purpose"] == "route" and b.call_log[0]["usage"] is None


def test_check_time_and_pause_resume():
    clock = FakeClock(0.0)
    b = Budget(clock=clock, run_seconds=300)
    clock.t = 200.0
    b.check_time()
    b.pause()
    clock.t = 450.0
    b.check_time()  # paused time is not counted
    b.resume()
    clock.t = 550.0  # 200 + 100 counted
    b.check_time()
    clock.t = 600.5  # 300.5 counted
    with pytest.raises(LimitHit) as ei:
        b.check_time()
    assert ei.value.name == "run_seconds"
    assert b.limits_hit == ["run_seconds"]


def test_pause_twice_and_resume_without_pause_are_ignored():
    clock = FakeClock(0.0)
    b = Budget(clock=clock, run_seconds=10)
    b.resume()  # no pause: ignored
    b.pause()
    clock.t = 5.0
    b.pause()  # nested pause: ignored, the first pause start stays
    clock.t = 100.0
    b.resume()
    b.check_time()  # 0 seconds counted
    clock.t = 111.0
    with pytest.raises(LimitHit):
        b.check_time()


def test_wrap_checks_time_first():
    clock = FakeClock(0.0)
    b = Budget(clock=clock, run_seconds=10)
    chat = fake_chat(usage={"input": 1, "output": 1})
    wrapped = b.wrap(chat, "nemotron")
    clock.t = 11.0
    with pytest.raises(LimitHit) as ei:
        wrapped([], "plan")
    assert ei.value.name == "run_seconds"
    assert chat.calls == []
    assert b.model_calls["nemotron"] == 0


def test_count_step_limit():
    b = Budget(clock=FakeClock(), tool_steps=2)
    b.count_step()
    b.count_step()
    with pytest.raises(LimitHit) as ei:
        b.count_step()
    assert ei.value.name == "tool_steps"
    with pytest.raises(LimitHit):
        b.count_step()
    assert b.limits_hit == ["tool_steps"]


def test_limits_hit_first_hit_order():
    clock = FakeClock(0.0)
    b = Budget(clock=clock, tool_steps=0, run_seconds=1)
    with pytest.raises(LimitHit):
        b.count_step()
    clock.t = 2.0
    with pytest.raises(LimitHit):
        b.check_time()
    with pytest.raises(LimitHit):
        b.count_step()
    assert b.limits_hit == ["tool_steps", "run_seconds"]


def test_wrap_rejects_unknown_model_key():
    b = Budget(clock=FakeClock())
    with pytest.raises(ValueError):
        b.wrap(fake_chat(), "gpt")


def test_tokens_checked_before_call():
    b = Budget(clock=FakeClock(), tokens=100)
    with pytest.raises(LimitHit):
        b.wrap(fake_chat(usage={"input": 140, "output": 10}), "router")([], "route")
    chat = fake_chat(usage={"input": 1, "output": 1})
    with pytest.raises(LimitHit) as ei:
        b.wrap(chat, "nemotron")([], "plan")
    assert ei.value.name == "tokens"
    assert chat.calls == []  # not called once over the token limit
    assert b.model_calls["nemotron"] == 0
    assert b.limits_hit == ["tokens"]


def test_time_checked_after_call():
    clock = FakeClock(0.0)
    b = Budget(clock=clock, run_seconds=10)

    def slow_chat(messages, purpose, **kw):
        clock.t = 11.0
        return {"text": "ok", "usage": {"input": 1, "output": 1}, "model": "m", "latency_ms": 11000.0}

    with pytest.raises(LimitHit) as ei:
        b.wrap(slow_chat, "nemotron")([], "plan")
    assert ei.value.name == "run_seconds"
    assert b.model_calls["nemotron"] == 1 and len(b.call_log) == 1
    assert b.limits_hit == ["run_seconds"]


def test_router_calls_do_not_use_the_nemotron_limit():
    b = Budget(clock=FakeClock())
    b.wrap(fake_chat(usage={"input": 1, "output": 1}), "router")([], "route")
    nemotron = b.wrap(fake_chat(usage={"input": 1, "output": 1}), "nemotron")
    for _ in range(limits.NEMOTRON_CALLS_PER_RUN):
        nemotron([], "plan")
    assert b.model_calls == {"router": 1, "nemotron": limits.NEMOTRON_CALLS_PER_RUN}
    assert b.limits_hit == []
    assert b.total_tokens() == 2 * (1 + limits.NEMOTRON_CALLS_PER_RUN)
