"""Baseline (spec 2.8 via section 6 table): Nemotron alone, one call, no data, no tools, no router, same limits.

The model writes the course numbers itself; the code only shapes the reply into the course.json top-level keys and
does not check or fix the values.
"""

from __future__ import annotations

import pathlib
import time

from common.schema import (
    BASELINE_JSON,
    EVENT_BASELINE,
    EVENT_FINAL,
    INDEX_COLLECTION,
    KIND_OK,
    ROUTE_NONE,
    STATUS_BASELINE_DONE,
    STATUS_FAILED,
    TRACE_JSONL,
    IndexInfo,
    RunRecord,
    utc_ts,
)

from loop import files
from loop.budget import Budget, LimitHit
from loop.planner import PLAN_RESPONSE_FORMAT, extract_json_object
from loop.executor import one_line
from loop.runner import finish_run, utc_now
from loop.trace import TraceWriter

BASELINE_PURPOSE = "baseline"
COURSE_KEYS = ("run_id", "request", "goal", "places", "total_min", "excluded", "unknowns", "warnings", "publish")
TEXT_NOT_JSON = "모델 응답을 JSON으로 읽지 못함"

BASELINE_SYSTEM = (
    "너는 K-콘텐츠 배경지 여행 코스를 짠다. 자료와 도구 없이 아는 만큼만 답한다.\n"
    "출력은 JSON 객체 하나뿐이다. 최상위 키는 goal, places, total_min, excluded, unknowns, warnings다.\n"
    '- goal: {"work": "<작품명 또는 빈 값>", "time_budget_min": <정수 또는 null>, "start": "<출발 역 또는 빈 값>", '
    '"constraints": ["<제약>"], "publish_requested": true 또는 false}\n'
    "- places: 순서대로. 각 항목에 order, place_id(모르면 빈 값), current_name, in_work_name, scene, old_names, "
    "station({name, line}), travel_min_from_prev, travel_mode(walk|transit|unknown), stay_min, arrive_min, "
    "origins([{name, name_kind, summary}])를 아는 만큼 넣는다.\n"
    "- total_min: 이동 시간과 머무는 시간의 합(정수 또는 null)\n"
    "- excluded: [{place_id, reason}], unknowns·warnings: 한 줄 문자열 목록"
)


def _default_goal() -> dict:
    return {"work": "", "time_budget_min": None, "start": "", "constraints": [], "publish_requested": False}


def shape_baseline(obj: dict | None, *, run_id: str, request: str) -> dict:
    """Exactly the nine Course top-level keys. Model values keep their content; missing keys get defaults."""
    out = {
        "run_id": run_id,
        "request": request,
        "goal": _default_goal(),
        "places": [],
        "total_min": None,
        "excluded": [],
        "unknowns": [],
        "warnings": [],
        "publish": {"status": "", "url": None},
    }
    if obj is None:
        out["warnings"].append(TEXT_NOT_JSON)
        return out
    if isinstance(obj.get("goal"), dict):
        goal = _default_goal()
        goal.update(obj["goal"])
        out["goal"] = goal
    for key in ("places", "excluded", "unknowns", "warnings"):
        if isinstance(obj.get(key), list):
            out[key] = obj[key]
    if "total_min" in obj:
        out["total_min"] = obj["total_min"]
    return out


def run_baseline(request: str, *, nemotron_chat, output_root, clock=time.monotonic, now=utc_now,
                 rand_hex=None) -> dict:
    """Returns {"run_id", "status", "run_dir", "text"}. A model failure or a hit limit ends FAILED without
    baseline.json."""
    started = now()
    run_id, run_dir = files.new_run_dir(pathlib.Path(output_root), started, rand_hex)
    run_dir = pathlib.Path(run_dir)
    trace = TraceWriter(run_dir / TRACE_JSONL, run_id, now=now)
    budget = Budget(clock=clock)
    chat = budget.wrap(nemotron_chat, "nemotron")
    messages = [{"role": "system", "content": BASELINE_SYSTEM}, {"role": "user", "content": request}]
    status, text = STATUS_FAILED, ""
    try:
        reply = chat(messages, BASELINE_PURPOSE, response_format=PLAN_RESPONSE_FORMAT)
    except LimitHit as exc:
        if exc.name not in budget.limits_hit:
            budget.limits_hit.append(exc.name)
        text = f"한도 초과: {exc.name}"
        trace.append(EVENT_BASELINE, kind="", summary=text,
                     model=budget.call_log[-1] if budget.call_log else None)
    except Exception as exc:
        text = f"모델 호출 실패: {type(exc).__name__}"
        trace.append(EVENT_BASELINE, kind="", summary=text,
                     model=budget.call_log[-1] if budget.call_log else None)
    else:
        body = reply.get("text") if isinstance(reply, dict) else None
        course = shape_baseline(extract_json_object(body), run_id=run_id, request=request)
        files.write_json(run_dir / BASELINE_JSON, course)
        status = STATUS_BASELINE_DONE
        text = one_line(f"기준선 코스 {len(course['places'])}곳, 총 {course['total_min']}분")
        trace.append(EVENT_BASELINE, kind=KIND_OK, summary=text, why="기준선: Nemotron 단독, 자료·도구 없음",
                     model=budget.call_log[-1] if budget.call_log else None)
    trace.append(EVENT_FINAL, kind=status, summary=text, why="코드 규칙: 실행 끝")
    record = RunRecord(run_id=run_id, request=request, route=ROUTE_NONE, status=status, started_at=utc_ts(started),
                       ended_at=utc_ts(now()),
                       index=IndexInfo(collection=INDEX_COLLECTION, fingerprint=""), limits_hit=list(budget.limits_hit))
    finish_run(run_dir, record, budget)
    return {"run_id": run_id, "status": status, "run_dir": str(run_dir), "text": text}
