"""Small helpers shared by the tools."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
SHOWN_VALUE_CHARS = 60  # model or plan values in warnings/unknowns are cut to this many chars

_FENCE = re.compile(r"```[A-Za-z0-9_-]*\s*\n?(.*?)```", re.DOTALL)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CLOSERS = {"[": "]", "{": "}"}


def shown(value: Any) -> str:
    """A model or plan value for warnings/unknowns: whitespace folded to one line, cut to SHOWN_VALUE_CHARS."""
    return " ".join(str(value).split())[:SHOWN_VALUE_CHARS]


def add_unique(items: list[str], message: str) -> None:
    """Append `message` only if the same line is not there yet (ctx.warnings / ctx.unknowns)."""
    if message not in items:
        items.append(message)


def parse_model_json(text: str) -> Any:
    """JSON from a model answer: strips ```json fences and surrounding chatter. ValueError if none parses."""
    if not isinstance(text, str):
        raise ValueError("model answer is not text")
    candidates: list[str] = []
    for m in _FENCE.finditer(text):
        candidates.append(m.group(1).strip())
    candidates.append(text.strip())
    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            pass
        starts = [i for i in (cand.find("["), cand.find("{")) if i >= 0]
        if not starts:
            continue
        start = min(starts)
        end = cand.rfind(_CLOSERS[cand[start]])
        if end > start:
            try:
                return json.loads(cand[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                pass
    raise ValueError("no JSON found in the model answer")


def find_pack(packs: list[dict], pack_id: str) -> dict | None:
    """The pack with `pack_id`; with an empty id, the only pack if there is exactly one, else None."""
    if not pack_id:
        return packs[0] if len(packs) == 1 else None
    for pack in packs:
        if pack.get("pack_id") == pack_id:
            return pack
    return None


def chunk_date(chunk_or_meta: dict) -> str:
    """`published` if it is a real YYYY-MM-DD date, else "" (no date sorts as the oldest)."""
    value = chunk_or_meta.get("published")
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return ""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return ""
    return value


def grade_rank(grade: str | None) -> int:
    """A=4 .. D=1; None or unknown = 0."""
    if grade is None:
        return 0
    return GRADE_RANK.get(grade, 0)
