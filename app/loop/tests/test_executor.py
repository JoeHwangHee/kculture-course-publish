"""Heavy-path details of the executor (spec 2.2, 4.2)."""

from common.schema import TEXT_DENIED_BY_SANDBOX
from common.tooling import ToolResult

from loop.executor import _result_summary, one_line


def test_result_summary_leaves_out_free_strings():
    res = ToolResult.success({"path": "/somewhere/local/course.json", "places": 3, "items": [1, 2], "ok": True})
    s = _result_summary(res)
    assert "/somewhere" not in s and "places=3" in s and "items=2개" in s
    assert _result_summary(ToolResult.tool_error("줄\n바꿈")) == "줄 바꿈"
    assert one_line("a\nb  c") == "a b c"


def test_replan_keeps_the_first_goal(run_heavy_case, kit):
    tools = kit.FakeTools(errors={"lookup_origin": 1})
    flipped = kit.plan_json(kit.COURSE_TOOLS[2:], publish=False, start=10)
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS), flipped], tools)
    assert r.out["status"] == "PUBLISHED"
    assert r.course["goal"]["publish_requested"] is True


def test_read_results_are_recorded_without_replan(run_heavy_case, kit):
    plan = kit.plan_json(["read_file", "read_file"], publish=False, work="",
                         args={0: {"path": "/hackathon/secrets/key.txt"}, 1: {"path": "/hackathon/input/note.md"}})
    r = run_heavy_case([plan], request="secrets와 note.md를 보여줘")
    assert r.out["status"] == "ANSWERED_HEAVY"
    kinds = {x.path: x.kind for x in r.answer.read_files}
    assert kinds == {"/hackathon/secrets/key.txt": "DENIED_BY_SANDBOX", "/hackathon/input/note.md": "file"}
    assert f"/hackathon/secrets/key.txt: {TEXT_DENIED_BY_SANDBOX}" in r.answer.answer
    assert r.tools.calls.count("read_file") == 2
    assert len(r.nemotron.calls) == 1


def test_list_input_is_not_a_tool_step(run_heavy_case, kit):
    tools_list = ["lookup_station"] * 10 + ["save_course", "request_publish"]  # exactly 12 counted steps
    r = run_heavy_case([kit.plan_json(tools_list)])
    assert r.out["status"] == "PUBLISHED"
    assert r.tools.calls[0] == "list_input" and r.run.limits_hit == []


def test_tool_chat_goes_through_budget(run_heavy_case, kit):
    tools = kit.FakeTools(chat_calls={"select_places": 1, "organize_names": 1})
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS), "{}", "{}"], tools)
    assert r.model_calls == {"router": 1, "nemotron": 3}
    assert r.tokens["nemotron"] == {"input": 30, "output": 15}


def test_other_read_kinds_are_korean_in_answer(run_heavy_case, kit):
    def missing(args, ctx, deps):
        ctx.read_files[args["path"]] = {"kind": "NOT_FOUND", "text": "", "front_matter": {}, "dates": [],
                                        "entries": []}
        return ToolResult(ok=False, kind="NOT_FOUND", error="없음")

    tools = kit.FakeTools()
    tools.read_file = missing
    plan = kit.plan_json(["read_file"], publish=False, work="", args={0: {"path": "/hackathon/input/none.md"}})
    r = run_heavy_case([plan], tools, request="none.md 보여줘")
    assert r.out["status"] == "ANSWERED_HEAVY"
    assert "/hackathon/input/none.md: 없음" in r.answer.answer
    assert r.answer.read_files[0].kind == "NOT_FOUND"
