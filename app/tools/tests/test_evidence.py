"""Tests for tools.evidence: lookup_origin, lookup_operating, organize_names, grade_evidence, search_db."""

from __future__ import annotations

import json

import pytest

from common.schema import KIND_OK, KIND_TOOL_ERROR, Conflict, Operating, OriginClaim, StaleItem
from common.tooling import DEPS_NAMES, NO_PLACE_KEY, TOOL_ARGS, Deps, ToolRegistry
from tools import evidence
from tools.tests.fakes import FakeChat, load_fixture_packs, make_ctx, make_deps

OFFICIAL = "fx-src-origin-dalmuri-official#c0"
BLOG = "fx-src-origin-dalmuri-blog#c0"


def _places(*place_ids: str) -> list[dict]:
    pack = load_fixture_packs()[0]
    lines = {s["name"]: s["line"] for s in pack["stations"]}
    out = []
    for order, pid in enumerate(place_ids, start=1):
        p = next(x for x in pack["places"] if x["place_id"] == pid)
        out.append({
            "order": order,
            "place_id": pid,
            "current_name": p["current_name"],
            "in_work_name": p["in_work_name"],
            "scene": p["scene"],
            "old_names": list(p["old_names"]),
            "station": {"name": p["station"], "line": lines[p["station"]]},
            "travel_min_from_prev": None,
            "travel_mode": "unknown",
            "travel_basis": "estimate",
            "travel_chunk_ids": [],
            "stay_min": p["stay_min"],
            "arrive_min": None,
            "priority": p["priority"],
            "pack_id": pack["pack_id"],
        })
    return out


def _dalmuri_answer() -> str:
    return json.dumps({
        "fx-01": [
            {"name": "달무리나루", "name_kind": "station", "summary": "달무리가 잘 보이던 나루터에서 온 이름.",
             "chunk_ids": [OFFICIAL], "input_paths": []},
            {"name": "달무리나루", "name_kind": "station", "summary": "뱃사공 달무리의 이름에서 왔다는 구전.",
             "chunk_ids": [BLOG], "input_paths": []},
        ]
    }, ensure_ascii=False)


# ---------------------------------------------------------------- registration


def test_specs_names_and_contract_args():
    names = [s.name for s in evidence.SPECS]
    assert sorted(names) == sorted(
        ["lookup_origin", "lookup_operating", "organize_names", "grade_evidence", "search_db"])
    reg = ToolRegistry()
    for spec in evidence.SPECS:
        reg.register(spec)
        assert spec.args == TOOL_ARGS[spec.name]
        assert spec.description and "\n" not in spec.description


# ---------------------------------------------------------------- completion 1: origin conflict


def test_origin_conflict_graded_a_then_d():
    chat = FakeChat([_dalmuri_answer()])
    deps = make_deps(chat=chat)
    ctx = make_ctx(places=_places("fx-01"))

    assert evidence.run_lookup_origin({"k": 5}, ctx, deps).ok
    res = evidence.run_organize_names({}, ctx, deps)
    assert res.ok and res.kind == KIND_OK
    assert len(chat.calls) == 1 and chat.calls[0][1] == "organize_names"
    assert res.data["claims"] == {"fx-01": 2}

    res = evidence.run_grade_evidence({}, ctx, deps)
    assert res.ok
    g = ctx.graded["fx-01"]
    assert len(g["conflicts"]) == 1
    conflict = g["conflicts"][0]
    assert conflict["name"] == "달무리나루"
    assert [c["grade"] for c in conflict["claims"]] == ["A", "D"]
    assert conflict["claims"][0]["chunk_ids"] == [OFFICIAL]
    assert conflict["claims"][0]["source_ids"] == ["fx-src-origin-dalmuri-official"]
    assert [c["grade"] for c in g["origins"]] == ["A", "D"]
    for c in g["origins"]:
        OriginClaim.from_dict(c)
    Conflict.from_dict(conflict)


def test_grade_order_newer_first_on_same_grade_and_none_last():
    deps = make_deps()
    ctx = make_ctx(places=_places("fx-01"))
    base = {"name_kind": "current", "summary": "", "grade": None, "source_ids": [], "input_paths": []}
    ctx.origins = {"fx-01": [
        dict(base, name="x", chunk_ids=["no-such#c0"]),
        dict(base, name="y", chunk_ids=["fx-src-op-solbit-2025#c0"]),  # A, 2025-01-10
        dict(base, name="z", chunk_ids=[OFFICIAL]),  # A, 2023-05-10
    ]}
    assert evidence.run_grade_evidence({}, ctx, deps).ok
    names = [c["name"] for c in ctx.graded["fx-01"]["origins"]]
    assert names == ["y", "z", "x"]
    assert ctx.graded["fx-01"]["origins"][-1]["grade"] is None
    assert "fx-01/x: 근거 없음" in ctx.warnings


# ---------------------------------------------------------------- completion 2: operating


