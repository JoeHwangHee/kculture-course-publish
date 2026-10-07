"""End-to-end flows of `run_ask` with fake transports and fake tools (spec 2.1, 2.2, 2.4, 4.4, 4.10)."""

import json

import pytest

from common import limits
from common.schema import (
    EVIDENCE_LABEL_LIGHT,
    TEXT_DENIED_BY_SANDBOX,
    TEXT_NO_PLACES_FOR_WORK,
    TEXT_UNAVAILABLE,
    TEXT_USER_SAID_DO_NOT_SEND,
)

from loop.runner import light_answer_text, run_ask


def _light_run(kit, tmp_path, router_replies, nemotron_replies):
    clock = kit.FakeClock()
    router = kit.ScriptedChat(router_replies, model="fake-nemotron-router")
    nemotron = kit.ScriptedChat(nemotron_replies, model="fake-nemotron")
    tools = kit.FakeTools()
    out = run_ask("안녕하세요", registry=tools.registry(), deps_factory=lambda chat: kit.make_deps(chat=chat),
                  router_chat=router, nemotron_chat=nemotron, output_root=tmp_path, clock=clock, sleep=clock.sleep,
                  now=kit.FakeNow())
    return out, router, nemotron, tools, kit.check_run(out["run_dir"], tmp_path)


# ---------------------------------------------------------------- light / unavailable


def test_light_question_answers_with_label_first_line(kit, tmp_path):
    out, router, nemotron, tools, r = _light_run(kit, tmp_path, ['{"weight": "light", "why": "인사"}'],
                                                 ["안녕하세요! 무엇을 도와드릴까요?"])
    assert out["status"] == "ANSWERED_LIGHT"
    assert out["text"].split("\n")[0] == EVIDENCE_LABEL_LIGHT
    assert r["run"].route == "light" and r["run"].status == "ANSWERED_LIGHT"
    assert r["answer"].evidence_label == EVIDENCE_LABEL_LIGHT
    assert r["answer"].answer.startswith(EVIDENCE_LABEL_LIGHT + "\n안녕하세요")
    assert len(nemotron.calls) == 1 and tools.calls == []
    assert r["model_calls"] == {"router": 1, "nemotron": 1}
    assert r["tokens"]["nemotron"]["input"] == 10 and r["tokens"]["router"]["input"] == 10
    assert kit.events(r["trace"]) == ["route", "light_answer", "final"]
    assert r["trace"][0]["model"]["name"] == "fake-nemotron-router"  # the route line names the Nemotron model
    assert r["trace"][1]["model"]["name"] == "fake-nemotron"
    assert r["run"].index.to_dict() == {"collection": "kb", "fingerprint": ""}


def test_light_label_is_not_doubled():
    assert light_answer_text(EVIDENCE_LABEL_LIGHT + "\n본문") == EVIDENCE_LABEL_LIGHT + "\n본문"
    assert light_answer_text("본문") == EVIDENCE_LABEL_LIGHT + "\n본문"


def test_router_fails_twice_is_unavailable_and_nemotron_is_not_called(kit, tmp_path):
    out, router, nemotron, tools, r = _light_run(kit, tmp_path, [TimeoutError("t"), "이건 JSON이 아님"], [])
    assert out["status"] == "UNAVAILABLE"
    assert out["text"] == TEXT_UNAVAILABLE
    assert len(router.calls) == 2 and nemotron.calls == [] and tools.calls == []
    assert r["run"].route == "none"
    assert r["model_calls"] == {"router": 2, "nemotron": 0}
    assert r["answer"].answer == TEXT_UNAVAILABLE
    assert kit.events(r["trace"]) == ["route", "route", "final"]


def test_router_retry_then_heavy(run_heavy_case, kit):
    router = kit.ScriptedChat([ConnectionError("x"), '{"weight": "heavy", "why": "코스"}'])
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], router=router)
    assert r.out["status"] == "PUBLISHED"
    assert r.model_calls["router"] == 2


def test_router_call_does_not_use_the_nemotron_limit(run_heavy_case, kit):
    # router 1 + plan 1 + 7 tool calls = Nemotron 8 exactly: the run ends inside the limit
    tools = kit.FakeTools(chat_calls={"organize_names": limits.NEMOTRON_CALLS_PER_RUN - 1})
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)] + ["{}"] * 10, tools)
    assert r.out["status"] == "PUBLISHED"
    assert r.run.limits_hit == []
    assert r.model_calls == {"router": 1, "nemotron": limits.NEMOTRON_CALLS_PER_RUN}


