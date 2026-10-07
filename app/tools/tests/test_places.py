"""Tests for tools.places (select_places, lookup_station) with fakes only."""

from __future__ import annotations

import json

from common.schema import KIND_TOOL_ERROR, REASON_OVER_BUDGET
from common.tooling import ToolSpec
from tools import places
from tools.tests.fakes import FakeChat, load_fixture_packs, make_ctx, make_deps

PACK = "fx-byeolmuri"
ROUTE = "fx-src-route-walk#c0"
MISSING = "fx-src-nope#c0"


def leg(frm, to, minutes, mode="walk", chunk_ids=(ROUTE,)):
    return {"from": frm, "to": to, "minutes": minutes, "mode": mode, "chunk_ids": list(chunk_ids)}


def run_select(legs, *, args=None, ctx=None, text=None, packs=None):
    chat = FakeChat([text if text is not None else json.dumps(legs, ensure_ascii=False)])
    deps = make_deps(chat=chat, packs=packs)
    ctx = ctx or make_ctx()
    base = {"pack_id": PACK, "candidate_place_ids": [], "free_places": [], "time_budget_min": 180, "start": "새벽솔역"}
    base.update(args or {})
    return places.run_select_places(base, ctx, deps), ctx, chat


def by_id(ctx):
    return {p["place_id"]: p for p in ctx.places}


# Minutes follow the fixture route source: stations 5-12 min from fx-01..fx-04, fx-05/fx-06 75-80 min away,
# 새벽솔 -> 달무리나루 6 min, 달무리나루 -> 솔빛고개 15 min. The far fx-05 sits in the middle of the order.
DEMO_LEGS = [
    leg("새벽솔", "fx-02", 7),
    leg("fx-02", "fx-04", 5, chunk_ids=(ROUTE, MISSING)),
    leg("fx-04", "fx-01", 20, "transit"),
    leg("fx-01", "fx-05", 95, "transit"),
    leg("fx-05", "fx-03", 87, chunk_ids=(MISSING,)),
    leg("fx-03", "fx-06", 107, "transit"),
]


def test_select_places_demo_cuts_far_places_to_budget():
    result, ctx, chat = run_select(DEMO_LEGS)

    assert result.ok, result.error
    assert len(chat.calls) == 1 and chat.calls[0][1] == "select_places"
    excluded_ids = [e["place_id"] for e in result.data["excluded"]]
    assert "fx-06" in excluded_ids and "fx-05" in excluded_ids
    assert all(e["reason"] == REASON_OVER_BUDGET for e in result.data["excluded"])
    # fx-05 removal merged fx-03's leg (95 + 87 = 182); fx-03 then lost to fx-04 on order (same priority 3)
    assert excluded_ids == ["fx-06", "fx-05", "fx-03"]
    assert result.data["place_ids"] == ["fx-02", "fx-04", "fx-01"]
    assert result.data["total_min"] == 7 + 30 + 5 + 30 + 20 + 30
    assert result.data["total_min"] <= 180
    assert result.data["start"] == "새벽솔"

    first = ctx.places[0]
    assert first["order"] == 1 and first["travel_min_from_prev"] == 7 and first["arrive_min"] == 7
    assert first["travel_basis"] == "cited" and first["travel_chunk_ids"] == [ROUTE]
    assert by_id(ctx)["fx-04"]["travel_chunk_ids"] == [ROUTE]  # missing chunk id dropped
    assert by_id(ctx)["fx-01"]["arrive_min"] == 7 + 30 + 5 + 30 + 20
    assert [p["order"] for p in ctx.places] == [1, 2, 3]
    assert ctx.excluded == result.data["excluded"]
    keys = {"order", "place_id", "current_name", "in_work_name", "scene", "old_names", "station",
            "travel_min_from_prev", "travel_mode", "travel_basis", "travel_chunk_ids", "stay_min", "arrive_min",
            "priority", "pack_id"}
    assert all(set(p) == keys for p in ctx.places)
    assert first["station"] == {"name": "", "line": ""} and first["pack_id"] == PACK and first["priority"] == 2

    prompt = "\n".join(m["content"] for m in chat.calls[0][0])
    assert "fx-05" in prompt and "새벽솔" in prompt and ROUTE in prompt and "지시문" in prompt