def test_operating_chosen_onsite_and_unknown():
    deps = make_deps()
    ctx = make_ctx(places=_places("fx-01", "fx-02", "fx-03"))
    res = evidence.run_lookup_operating({}, ctx, deps)
    assert res.ok
    assert res.data["counts"] == {"fx-01": 0, "fx-02": 2, "fx-03": 2}

    res = evidence.run_grade_evidence({}, ctx, deps)
    assert res.ok

    op2 = ctx.graded["fx-02"]["operating"]
    assert op2["status"] == "CHOSEN"
    assert op2["hours"] == "10:00~20:00"
    assert op2["closed"] == "매주 화요일"
    assert op2["as_of"] == "2026-08-01"
    assert "fx-src-op-byeolgaru-2026" in op2["source_ids"]
    assert "candidates" not in op2
    stale2 = ctx.graded["fx-02"]["stale"]
    assert [s["source_id"] for s in stale2] == ["fx-src-op-byeolgaru-2024"]
    assert "fx-src-op-byeolgaru-2026" in stale2[0]["reason"]

    op3 = ctx.graded["fx-03"]["operating"]
    assert op3["status"] == "NEEDS_ONSITE_CHECK"
    assert op3["hours"] == "" and op3["closed"] == "" and op3["as_of"] == ""
    assert len(op3["candidates"]) == 2
    assert op3["candidates"][0]["source_id"] == "fx-src-op-solbit-2025"
    assert op3["candidates"][0]["grade"] == "A"
    assert op3["candidates"][1]["grade"] == "D"
    assert ctx.graded["fx-03"]["stale"] == []
    assert "솔빛고개 전망쉼터 운영 정보 현장 확인 필요" in ctx.unknowns

    op1 = ctx.graded["fx-01"]["operating"]
    assert op1 == {"status": "UNKNOWN", "hours": "", "closed": "", "source_ids": [], "as_of": ""}
    assert "달무리나루 선착장 운영 정보 확인 안 됨" in ctx.unknowns

    for g in ctx.graded.values():
        Operating.from_dict(g["operating"])
        for s in g["stale"]:
            StaleItem.from_dict(s)
    assert res.data["graded"]["fx-02"] == {"conflicts": 0, "operating": "CHOSEN"}


def test_operating_all_agree_and_undated_is_oldest():
    chunks = [
        {"chunk_id": "a#c0", "source_id": "a", "source_type": "media", "published": "2025-01-01",
         "kind": "operating", "place_ids": ["p1"], "hours": "9~18", "closed": "월"},
        {"chunk_id": "a#c1", "source_id": "a", "source_type": "media", "published": "2025-01-01",
         "kind": "operating", "place_ids": ["p1"], "hours": "9~18", "closed": "월"},
        {"chunk_id": "b#c0", "source_id": "b", "source_type": "official", "published": "2024-01-01",
         "kind": "operating", "place_ids": ["p1"], "hours": "9~18", "closed": "월"},
        {"chunk_id": "c#c0", "source_id": "c", "source_type": "official", "published": "",
         "kind": "operating", "place_ids": ["p2"], "hours": "8~20", "closed": "없음"},
        {"chunk_id": "d#c0", "source_id": "d", "source_type": "official", "published": "2020-01-01",
         "kind": "operating", "place_ids": ["p2"], "hours": "9~18", "closed": "월"},
    ]
    deps = make_deps(chunks=chunks)
    places = [{"place_id": "p1", "current_name": "가"}, {"place_id": "p2", "current_name": "나"}]
    ctx = make_ctx(places=places)
    evidence.run_lookup_operating({}, ctx, deps)
    assert evidence.run_grade_evidence({}, ctx, deps).ok
    op1 = ctx.graded["p1"]["operating"]
    assert op1["status"] == "CHOSEN" and op1["source_ids"] == ["a", "b"] and op1["as_of"] == "2025-01-01"
    op2 = ctx.graded["p2"]["operating"]
    assert op2["status"] == "CHOSEN" and op2["hours"] == "9~18" and op2["source_ids"] == ["d"]
    assert [s["source_id"] for s in ctx.graded["p2"]["stale"]] == ["c"]


# ---------------------------------------------------------------- existence checks


def test_missing_chunk_and_unread_path_dropped_with_warnings():
    answer = json.dumps({
        "fx-01": [
            {"name": "달무리나루", "name_kind": "station", "summary": "s1",
             "chunk_ids": [OFFICIAL, "fx-src-made-up#c0"], "input_paths": ["/hackathon/input/never-read.md"]},
            {"name": "수호단 비밀 부두", "name_kind": "in_work", "summary": "s2",
             "chunk_ids": ["fx-src-ghost#c0"], "input_paths": []},
        ],
        "fx-99": [{"name": "?", "name_kind": "current", "summary": "", "chunk_ids": [], "input_paths": []}],
    }, ensure_ascii=False)
    deps = make_deps(chat=FakeChat([answer]))
    ctx = make_ctx(places=_places("fx-01"))
    res = evidence.run_organize_names({}, ctx, deps)
    assert res.ok
    assert set(ctx.origins) == {"fx-01"}
    assert res.data["dropped"] == 4
    first, second = ctx.origins["fx-01"]
    assert first["chunk_ids"] == [OFFICIAL]
    assert first["input_paths"] == []
    assert first["source_ids"] == ["fx-src-origin-dalmuri-official"]
    assert second["chunk_ids"] == []
    assert "fx-01/달무리나루: 근거 청크 fx-src-made-up#c0 없음, 버림" in ctx.warnings
    assert "fx-01/달무리나루: 근거 파일 /hackathon/input/never-read.md 이번 실행에서 읽지 않음, 버림" in ctx.warnings
    assert "fx-01/수호단 비밀 부두: 근거 청크 fx-src-ghost#c0 없음, 버림" in ctx.warnings
    assert any("fx-99" in w for w in ctx.warnings)

    assert evidence.run_grade_evidence({}, ctx, deps).ok
    origins = ctx.graded["fx-01"]["origins"]
    assert origins[0]["grade"] == "A"
    assert origins[-1]["name"] == "수호단 비밀 부두" and origins[-1]["grade"] is None
    assert "fx-01/수호단 비밀 부두: 근거 없음" in ctx.warnings


