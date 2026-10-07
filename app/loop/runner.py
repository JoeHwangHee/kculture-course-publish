"""One request = one run (spec 2.1): run folder, router, light / heavy / UNAVAILABLE, trace final, run.json."""

from __future__ import annotations

import copy
import pathlib
import time
from datetime import datetime, timezone

from common import limits
from common.schema import (
    EVENT_FINAL,
    EVENT_LIGHT_ANSWER,
    EVENT_ROUTE,
    EVIDENCE_LABEL_LIGHT,
    INDEX_COLLECTION,
    RUN_JSON,
    KIND_OK,
    ROUTE_HEAVY,
    ROUTE_LIGHT,
    ROUTE_NONE,
    STATUS_ANSWERED_LIGHT,
    STATUS_FAILED,
    STATUS_UNAVAILABLE,
    TEXT_UNAVAILABLE,
    TRACE_JSONL,
    AnswerRecord,
    IndexInfo,
    RunRecord,
    utc_ts,
)
from common.tooling import RunContext

from loop import files
from loop.budget import Budget, LimitHit
from loop.executor import one_line, run_heavy
from loop.router import route, work_label
from loop.trace import TraceWriter

LIGHT_PURPOSE = "light_answer"
LIGHT_SYSTEM = (
    "너는 K-콘텐츠 배경지 안내 도우미다. 자료 검색 없이 짧게(다섯 문장 이내) 한국어로 답한다. "
    "모르는 사실은 지어내지 않고 모른다고 말한다."
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def light_answer_text(body: str) -> str:
    """EVIDENCE_LABEL_LIGHT as the first line, then the body (a label line the model already wrote is dropped)."""
    lines = (body or "").strip().split("\n")
    while lines and lines[0].strip() in (EVIDENCE_LABEL_LIGHT, ""):
        lines.pop(0)
    rest = "\n".join(lines).strip()
    return EVIDENCE_LABEL_LIGHT + ("\n" + rest if rest else "")


def _write_answer(run_dir, run_id, request, route_name, status, answer, label="", warnings=()):
    files.write_answer(run_dir, AnswerRecord(run_id=run_id, request=request, route=route_name, status=status,
                                             answer=answer, evidence_label=label, warnings=list(warnings)))


def run_dict(record: RunRecord, budget) -> dict:
    """run.json as a dict: the record with `model_calls` / `tokens` taken from the Budget ({"router", "nemotron"},
    contract 4.4 as revised by 0010; the common records still carry the old keys until the merge)."""
    data = record.to_dict()
    data["model_calls"] = copy.deepcopy(budget.model_calls)
    data["tokens"] = copy.deepcopy(budget.tokens)
    return data


def write_run_json(run_dir: pathlib.Path, data: dict) -> None:
    """Write run.json so that `files` lists every run file, run.json included."""
    files.write_json(pathlib.Path(run_dir) / RUN_JSON, data)
    data["files"] = files.list_run_files(run_dir)
    files.write_json(pathlib.Path(run_dir) / RUN_JSON, data)


def finish_run(run_dir: pathlib.Path, record: RunRecord, budget) -> None:
    write_run_json(run_dir, run_dict(record, budget))


def run_ask(request: str, *, registry, deps_factory, router_chat, nemotron_chat, output_root, publish_repo: str = "",
            index_fingerprint: str = "", clock=time.monotonic, sleep=time.sleep, now=utc_now,
            rand_hex=None, approval_wait_s: int = limits.APPROVAL_WAIT_SECONDS) -> dict:
    """Run one request end to end. Returns {"run_id", "status", "run_dir", "text"} (text = screen summary).

    deps_factory(chat) gets the Budget-wrapped Nemotron chat and returns Deps, so model calls made by tools count
    against the same limits.
    """
    started = now()
    run_id, run_dir = files.new_run_dir(pathlib.Path(output_root), started, rand_hex)
    run_dir = pathlib.Path(run_dir)
    trace = TraceWriter(run_dir / TRACE_JSONL, run_id, now=now)
    budget = Budget(clock=clock)
    route_name, status, text = ROUTE_NONE, STATUS_FAILED, ""
    try:
        router = budget.wrap(router_chat, "router")  # own counter: not part of the Nemotron call limit
        nemotron = budget.wrap(nemotron_chat, "nemotron")
        deps = deps_factory(nemotron)  # before the router: it needs the work list from the theme packs (0019)
        works = _work_list(deps, budget, trace)
        weight = route(request, router, trace, budget=budget, works=works)
        if weight is None:
            status, text = STATUS_UNAVAILABLE, TEXT_UNAVAILABLE
            _write_answer(run_dir, run_id, request, ROUTE_NONE, status, text, warnings=budget.warnings)
        elif weight == ROUTE_LIGHT:
            route_name = ROUTE_LIGHT
            status, text = _light(request, run_id, run_dir, nemotron, budget, trace)
        else:
            route_name = ROUTE_HEAVY
            ctx = RunContext(run_id=run_id, request=request, run_dir=str(run_dir.resolve()),
                             publish_repo=publish_repo)
            outcome = run_heavy(ctx, registry=registry, deps=deps, nemotron_chat=nemotron, budget=budget,
                                trace=trace, sleep=sleep, clock=clock, now=now, run_dir=run_dir,
                                approval_wait_s=approval_wait_s)
            status, text = outcome.status, outcome.text
    except LimitHit as exc:
        if exc.name not in budget.limits_hit:
            budget.limits_hit.append(exc.name)
        status, text = STATUS_FAILED, f"한도 초과: {exc.name}"
        _write_answer(run_dir, run_id, request, route_name, status, text, warnings=budget.warnings)
    except Exception as exc:  # unexpected: still leave run.json and the final trace line
        status, text = STATUS_FAILED, f"예상하지 못한 오류: {type(exc).__name__}"
        budget.warnings.append(f"예상하지 못한 오류: {type(exc).__name__}")
        try:
            _write_answer(run_dir, run_id, request, route_name, status, text, warnings=budget.warnings)
        except Exception:
            pass
    trace.append(EVENT_FINAL, kind=status, summary=one_line(text or status),
                 why="코드 규칙: 실행 끝")
    record = RunRecord(run_id=run_id, request=request, route=route_name, status=status, started_at=utc_ts(started),
                       ended_at=utc_ts(now()),
                       index=IndexInfo(collection=INDEX_COLLECTION, fingerprint=index_fingerprint),
                       limits_hit=list(budget.limits_hit))
    finish_run(run_dir, record, budget)
    return {"run_id": run_id, "status": status, "run_dir": str(run_dir), "text": text}


def _work_list(deps, budget, trace) -> list[str]:
    """Work labels for the router prompt; on a read failure go on without them and leave a warning."""
    try:
        packs = deps.theme_packs()
    except LimitHit:
        raise
    except Exception as exc:
        warning = f"경고: 작품 목록을 읽지 못함({type(exc).__name__})"
        budget.warnings.append(warning)
        trace.append(EVENT_ROUTE, kind="", summary=warning, why="코드 규칙: 목록 없이 무게 판단")
        return []
    return [label for label in (work_label(p) for p in packs or []) if label]


def _light(request, run_id, run_dir, nemotron, budget, trace) -> tuple[str, str]:
    mark = len(budget.call_log)
    messages = [{"role": "system", "content": LIGHT_SYSTEM}, {"role": "user", "content": request}]
    try:
        reply = nemotron(messages, LIGHT_PURPOSE)
    except LimitHit:
        raise
    except Exception as exc:
        model = budget.call_log[-1] if len(budget.call_log) > mark else None
        reason = f"가벼운 답 모델 호출 실패: {type(exc).__name__}"
        trace.append(EVENT_LIGHT_ANSWER, kind="", summary=reason, model=model)
        _write_answer(run_dir, run_id, request, ROUTE_LIGHT, STATUS_FAILED, reason, warnings=budget.warnings)
        return STATUS_FAILED, reason
    model = budget.call_log[-1] if len(budget.call_log) > mark else None
    body = reply.get("text") if isinstance(reply, dict) else ""
    answer = light_answer_text(body if isinstance(body, str) else "")
    trace.append(EVENT_LIGHT_ANSWER, kind=KIND_OK, summary=one_line(answer.split("\n", 1)[-1], 120),
                 why="라우터가 light로 판단", model=model)
    _write_answer(run_dir, run_id, request, ROUTE_LIGHT, STATUS_ANSWERED_LIGHT, answer,
                  label=EVIDENCE_LABEL_LIGHT, warnings=budget.warnings)
    return STATUS_ANSWERED_LIGHT, answer