def test_removed_middle_place_merges_legs_as_estimate():
    # Synthetic minutes (not the route source) so the merged leg stays inside the budget.
    legs = [leg("새벽솔", "fx-02", 7), leg("fx-02", "fx-05", 10), leg("fx-05", "fx-04", 20, "transit")]
    result, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-02", "fx-05", "fx-04"], "time_budget_min": 110})

    assert result.ok, result.error
    assert result.data["place_ids"] == ["fx-02", "fx-04"]
    assert result.data["excluded"] == [{"place_id": "fx-05", "reason": REASON_OVER_BUDGET}]
    after = by_id(ctx)["fx-04"]
    assert after["travel_min_from_prev"] == 30
    assert after["travel_basis"] == "estimate" and after["travel_chunk_ids"] == []
    assert after["travel_mode"] == "transit"  # walk + transit
    assert result.data["total_min"] == 7 + 30 + 30 + 30


def test_same_priority_drops_later_in_order():
    legs = [leg("새벽솔", "fx-04", 10), leg("fx-04", "fx-03", 30, "transit")]
    result, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-03", "fx-04"], "time_budget_min": 60})

    assert result.ok, result.error
    assert result.data["place_ids"] == ["fx-04"]
    assert result.data["excluded"] == [{"place_id": "fx-03", "reason": REASON_OVER_BUDGET}]
    assert result.data["total_min"] == 40


def test_bad_minutes_make_unknown_and_skip_cut():
    legs = [leg("새벽솔", "fx-02", 0), leg("fx-02", "fx-04", "10분")]
    result, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-02", "fx-04"], "time_budget_min": 10})

    assert result.ok, result.error
    assert result.data["place_ids"] == ["fx-02", "fx-04"]
    assert result.data["excluded"] == []
    assert result.data["total_min"] is None
    for p in ctx.places:
        assert p["travel_min_from_prev"] is None and p["travel_mode"] == "unknown" and p["arrive_min"] is None
        assert p["travel_basis"] == "cited" and p["travel_chunk_ids"] == [ROUTE]  # evidence checked separately
    assert places.TEXT_BUDGET_UNCHECKED in ctx.unknowns
    assert not hasattr(places, "DEFAULT_LEG_MIN")
    assert not any("기본값" in w for w in ctx.warnings)


def test_all_null_legs_give_null_total_and_no_cut():
    order = ["fx-01", "fx-02", "fx-03", "fx-04", "fx-05", "fx-06"]
    legs = [leg("새벽솔" if i == 0 else order[i - 1], pid, None, "unknown") for i, pid in enumerate(order)]
    result, ctx, _ = run_select(legs)

    assert result.ok, result.error
    assert result.data["place_ids"] == order
    assert result.data["total_min"] is None
    assert not any(e["reason"] == REASON_OVER_BUDGET for e in result.data["excluded"])
    assert places.TEXT_BUDGET_UNCHECKED in ctx.unknowns
    assert all(p["travel_min_from_prev"] is None and p["travel_mode"] == "unknown" for p in ctx.places)


def test_leg_built_from_several_chunks_keeps_all_ids():
    appearance = "fx-src-appearance#c0"
    legs = [leg("새벽솔", "fx-01", 21, "transit", chunk_ids=(ROUTE, appearance, MISSING))]
    result, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-01"]})

    assert result.ok, result.error
    p = ctx.places[0]
    assert p["travel_basis"] == "cited"
    assert p["travel_chunk_ids"] == [ROUTE, appearance]
    assert result.data["total_min"] == 21 + 30