def test_name_kind_fixed_from_place_names():
    answer = json.dumps({"fx-01": [
        {"name": "달무리 나루터", "name_kind": "옛이름", "summary": "", "chunk_ids": [OFFICIAL], "input_paths": []},
        {"name": "모르는 이름", "name_kind": "bad", "summary": "", "chunk_ids": [OFFICIAL], "input_paths": []},
    ]}, ensure_ascii=False)
    deps = make_deps(chat=FakeChat([answer]))
    ctx = make_ctx(places=_places("fx-01"))
    assert evidence.run_organize_names({}, ctx, deps).ok
    kinds = [c["name_kind"] for c in ctx.origins["fx-01"]]
    assert kinds == ["old", "current"]
    assert [c["name"] for c in ctx.origins["fx-01"]] == ["달무리 나루터", "모르는 이름"]
    assert "fx-01/모르는 이름: 장소 이름 목록에 없는 이름" in ctx.warnings
    assert not any("달무리 나루터: 장소 이름" in w for w in ctx.warnings)


# ---------------------------------------------------------------- organize_names: one call, errors


def test_organize_names_one_chat_call_for_many_places():
    answer = json.dumps({"fx-01": [], "fx-02": [], "fx-03": []})
    chat = FakeChat([answer])
    deps = make_deps(chat=chat)
    ctx = make_ctx(places=_places("fx-01", "fx-02", "fx-03"))
    evidence.run_lookup_origin({}, ctx, deps)
    res = evidence.run_organize_names({}, ctx, deps)
    assert res.ok
    assert len(chat.calls) == 1
    prompt = json.dumps(chat.calls[0][0], ensure_ascii=False)
    for pid in ("fx-01", "fx-02", "fx-03"):
        assert pid in prompt


@pytest.mark.parametrize("reply", ["유래를 모르겠습니다", "[1, 2]", RuntimeError("boom")])
def test_organize_names_bad_reply_is_tool_error(reply):
    deps = make_deps(chat=FakeChat([reply]))
    ctx = make_ctx(places=_places("fx-01"))
    res = evidence.run_organize_names({}, ctx, deps)
    assert not res.ok and res.kind == KIND_TOOL_ERROR


def test_organize_names_no_evidence_without_places_skips_chat():
    chat = FakeChat([])
    ctx = make_ctx()
    res = evidence.run_organize_names({}, ctx, make_deps(chat=chat))
    assert res.ok and ctx.origins == {}
    assert chat.calls == []
    assert "유래를 정리할 근거 없음" in ctx.warnings


# ---------------------------------------------------------------- lookup_origin, lookup_operating, search_db


def test_lookup_origin_fills_evidence_per_name():
    deps = make_deps()
    ctx = make_ctx(places=_places("fx-01"))
    res = evidence.run_lookup_origin({"k": 5}, ctx, deps)
    assert res.ok
    ev = ctx.evidence["fx-01"]
    ids = {c["chunk_id"] for c in ev["달무리나루"]}
    assert {OFFICIAL, BLOG} <= ids
    for name, chunks in ev.items():
        for c in chunks:
            assert name in c.get("about", []) or name in c.get("text", "")
    assert set(ev) == {"달무리나루 선착장", "달무리 나루터", "수호단 비밀 부두", "달무리나루", "달무리나루역"}
    assert res.data["counts"]["fx-01"]["달무리나루"] == len(ev["달무리나루"])


def test_lookup_tools_need_places():
    deps = make_deps()
    assert evidence.run_lookup_origin({}, make_ctx(), deps).kind == KIND_TOOL_ERROR
    assert evidence.run_lookup_operating({}, make_ctx(), deps).kind == KIND_TOOL_ERROR


def test_search_db():
    deps = make_deps()
    ctx = make_ctx()
    res = evidence.run_search_db({"query": "솔빛고개 햇빛", "k": 3}, ctx, deps)
    assert res.ok
    assert 0 < len(ctx.search_results) <= 3
    assert res.data["chunk_ids"] == [c["chunk_id"] for c in ctx.search_results]
    assert "fx-src-origin-solbit-academic#c0" in res.data["chunk_ids"]
    assert evidence.run_search_db({"query": "  "}, ctx, deps).kind == KIND_TOOL_ERROR


# ---------------------------------------------------------------- question without places ("_")