# ---------------------------------------------------------------- heavy course + publish


def test_course_publish_blocked_waits_then_passes(run_heavy_case, kit):
    tools = kit.FakeTools(publish_kinds=["BLOCKED_BY_POLICY", "BLOCKED_BY_POLICY", "CREATED"])
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], tools)
    assert r.out["status"] == "PUBLISHED"
    assert r.run.route == "heavy" and r.run.status == "PUBLISHED"
    assert [a.result for a in r.publish.attempts] == ["BLOCKED_BY_POLICY", "BLOCKED_BY_POLICY", "CREATED"]
    assert r.publish.issue_url == "https://github.com/o/r/issues/1"
    assert r.publish.repo == "o/r" and r.publish.target == "github-issue"
    assert r.course["publish"] == {"status": "PUBLISHED", "url": "https://github.com/o/r/issues/1"}
    ev = kit.events(r.trace)
    assert ev[:4] == ["route", "step", "plan", "plan_check"]
    assert r.trace[1]["tool"] == "list_input" and r.trace[1]["why"] == "코드 규칙: 계획 전 입력 목록"
    assert ev.count("publish_attempt") == 3 and ev.count("approval_wait") == 2
    assert r.clock.sleeps == [limits.PUBLISH_RETRY_INTERVAL_SECONDS] * 2
    assert tools.calls.count("request_publish") == 3
    assert not hasattr(r, "answer")  # a course run writes course files, not answer.json
    assert r.run.limits_hit == []
    assert "course.json" in r.run.files and "publish.json" in r.run.files


def test_plan_prompt_gets_list_input_and_theme_packs(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)])
    call = r.nemotron.calls[0]
    assert call["purpose"] == "plan" and call["kw"]["response_format"] == {"type": "json_object"}
    user = call["messages"][-1]["content"]
    for part in ("별무리 배경지 코스 짜줘", "note.md", "fx-01", "/hackathon/secrets", "select_places"):
        assert part in user
    assert r.tools.calls[0] == "list_input"


def test_publish_not_requested_is_course_saved_without_sending(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS, publish=False)], request="코스 짜줘. 게시는 하지 마")
    assert r.out["status"] == "COURSE_SAVED"
    assert "request_publish" not in r.tools.calls
    assert not hasattr(r, "publish")
    skipped = [t for t in r.trace if t["event"] == "step" and t["tool"] == "request_publish"]
    assert len(skipped) == 1 and skipped[0]["result"]["summary"] == TEXT_USER_SAID_DO_NOT_SEND
    assert TEXT_USER_SAID_DO_NOT_SEND in r.trace[-1]["result"]["summary"]
    assert r.course["publish"] == {"status": "", "url": None}


def test_course_plan_without_publish_gets_filled_publish_once(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS[:-1])])
    assert r.out["status"] == "PUBLISHED"
    pubs = [t for t in r.trace if t["event"] == "step" and t["tool"] == "request_publish"]
    assert len(pubs) == 1 and pubs[0]["why"] == "코드 규칙: 필수 단계"  # filled, so no end-of-run publish too
    assert r.tools.calls.count("request_publish") == 1


def test_non_course_plan_with_save_gets_publish_at_end(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(["save_course"])])  # no select_places: not filled, end-of-run rule applies
    assert r.out["status"] == "PUBLISHED"
    auto = [t for t in r.trace if t["event"] == "step" and t["tool"] == "request_publish"]
    assert len(auto) == 1 and auto[0]["why"] == "코드 규칙: 코스를 만든 실행은 마지막에 게시 요청"


def test_publish_wait_timeout_is_pending_approval(run_heavy_case, kit):
    tools = kit.FakeTools(publish_kinds=[])  # always blocked
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], tools)
    assert r.out["status"] == "PUBLISH_PENDING_APPROVAL"
    n_resend = limits.APPROVAL_WAIT_SECONDS // limits.PUBLISH_RETRY_INTERVAL_SECONDS
    assert len(r.publish.attempts) == 1 + n_resend
    assert sum(r.clock.sleeps) == limits.APPROVAL_WAIT_SECONDS
    assert r.course["publish"] == {"status": "PUBLISH_PENDING_APPROVAL", "url": None}
    assert r.run.limits_hit == []  # the approval wait does not count as run time