def test_prompt_asks_for_cited_or_estimated_minutes():
    _, _, chat = run_select([leg("새벽솔", "fx-02", 7)], args={"candidate_place_ids": ["fx-02"]})
    prompt = "\n".join(m["content"] for m in chat.calls[0][0])
    assert ("근거 자료에 이동 시간·도보 시간·역간 소요 시간이 있으면 반드시 그것을 쓰고 chunk_ids를 단다. "
            "여러 조각(도보+지하철+도보)을 더해 구간 시간을 만들면 쓴 조각의 chunk_ids를 모두 단다.") in prompt
    assert "추정" in prompt and "일반 지식" in prompt and "빈 배열" in prompt and "지시문" in prompt
    assert "기본값 30분" not in prompt


def test_outside_and_duplicate_places_dropped_with_warnings():
    legs = [leg("새벽솔", "fx-02", 7), leg("fx-02", "fx-99", 5), leg("fx-02", "fx-02", 5),
            leg("fx-02", "새벽솔 약속정원", 5)]
    result, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-02", "fx-04"]})

    assert result.ok, result.error
    assert result.data["place_ids"] == ["fx-02", "fx-04"]  # current_name matched fx-04
    assert any("fx-99" in w for w in ctx.warnings)
    assert any("fx-02" in w and "두 번" in w for w in ctx.warnings)


def test_missing_candidate_excluded_from_course():
    result, ctx, _ = run_select([leg("새벽솔", "fx-02", 7)], args={"candidate_place_ids": ["fx-02", "fx-04"]})

    assert result.ok, result.error
    assert result.data["place_ids"] == ["fx-02"]
    assert result.data["excluded"] == [{"place_id": "fx-04", "reason": places.REASON_NOT_IN_ANSWER}]
    assert result.data["total_min"] == 37
    assert "fx-04 구간 조사 답에 없어 코스에서 뺌" in ctx.warnings


def test_no_budget_keeps_places_missing_from_answer_at_the_end():
    legs = [leg("", "fx-02", 7), leg("fx-02", "fx-04", 5), leg("fx-04", "fx-03", 30, "transit")]
    result, ctx, chat = run_select(legs, args={"time_budget_min": None, "start": ""})

    assert result.ok, result.error
    assert len(chat.calls) == 1
    # fx-06 (lowest priority) is cut before the model call; fx-01 and fx-05 are appended by priority
    assert result.data["place_ids"] == ["fx-02", "fx-04", "fx-03", "fx-01", "fx-05"]
    assert result.data["excluded"] == [{"place_id": "fx-06", "reason": places.REASON_NO_BUDGET_LIMIT}]
    assert places.REASON_NOT_IN_ANSWER not in [e["reason"] for e in ctx.excluded]
    tail = by_id(ctx)["fx-01"]
    assert tail["travel_min_from_prev"] is None and tail["travel_mode"] == "unknown"
    assert tail["travel_basis"] == "estimate" and tail["travel_chunk_ids"] == []
    assert "fx-01 구간 조사 답에 없어 끝에 붙임(이동 시간 모름)" in ctx.warnings
    assert "fx-05 구간 조사 답에 없어 끝에 붙임(이동 시간 모름)" in ctx.warnings
    assert result.data["total_min"] is None
    assert places.TEXT_BUDGET_UNCHECKED not in ctx.unknowns


def test_model_skipping_far_places_leaves_them_excluded():
    legs = [leg("새벽솔", "fx-02", 7), leg("fx-02", "fx-04", 5), leg("fx-04", "fx-01", 20, "transit"),
            leg("fx-01", "fx-03", 30, "transit")]
    result, ctx, _ = run_select(legs)

    assert result.ok, result.error
    assert result.data["place_ids"] == ["fx-02", "fx-04", "fx-01", "fx-03"]
    assert result.data["excluded"] == [
        {"place_id": "fx-05", "reason": "구간 조사 답에 없음"},
        {"place_id": "fx-06", "reason": "구간 조사 답에 없음"},
    ]
    assert result.data["total_min"] == 7 + 30 + 5 + 30 + 20 + 30 + 30 + 20
    assert ctx.excluded == result.data["excluded"]


