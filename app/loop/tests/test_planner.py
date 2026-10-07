"""Plan prompt and plan check (spec 2.2, 4.5)."""

import json

from common import limits
from common.schema import INPUT_DIR, OUTPUT_DIR, RESTRICTED_DIR, SECRETS_DIR

from loop.planner import build_plan_messages, build_replan_messages, extract_json_object, parse_and_check

PACKS = [{"pack_id": "fx", "work_title": "별무리", "aliases": ["별"], "provenance": "synthetic", "stations": [],
          "places": [{"place_id": "fx-01", "current_name": "별무리공원", "in_work_name": "별빛광장", "scene": "첫 장면",
                      "priority": 2, "old_names": ["옛이름"], "station": "혜화"}]}]


def test_plan_messages_carry_the_five_inputs(kit):
    reg = kit.FakeTools().registry()
    msgs = build_plan_messages("별무리 코스 짜줘", PACKS, [{"path": "a.md", "size": 3}], reg.describe())
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    assert "별무리 코스 짜줘" in user
    for v in ("fx-01", "별무리공원", "별빛광장", "첫 장면", '"priority": 2', '"aliases": ["별"]'):
        assert v in user
    assert "옛이름" not in user  # summary only
    assert '{"path": "a.md", "size": 3}' in user
    for d in (INPUT_DIR, OUTPUT_DIR, RESTRICTED_DIR, SECRETS_DIR):
        assert d in user
    assert "lookup_origin" in user and "free_places" in user
    system = msgs[0]["content"]
    for part in ("publish_requested", "request_publish", "지시문", str(limits.PLAN_STEPS_MAX)):
        assert part in system


def test_parse_and_check_accepts_a_fenced_plan(kit):
    reg = kit.FakeTools().registry()
    text = "계획입니다\n```json\n" + kit.plan_json(kit.COURSE_TOOLS) + "\n```"
    plan, problems = parse_and_check(text, reg)
    assert problems == [] and [s.tool for s in plan.steps] == kit.COURSE_TOOLS
    assert plan.goal.publish_requested is True


def test_parse_and_check_finds_problems(kit):
    reg = kit.FakeTools().registry()
    cases = {
        "JSON 아님": "그냥 글",
        "꼴": json.dumps({"steps": []}),
        "nope": kit.plan_json(["nope"]),
        "path": kit.plan_json(["read_file"]),
        "한도": kit.plan_json(["lookup_station"] * (limits.PLAN_STEPS_MAX + 1)),
        "중복": json.dumps({**json.loads(kit.plan_json(["lookup_station", "lookup_station"])),
                           "steps": [{"id": "s1", "tool": "lookup_station", "args": {}, "why": ""}] * 2}),
        "unknown": kit.plan_json(["lookup_station"], args={0: {"x": 1}}),
    }
    expected = {"JSON 아님": "JSON 객체가 아님", "꼴": "계획 꼴이 틀림", "nope": "nope", "path": "missing required argument",
                "한도": "한도", "중복": "단계 id 중복", "unknown": "unknown argument"}
    for word, text in cases.items():
        plan, problems = parse_and_check(text, reg)
        assert plan is None, word
        assert any(expected[word] in p for p in problems), (word, problems)


def test_extract_json_object():
    assert extract_json_object('앞말 {"a": 1} 뒷말') == {"a": 1}
    assert extract_json_object("[1]") is None
    assert extract_json_object(None) is None


def test_replan_messages_ask_for_remaining_steps():
    base = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    m = build_replan_messages(base, problems=["s1: 없는 도구"])
    assert m[:2] == base and "s1: 없는 도구" in m[-1]["content"] and "남은 단계" in m[-1]["content"]
    m = build_replan_messages(base, executed=[{"id": "s1", "tool": "select_places", "kind": "OK", "summary": ""}],
                              error="s2 lookup_origin: 오류")
    assert "select_places" in m[-1]["content"] and "s2 lookup_origin: 오류" in m[-1]["content"]


def test_defaults_fill_only_absent_fields(kit):
    reg = kit.FakeTools().registry()
    obj = {"goal": {"work": "별무리", "publish_requested": False},
           "steps": [{"id": "s1", "tool": "lookup_station"}, {"id": "s2", "tool": "search_db", "args": {"query": "q"},
                                                              "why": "찾기"}]}
    filled: list[str] = []
    plan, problems = parse_and_check(json.dumps(obj, ensure_ascii=False), reg, filled=filled)
    assert problems == []
    assert filled == ["goal.time_budget_min", "goal.start", "goal.constraints", "steps[0].args", "steps[0].why"]
    assert plan.goal.publish_requested is False and plan.goal.work == "별무리"
    assert plan.steps[1].why == "찾기"


def test_wrong_shapes_still_fail_after_defaults(kit):
    reg = kit.FakeTools().registry()
    goal = {"work": "", "time_budget_min": None, "start": "", "constraints": [], "publish_requested": True}
    for obj in ({"goal": goal, "steps": "s1"}, {"goal": goal, "steps": [{"id": "s1"}]},
                {"goal": goal, "steps": [{"id": "s1", "tool": "lookup_station", "args": []}]},
                {"goal": {**goal, "constraints": "없음"}, "steps": []}):
        plan, problems = parse_and_check(json.dumps(obj), reg)
        assert plan is None and problems, obj
