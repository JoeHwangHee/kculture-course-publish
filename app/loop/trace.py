"""Decision record writer: one hash-chained JSON line per judgement or tool call (spec 2.6, 4.4).

Never pass key or token values, full response bodies or local absolute paths in any field.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any, Callable

from common.schema import (
    GENESIS_HASH,
    SchemaError,
    TraceLine,
    TraceModel,
    TraceResult,
    prev_hash_for,
    split_trace_lines,
    utc_ts,
)

TEXT_MAX_CHARS = 500  # summary / why are folded to one line and cut here


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())[:TEXT_MAX_CHARS]


class TraceWriter:
    def __init__(self, path: pathlib.Path, run_id: str,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.path = pathlib.Path(path)
        self.run_id = run_id
        self._now = now
        self._seq = 1
        self._prev_hash = GENESIS_HASH
        if self.path.exists():
            text = self.path.read_text(encoding="utf-8")
            lines = split_trace_lines(text)
            if lines:
                last = lines[-1]
                try:
                    last_obj = json.loads(last)
                    last_seq = last_obj["seq"]
                    last_run_id = last_obj["run_id"]
                except (ValueError, KeyError, TypeError):
                    raise SchemaError("trace.jsonl 마지막 줄을 읽지 못했습니다") from None
                if isinstance(last_seq, bool) or not isinstance(last_seq, int):
                    raise SchemaError("trace.jsonl 마지막 줄의 seq가 정수가 아닙니다")
                if last_run_id != run_id:
                    raise SchemaError("trace.jsonl 마지막 줄의 run_id가 이어 쓸 실행과 다릅니다")
                self._seq = last_seq + 1
                self._prev_hash = prev_hash_for(last)
                if not text.endswith("\n"):
                    # Close the last line first so the next line starts on its own.
                    with open(self.path, "a", encoding="utf-8", newline="") as fh:
                        fh.write("\n")
                        fh.flush()

    def append(self, event: str, *, tool: str = "", args: dict | None = None, kind: str = "",
               summary: str = "", why: str = "", model: dict | None = None) -> dict[str, Any]:
        """Write one line (flushed at once) and return it as a dict."""
        if model is None or isinstance(model, TraceModel):
            trace_model = model
        else:
            trace_model = TraceModel.from_dict(model)
        line = TraceLine(
            seq=self._seq,
            ts=utc_ts(self._now()),
            run_id=self.run_id,
            event=event,
            tool=tool,
            args=dict(args or {}),
            result=TraceResult(kind=kind, summary=_one_line(summary)),
            why=_one_line(why),
            model=trace_model,
            prev_hash=self._prev_hash,
        )
        text = line.to_json_line()
        with open(self.path, "a", encoding="utf-8", newline="") as fh:
            fh.write(text + "\n")
            fh.flush()
        self._seq += 1
        self._prev_hash = prev_hash_for(text)
        return line.to_dict()
