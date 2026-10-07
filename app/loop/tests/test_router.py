"""Weight router on Nemotron (spec 2.1 step 2, decision 0010)."""

import json

import pytest

from common.schema import split_trace_lines, verify_trace

from loop.budget import ROUTER_CALLS_DEFAULT, Budget, LimitHit
from loop.router import ROUTER_SYSTEM, build_router_system, route, work_label
from loop.trace import TraceWriter

RUN_ID = "20261007T033105Z-0a1f"


def _setup(tmp_path, kit, replies, **budget_kw):
    trace = TraceWriter(tmp_path / "trace.jsonl", RUN_ID)
    budget = Budget(clock=kit.FakeClock(), **budget_kw)
    router = kit.ScriptedChat(replies, model="fake-nemotron")
    return trace, budget, router, budget.wrap(router, "router")


def _trace(tmp_path):
    lines = split_trace_lines((tmp_path / "trace.jsonl").read_text(encoding="utf-8"))
    assert verify_trace(lines) == []
    return [json.loads(x) for x in lines]


@pytest.mark.parametrize("weight", ["heavy", "light"])
def test_weight_is_returned_and_recorded(tmp_path, kit, weight):
    trace, budget, router, wrapped = _setup(tmp_path, kit, [f'```json\n{{"weight": "{weight}", "why": "이유"}}\n```'])
    assert route("요청", wrapped, trace, budget=budget) == weight
    lines = _trace(tmp_path)
    assert len(lines) == 1
    assert lines[0]["event"] == "route" and lines[0]["result"] == {"kind": "OK", "summary": weight}
    assert lines[0]["why"] == "이유" and lines[0]["model"]["name"] == "fake-nemotron"
    call = router.calls[0]
    assert call["purpose"] == "route"
    assert call["kw"] == {"response_format": {"type": "json_object"}}
    assert call["messages"][0] == {"role": "system", "content": ROUTER_SYSTEM}
    assert call["messages"][1] == {"role": "user", "content": "요청"}
    assert budget.model_calls == {"router": 1, "nemotron": 0}


@pytest.mark.parametrize("text, weight", [
    ('먼저 생각해 보면 이 요청은 코스를 묻는다. 그래서 {"weight": "heavy", "why": "코스"}가 맞다.', "heavy"),
    ('<think>인사인지 본다. {잡문}</think>\n{"weight": "light", "why": "인사"}', "light"),
    ('판단: {"weight": "light", "why": "인사"} 이상이다 {끝}', "light"),
])
def test_reasoning_text_around_the_json(tmp_path, kit, text, weight):
    trace, budget, router, wrapped = _setup(tmp_path, kit, [text])
    assert route("요청", wrapped, trace, budget=budget) == weight
    assert len(router.calls) == 1


def test_system_prompt_only_judges_weight():
    for part in ("답하지 않는다", "애매하면 heavy", '"weight"', "파일·폴더 내용"):
        assert part in ROUTER_SYSTEM


@pytest.mark.parametrize("bad", ["", "   ", "heavy", '{"weight": "medium"}', '["heavy"]', ConnectionError("x")])
def test_one_failure_then_retry(tmp_path, kit, bad):
    trace, budget, router, wrapped = _setup(tmp_path, kit, [bad, '{"weight": "light", "why": "인사"}'])
    assert route("안녕", wrapped, trace, budget=budget) == "light"
    lines = _trace(tmp_path)
    assert [x["result"]["kind"] for x in lines] == ["", "OK"]
    assert lines[0]["result"]["summary"].startswith("실패: ")
    assert budget.model_calls["router"] == 2


def test_two_failures_return_none_without_guessing(tmp_path, kit):
    trace, budget, router, wrapped = _setup(tmp_path, kit, [TimeoutError(), "모르겠음", '{"weight": "heavy"}'])
    assert route("요청", wrapped, trace, budget=budget) is None
    assert len(router.calls) == ROUTER_CALLS_DEFAULT == 2
    assert len(_trace(tmp_path)) == 2


def test_third_router_call_is_blocked_by_the_router_limit(tmp_path, kit):
    trace, budget, router, wrapped = _setup(tmp_path, kit, ['{"weight": "heavy"}'] * 3)
    route("a", wrapped, trace, budget=budget)
    route("b", wrapped, trace, budget=budget)
    with pytest.raises(LimitHit) as ei:
        route("c", wrapped, trace, budget=budget)
    assert ei.value.name == "router_calls"
    assert len(router.calls) == 2
    assert budget.limits_hit == ["router_calls"]
    assert budget.model_calls == {"router": 2, "nemotron": 0}


def test_limit_hit_propagates(tmp_path, kit):
    trace, budget, router, wrapped = _setup(tmp_path, kit, ['{"weight": "heavy"}'], router_calls=0)
    with pytest.raises(LimitHit):
        route("요청", wrapped, trace, budget=budget)
    assert router.calls == []


DEMO_SENTENCE = "케데헌 보고 왔어요"


def test_system_prompt_has_service_context_and_light_is_narrow():
    for part in ("K-콘텐츠", "배경지", "근거 등급", "작품을 보고 왔다고", "남은 시간", "출발지", "운영 시간",
                 "light로 보는 요청은 세 가지뿐", "인사만 있는 말", "사용법", "애매하면 heavy", '"weight"'):
        assert part in ROUTER_SYSTEM, part
    assert "(목록 없음)" in ROUTER_SYSTEM


def test_demo_sentence_is_not_in_the_prompt():
    assert DEMO_SENTENCE not in ROUTER_SYSTEM
    assert DEMO_SENTENCE not in build_router_system(["케이팝 데몬 헌터스(케데헌, KPop Demon Hunters)"])
    assert "혜화" not in ROUTER_SYSTEM


def test_work_labels_reach_the_system_prompt(tmp_path, kit):
    trace, budget, router, wrapped = _setup(tmp_path, kit, ['{"weight": "heavy", "why": "작품"}'])
    works = [work_label({"work_title": "별무리", "aliases": ["별", "Byeolmuri"]}), work_label({"work_title": "달빛"})]
    assert works == ["별무리(별, Byeolmuri)", "달빛"]
    assert route("별 보고 왔어요", wrapped, trace, budget=budget, works=works) == "heavy"
    system = router.calls[0]["messages"][0]["content"]
    assert "별무리(별, Byeolmuri), 달빛" in system and "(목록 없음)" not in system