def test_no_place_question_graded_from_search_and_input_file():
    path = "/hackathon/input/notes/solbit.md"
    answer = json.dumps({NO_PLACE_KEY: [
        {"name": "솔빛고개", "name_kind": "station", "summary": "소나무 사이로 햇빛이 드는 고개.",
         "chunk_ids": ["fx-src-origin-solbit-academic#c0"], "input_paths": []},
        {"name": "솔빛고개", "name_kind": "station", "summary": "메모에 적힌 다른 풀이.",
         "chunk_ids": [], "input_paths": [path]},
    ]}, ensure_ascii=False)
    chat = FakeChat([answer])
    deps = make_deps(chat=chat)
    ctx = make_ctx()
    ctx.read_files = {
        path: {"kind": "file", "text": "솔빛고개는 고개 이름이 아니라 옛 주막 이름이라는 메모.", "front_matter": {},
               "dates": [], "entries": []},
        "/hackathon/input/notes": {"kind": "dir", "text": "", "front_matter": {}, "dates": [], "entries": []},
    }
    assert evidence.run_search_db({"query": "솔빛고개 유래"}, ctx, deps).ok
    assert evidence.run_organize_names({}, ctx, deps).ok
    assert len(chat.calls) == 1
    prompt = json.dumps(chat.calls[0][0], ensure_ascii=False)
    assert path in prompt and "fx-src-origin-solbit-academic#c0" in prompt

    res = evidence.run_grade_evidence({}, ctx, deps)
    assert res.ok
    g = ctx.graded[NO_PLACE_KEY]
    assert [c["grade"] for c in g["origins"]] == ["B", "D"]
    assert g["origins"][1]["input_paths"] == [path]
    assert len(g["conflicts"]) == 1
    assert g["operating"]["status"] == "UNKNOWN"
    assert ctx.unknowns == []
    assert res.data["graded"][NO_PLACE_KEY]["operating"] == "UNKNOWN"


def test_grade_evidence_nothing_to_grade():
    ctx = make_ctx()
    res = evidence.run_grade_evidence({}, ctx, make_deps())
    assert res.ok and ctx.graded == {}


def test_free_place_origin_from_read_input_file():
    path = "/hackathon/input/food/gukbap.md"
    answer = json.dumps({"free-1": [
        {"name": "가상 국밥집", "name_kind": "current", "summary": "주인 할머니 별명에서 온 이름이라는 메모.",
         "chunk_ids": [], "input_paths": [path]},
    ]}, ensure_ascii=False)
    chat = FakeChat([answer])
    deps = make_deps(chat=chat)
    ctx = make_ctx(places=[{"order": 1, "place_id": "free-1", "current_name": "가상 국밥집", "in_work_name": "",
                            "scene": "", "old_names": [], "station": {"name": "", "line": ""}}])
    ctx.read_files = {path: {"kind": "file", "text": "가상 국밥집은 주인 할머니 별명을 딴 이름이다.",
                             "front_matter": {}, "dates": [], "entries": []}}
    for i in range(6):
        ctx.read_files[f"/hackathon/input/extra/{i}.md"] = {
            "kind": "file", "text": "기타", "front_matter": {}, "dates": [], "entries": []}

    assert evidence.run_organize_names({}, ctx, deps).ok
    assert len(chat.calls) == 1
    prompt = json.dumps(chat.calls[0][0], ensure_ascii=False)
    assert path in prompt
    assert "/hackathon/input/extra/4.md" not in prompt  # at most 5 files: gukbap + extra/0..3

    assert evidence.run_grade_evidence({}, ctx, deps).ok
    origins = ctx.graded["free-1"]["origins"]
    assert len(origins) == 1
    assert origins[0]["grade"] == "D"
    assert origins[0]["input_paths"] == [path]
    assert ctx.graded["free-1"]["operating"]["status"] == "UNKNOWN"


# ---------------------------------------------------------------- review fixes


def _op(sid, stype, published, hours, closed, place="p1"):
    return {"chunk_id": f"{sid}#c0", "source_id": sid, "source_type": stype, "published": published,
            "kind": "operating", "place_ids": [place], "hours": hours, "closed": closed}


def _grade_operating(chunks, place_id="p1"):
    deps = make_deps(chunks=chunks)
    ctx = make_ctx(places=[{"place_id": place_id, "current_name": "가"}])
    assert evidence.run_lookup_operating({}, ctx, deps).ok
    assert evidence.run_grade_evidence({}, ctx, deps).ok
    return ctx, ctx.graded[place_id]


@pytest.mark.parametrize("reverse", [False, True])
def test_operating_same_date_same_grade_tie_needs_onsite(reverse):
    chunks = [_op("s1", "official", "2026-01-01", "9~18", "월"), _op("s2", "official", "2026-01-01", "8~20", "없음"),
              _op("s3", "media", "2025-01-01", "9~18", "월")]
    if reverse:
        chunks.reverse()
    ctx, g = _grade_operating(chunks)
    op = g["operating"]
    assert op["status"] == "NEEDS_ONSITE_CHECK"
    assert [c["source_id"] for c in op["candidates"]] == ["s1", "s2", "s3"]
    assert op["source_ids"] == ["s1", "s2", "s3"]
    assert g["stale"] == []
    assert "가 운영 정보 현장 확인 필요" in ctx.unknowns