def test_publish_http_error_is_publish_failed_without_wait(run_heavy_case, kit):
    tools = kit.FakeTools(publish_kinds=["HTTP_ERROR"])
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], tools)
    assert r.out["status"] == "PUBLISH_FAILED"
    assert [(a.result, a.http_status) for a in r.publish.attempts] == [("HTTP_ERROR", 422)]
    assert r.clock.sleeps == []


def test_no_resend_after_created(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS + ["request_publish"])])
    assert r.out["status"] == "PUBLISHED"
    assert r.tools.calls.count("request_publish") == 1
    assert len(r.publish.attempts) == 1


# ---------------------------------------------------------------- re-plan


def test_plan_check_failure_then_replan(run_heavy_case, kit):
    bad = kit.plan_json(["select_places", "book_hotel"])
    r = run_heavy_case([bad, kit.plan_json(kit.COURSE_TOOLS)])
    assert r.out["status"] == "PUBLISHED"
    ev = kit.events(r.trace)
    assert ev[2:6] == ["plan", "plan_check", "replan", "plan_check"]
    assert r.trace[3]["result"]["kind"] == "TOOL_ERROR" and "book_hotel" in r.trace[3]["result"]["summary"]
    assert r.trace[5]["result"]["kind"] == "OK"
    assert "book_hotel" in r.nemotron.calls[1]["messages"][-1]["content"]
    assert "book_hotel" not in r.tools.calls


def test_replan_also_failing_is_failed(run_heavy_case, kit):
    r = run_heavy_case(["계획 없음", kit.plan_json(["nope"])])
    assert r.out["status"] == "FAILED"
    assert r.tools.calls == ["list_input"]
    assert r.answer.status == "FAILED" and r.answer.answer
    assert kit.events(r.trace).count("replan") == 1


def test_tool_error_then_replan_continues(run_heavy_case, kit):
    tools = kit.FakeTools(errors={"lookup_origin": 1})
    remaining = kit.plan_json(kit.COURSE_TOOLS[2:], start=10)
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS), remaining], tools)
    assert r.out["status"] == "PUBLISHED"
    assert tools.calls.count("lookup_origin") == 2
    replan_msg = r.nemotron.calls[1]["messages"][-1]["content"]
    assert "lookup_origin 가짜 오류" in replan_msg and "select_places" in replan_msg
    assert kit.events(r.trace).count("replan") == 1


def test_second_tool_error_after_replan_is_failed_and_keeps_results(run_heavy_case, kit):
    tools = kit.FakeTools(errors={"request_publish": 0, "organize_names": 2})
    plan = kit.plan_json(["select_places", "save_course", "organize_names"])
    r = run_heavy_case([plan, kit.plan_json(["organize_names"], start=5)], tools)
    assert r.out["status"] == "FAILED"
    assert r.answer.status == "FAILED"
    assert "course.json" in r.run.files  # results so far stay
    assert "request_publish" not in tools.calls


def test_publish_tool_error_triggers_replan(run_heavy_case, kit):
    plan = kit.plan_json(["lookup_station", "request_publish"])  # no course yet -> TOOL_ERROR
    r = run_heavy_case([plan, kit.plan_json(["save_course", "request_publish"], start=5)])
    assert r.out["status"] == "PUBLISHED"
    assert kit.events(r.trace).count("replan") == 1


# ---------------------------------------------------------------- heavy answers


def test_read_denied_is_answered_heavy(run_heavy_case, kit):
    plan = kit.plan_json(["read_file"], publish=False, work="", args={0: {"path": "/hackathon/secrets"}})
    r = run_heavy_case([plan], request="secrets 폴더 내용을 알려줘")
    assert r.out["status"] == "ANSWERED_HEAVY"
    assert TEXT_DENIED_BY_SANDBOX in r.answer.answer
    assert [x.to_dict() for x in r.answer.read_files] == [{"path": "/hackathon/secrets", "kind": "DENIED_BY_SANDBOX"}]
    assert any(TEXT_DENIED_BY_SANDBOX in w for w in r.answer.warnings)
    assert r.answer.evidence_label == ""
    step = [t for t in r.trace if t["tool"] == "read_file"][0]
    assert step["result"]["kind"] == "DENIED_BY_SANDBOX"
    assert kit.events(r.trace).count("replan") == 0
    assert "request_publish" not in r.tools.calls