def test_model_values_in_warnings_are_one_short_line():
    long_to = "가짜\n장소 " + "나" * 200
    legs = [leg("새벽솔", "fx-02", 7), leg("fx-02", long_to, 5)]
    _, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-02", "fx-0\n" + "9" * 200]})

    assert ctx.warnings
    for w in ctx.warnings:
        assert "\n" not in w
        assert len(w) <= 60 + 30


def test_rerun_on_same_ctx_does_not_duplicate_excluded():
    ctx = make_ctx()
    run_select(DEMO_LEGS, ctx=ctx)
    result, ctx, _ = run_select(DEMO_LEGS, ctx=ctx)
    assert ctx.excluded == result.data["excluded"]
    assert len(ctx.excluded) == 3


def test_bad_mode_keeps_minutes_and_warns():
    legs = [leg("새벽솔", "fx-02", 7, "bus")]
    result, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-02"]})
    p = ctx.places[0]
    assert p["travel_mode"] == "unknown" and p["travel_min_from_prev"] == 7
    assert result.data["total_min"] == 37
    assert "fx-02 이동 수단 확인 안 됨" in ctx.warnings


def test_budget_removing_everything_gives_null_total():
    result, ctx, _ = run_select([leg("새벽솔", "fx-02", 7)], args={"candidate_place_ids": ["fx-02"],
                                                                   "time_budget_min": 10})
    assert result.ok, result.error
    assert result.data["place_ids"] == [] and result.data["total_min"] is None
    assert ctx.places == []
    assert "시간 예산 안에 들어가는 장소가 없음" in ctx.warnings


def test_non_positive_budget_is_ignored():
    legs = [leg("새벽솔", "fx-02", 7), leg("fx-02", "fx-04", 5)]
    result, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-02", "fx-04"], "time_budget_min": -10})
    assert result.data["place_ids"] == ["fx-02", "fx-04"] and result.data["excluded"] == []
    assert "시간 예산 값이 0 이하라 무시함" in ctx.warnings


def test_prompt_includes_only_read_files_of_kind_file():
    ctx = make_ctx(read_files={
        "/hackathon/input/route.md": {"kind": "file", "text": "파일본문표지 새벽솔역에서 걸어서 7분"},
        "/hackathon/input/pics": {"kind": "other", "text": "다른종류표지"},
    })
    _, _, chat = run_select([leg("새벽솔", "fx-02", 7)], ctx=ctx, args={"candidate_place_ids": ["fx-02"]})
    prompt = "\n".join(m["content"] for m in chat.calls[0][0])
    assert "파일본문표지" in prompt
    assert "다른종류표지" not in prompt


def test_no_budget_keeps_five_by_priority():
    legs = [leg("새벽솔", f"fx-0{i}", 10) for i in range(1, 6)]
    result, ctx, _ = run_select(legs, args={"time_budget_min": None})

    assert result.ok, result.error
    assert result.data["place_ids"] == ["fx-01", "fx-02", "fx-03", "fx-04", "fx-05"]
    assert result.data["excluded"] == [{"place_id": "fx-06", "reason": places.REASON_NO_BUDGET_LIMIT}]
    assert result.data["total_min"] is not None


def test_budget_and_start_from_goal():
    ctx = make_ctx(goal={"time_budget_min": 60, "start": "새벽솔역"})
    legs = [leg("새벽솔", "fx-04", 10), leg("fx-04", "fx-03", 30, "transit")]
    result, ctx, _ = run_select(legs, ctx=ctx,
                                args={"candidate_place_ids": ["fx-03", "fx-04"], "time_budget_min": None, "start": ""})
    assert result.data["start"] == "새벽솔"
    assert result.data["place_ids"] == ["fx-04"]


