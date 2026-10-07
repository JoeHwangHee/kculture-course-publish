"""save_course: writes course.json and course.md into the run folder (spec 4.4, 4.6).

Only the contract keys are kept (extra keys such as `priority` or `pack_id` are dropped) and the result is checked
with `Course.from_dict` before anything is written. The run folder is made by the loop, not here.
"""

from __future__ import annotations

import json
import os
from dataclasses import fields
from typing import Any

from common.schema import (
    COURSE_JSON,
    COURSE_MD,
    OPERATING_CHOSEN,
    OPERATING_NEEDS_ONSITE_CHECK,
    OPERATING_UNKNOWN,
    TEXT_ESTIMATE,
    TEXT_NO_EVIDENCE,
    TEXT_ONSITE_CHECK,
    TEXT_UNCONFIRMED,
    Conflict,
    Course,
    CoursePlace,
    ExcludedItem,
    Goal,
    Operating,
    OriginClaim,
    SchemaError,
    StaleItem,
)
from common.tooling import Deps, RunContext, ToolResult, ToolSpec
from tools._shared import grade_rank

DEFAULT_TITLE = "K-콘텐츠 배경지 코스"
TEXT_UNKNOWN_DATE = "날짜 미상"  # source without a date in course.md
NAME_KIND_LABELS = {"current": "지금 이름", "old": "옛 이름", "in_work": "작품 속 이름", "station": "역 이름"}
MODE_LABELS = {"walk": "도보", "transit": "대중교통", "unknown": "알 수 없음"}


def _keys(cls: type) -> list[str]:
    return [f.name for f in fields(cls)]


def _pick(value: Any, cls: type) -> Any:
    """Only the record's keys of a dict; anything else is returned as is (validation reports it)."""
    if not isinstance(value, dict):
        return value
    return {k: value[k] for k in _keys(cls) if k in value}


def _pick_list(value: Any, cls: type) -> Any:
    if not isinstance(value, list):
        return value
    return [_pick(v, cls) for v in value]


_CLAIM_DEFAULTS = {"summary": "", "grade": None, "source_ids": [], "chunk_ids": [], "input_paths": []}


def _claims(value: Any) -> Any:
    """Origin claims with only OriginClaim keys; absent optional-in-spirit keys get empty values."""
    if not isinstance(value, list):
        return value
    return [{**_CLAIM_DEFAULTS, **_pick(v, OriginClaim)} if isinstance(v, dict) else v for v in value]


def _empty_operating() -> dict[str, Any]:
    return {"status": OPERATING_UNKNOWN, "hours": "", "closed": "", "source_ids": [], "as_of": ""}


def _place(index: int, place: dict[str, Any], graded: dict[str, Any]) -> dict[str, Any]:
    out = _pick(place, CoursePlace)
    for k in ("origins", "conflicts", "operating", "stale"):
        out.pop(k, None)
    out.setdefault("order", index + 1)
    out.setdefault("old_names", [])
    out.setdefault("travel_chunk_ids", [])
    station = out.get("station", {"name": "", "line": ""})
    if isinstance(station, str):  # pack station name before lookup_station filled the line
        station = {"name": station, "line": ""}
    if isinstance(station, dict):
        station = {"name": station.get("name", ""), "line": station.get("line", "")}
    out["station"] = station

    g = graded if isinstance(graded, dict) else {}
    out["origins"] = _claims(g.get("origins", []))
    conflicts = g.get("conflicts", [])
    if isinstance(conflicts, list):
        conflicts = [
            {**_pick(c, Conflict), "claims": _claims(c.get("claims", []))}
            if isinstance(c, dict) else c
            for c in conflicts
        ]
    out["conflicts"] = conflicts
    operating = g.get("operating") or {}
    if isinstance(operating, dict):
        operating = {**_empty_operating(), **_pick(operating, Operating)}
    out["operating"] = operating
    out["stale"] = _pick_list(g.get("stale", []), StaleItem)
    return {k: out[k] for k in _keys(CoursePlace) if k in out}


def _goal(goal: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"work": "", "time_budget_min": None, "start": "", "constraints": [],
                           "publish_requested": True}
    if isinstance(goal, dict):
        out.update(_pick(goal, Goal))
    return out