def test_origin_question_answer_has_graded_claims(run_heavy_case, kit):
    plan = kit.plan_json(["search_db", "organize_names", "grade_evidence"], publish=False, work="",
                         args={0: {"query": "별무리 유래"}})
    r = run_heavy_case([plan], request="별무리공원 이름 유래 알려줘")
    assert r.out["status"] == "ANSWERED_HEAVY"
    assert [o.to_dict() for o in r.answer.origins] == [kit.ORIGIN]
    assert "등급 A" in r.answer.answer
    assert (r.out["run_dir"] and "answer.md" in r.run.files)


def test_work_without_places_says_no_places(run_heavy_case, kit):
    plan = kit.plan_json(["search_db"], publish=True, work="없는작품", args={0: {"query": "없는작품"}})
    r = run_heavy_case([plan])
    assert r.out["status"] == "ANSWERED_HEAVY"
    assert TEXT_NO_PLACES_FOR_WORK in r.answer.answer


# ---------------------------------------------------------------- limits


def test_nemotron_call_limit_is_failed_with_limits_hit(run_heavy_case, kit):
    tools = kit.FakeTools(chat_calls={"organize_names": 9})
    replies = [kit.plan_json(kit.COURSE_TOOLS)] + ["{}"] * 20
    r = run_heavy_case(replies, tools)
    assert r.out["status"] == "FAILED"
    assert r.run.limits_hit == ["nemotron_calls"]
    assert r.model_calls["nemotron"] == limits.NEMOTRON_CALLS_PER_RUN  # tool calls went through the Budget
    assert kit.events(r.trace).count("replan") == 0
    assert r.answer.status == "FAILED"


def test_tool_step_limit_is_failed_with_limits_hit(run_heavy_case, kit):
    tools = kit.FakeTools(errors={"organize_names": 1})
    first = kit.plan_json(["lookup_station"] * 10 + ["save_course", "organize_names"])  # 12 steps, the 12th fails
    r = run_heavy_case([first, kit.plan_json(["organize_names"], start=20)], tools)  # re-planned step = 13th
    assert r.out["status"] == "FAILED"
    assert r.run.limits_hit == ["tool_steps"]
    assert tools.calls.count("organize_names") == 1  # the 13th step is not run
    assert "request_publish" not in tools.calls
    assert "course.json" in r.run.files


def test_end_of_run_publish_is_not_a_tool_step(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(["lookup_station"] * 11 + ["save_course"])])  # 12 steps + automatic publish
    assert r.out["status"] == "PUBLISHED"
    assert r.run.limits_hit == []
    assert r.tools.calls.count("request_publish") == 1


def test_budget_warnings_reach_course_json(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], nemotron_usage=None)
    assert r.out["status"] == "PUBLISHED"
    assert any("usage가 없어" in w for w in r.course["warnings"])
    assert len(r.course["warnings"]) == len(set(r.course["warnings"]))


def test_plan_missing_why_and_constraints_runs_without_replan(run_heavy_case, kit):
    plan = json.loads(kit.plan_json(kit.COURSE_TOOLS))
    del plan["goal"]["constraints"]
    del plan["goal"]["publish_requested"]
    for step in plan["steps"]:
        del step["why"]
    del plan["steps"][1]["args"]
    r = run_heavy_case([json.dumps(plan, ensure_ascii=False)])
    assert r.out["status"] == "PUBLISHED"  # publish_requested defaults to true
    assert kit.events(r.trace).count("replan") == 0
    check = [t for t in r.trace if t["event"] == "plan_check"][0]
    assert check["result"]["kind"] == "OK"
    assert "기본값 채움: goal.constraints, goal.publish_requested, steps[0].why" in check["result"]["summary"]
    assert r.course["goal"]["constraints"] == []


def test_publish_exception_keeps_attempts_in_ask(run_heavy_case, kit):
    tools = kit.FakeTools(publish_kinds=["BLOCKED_BY_POLICY", "BOOM"])
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], tools)
    assert r.out["status"] == "FAILED"
    assert [a.result for a in r.publish.attempts] == ["BLOCKED_BY_POLICY"]
    assert r.publish.status == "PUBLISH_PENDING_APPROVAL"