@pytest.mark.parametrize("reverse", [False, True])
def test_operating_undated_tie_needs_onsite(reverse):
    chunks = [_op("u1", "media", "", "9~18", "월"), _op("u2", "media", "", "10~19", "화")]
    if reverse:
        chunks.reverse()
    _, g = _grade_operating(chunks)
    assert g["operating"]["status"] == "NEEDS_ONSITE_CHECK"
    assert [c["source_id"] for c in g["operating"]["candidates"]] == ["u1", "u2"]


@pytest.mark.parametrize("reverse", [False, True])
def test_operating_same_date_higher_grade_chosen_with_reason(reverse):
    chunks = [_op("hi", "official", "2026-01-01", "9~18", "월"), _op("lo", "informal", "2026-01-01", "8~20", "없음"),
              _op("old", "media", "2024-01-01", "7~17", "일")]
    if reverse:
        chunks.reverse()
    _, g = _grade_operating(chunks)
    op = g["operating"]
    assert op["status"] == "CHOSEN" and op["hours"] == "9~18" and op["source_ids"] == ["hi"]
    reasons = {s["source_id"]: s["reason"] for s in g["stale"]}
    assert [s["source_id"] for s in g["stale"]] == ["lo", "old"]
    assert reasons["lo"] == ("hours: 같은 날짜의 더 높은 등급 자료 hi(2026-01-01)와 다름; "
                             "closed: 같은 날짜의 더 높은 등급 자료 hi(2026-01-01)와 다름")
    assert reasons["old"] == ("hours: 2024-01-01 자료로, 더 새로운 hi(2026-01-01)와 다름; "
                              "closed: 2024-01-01 자료로, 더 새로운 hi(2026-01-01)와 다름")


def test_operating_source_without_hours_and_closed_is_left_out():
    chunks = [_op("e1", "official", "2026-05-01", "", ""), _op("ok", "media", "2025-01-01", "9~18", "월"),
              _op("e2", "official", "2026-01-01", "", "", place="p2")]
    deps = make_deps(chunks=chunks)
    ctx = make_ctx(places=[{"place_id": "p1", "current_name": "가"}, {"place_id": "p2", "current_name": "나"}])
    evidence.run_lookup_operating({}, ctx, deps)
    assert evidence.run_grade_evidence({}, ctx, deps).ok
    assert "p1: 운영 자료 e1에 운영 시간·휴무 없음, 판정에서 뺌" in ctx.warnings
    op1 = ctx.graded["p1"]["operating"]
    assert op1["status"] == "CHOSEN" and op1["source_ids"] == ["ok"] and ctx.graded["p1"]["stale"] == []
    assert ctx.graded["p2"]["operating"]["status"] == "UNKNOWN"
    assert "나 운영 정보 확인 안 됨" in ctx.unknowns


@pytest.mark.parametrize("answer", [{"fx-01": "x"}, {"zz": []}, {}])
def test_organize_names_no_usable_entry_is_tool_error(answer):
    deps = make_deps(chat=FakeChat([json.dumps(answer)]))
    ctx = make_ctx(places=_places("fx-01"))
    res = evidence.run_organize_names({}, ctx, deps)
    assert not res.ok and res.kind == KIND_TOOL_ERROR


def test_organize_names_no_place_without_underscore_key_is_tool_error():
    deps = make_deps(chat=FakeChat([json.dumps({"fx-01": []})]))
    ctx = make_ctx()
    ctx.search_results = [deps.get_chunk(OFFICIAL)]
    res = evidence.run_organize_names({}, ctx, deps)
    assert not res.ok and res.kind == KIND_TOOL_ERROR


def test_get_chunk_failure_is_tool_error():
    base = make_deps(chat=FakeChat([_dalmuri_answer()]))

    def broken(_cid):
        raise OSError("index gone")

    deps = Deps(**{**{n: getattr(base, n) for n in DEPS_NAMES}, "get_chunk": broken})
    ctx = make_ctx(places=_places("fx-01"))
    res = evidence.run_organize_names({}, ctx, deps)
    assert not res.ok and res.kind == KIND_TOOL_ERROR
    ctx.origins = {"fx-01": [{"name": "달무리나루", "name_kind": "station", "summary": "", "grade": None,
                              "source_ids": [], "chunk_ids": [OFFICIAL], "input_paths": []}]}
    res = evidence.run_grade_evidence({}, ctx, deps)
    assert not res.ok and res.kind == KIND_TOOL_ERROR


def test_cited_denied_or_dir_path_is_dropped():
    denied = "/hackathon/input/locked.md"  # inside the input folder, refused by the sandbox
    folder = "/hackathon/input/notes"
    answer = json.dumps({"fx-01": [
        {"name": "달무리나루", "name_kind": "station", "summary": "", "chunk_ids": [OFFICIAL],
         "input_paths": [denied, folder]},
    ]}, ensure_ascii=False)
    deps = make_deps(chat=FakeChat([answer]))
    ctx = make_ctx(places=_places("fx-01"))
    ctx.read_files = {
        denied: {"kind": "DENIED_BY_SANDBOX", "text": "", "front_matter": {}, "dates": [], "entries": []},
        folder: {"kind": "dir", "text": "", "front_matter": {}, "dates": [], "entries": []},
    }
    res = evidence.run_organize_names({}, ctx, deps)
    assert res.ok and res.data["dropped"] == 2
    assert ctx.origins["fx-01"][0]["input_paths"] == []
    assert ("fx-01/달무리나루: 근거 경로 /hackathon/input/locked.md는 파일 본문이 아님(kind=DENIED_BY_SANDBOX), 버림"
            in ctx.warnings)
    assert "fx-01/달무리나루: 근거 경로 /hackathon/input/notes는 파일 본문이 아님(kind=dir), 버림" in ctx.warnings


