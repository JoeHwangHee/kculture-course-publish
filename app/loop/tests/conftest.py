"""Fakes for the loop flow tests: scripted chats, a fake clock, fake tools and Deps, and record checks.

Nothing here touches the network or a key. `sleep` only moves the fake clock forward.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from common.schema import (
    ANSWER_JSON,
    COURSE_JSON,
    COURSE_MD,
    PUBLISH_JSON,
    RUN_JSON,
    SECRETS_DIR,
    TEXT_DENIED_BY_SANDBOX,
    TRACE_JSONL,
    AnswerRecord,
    Course,
    ModelCalls,
    PublishRecord,
    RunRecord,
    Tokens,
    split_trace_lines,
    verify_trace,
)
from common.tooling import Deps, ToolRegistry, ToolResult, ToolSpec

USAGE = {"input": 10, "output": 5}


class ScriptedChat:
    """Returns the scripted replies in order (str -> text, Exception -> raised). Records every call."""

    def __init__(self, replies=(), model="fake-model", usage=USAGE):
        self.replies = list(replies)
        self.model = model
        self.usage = usage
        self.calls: list[dict] = []

    def __call__(self, messages, purpose, **kw):
        self.calls.append({"messages": messages, "purpose": purpose, "kw": kw})
        if not self.replies:
            raise RuntimeError("scripted chat ran out of replies")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        finish = "stop"
        if isinstance(reply, dict):  # {"text", "finish_reason"} for a cut answer
            reply, finish = reply["text"], reply.get("finish_reason", "stop")
        usage = dict(self.usage) if self.usage is not None else None
        return {"text": reply, "usage": usage, "model": self.model, "latency_ms": 1.0, "finish_reason": finish}


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class FakeNow:
    """UTC clock that moves one millisecond per call (trace ts stays valid)."""

    def __init__(self):
        self.t = datetime(2026, 10, 7, 3, 31, 5, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.t += timedelta(milliseconds=1)
        return self.t


def plan_json(tools, *, publish=True, work="별무리", args=None, start=0) -> str:
    """A 4.5 plan as text. `tools` are names; `args` maps step index -> args."""
    args = args or {}
    steps = [{"id": f"s{start + i + 1}", "tool": t, "args": args.get(i, {}), "why": f"{t} 단계"}
             for i, t in enumerate(tools)]
    goal = {"work": work, "time_budget_min": 180, "start": "혜화", "constraints": [], "publish_requested": publish}
    return json.dumps({"goal": goal, "steps": steps}, ensure_ascii=False)


COURSE_TOOLS = ["select_places", "lookup_station", "lookup_origin", "lookup_operating", "organize_names",
                "grade_evidence", "save_course", "request_publish"]

ORIGIN = {"name": "별무리공원", "name_kind": "current", "summary": "별이 무리 지어 보이던 언덕", "grade": "A",
          "source_ids": ["fx-src-1"], "chunk_ids": ["c1"], "input_paths": []}


def course_place() -> dict:
    return {"order": 1, "place_id": "fx-01", "current_name": "별무리공원", "in_work_name": "별빛광장", "scene": "첫 장면",
            "old_names": [], "station": {"name": "혜화", "line": "4호선"}, "travel_min_from_prev": 10,
            "travel_mode": "walk", "travel_basis": "cited", "travel_chunk_ids": [], "stay_min": 30, "arrive_min": 10,
            "origins": [dict(ORIGIN)], "conflicts": [],
            "operating": {"status": "UNKNOWN", "hours": "", "closed": "", "source_ids": [], "as_of": ""}, "stale": []}


class FakeTools:
    """Fake tools that fill RunContext keys like the real ones. `publish_kinds` scripts request_publish."""

    def __init__(self, publish_kinds=("CREATED",), errors=None, chat_calls=None, on_step=None, overrides=None):
        self.overrides = dict(overrides or {})  # tool name -> body(args, ctx, deps) replacing the default fake
        self.publish_kinds = list(publish_kinds)
        self.errors = dict(errors or {})  # tool name -> number of TOOL_ERROR results to give first
        self.chat_calls = dict(chat_calls or {})  # tool name -> deps.chat calls per run
        self.on_step = on_step or {}  # tool name -> callable() run before the tool
        self.calls: list[str] = []

    def _wrap(self, name, body):
        def run(args, ctx, deps):
            self.calls.append(name)
            if name in self.on_step:
                self.on_step[name]()
            if self.errors.get(name, 0) > 0:
                self.errors[name] -= 1
                return ToolResult.tool_error(f"{name} 가짜 오류")
            for _ in range(self.chat_calls.get(name, 0)):
                try:  # real tools turn a model failure into TOOL_ERROR
                    deps.chat([{"role": "user", "content": "x"}], name)
                except Exception as exc:
                    return ToolResult.tool_error(f"모델 호출 실패: {type(exc).__name__}")
            return body(args, ctx, deps)
        return run

    def list_input(self, args, ctx, deps):
        ctx.input_files = [{"path": "note.md", "size": 12}]
        return ToolResult.success({"files": ctx.input_files})

    def select_places(self, args, ctx, deps):
        ctx.places = [{"place_id": "fx-01", "current_name": "별무리공원", "priority": 1, "pack_id": "fx"}]
        return ToolResult.success({"places": 1})

    def noop(self, args, ctx, deps):
        return ToolResult.success()

    def grade_evidence(self, args, ctx, deps):
        key = ctx.places[0]["place_id"] if ctx.places else "_"
        ctx.graded = {key: {"origins": [dict(ORIGIN)], "conflicts": [], "operating": {}, "stale": []}}
        return ToolResult.success({"graded": 1})

    def save_course(self, args, ctx, deps):
        course = {"run_id": ctx.run_id, "request": ctx.request, "goal": dict(ctx.goal), "places": [course_place()],
                  "total_min": 40, "excluded": [], "unknowns": [], "warnings": list(ctx.warnings),
                  "publish": {"status": "", "url": None}}
        Course.from_dict(course)
        run_dir = pathlib.Path(ctx.run_dir)
        (run_dir / COURSE_JSON).write_text(json.dumps(course, ensure_ascii=False), encoding="utf-8")
        (run_dir / COURSE_MD).write_text("# 코스\n", encoding="utf-8")
        ctx.course = course
        return ToolResult.success({"places": 1, "path": str(run_dir / COURSE_JSON)})

    def request_publish(self, args, ctx, deps):
        if not ctx.course or not ctx.publish_repo:
            return ToolResult.tool_error("코스나 게시 저장소가 없음")
        kind = self.publish_kinds.pop(0) if self.publish_kinds else "BLOCKED_BY_POLICY"
        if kind == "BOOM":
            raise RuntimeError("가짜 전송 예외")
        if kind == "CREATED":
            return ToolResult(ok=True, kind=kind, data={"http_status": 201,
                                                        "issue_url": "https://github.com/o/r/issues/1"})
        status = {"BLOCKED_BY_POLICY": None, "HTTP_ERROR": 422, "NETWORK_ERROR": None}[kind]
        return ToolResult(ok=False, kind=kind, data={"http_status": status, "issue_url": None})

    def read_file(self, args, ctx, deps):
        path = args["path"]
        if path.startswith(SECRETS_DIR):
            ctx.read_files[path] = {"kind": "DENIED_BY_SANDBOX", "text": "", "front_matter": {}, "dates": [],
                                    "entries": []}
            return ToolResult(ok=False, kind="DENIED_BY_SANDBOX", data={"note": TEXT_DENIED_BY_SANDBOX},
                              error="Permission denied")
        ctx.read_files[path] = {"kind": "file", "text": "본문", "front_matter": {}, "dates": [], "entries": []}
        return ToolResult.success({"bytes": 6})

    def search_db(self, args, ctx, deps):
        ctx.search_results = deps.search(args["query"], args["k"])
        return ToolResult.success({"hits": len(ctx.search_results)})

    def registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        bodies = {
            "list_input": self.list_input, "select_places": self.select_places, "lookup_station": self.noop,
            "lookup_origin": self.noop, "lookup_operating": self.noop, "organize_names": self.noop,
            "grade_evidence": self.grade_evidence, "save_course": self.save_course,
            "request_publish": self.request_publish, "search_db": self.search_db, "read_file": self.read_file,
        }
        bodies.update(self.overrides)
        for name, body in bodies.items():
            reg.register(ToolSpec(name=name, run=self._wrap(name, body), description=f"가짜 {name}"))
        return reg


def make_deps(chat=None, now=None) -> Deps:
    return Deps(
        search=lambda query, k: [{"chunk_id": "c1", "title": "가짜 자료"}],
        get_chunk=lambda chunk_id: None,
        chunks_where=lambda kind, place_id: [],
        theme_packs=lambda: [{"pack_id": "fx", "work_title": "별무리", "aliases": ["별"],
                              "places": [{"place_id": "fx-01", "current_name": "별무리공원",
                                          "in_work_name": "별빛광장", "scene": "첫 장면", "priority": 1}]}],
        chat=chat or (lambda messages, purpose: {"text": "", "usage": None, "model": "x"}),
        http_post_json=lambda url, headers, body: {"status": None, "body": "", "error": "NETWORK"},
        read_path=lambda path, max_bytes: b"",
        now=now or (lambda: datetime(2026, 10, 7, tzinfo=timezone.utc)),
    )


def check_run(run_dir, tmp_path) -> dict:
    """Common checks for every run folder; returns the parsed records."""
    run_dir = pathlib.Path(run_dir)
    text = (run_dir / TRACE_JSONL).read_text(encoding="utf-8")
    lines = split_trace_lines(text)
    assert verify_trace(lines) == []
    assert str(tmp_path) not in text
    assert str(pathlib.Path(tmp_path).resolve()) not in text
    trace = [json.loads(line) for line in lines]
    assert trace[-1]["event"] == "final"
    run_data = json.loads((run_dir / RUN_JSON).read_text(encoding="utf-8"))
    # 4.4 as revised by 0010: model_calls / tokens keyed exactly by router and nemotron (no other model key)
    assert set(run_data["model_calls"]) == {"router", "nemotron"}
    assert set(run_data["tokens"]) == {"router", "nemotron"}
    assert all(set(v) == {"input", "output"} for v in run_data["tokens"].values())
    # the other keys are checked with the common record (its own default counters stand in for the two above)
    run = RunRecord.from_dict({**run_data, "model_calls": ModelCalls().to_dict(), "tokens": Tokens().to_dict()})
    assert RUN_JSON in run.files and TRACE_JSONL in run.files
    out = {"trace": trace, "run": run, "model_calls": run_data["model_calls"], "tokens": run_data["tokens"]}
    if (run_dir / ANSWER_JSON).exists():
        out["answer"] = AnswerRecord.from_dict(json.loads((run_dir / ANSWER_JSON).read_text(encoding="utf-8")))
    if (run_dir / PUBLISH_JSON).exists():
        out["publish"] = PublishRecord.from_dict(json.loads((run_dir / PUBLISH_JSON).read_text(encoding="utf-8")))
    if (run_dir / COURSE_JSON).exists():
        out["course"] = json.loads((run_dir / COURSE_JSON).read_text(encoding="utf-8"))
    return out


def events(trace) -> list[str]:
    return [t["event"] for t in trace]


@pytest.fixture
def kit():
    return SimpleNamespace(ScriptedChat=ScriptedChat, FakeClock=FakeClock, FakeNow=FakeNow, FakeTools=FakeTools,
                           plan_json=plan_json, COURSE_TOOLS=COURSE_TOOLS, ORIGIN=ORIGIN, make_deps=make_deps,
                           check_run=check_run, events=events)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def run_heavy_case(tmp_path, clock):
    """Run `run_ask` on the heavy route with the given Nemotron script and fake tools."""
    from loop.runner import run_ask

    def go(nemotron_replies, tools=None, *, request="별무리 배경지 코스 짜줘", router=None, publish_repo="o/r",
           deps_factory=None, nemotron_usage=USAGE):
        tools = tools or FakeTools()
        nemotron = ScriptedChat(nemotron_replies, model="fake-nemotron", usage=nemotron_usage)
        router = router or ScriptedChat(['{"weight": "heavy", "why": "코스 요청"}'], model="fake-nemotron")
        out = run_ask(request, registry=tools.registry(),
                      deps_factory=deps_factory or (lambda chat: make_deps(chat=chat)),
                      router_chat=router, nemotron_chat=nemotron, output_root=tmp_path, publish_repo=publish_repo,
                      index_fingerprint="fp", clock=clock, sleep=clock.sleep, now=FakeNow())
        checked = check_run(out["run_dir"], tmp_path)
        return SimpleNamespace(out=out, tools=tools, nemotron=nemotron, router=router, clock=clock, **checked)

    return go