def test_run_time_limit_is_failed(run_heavy_case, kit, clock):
    tools = kit.FakeTools(on_step={"select_places": lambda: clock.sleep(limits.RUN_SECONDS + 1)})
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], tools)
    assert r.out["status"] == "FAILED"
    assert r.run.limits_hit == ["run_seconds"]
    assert "lookup_station" not in tools.calls


def test_plan_over_twelve_steps_fails_check(run_heavy_case, kit):
    long_plan = kit.plan_json(["lookup_station"] * 13)
    r = run_heavy_case([long_plan, kit.plan_json(kit.COURSE_TOOLS)])
    assert r.trace[3]["result"]["kind"] == "TOOL_ERROR"
    assert r.out["status"] == "PUBLISHED"


# ---------------------------------------------------------------- unexpected errors


def test_unexpected_error_still_writes_run_and_final(run_heavy_case, kit):
    def broken(chat):
        raise KeyError("boom")

    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], deps_factory=broken)
    assert r.out["status"] == "FAILED"
    assert r.trace[-1]["result"]["kind"] == "FAILED"
    assert any("KeyError" in w for w in r.answer.warnings)


def test_trace_steps_have_model_only_when_called(run_heavy_case, kit):
    tools = kit.FakeTools(chat_calls={"organize_names": 1})
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS), "{}"], tools)
    steps = {t["tool"]: t for t in r.trace if t["event"] == "step"}
    assert steps["organize_names"]["model"]["purpose"] == "organize_names"
    assert steps["lookup_station"]["model"] is None
    plan = [t for t in r.trace if t["event"] == "plan"][0]
    assert plan["model"]["name"] == "fake-nemotron"
    assert json.dumps(r.trace, ensure_ascii=False).count("course.json") == 0


def _swallowing_organize_names(n_calls):
    """Like the real tool: every deps.chat exception (LimitHit included) becomes TOOL_ERROR."""
    from common.tooling import ToolResult

    def run(args, ctx, deps):
        for _ in range(n_calls):
            try:
                deps.chat([{"role": "user", "content": "묶어 줘"}], "organize_names")
            except Exception as exc:
                return ToolResult.tool_error(f"모델 호출 실패: {type(exc).__name__}")
        return ToolResult.success()

    return run


def _forbid_replan(monkeypatch):
    """Make any entry into re-planning fail the test at once (pytest.fail is a BaseException, not caught)."""
    from loop.executor import HeavyRun

    calls = []

    def no_replan(self, **what):
        calls.append(what)
        pytest.fail("re-plan must not start after a limit was hit inside a tool")

    monkeypatch.setattr(HeavyRun, "_replan", no_replan)
    return calls


def _no_tool_error_step(trace, tool):
    return not [t for t in trace if t["event"] == "step" and t["tool"] == tool]


def test_limit_swallowed_by_tool_still_fails_nemotron_calls(run_heavy_case, kit, monkeypatch):
    replans = _forbid_replan(monkeypatch)
    tools = kit.FakeTools(overrides={"organize_names": _swallowing_organize_names(limits.NEMOTRON_CALLS_PER_RUN + 1)})
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)] + ["{}"] * 20, tools)
    assert r.out["status"] == "FAILED"
    assert r.run.limits_hit == ["nemotron_calls"]
    assert kit.events(r.trace).count("replan") == 0
    assert "grade_evidence" not in tools.calls
    assert tools.calls.count("organize_names") == 1  # the tool ran and swallowed the LimitHit
    assert replans == []
    assert _no_tool_error_step(r.trace, "organize_names")  # no TOOL_ERROR step line for the swallowing tool
    # verify_trace(...) == [] and the final line are checked by run_heavy_case (conftest.check_run)
    assert r.trace[-1]["result"]["kind"] == "FAILED"


def test_limit_swallowed_by_tool_still_fails_tokens(run_heavy_case, kit, monkeypatch):
    replans = _forbid_replan(monkeypatch)
    big = {"input": limits.TOKENS_PER_RUN // 2 + 1, "output": 0}  # the plan fits; the tool's first call goes over
    tools = kit.FakeTools(overrides={"organize_names": _swallowing_organize_names(3)})
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)] + ["{}"] * 5, tools, nemotron_usage=big)
    assert r.out["status"] == "FAILED"
    assert r.run.limits_hit == ["tokens"]
    assert kit.events(r.trace).count("replan") == 0
    assert "grade_evidence" not in tools.calls
    assert tools.calls.count("organize_names") == 1  # the tool ran and swallowed the LimitHit
    assert replans == []
    assert _no_tool_error_step(r.trace, "organize_names")  # no TOOL_ERROR step line for the swallowing tool
    assert r.trace[-1]["result"]["kind"] == "FAILED"