def build_course(ctx: RunContext) -> dict[str, Any]:
    """Course dict (course.json shape) from the run context; not yet validated."""
    places = [_place(i, p, ctx.graded.get(p.get("place_id", ""), {}) if isinstance(p, dict) else {})
              if isinstance(p, dict) else p
              for i, p in enumerate(ctx.places)]
    total: int | None = None
    if places and isinstance(places[-1], dict):
        last = places[-1]
        arrive, stay = last.get("arrive_min"), last.get("stay_min")
        if isinstance(arrive, int) and isinstance(stay, int):
            total = arrive + stay
    return {
        "run_id": ctx.run_id,
        "request": ctx.request,
        "goal": _goal(ctx.goal),
        "places": places,
        "total_min": total,
        "excluded": _pick_list(list(ctx.excluded), ExcludedItem),
        "unknowns": list(ctx.unknowns),
        "warnings": list(ctx.warnings),
        "publish": {"status": "", "url": None},
    }


# ---------------------------------------------------------------- course.md


def _source_labels(claim: dict[str, Any], deps: Deps, ctx: RunContext) -> list[str]:
    labels: list[str] = []
    for chunk_id in claim.get("chunk_ids") or []:
        chunk = deps.get_chunk(chunk_id)
        if not chunk:
            continue
        who = chunk.get("publisher") or chunk.get("source_id") or chunk_id
        label = f"{who} {chunk.get('published') or TEXT_UNKNOWN_DATE}"
        if label not in labels:
            labels.append(label)
    for path in claim.get("input_paths") or []:
        meta = (ctx.read_files.get(path) or {}).get("front_matter") or {}
        label = f"{meta.get('publisher') or path} {meta.get('published') or TEXT_UNKNOWN_DATE}"
        if label not in labels:
            labels.append(label)
    return labels


def _one_line(value: Any) -> str:
    """Model-written text folded to one line for course.md (line breaks and runs of spaces become one space)."""
    return " ".join(str(value).split())


def _claim_line(claim: dict[str, Any], deps: Deps, ctx: RunContext) -> str:
    kind = NAME_KIND_LABELS.get(claim.get("name_kind", ""), claim.get("name_kind", ""))
    head = f"{_one_line(claim.get('name', ''))}({kind}): {_one_line(claim.get('summary', '')) or '요약 없음'}"
    grade = claim.get("grade")
    if grade is None:
        return f"{head} — {TEXT_NO_EVIDENCE}"
    sources = _source_labels(claim, deps, ctx)
    return f"{head} — 등급 {grade}, 출처: {'; '.join(sources) if sources else TEXT_UNCONFIRMED}"


def _travel_line(place: dict[str, Any]) -> str:
    minutes = place.get("travel_min_from_prev")
    if minutes is None:
        return "이동 시간 확인 안 됨"
    mode = MODE_LABELS.get(place.get("travel_mode", ""), place.get("travel_mode", ""))
    line = f"{minutes}분({mode})"
    if place.get("travel_basis") == "estimate":
        line += f" ({TEXT_ESTIMATE})"
    return line


def _candidate_line(candidate: Any) -> str:
    if not isinstance(candidate, dict):
        return str(candidate)
    parts = []
    if candidate.get("hours"):
        parts.append(f"운영 시간 {candidate['hours']}")
    if candidate.get("closed"):
        parts.append(f"휴무 {candidate['closed']}")
    extra = [str(candidate[k]) for k in ("grade", "published", "as_of") if candidate.get(k)]
    if candidate.get("grade"):
        extra[0] = f"등급 {candidate['grade']}"
    who = candidate.get("source_id") or candidate.get("publisher") or "출처 미상"
    tail = f" ({', '.join(extra)})" if extra else ""
    return f"{who}: {', '.join(parts) or '내용 없음'}{tail}"


def _operating_lines(op: dict[str, Any]) -> list[str]:
    status = op.get("status")
    sources = ", ".join(op.get("source_ids") or []) or TEXT_UNCONFIRMED
    if status == OPERATING_CHOSEN:
        return [f"- 운영 시간 {op.get('hours', '')}, 휴무 {op.get('closed', '')} "
                f"({op.get('as_of', '') or '날짜 미상'} 기준, 출처 {sources})"]
    if status == OPERATING_NEEDS_ONSITE_CHECK:
        lines = [f"- {TEXT_ONSITE_CHECK}(자료끼리 엇갈림)"]
        lines += [f"  - {_candidate_line(c)}" for c in op.get("candidates") or []]
        return lines
    return ["- 운영 정보 확인 안 됨"]