def test_grade_evidence_keeps_only_contract_keys_and_official_input_is_a():
    path = "/hackathon/input/official.md"
    deps = make_deps()
    ctx = make_ctx()
    ctx.read_files = {path: {"kind": "file", "text": "공식 자료", "dates": [], "entries": [],
                             "front_matter": {"source_id": "in-official", "source_type": "official",
                                              "published": "2026-01-01"}}}
    ctx.origins = {NO_PLACE_KEY: [{"name": "솔빛고개", "name_kind": "station", "summary": "s", "grade": "D",
                                   "source_ids": [], "chunk_ids": [], "input_paths": [path], "extra": 1,
                                   "date": "2026-01-01"}]}
    assert evidence.run_grade_evidence({}, ctx, deps).ok
    claim = ctx.graded[NO_PLACE_KEY]["origins"][0]
    assert set(claim) == {"name", "name_kind", "summary", "grade", "source_ids", "chunk_ids", "input_paths"}
    assert claim["grade"] == "A"
    assert claim["source_ids"] == ["in-official"]


def test_no_place_warning_uses_underscore_key():
    deps = make_deps()
    ctx = make_ctx()
    ctx.origins = {NO_PLACE_KEY: [{"name": "솔빛고개", "name_kind": "station", "summary": "", "grade": None,
                                   "source_ids": [], "chunk_ids": ["nope#c0"], "input_paths": []}]}
    assert evidence.run_grade_evidence({}, ctx, deps).ok
    assert "_/솔빛고개: 근거 청크 nope#c0 없음, 버림" in ctx.warnings
    assert "_/솔빛고개: 근거 없음" in ctx.warnings


def test_model_values_in_warnings_are_one_short_line():
    junk = "가짜\n값 " + "x" * 300
    answer = json.dumps({
        "fx-01": [
            {"name": junk, "name_kind": "current", "summary": "",
             "chunk_ids": [junk + "#c0"], "input_paths": ["/hackathon/input/" + junk]},
        ],
        junk: [],
        "fx-01\n" + "y" * 300: "not a list",
    }, ensure_ascii=False)
    deps = make_deps(chat=FakeChat([answer]))
    ctx = make_ctx(places=_places("fx-01"))
    ctx.read_files = {"/hackathon/input/" + junk: {"kind": "dir", "text": "", "front_matter": {}, "dates": [],
                                                   "entries": []}}
    assert evidence.run_organize_names({}, ctx, deps).ok
    assert evidence.run_grade_evidence({}, ctx, deps).ok
    assert len(ctx.warnings) >= 4
    for w in ctx.warnings:
        assert "\n" not in w
        assert len(w) <= 200


@pytest.mark.parametrize("chunks", [
    [],  # no operating source -> UNKNOWN
    [_op("s-old", "official", "2025-01-10", "10:00-18:00", "월", place="free-1"),
     _op("s-new", "informal", "2026-09-01", "09:00-17:00", "화", place="free-1")],  # newer but lower -> onsite
])
def test_operating_unknowns_with_long_free_place_name_are_one_line(chunks):
    deps = make_deps(chunks=chunks)
    ctx = make_ctx(places=[{"place_id": "free-1", "current_name": "가짜\n가게 " + "z" * 300}])
    assert evidence.run_lookup_operating({}, ctx, deps).ok
    assert evidence.run_grade_evidence({}, ctx, deps).ok
    assert any("운영 정보" in u for u in ctx.unknowns)
    for u in ctx.unknowns:
        assert "\n" not in u and len(u) <= 200



# ---------------------------------------------------------------- per-field operating judgement (K1-W7)


def _both_orders(chunks):
    out = []
    for seq in (chunks, list(reversed(chunks))):
        _, g = _grade_operating([dict(c) for c in seq])
        out.append(g)
    assert out[0] == out[1]
    return out[0]


def test_operating_fields_filled_by_different_sources():
    g = _both_orders([_op("A", "official", "", "09:00~18:00", ""), _op("B", "official", "2026-09-29", "", "매주 월요일")])
    op = g["operating"]
    assert op["status"] == "CHOSEN"
    assert op["hours"] == "09:00~18:00" and op["closed"] == "매주 월요일"
    assert op["as_of"] == "2026-09-29"
    assert sorted(op["source_ids"]) == ["A", "B"]
    assert g["stale"] == []


def test_operating_same_hours_old_official_new_media_agree():
    g = _both_orders([_op("old", "official", "2024-01-01", "9~18", ""), _op("new", "media", "2026-01-01", "9~18", "")])
    op = g["operating"]
    assert op["status"] == "CHOSEN" and op["hours"] == "9~18" and op["closed"] == ""
    assert sorted(op["source_ids"]) == ["new", "old"]
    assert op["as_of"] == "2026-01-01"
    assert g["stale"] == []