# ---------------------------------------------------------------- approval wait limit (0014)


def _wait_run(tmp_path, kit, wait_s):
    clock = kit.FakeClock()
    tools = kit.FakeTools(publish_kinds=[])  # always blocked
    out = run_ask("별무리 코스 짜줘", registry=tools.registry(), deps_factory=lambda chat: kit.make_deps(chat=chat),
                  router_chat=kit.ScriptedChat(['{"weight": "heavy"}']),
                  nemotron_chat=kit.ScriptedChat([kit.plan_json(kit.COURSE_TOOLS)]), output_root=tmp_path,
                  publish_repo="o/r", clock=clock, sleep=clock.sleep, now=kit.FakeNow(), approval_wait_s=wait_s)
    return out, clock, tools, kit.check_run(out["run_dir"], tmp_path)


def test_wait_limit_zero_ends_pending_without_waiting(kit, tmp_path):
    out, clock, tools, r = _wait_run(tmp_path, kit, 0)
    assert out["status"] == "PUBLISH_PENDING_APPROVAL"
    assert len(r["publish"].attempts) == 1 and tools.calls.count("request_publish") == 1
    assert clock.sleeps == []
    waits = [t for t in r["trace"] if t["event"] == "approval_wait"]
    assert len(waits) == 1
    assert waits[0]["args"] == {"wait_limit_s": 0}
    assert waits[0]["result"]["summary"] == "승인 대기 한도 0초: 기다리지 않음"


def test_wait_limit_below_interval_does_not_wait(kit, tmp_path):
    out, clock, tools, r = _wait_run(tmp_path, kit, limits.PUBLISH_RETRY_INTERVAL_SECONDS - 1)
    assert out["status"] == "PUBLISH_PENDING_APPROVAL"
    assert len(r["publish"].attempts) == 1 and clock.sleeps == []


def test_wait_limit_thirty_resends_three_times(kit, tmp_path):
    out, clock, tools, r = _wait_run(tmp_path, kit, 30)
    assert out["status"] == "PUBLISH_PENDING_APPROVAL"
    assert len(r["publish"].attempts) == 1 + 3
    assert clock.sleeps == [limits.PUBLISH_RETRY_INTERVAL_SECONDS] * 3
    waits = [t for t in r["trace"] if t["event"] == "approval_wait"]
    assert waits[0]["args"] == {"wait_limit_s": 30} and len(waits) == 3


def test_default_wait_limit_is_unchanged(kit, tmp_path):
    out, clock, tools, r = _wait_run(tmp_path, kit, limits.APPROVAL_WAIT_SECONDS)
    assert len(r["publish"].attempts) == 1 + limits.APPROVAL_WAIT_SECONDS // limits.PUBLISH_RETRY_INTERVAL_SECONDS


# ---------------------------------------------------------------- router work list (0019)


def test_router_prompt_gets_theme_pack_works(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)])
    system = r.router.calls[0]["messages"][0]["content"]
    assert "별무리(별)" in system  # work_title(aliases) of the fake theme pack
    assert "케데헌 보고 왔어요" not in system


def test_theme_pack_failure_leaves_warning_and_still_routes(run_heavy_case, kit):
    def deps_factory(chat):
        deps = kit.make_deps(chat=chat)

        def broken():
            raise OSError("팩 없음")

        import dataclasses
        return dataclasses.replace(deps, theme_packs=broken)

    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], deps_factory=deps_factory)
    first = r.trace[0]
    assert first["event"] == "route" and first["result"] == {"kind": "", "summary": "경고: 작품 목록을 읽지 못함(OSError)"}
    assert r.trace[1]["event"] == "route" and r.trace[1]["result"] == {"kind": "OK", "summary": "heavy"}
    assert "(목록 없음)" in r.router.calls[0]["messages"][0]["content"]
    assert r.run.route == "heavy"
    assert any("작품 목록을 읽지 못함" in w for w in r.course["warnings"])  # budget warning carried to the course


# ---------------------------------------------------------------- course plan fill (0022)


def _steps(r):
    return [(t["tool"], t["why"]) for t in r.trace if t["event"] == "step" and t["tool"] != "list_input"]