def test_free_places_get_code_ids():
    free = [{"name": "가상 서점", "note": "주인공이 들른 서점"}, {"name": "가상 카페", "note": "엔딩 카페"}]
    legs = [leg("새벽솔", "free-1", 10), leg("free-1", "free-2", 5)]
    result, ctx, _ = run_select(legs, args={"pack_id": "", "candidate_place_ids": [], "free_places": free,
                                            "time_budget_min": None})

    assert result.ok, result.error
    assert result.data["place_ids"] == ["free-1", "free-2"]
    p = by_id(ctx)["free-1"]
    assert p["current_name"] == "가상 서점" and p["scene"] == "주인공이 들른 서점"
    assert p["in_work_name"] == "" and p["old_names"] == [] and p["priority"] is None and p["pack_id"] == ""
    assert p["stay_min"] == 60
    assert "free-1 머무는 시간 추정(60분)" in ctx.warnings


def test_free_places_alone_skip_the_only_pack():
    legs = [leg("새벽솔", "free-1", 10)]
    result, ctx, _ = run_select(legs, args={"pack_id": "", "free_places": [{"name": "가상 서점", "note": ""}]})
    assert result.data["place_ids"] == ["free-1"]
    assert all(not p["place_id"].startswith("fx-") for p in ctx.places)


def test_all_empty_uses_the_only_pack():
    legs = [leg("새벽솔", f"fx-0{i}", 5) for i in range(1, 7)]
    result, ctx, _ = run_select(legs, args={"pack_id": "", "time_budget_min": None})
    assert result.ok, result.error
    assert len(ctx.places) == 5 and all(p["pack_id"] == PACK for p in ctx.places)


def test_candidate_ids_without_pack_id_search_every_pack():
    other = {"pack_id": "fx-other", "stations": [], "places": [
        {"place_id": "ot-01", "current_name": "가상 다리", "in_work_name": "", "scene": "", "old_names": [],
         "station": "", "stay_min": 15, "priority": 1}]}
    packs = load_fixture_packs() + [other]
    legs = [leg("새벽솔", "fx-02", 7), leg("fx-02", "ot-01", 10)]
    result, ctx, _ = run_select(legs, packs=packs,
                                args={"pack_id": "", "candidate_place_ids": ["fx-02", "ot-01", "fx-99"]})
    assert result.ok, result.error
    assert result.data["place_ids"] == ["fx-02", "ot-01"]
    assert by_id(ctx)["ot-01"]["pack_id"] == "fx-other" and by_id(ctx)["fx-02"]["pack_id"] == PACK
    assert any("fx-99" in w for w in ctx.warnings)


def test_no_start_first_place_has_no_leg():
    legs = [leg("", "fx-02", 7), leg("fx-02", "fx-04", 5)]
    result, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-02", "fx-04"], "start": ""})

    first = ctx.places[0]
    assert first["travel_min_from_prev"] is None and first["arrive_min"] == 0
    assert result.data["total_min"] == 30 + 5 + 30
    assert places.TEXT_BUDGET_UNCHECKED not in ctx.unknowns


def test_bad_model_answer_is_tool_error():
    result, ctx, _ = run_select([], text="순서를 정할 수 없습니다")
    assert not result.ok and result.kind == KIND_TOOL_ERROR
    result, _, _ = run_select([], text='{"from": "a"}')
    assert not result.ok and result.kind == KIND_TOOL_ERROR


def test_chat_exception_is_tool_error():
    deps = make_deps(chat=FakeChat([RuntimeError("boom")]))
    result = places.run_select_places({"pack_id": PACK}, make_ctx(), deps)
    assert result.kind == KIND_TOOL_ERROR


def test_unknown_pack_and_no_candidates_are_tool_errors():
    result, _, chat = run_select([], args={"pack_id": "fx-none"})
    assert result.kind == KIND_TOOL_ERROR and chat.calls == []
    result, _, chat = run_select([], args={"candidate_place_ids": ["fx-99"]})
    assert result.kind == KIND_TOOL_ERROR and chat.calls == []


