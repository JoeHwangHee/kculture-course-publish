"""Per-run budget the code enforces (spec 4.10): logical model calls, token sums, run time, tool steps.

- Logical calls only: HTTP resends inside a client are not seen here.
- Run time excludes the approval wait (`pause()` .. `resume()`).
- Every hit limit is named once in `limits_hit` (first-hit order) and raised as `LimitHit(name)`.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from common import limits

LIMIT_NAMES = ("router_calls", "nemotron_calls", "tokens", "run_seconds", "tool_steps")
MODEL_KEYS = ("router", "nemotron")  # the router is Nemotron too, counted on its own counter (0010)
# Contract 4.10: two router calls per run (first + one retry). The upper orchestrator renames the common constant
# at merge time; until then fall back to 2.
ROUTER_CALLS_DEFAULT = getattr(limits, "ROUTER_CALLS_PER_RUN", 2)


class LimitHit(Exception):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name  # one of LIMIT_NAMES


def _int_or_zero(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


class Budget:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        router_calls: int = ROUTER_CALLS_DEFAULT,
        nemotron_calls: int = limits.NEMOTRON_CALLS_PER_RUN,
        tokens: int = limits.TOKENS_PER_RUN,
        run_seconds: float = limits.RUN_SECONDS,
        tool_steps: int = limits.TOOL_STEPS,
    ):
        self._clock = clock
        self._start = clock()
        # Limits live under private names; `tokens` the attribute is the usage sum.
        self._max_calls = {"router": router_calls, "nemotron": nemotron_calls}
        self._max_tokens = tokens
        self._max_seconds = run_seconds
        self._max_steps = tool_steps
        self._paused_total = 0.0
        self._paused_at: float | None = None
        self.steps = 0
        # Plain dicts in the run.json shape (4.4 as revised by 0010): {"router", "nemotron"}.
        self.model_calls: dict[str, int] = {k: 0 for k in MODEL_KEYS}
        self.tokens: dict[str, dict[str, int]] = {k: {"input": 0, "output": 0} for k in MODEL_KEYS}
        self.limits_hit: list[str] = []
        self.warnings: list[str] = []
        self.call_log: list[dict[str, Any]] = []
        # finish_reason per call, parallel to call_log ("length" = the answer was cut); call_log keeps the 4 trace keys
        self.finish_reasons: list[str | None] = []

    # ------------------------------------------------------------ helpers

    def _hit(self, name: str) -> None:
        if name not in self.limits_hit:
            self.limits_hit.append(name)
        raise LimitHit(name)

    def elapsed(self) -> float:
        """Seconds since construction, minus paused time (including a pause still running)."""
        now = self._clock()
        paused = self._paused_total
        if self._paused_at is not None:
            paused += now - self._paused_at
        return now - self._start - paused

    def total_tokens(self) -> int:
        return sum(t["input"] + t["output"] for t in self.tokens.values())

    # ------------------------------------------------------------ limits

    def check_time(self) -> None:
        if self.elapsed() > self._max_seconds:
            self._hit("run_seconds")

    def pause(self) -> None:
        """Stop the run clock (approval wait). A second pause while paused is ignored."""
        if self._paused_at is None:
            self._paused_at = self._clock()

    def resume(self) -> None:
        """Restart the run clock. Ignored when not paused."""
        if self._paused_at is not None:
            self._paused_total += self._clock() - self._paused_at
            self._paused_at = None

    def count_step(self) -> None:
        self.steps += 1
        if self.steps > self._max_steps:
            self._hit("tool_steps")

    def wrap(self, chat_fn: Callable[..., dict], model_key: str) -> Callable[..., dict]:
        """`wrapped(messages, purpose, **kw)` -> chat_fn's dict, counted against this budget."""
        if model_key not in MODEL_KEYS:
            raise ValueError(f"model_key는 {list(MODEL_KEYS)} 가운데 하나여야 합니다: {model_key!r}")

        def wrapped(messages, purpose, **kw):
            self.check_time()
            if self.total_tokens() > self._max_tokens:
                self._hit("tokens")
            if self.model_calls[model_key] >= self._max_calls[model_key]:
                self._hit(f"{model_key}_calls")
            started = self._clock()
            try:
                result = chat_fn(messages, purpose, **kw)
            except BaseException:
                # No response: one logical call, no usage, no usage warning.
                self._count(model_key)
                self.call_log.append({"name": model_key, "purpose": purpose,
                                      "latency_ms": float((self._clock() - started) * 1000), "usage": None})
                self.finish_reasons.append(None)
                raise
            self._count(model_key)
            result_dict = result if isinstance(result, dict) else {}
            name = result_dict.get("model")
            if not isinstance(name, str) or not name:
                name = model_key
            usage = result_dict.get("usage")
            count = self.tokens[model_key]
            if isinstance(usage, dict):
                count["input"] += _int_or_zero(usage.get("input"))
                count["output"] += _int_or_zero(usage.get("output"))
                logged_usage = dict(usage)
            else:
                self.warnings.append(f"{name} 응답에 usage가 없어 0으로 셈")
                logged_usage = None
            latency = result_dict.get("latency_ms")
            if not isinstance(latency, (int, float)) or isinstance(latency, bool):
                latency = (self._clock() - started) * 1000
            self.call_log.append({"name": name, "purpose": purpose, "latency_ms": float(latency),
                                  "usage": logged_usage})
            reason = result_dict.get("finish_reason")
            self.finish_reasons.append(reason if isinstance(reason, str) else None)
            if self.total_tokens() > self._max_tokens:
                self._hit("tokens")
            self.check_time()
            return result

        return wrapped

    def _count(self, model_key: str) -> None:
        self.model_calls[model_key] += 1