def test_select_places_only_plan_is_filled_to_eight_steps(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(["select_places"])])
    assert r.out["status"] == "PUBLISHED"
    assert [t for t, _ in _steps(r)] == kit.COURSE_TOOLS
    assert all(why == "코드 규칙: 필수 단계" for t, why in _steps(r)[1:])
    check = [t for t in r.trace if t["event"] == "plan_check"][0]
    assert check["result"]["kind"] == "OK"
    assert ("코드 규칙: 코스 계획의 빠진 단계를 채움: [lookup_station, lookup_origin, lookup_operating, "
            "organize_names, grade_evidence, save_course, request_publish]") in check["result"]["summary"]
    assert r.tools.calls.count("request_publish") == 1
    assert kit.events(r.trace).count("replan") == 0


def test_fill_without_publish_requested_is_course_saved(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(["select_places"], publish=False)])
    assert r.out["status"] == "COURSE_SAVED"
    assert [t for t, _ in _steps(r)] == kit.COURSE_TOOLS[:-1]
    assert "request_publish" not in r.tools.calls


def test_fill_keeps_model_order_and_inserts_only_missing(run_heavy_case, kit):
    plan = kit.plan_json(["select_places", "lookup_origin", "lookup_station", "save_course"],
                         args={1: {"k": 3}})
    r = run_heavy_case([plan])
    tools = [t for t, _ in _steps(r)]
    assert tools == ["select_places", "lookup_origin", "lookup_station", "lookup_operating", "organize_names",
                     "grade_evidence", "save_course", "request_publish"]
    origin = [t for t in r.trace if t["event"] == "step" and t["tool"] == "lookup_origin"][0]
    assert origin["args"] == {"k": 3} and origin["why"] == "lookup_origin 단계"


def test_plan_without_select_places_is_not_filled(run_heavy_case, kit):
    plan = kit.plan_json(["read_file"], publish=True, work="", args={0: {"path": "/hackathon/secrets"}})
    r = run_heavy_case([plan])
    assert r.out["status"] == "ANSWERED_HEAVY"
    assert [t for t, _ in _steps(r)] == ["read_file"]
    assert "채움" not in [t for t in r.trace if t["event"] == "plan_check"][0]["result"]["summary"]


def test_fill_over_twelve_drops_optional_steps_from_the_end(run_heavy_case, kit):
    tools_list = ["select_places"] + ["search_db"] * 10  # 11 steps + 7 filled -> 6 optional steps dropped
    plan = kit.plan_json(tools_list, args={i: {"query": f"q{i}"} for i in range(1, 11)})
    r = run_heavy_case([plan])
    assert r.out["status"] == "PUBLISHED"
    steps = [t for t, _ in _steps(r)]
    assert len(steps) == limits.PLAN_STEPS_MAX and steps.count("search_db") == 4
    summary = [t for t in r.trace if t["event"] == "plan_check"][0]["result"]["summary"]
    assert "단계 수 한도로 뺀 선택 단계: [s11:search_db" in summary


def test_fill_unit_ids_do_not_collide():
    from common.schema import Plan
    from loop.planner import fill_course_steps

    goal = {"work": "", "time_budget_min": None, "start": "", "constraints": [], "publish_requested": True}
    plan = Plan.from_dict({"goal": goal, "steps": [{"id": "f1", "tool": "select_places", "args": {}, "why": ""}]})
    filled, dropped = fill_course_steps(plan)
    ids = [s.id for s in plan.steps]
    assert len(ids) == len(set(ids)) == 8 and dropped == [] and len(filled) == 7



# ---------------------------------------------------------------- 0025


def test_replan_without_select_places_refills_failed_required_step(run_heavy_case, kit):
    tools = kit.FakeTools(errors={"organize_names": 1})
    replan = kit.plan_json(["grade_evidence", "save_course", "request_publish"], start=20)
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS), replan], tools)
    assert r.out["status"] == "PUBLISHED"
    assert tools.calls.count("organize_names") == 2  # failed once, filled again before grade_evidence
    for done in ("select_places", "lookup_station", "lookup_origin", "lookup_operating"):
        assert tools.calls.count(done) == 1  # already succeeded: not run again
    after_replan = [t["tool"] for t in r.trace if t["event"] == "step"][6:]
    assert after_replan == ["organize_names", "grade_evidence", "save_course", "request_publish"]
    check = [t for t in r.trace if t["event"] == "plan_check"][-1]
    assert "코드 규칙: 코스 계획의 빠진 단계를 채움: [organize_names]" in check["result"]["summary"]