def test_operating_hours_conflict_needs_onsite_but_closed_decided():
    g = _both_orders([
        _op("old", "official", "2024-01-01", "9~18", ""),
        _op("new", "media", "2026-01-01", "10~20", ""),
        _op("cl", "media", "2025-06-01", "", "매주 화요일"),
    ])
    op = g["operating"]
    assert op["status"] == "NEEDS_ONSITE_CHECK"
    assert op["hours"] == "" and op["closed"] == "매주 화요일"
    assert [c["source_id"] for c in op["candidates"]] == ["old", "new"]
    assert op["source_ids"] == ["cl"]
    assert op["as_of"] == "2025-06-01"
    assert g["stale"] == []


def test_operating_hours_old_media_is_stale_under_new_official():
    g = _both_orders([_op("old", "media", "2024-10-30", "9~18", "월"), _op("new", "official", "2026-05-31", "10~20", "")])
    op = g["operating"]
    assert op["status"] == "CHOSEN"
    assert op["hours"] == "10~20" and op["closed"] == "월"
    assert sorted(op["source_ids"]) == ["new", "old"]
    assert op["as_of"] == "2026-05-31"
    assert g["stale"] == [{"source_id": "old", "reason": "hours: 2024-10-30 자료로, 더 새로운 new(2026-05-31)와 다름"}]


# ---------------------------------------------------------------- station aliases (K1-W9)

_ALIAS_PACK = {
    "pack_id": "pk", "work_title": "가상 작품", "aliases": [], "provenance": "synthetic",
    "stations": [{"name": "가상자양", "aliases": ["자양", "자양역"], "line": "가상7호선"}],
    "places": [],
}
_ALIAS_CHUNK = {
    "chunk_id": "st-alias#c0", "source": "sources/st-alias.md", "title": "역 이름 풀이", "text": "옛 나루 이름에서 왔다.",
    "char_start": 0, "char_end": 10, "dates_in_text": [], "mtime": 0.0, "source_id": "st-alias",
    "publisher": "가상 공사", "source_type": "official", "published": "2026-01-01", "url": "",
    "provenance": "synthetic", "kind": "origin", "about": ["자양역"],
}


def _alias_place(pack_id="pk", station=None):
    return {"order": 1, "place_id": "q1", "current_name": "가상 공원", "in_work_name": "", "scene": "",
            "old_names": [], "station": station if station is not None else {"name": "가상자양", "line": "가상7호선"},
            "pack_id": pack_id}


@pytest.mark.parametrize("pack_id,station", [("pk", None), ("", None), ("pk", "가상자양")])
def test_lookup_origin_uses_station_aliases(pack_id, station):
    deps = make_deps(chunks=[_ALIAS_CHUNK], packs=[_ALIAS_PACK])
    ctx = make_ctx(places=[_alias_place(pack_id, station)])
    assert evidence.run_lookup_origin({}, ctx, deps).ok
    ev = ctx.evidence["q1"]
    assert "자양" in ev and "자양역" in ev and "가상자양" in ev
    assert [c["chunk_id"] for c in ev["자양역"]] == ["st-alias#c0"]
    assert ev["가상자양"] == []


def test_organize_names_alias_claim_is_station_without_warning():
    answer = json.dumps({"q1": [{"name": "자양역", "name_kind": "bad", "summary": "옛 나루 이름",
                                 "chunk_ids": ["st-alias#c0"], "input_paths": []}]}, ensure_ascii=False)
    calls = []
    base = make_deps(chunks=[_ALIAS_CHUNK], packs=[_ALIAS_PACK], chat=FakeChat([answer]))

    def packs():
        calls.append(1)
        return base.theme_packs()

    deps = Deps(**{**{n: getattr(base, n) for n in DEPS_NAMES}, "theme_packs": packs})
    ctx = make_ctx(places=[_alias_place(), dict(_alias_place(), place_id="q2")])
    res = evidence.run_organize_names({}, ctx, deps)
    assert res.ok
    assert ctx.origins["q1"][0]["name_kind"] == "station"
    assert not any("장소 이름 목록에 없는 이름" in w for w in ctx.warnings)
    assert len(calls) == 1
    assert "자양역" in json.dumps(base.chat.calls[0][0], ensure_ascii=False)


def test_lookup_origin_theme_packs_error_goes_on_without_aliases():
    base = make_deps(chunks=[_ALIAS_CHUNK], packs=[_ALIAS_PACK])

    def broken():
        raise OSError("packs gone")

    deps = Deps(**{**{n: getattr(base, n) for n in DEPS_NAMES}, "theme_packs": broken})
    ctx = make_ctx(places=[_alias_place()])
    res = evidence.run_lookup_origin({}, ctx, deps)
    assert res.ok
    assert set(ctx.evidence["q1"]) == {"가상 공원", "가상자양"}


# ---------------------------------------------------------------- input-folder scope and tie order (K1-W10)