def render_course_md(course: dict[str, Any], deps: Deps, ctx: RunContext) -> str:
    """Korean Markdown of the course. Writes no local path (input paths are /hackathon/ paths)."""
    goal = course.get("goal") or {}
    title = goal.get("work") or DEFAULT_TITLE
    budget = goal.get("time_budget_min")
    total = course.get("total_min")
    lines = [
        f"# {title} 배경지 코스" if goal.get("work") else f"# {DEFAULT_TITLE}",
        "",
        f"- 요청: {course.get('request', '')}",
        f"- 출발점: {goal.get('start') or '정하지 않음'}",
        f"- 시간 예산: {f'{budget}분' if budget is not None else '정하지 않음'}",
        f"- 총 소요: {f'{total}분' if total is not None else '계산 못 함'}",
        "",
    ]
    for place in course.get("places") or []:
        station = place.get("station") or {}
        station_text = station.get("name") or TEXT_UNCONFIRMED
        if station.get("line"):
            station_text += f"({station['line']})"
        arrive = place.get("arrive_min")
        lines += [
            f"## {place.get('order')}. {place.get('current_name', '')}",
            "",
            f"- 작품 속 이름: {place.get('in_work_name', '')}",
            f"- 장면: {place.get('scene', '')}",
            f"- 옛 이름: {', '.join(place.get('old_names') or []) or '없음'}",
            f"- 가까운 역: {station_text}",
            f"- 이동: {_travel_line(place)}",
            f"- 도착: {f'출발부터 {arrive}분' if arrive is not None else '계산 못 함'}",
            f"- 머무는 시간: {place.get('stay_min')}분",
            "",
            "### 이름 유래",
            "",
        ]
        origins = place.get("origins") or []
        lines += [f"- {_claim_line(c, deps, ctx)}" for c in origins] or ["- 유래 자료 없음"]
        for conflict in place.get("conflicts") or []:
            lines += ["", f"- {_one_line(conflict.get('name', ''))}: 유래가 엇갈림"]
            claims = sorted(conflict.get("claims") or [], key=lambda c: -grade_rank(c.get("grade")))
            lines += [f"  - {_claim_line(c, deps, ctx)}" for c in claims]
        lines += ["", "### 운영 정보", ""]
        lines += _operating_lines(place.get("operating") or {})
        stale = place.get("stale") or []
        if stale:
            lines += ["", "### 오래된 자료", ""]
            lines += [f"- {s.get('source_id', '')}: {s.get('reason', '')}" for s in stale]
        lines.append("")
    for heading, items in (
        ("제외한 장소", [f"{e.get('place_id', '')}: {e.get('reason', '')}" for e in course.get("excluded") or []]),
        ("확인 안 된 것", list(course.get("unknowns") or [])),
        ("경고", list(course.get("warnings") or [])),
    ):
        if items:
            lines += [f"## {heading}", ""] + [f"- {i}" for i in items] + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------- save_course


def run_save_course(args: dict[str, Any], ctx: RunContext, deps: Deps) -> ToolResult:
    if not ctx.run_dir or not os.path.isdir(ctx.run_dir):
        return ToolResult.tool_error("실행 폴더가 없음")
    try:
        validated = Course.from_dict(build_course(ctx))
    except SchemaError as exc:
        return ToolResult.tool_error(f"코스가 계약 형식과 다름: {exc}")
    course = validated.to_dict()
    try:
        markdown = render_course_md(course, deps, ctx)
    except Exception as exc:  # noqa: BLE001 - one-line tool error instead of a crash
        return ToolResult.tool_error(f"course.md를 만들지 못함: {type(exc).__name__}")
    try:
        with open(os.path.join(ctx.run_dir, COURSE_JSON), "w", encoding="utf-8") as f:
            json.dump(course, f, ensure_ascii=False, indent=2)
            f.write("\n")
        with open(os.path.join(ctx.run_dir, COURSE_MD), "w", encoding="utf-8") as f:
            f.write(markdown)
    except OSError as exc:
        return ToolResult.tool_error(f"파일 쓰기 실패: {type(exc).__name__}")
    ctx.course = course
    return ToolResult.success({"files": [COURSE_MD, COURSE_JSON], "total_min": course["total_min"],
                               "places": len(course["places"])})


SPECS = [
    ToolSpec(name="save_course", run=run_save_course,
             description="코스를 실행 폴더의 course.md·course.json으로 저장한다"),
]