def test_replan_with_select_places_again_does_not_refill_done_steps(run_heavy_case, kit):
    tools = kit.FakeTools(errors={"organize_names": 1})
    replan = kit.plan_json(["select_places", "grade_evidence", "save_course"], start=20)
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS), replan], tools)
    assert r.out["status"] == "PUBLISHED"
    assert tools.calls.count("lookup_station") == 1 and tools.calls.count("organize_names") == 2
    check = [t for t in r.trace if t["event"] == "plan_check"][-1]
    assert "[organize_names, request_publish]" in check["result"]["summary"]


def test_cut_answer_is_marked_on_the_step(run_heavy_case, kit):
    tools = kit.FakeTools(chat_calls={"organize_names": 1})
    cut = {"text": '{"names": [', "finish_reason": "length"}
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS), cut], tools)
    step = [t for t in r.trace if t["event"] == "step" and t["tool"] == "organize_names"][0]
    assert step["result"]["summary"].endswith("; 모델 답이 출력 한도에서 잘림")
    other = [t for t in r.trace if t["event"] == "step" and t["tool"] == "lookup_station"][0]
    assert "잘림" not in other["result"]["summary"]
    assert "organize_names: 모델 답이 출력 한도에서 잘림" in r.course["warnings"]  # budget warning carried


def test_cut_plan_answer_is_marked_on_the_plan_line(run_heavy_case, kit):
    r = run_heavy_case([{"text": kit.plan_json(kit.COURSE_TOOLS), "finish_reason": "length"}])
    plan = [t for t in r.trace if t["event"] == "plan"][0]
    assert plan["result"]["summary"].endswith("; 모델 답이 출력 한도에서 잘림")


# ---------------------------------------------------------------- 0028


def test_evidence_steps_after_organize_names_move_before_it(run_heavy_case, kit):
    tools_list = ["select_places", "lookup_station", "lookup_origin", "lookup_operating", "organize_names",
                  "grade_evidence", "read_file", "read_file", "read_file"]
    args = {6: {"path": "/hackathon/input/a.md"}, 7: {"path": "/hackathon/input/b.md"},
            8: {"path": "/hackathon/input/c.md"}}
    r = run_heavy_case([kit.plan_json(tools_list, args=args)])
    assert r.out["status"] == "PUBLISHED"
    assert [t for t, _ in _steps(r)] == ["select_places", "lookup_station", "lookup_origin", "lookup_operating",
                                         "read_file", "read_file", "read_file", "organize_names", "grade_evidence",
                                         "save_course", "request_publish"]
    reads = [t["args"]["path"] for t in r.trace if t["event"] == "step" and t["tool"] == "read_file"]
    assert reads == ["/hackathon/input/a.md", "/hackathon/input/b.md", "/hackathon/input/c.md"]
    check = [t for t in r.trace if t["event"] == "plan_check"][0]["result"]["summary"]
    assert "코드 규칙: 근거 수집 단계를 정리 앞으로 옮김: [read_file, read_file, read_file]" in check


def test_evidence_steps_already_in_front_stay(run_heavy_case, kit):
    plan = kit.plan_json(["read_file"] + kit.COURSE_TOOLS, args={0: {"path": "/hackathon/input/a.md"}})
    r = run_heavy_case([plan])
    assert [t for t, _ in _steps(r)] == ["read_file"] + kit.COURSE_TOOLS
    check = [t for t in r.trace if t["event"] == "plan_check"][0]["result"]["summary"]
    assert "옮김" not in check


def test_replan_without_organize_names_moves_evidence_before_save_course(run_heavy_case, kit):
    tools = kit.FakeTools(errors={"grade_evidence": 1})
    replan = kit.plan_json(["grade_evidence", "save_course", "search_db", "request_publish"], start=20,
                           args={2: {"query": "유래"}})
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS), replan], tools)
    assert r.out["status"] == "PUBLISHED"
    after_replan = [t["tool"] for t in r.trace if t["event"] == "step"][7:]
    assert after_replan == ["grade_evidence", "search_db", "save_course", "request_publish"]
    check = [t for t in r.trace if t["event"] == "plan_check"][-1]["result"]["summary"]
    assert "근거 수집 단계를 정리 앞으로 옮김: [search_db]" in check
