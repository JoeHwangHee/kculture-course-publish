"""The demo plan run end to end through the registry with fakes (spec 2.2, 2.3, 2.4, 2.5, 4.5, 4.6).

select_places -> lookup_station -> lookup_origin -> lookup_operating -> organize_names -> grade_evidence
-> save_course -> request_publish, then the secrets scene (read_file on /hackathon/secrets).
"""

from __future__ import annotations

import json

import pytest

from common.limits import READ_FILE_MAX_BYTES
from common.schema import (
    COURSE_JSON,
    COURSE_MD,
    KIND_BLOCKED_BY_POLICY,
    KIND_DENIED_BY_SANDBOX,
    REASON_OVER_BUDGET,
    RESULT_KINDS,
    TEXT_DENIED_BY_SANDBOX,
    Course,
)
from common.tooling import ToolRegistry
from tools import register_all
from tools.tests.fakes import FakeChat, FakeFS, FakeHttp, make_ctx, make_deps

ROUTE = "fx-src-route-walk#c0"
DALMURI_OFFICIAL = "fx-src-origin-dalmuri-official#c0"
DALMURI_BLOG = "fx-src-origin-dalmuri-blog#c0"
SOLBIT_ACADEMIC = "fx-src-origin-solbit-academic#c0"

LEGS = [
    {"from": "새벽솔", "to": "fx-02", "minutes": 7, "mode": "walk", "chunk_ids": [ROUTE]},
    {"from": "fx-02", "to": "fx-04", "minutes": 5, "mode": "walk", "chunk_ids": [ROUTE]},
    {"from": "fx-04", "to": "fx-01", "minutes": 15, "mode": "transit", "chunk_ids": [ROUTE]},
    {"from": "fx-01", "to": "fx-03", "minutes": 25, "mode": "transit", "chunk_ids": [ROUTE]},
    {"from": "fx-03", "to": "fx-05", "minutes": 80, "mode": "walk", "chunk_ids": [ROUTE]},
    {"from": "fx-05", "to": "fx-06", "minutes": 100, "mode": "transit", "chunk_ids": [ROUTE]},
]

NAMES = {
    "fx-01": [
        {"name": "달무리나루", "name_kind": "station", "summary": "강 위로 달무리가 잘 보이던 나루터라는 데서 온 이름",
         "chunk_ids": [DALMURI_OFFICIAL], "input_paths": []},
        {"name": "달무리나루", "name_kind": "station", "summary": "나루의 뱃사공 '달무리'의 이름에서 왔다는 구전",
         "chunk_ids": [DALMURI_BLOG], "input_paths": []},
    ],
    "fx-03": [
        {"name": "솔빛고개", "name_kind": "station", "summary": "가상 지명 사전에 실린 고개 이름의 유래",
         "chunk_ids": [SOLBIT_ACADEMIC], "input_paths": []},
    ],
}

DEMO_PLAN = [
    ("select_places", {"pack_id": "fx-byeolmuri", "time_budget_min": 180, "start": "새벽솔역"}),
    ("lookup_station", {}),
    ("lookup_origin", {}),
    ("lookup_operating", {}),
    ("organize_names", {}),
    ("grade_evidence", {}),
    ("save_course", {}),
    ("request_publish", {}),
]


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_all(registry)
    return registry


def _step(registry: ToolRegistry, name: str, args: dict, ctx, deps):
    assert registry.check_args(name, args) == [], name
    return registry.get(name).run(registry.with_defaults(name, args), ctx, deps)


@pytest.fixture
def demo(tmp_path):
    chat = FakeChat([json.dumps(LEGS, ensure_ascii=False), json.dumps(NAMES, ensure_ascii=False)])
    http = FakeHttp({"status": None, "body": "", "error": "TUNNEL_403"})
    deps = make_deps(chat=chat, http=http)
    ctx = make_ctx(
        run_dir=str(tmp_path), publish_repo="o/r",
        goal={"work": "별무리 수호단", "time_budget_min": 180, "start": "새벽솔역", "constraints": [],
              "publish_requested": True},
    )
    registry = _registry()
    results = {name: _step(registry, name, args, ctx, deps) for name, args in DEMO_PLAN}
    course_json = json.loads((tmp_path / COURSE_JSON).read_text(encoding="utf-8"))
    return {"ctx": ctx, "results": results, "chat": chat, "http": http, "course": course_json, "dir": tmp_path}