def test_lookup_station_fills_pack_station_and_flags_free_place():
    free = [{"name": "가상 서점", "note": ""}]
    legs = [leg("새벽솔", "fx-02", 7), leg("fx-02", "free-1", 5)]
    _, ctx, _ = run_select(legs, args={"candidate_place_ids": ["fx-02"], "free_places": free})
    deps = make_deps()

    result = places.run_lookup_station({}, ctx, deps)

    assert result.ok, result.error
    assert by_id(ctx)["fx-02"]["station"] == {"name": "새벽솔", "line": "가상1호선"}
    assert by_id(ctx)["free-1"]["station"] == {"name": "", "line": ""}
    assert result.data["stations"] == {"fx-02": "새벽솔", "free-1": ""}
    assert "가상 서점 가까운 역 확인 안 됨" in ctx.unknowns


def test_lookup_station_needs_places():
    result = places.run_lookup_station({}, make_ctx(), make_deps())
    assert result.kind == KIND_TOOL_ERROR
    assert "코스에 장소가 없음" in result.error


def test_lookup_station_flags_station_missing_from_pack():
    packs = load_fixture_packs()
    for p in packs[0]["places"]:
        if p["place_id"] == "fx-02":
            p["station"] = "없는역"
    chat = FakeChat([json.dumps([leg("새벽솔", "fx-02", 7)])])
    deps = make_deps(chat=chat, packs=packs)
    ctx = make_ctx()
    places.run_select_places({"pack_id": PACK, "candidate_place_ids": ["fx-02"], "start": "새벽솔역"}, ctx, deps)

    result = places.run_lookup_station({}, ctx, deps)

    assert result.ok, result.error
    assert ctx.places[0]["station"] == {"name": "없는역", "line": ""}
    assert "별가루 골목시장 가까운 역 호선 확인 안 됨" in ctx.unknowns


def test_specs_use_contract_names():
    assert [s.name for s in places.SPECS] == ["select_places", "lookup_station"]
    assert all(isinstance(s, ToolSpec) and s.description for s in places.SPECS)


class Boom(RuntimeError):
    pass


def _raiser(*_a, **_k):
    raise Boom("secret detail")


def test_dep_failures_are_tool_errors_with_type_name_only():
    import dataclasses

    deps = dataclasses.replace(make_deps(chat=FakeChat([])), theme_packs=_raiser)
    result = places.run_select_places({"pack_id": PACK}, make_ctx(), deps)
    assert result.kind == KIND_TOOL_ERROR and "Boom" in result.error and "secret" not in result.error

    chat = FakeChat([json.dumps([leg("새벽솔", "fx-02", 7)])])
    deps = dataclasses.replace(make_deps(chat=chat), get_chunk=_raiser)
    result = places.run_select_places({"pack_id": PACK, "candidate_place_ids": ["fx-02"]}, make_ctx(), deps)
    assert result.kind == KIND_TOOL_ERROR and "Boom" in result.error and "secret" not in result.error

    deps = make_deps(chat=FakeChat([Boom("secret detail")]))
    result = places.run_select_places({"pack_id": PACK}, make_ctx(), deps)
    assert result.kind == KIND_TOOL_ERROR and "Boom" in result.error and "secret" not in result.error

    _, ctx, _ = run_select([leg("새벽솔", "fx-02", 7)], args={"candidate_place_ids": ["fx-02"]})
    deps = dataclasses.replace(make_deps(), theme_packs=_raiser)
    result = places.run_lookup_station({}, ctx, deps)
    assert result.kind == KIND_TOOL_ERROR and "Boom" in result.error and "secret" not in result.error


def test_no_budget_reason_text():
    assert places.REASON_NO_BUDGET_LIMIT == "시간 예산 없는 요청의 최대 5곳 초과"