def test_evidence_path_outside_input_folder_is_dropped():
    out_path = "/hackathon/output/x/course.md"
    in_path = "/hackathon/input/a.md"
    answer = json.dumps({"fx-01": [
        {"name": "달무리나루", "name_kind": "station", "summary": "s", "chunk_ids": [], "input_paths": [out_path]},
    ]}, ensure_ascii=False)
    chat = FakeChat([answer])
    deps = make_deps(chat=chat)
    ctx = make_ctx(places=_places("fx-01"))
    ctx.read_files = {
        out_path: {"kind": "file", "text": "출력 파일 본문", "dates": [], "entries": [],
                   "front_matter": {"source_type": "official"}},
        in_path: {"kind": "file", "text": "입력 파일 본문", "front_matter": {}, "dates": [], "entries": []},
    }
    res = evidence.run_organize_names({}, ctx, deps)
    assert res.ok and res.data["dropped"] == 1
    prompt = json.dumps(chat.calls[0][0], ensure_ascii=False)
    assert out_path not in prompt and in_path in prompt
    assert ctx.origins["fx-01"][0]["input_paths"] == []
    warn = "fx-01/달무리나루: 근거 경로 /hackathon/output/x/course.md는 입력 폴더 밖, 버림"
    assert warn in ctx.warnings

    ctx.warnings.clear()
    ctx.origins["fx-01"][0]["input_paths"] = [out_path]  # grade_evidence checks again
    assert evidence.run_grade_evidence({}, ctx, deps).ok
    claim = ctx.graded["fx-01"]["origins"][0]
    assert claim["grade"] is None and claim["input_paths"] == []
    assert warn in ctx.warnings


def test_no_place_prompt_skips_files_outside_input_folder():
    out_path = "/hackathon/output/x/course.md"
    chat = FakeChat([json.dumps({NO_PLACE_KEY: []})])
    ctx = make_ctx()
    ctx.read_files = {out_path: {"kind": "file", "text": "본문", "front_matter": {}, "dates": [], "entries": []}}
    res = evidence.run_organize_names({}, ctx, make_deps(chat=chat))
    assert res.ok and chat.calls == [] and ctx.origins == {}


def test_tied_claims_order_does_not_follow_model_order():
    p1, p2 = "/hackathon/input/b.md", "/hackathon/input/a.md"
    claims = [
        {"name": "솔빛고개", "name_kind": "station", "summary": "둘째 풀이", "chunk_ids": [], "input_paths": [p1]},
        {"name": "솔빛고개", "name_kind": "station", "summary": "첫째 풀이", "chunk_ids": [], "input_paths": [p2]},
        {"name": "솔빛고개", "name_kind": "station", "summary": "나", "chunk_ids": [], "input_paths": [p2]},
    ]
    results = []
    for seq in (claims, list(reversed(claims))):
        ctx = make_ctx()
        ctx.read_files = {p: {"kind": "file", "text": "메모", "front_matter": {}, "dates": [], "entries": []}
                          for p in (p1, p2)}
        deps = make_deps(chat=FakeChat([json.dumps({NO_PLACE_KEY: seq}, ensure_ascii=False)]))
        assert evidence.run_organize_names({}, ctx, deps).ok
        assert evidence.run_grade_evidence({}, ctx, deps).ok
        results.append(ctx.graded[NO_PLACE_KEY])
    assert results[0] == results[1]
    assert [c["summary"] for c in results[0]["origins"]] == ["나", "첫째 풀이", "둘째 풀이"]
    assert [c["summary"] for c in results[0]["conflicts"][0]["claims"]] == ["나", "첫째 풀이", "둘째 풀이"]


# ---------------------------------------------------------------- short answers (K1-W13)


def test_organize_prompt_is_trimmed_and_asks_for_short_answers():
    long_chunk = dict(_ALIAS_CHUNK, chunk_id="long#c0", source_id="long", about=["가상 공원"], text="가" * 2000)
    path = "/hackathon/input/long.md"
    chat = FakeChat([json.dumps({"q1": []})])
    deps = make_deps(chunks=[long_chunk], packs=[_ALIAS_PACK], chat=chat)
    ctx = make_ctx(places=[_alias_place()])
    ctx.read_files = {path: {"kind": "file", "text": "나" * 2000, "front_matter": {}, "dates": [], "entries": []}}
    assert evidence.run_lookup_origin({}, ctx, deps).ok
    assert ctx.evidence["q1"]["가상 공원"][0]["text"] == "가" * 2000  # evidence itself is not cut
    assert evidence.run_organize_names({}, ctx, deps).ok
    assert len(chat.calls) == 1
    system, user = chat.calls[0][0]
    payload = json.loads(user["content"].split("\n", 1)[1])
    texts = [e["text"] for p in payload["places"] for n in p["names"] for e in n["evidence"]]
    texts += [f["text"] for f in payload["input_files"]]
    assert texts and max(len(t) for t in texts) == evidence.PROMPT_TEXT_CHARS == 600
    assert "주장 summary는 60자 이내" in system["content"]
    assert "이름 하나에 주장은 많아야 3개 — 근거 등급이 높을 것 같은 자료가 아니라 서로 다른 유래 설을 우선" in system["content"]
    assert "JSON 밖 설명 없이 JSON만" in system["content"]
    assert "한두 문장" not in system["content"]
    assert "이름마다 유래를 60자 이내 한 문장 한국어로 요약" in system["content"]
    assert evidence.SUMMARY_MAX_CHARS == 60 and evidence.CLAIMS_PER_NAME_MAX == 3