def _place(course: dict, place_id: str) -> dict:
    return next(p for p in course["places"] if p["place_id"] == place_id)


def test_every_step_kind_is_in_the_contract_set_and_only_publish_fails(demo):
    for name, result in demo["results"].items():
        assert result.kind in RESULT_KINDS, name
        if name != "request_publish":
            assert result.ok is True, f"{name}: {result.error}"


def test_exactly_two_model_calls(demo):
    assert [purpose for _, purpose in demo["chat"].calls] == ["select_places", "organize_names"]


def test_course_starts_at_start_and_fits_budget(demo):
    course = demo["course"]
    first = course["places"][0]
    assert first["place_id"] == "fx-02"
    assert first["travel_min_from_prev"] == 7  # leg from the start station, not 0
    assert first["arrive_min"] == 7
    assert [p["place_id"] for p in course["places"]] == ["fx-02", "fx-04", "fx-01", "fx-03"]
    assert course["total_min"] is not None and course["total_min"] <= 180
    assert course["total_min"] == 162  # 7+30 +5+30 +15+30 +25+20
    assert course["excluded"] == [
        {"place_id": "fx-06", "reason": REASON_OVER_BUDGET},
        {"place_id": "fx-05", "reason": REASON_OVER_BUDGET},
    ]
    assert demo["results"]["select_places"].data["start"] == "새벽솔"


def test_origin_conflict_is_kept_higher_grade_first(demo):
    fx01 = _place(demo["course"], "fx-01")
    conflicts = [c for c in fx01["conflicts"] if c["name"] == "달무리나루"]
    assert len(conflicts) == 1
    assert [c["grade"] for c in conflicts[0]["claims"]] == ["A", "D"]
    assert conflicts[0]["claims"][0]["chunk_ids"] == [DALMURI_OFFICIAL]
    fx03 = _place(demo["course"], "fx-03")
    assert [(o["name"], o["grade"]) for o in fx03["origins"]] == [("솔빛고개", "B")]


def test_operating_freshness(demo):
    fx02 = _place(demo["course"], "fx-02")
    assert fx02["operating"]["status"] == "CHOSEN"
    assert fx02["operating"]["hours"] == "10:00~20:00"
    assert fx02["operating"]["as_of"] == "2026-08-01"
    assert [s["source_id"] for s in fx02["stale"]] == ["fx-src-op-byeolgaru-2024"]
    fx03 = _place(demo["course"], "fx-03")
    assert fx03["operating"]["status"] == "NEEDS_ONSITE_CHECK"
    assert len(fx03["operating"]["candidates"]) == 2


def test_course_files_follow_the_contract(demo):
    Course.from_dict(demo["course"])
    assert demo["ctx"].course == demo["course"]
    md = (demo["dir"] / COURSE_MD).read_text(encoding="utf-8")
    assert "현장 확인 필요" in md
    assert "등급 A, 출처: 가상시 지명위원회 2023-05-10" in md
    assert str(demo["dir"]) not in md


def test_publish_is_blocked_by_policy_not_replanned(demo):
    result = demo["results"]["request_publish"]
    assert result.kind == KIND_BLOCKED_BY_POLICY
    assert result.ok is False
    assert result.needs_replan is False
    assert len(demo["http"].calls) == 1
    url, headers, body = demo["http"].calls[0]
    assert url == "https://api.github.com/repos/o/r/issues"
    assert "authorization" not in {k.lower() for k in headers}
    assert body["title"] == "K-콘텐츠 배경지 코스: 별무리 수호단"


def test_secrets_scene_is_denied_by_sandbox():
    fs = FakeFS({"/hackathon/secrets": PermissionError(13, "Permission denied")})
    ctx = make_ctx()
    result = _step(_registry(), "read_file", {"path": "/hackathon/secrets"}, ctx, make_deps(fs=fs))
    assert result.kind == KIND_DENIED_BY_SANDBOX
    assert result.ok is False
    assert result.needs_replan is False
    assert result.data["note"] == TEXT_DENIED_BY_SANDBOX
    assert fs.calls == [("/hackathon/secrets", READ_FILE_MAX_BYTES + 1)]
    assert ctx.read_files["/hackathon/secrets"]["kind"] == "DENIED_BY_SANDBOX"
