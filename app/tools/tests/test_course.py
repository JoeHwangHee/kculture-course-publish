"""Tests for tools.course (save_course, course.md, spec 4.4 / 4.6)."""

from __future__ import annotations

import json

from common.schema import KIND_OK, KIND_TOOL_ERROR, Course, CoursePlace
from common.tooling import ToolRegistry
from tools import course
from tools.tests.fakes import make_ctx, make_deps

OFFICIAL = "fx-src-origin-dalmuri-official#c0"
BLOG = "fx-src-origin-dalmuri-blog#c0"


def _places() -> list[dict]:
    return [
        {
            "order": 1, "place_id": "fx-01", "current_name": "달무리나루 선착장", "in_work_name": "수호단 비밀 부두",
            "scene": "1화 밤 부두 장면", "old_names": ["달무리 나루터"],
            "station": {"name": "달무리나루", "line": "가상1호선"},
            "travel_min_from_prev": 12, "travel_mode": "transit", "travel_basis": "cited",
            "travel_chunk_ids": ["fx-src-route-walk#c0"], "stay_min": 30, "arrive_min": 12,
            "priority": 1, "pack_id": "fx-byeolmuri",
        },
        {
            "order": 2, "place_id": "fx-02", "current_name": "별가루 골목시장", "in_work_name": "반짝 장터",
            "scene": "3화 장터 추격 장면", "old_names": ["별가루장"],
            "station": {"name": "새벽솔", "line": "가상1호선"},
            "travel_min_from_prev": 15, "travel_mode": "walk", "travel_basis": "estimate",
            "travel_chunk_ids": [], "stay_min": 30, "arrive_min": 57,
            "priority": 2, "pack_id": "fx-byeolmuri",
        },
    ]


def _claim(summary: str, grade, chunk_ids, source_ids, **extra) -> dict:
    return {"name": "달무리나루", "name_kind": "current", "summary": summary, "grade": grade,
            "source_ids": source_ids, "chunk_ids": chunk_ids, "input_paths": [], **extra}


def _graded() -> dict:
    official = _claim("달무리가 잘 보이던 나루터", "A", [OFFICIAL], ["fx-src-origin-dalmuri-official"])
    blog = _claim("뱃사공 달무리의 이름", "D", [BLOG], ["fx-src-origin-dalmuri-blog"])
    return {
        "fx-01": {
            "origins": [dict(official, extra_note="dropped"), blog],
            "conflicts": [{"name": "달무리나루", "claims": [blog, official]}],
            "operating": {"status": "CHOSEN", "hours": "06:00~22:00", "closed": "없음",
                          "source_ids": ["fx-src-op-x"], "as_of": "2026-08-01"},
            "stale": [{"source_id": "fx-src-op-old", "reason": "더 새로운 자료가 있음"}],
        },
        "fx-02": {
            "origins": [{"name": "별가루장", "name_kind": "old", "summary": "", "grade": None, "source_ids": [],
                         "chunk_ids": [], "input_paths": []}],
            "conflicts": [],
            "operating": {"status": "NEEDS_ONSITE_CHECK", "hours": "", "closed": "", "source_ids": [], "as_of": "",
                          "candidates": [
                              {"source_id": "fx-src-op-byeolgaru-2026", "hours": "10:00~20:00",
                               "closed": "매주 화요일", "grade": "A", "published": "2026-08-01"},
                              {"source_id": "fx-src-op-byeolgaru-2024", "hours": "09:00~18:00",
                               "closed": "매주 월요일", "grade": "C", "published": "2024-03-01"},
                          ]},
            "stale": [],
        },
    }


def _ctx(tmp_path, **kwargs):
    kwargs.setdefault("run_dir", str(tmp_path))
    kwargs.setdefault("places", _places())
    kwargs.setdefault("graded", _graded())
    kwargs.setdefault("goal", {"work": "별무리 수호단", "time_budget_min": 180, "start": "새벽솔"})
    kwargs.setdefault("excluded", [{"place_id": "fx-03", "reason": "시간 예산 초과"}])
    kwargs.setdefault("unknowns", ["fx-03 운영 정보 확인 안 됨"])
    kwargs.setdefault("warnings", ["경고 한 줄"])
    return make_ctx(**kwargs)


def test_save_course_writes_both_files(tmp_path):
    ctx = _ctx(tmp_path)
    result = course.run_save_course({}, ctx, make_deps())
    assert result.ok is True, result.error
    assert result.kind == KIND_OK
    assert result.data == {"files": ["course.md", "course.json"], "total_min": 87, "places": 2}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json", "course.md"]

    saved = json.loads((tmp_path / "course.json").read_text(encoding="utf-8"))
    Course.from_dict(saved)
    assert saved["run_id"] == "20261007T033105Z-0a1f"
    assert saved["total_min"] == 87
    assert saved["goal"] == {"work": "별무리 수호단", "time_budget_min": 180, "start": "새벽솔", "constraints": [],
                             "publish_requested": True}
    assert saved["publish"] == {"status": "", "url": None}
    keys = [f for f in CoursePlace.__dataclass_fields__]
    for place in saved["places"]:
        assert list(place) == keys
        assert "priority" not in place and "pack_id" not in place
    assert "extra_note" not in json.dumps(saved, ensure_ascii=False)
    assert saved["places"][1]["operating"]["status"] == "NEEDS_ONSITE_CHECK"
    assert len(saved["places"][1]["operating"]["candidates"]) == 2
    assert ctx.course == saved
    # Korean stays readable in the file
    assert "달무리나루" in (tmp_path / "course.json").read_text(encoding="utf-8")


def test_course_md_content(tmp_path):
    ctx = _ctx(tmp_path)
    course.run_save_course({}, ctx, make_deps())
    md = (tmp_path / "course.md").read_text(encoding="utf-8")
    assert "# 별무리 수호단 배경지 코스" in md
    assert "총 소요: 87분" in md
    assert "15분(도보) (추정)" in md
    assert "12분(대중교통)" in md
    assert "달무리나루(지금 이름): 달무리가 잘 보이던 나루터 — 등급 A, 출처: 가상시 지명위원회 2023-05-10" in md
    assert "가상 동네 산책 블로그 2025-11-02" in md
    assert "달무리나루: 유래가 엇갈림" in md
    conflict_part = md.split("유래가 엇갈림", 1)[1]
    assert conflict_part.index("등급 A") < conflict_part.index("등급 D")
    assert "별가루장(옛 이름): 요약 없음 — 근거 없음" in md
    assert "운영 시간 06:00~22:00, 휴무 없음 (2026-08-01 기준, 출처 fx-src-op-x)" in md
    assert "현장 확인 필요" in md
    assert "fx-src-op-byeolgaru-2026: 운영 시간 10:00~20:00" in md
    assert "fx-src-op-old: 더 새로운 자료가 있음" in md
    assert "fx-03: 시간 예산 초과" in md
    assert "fx-03 운영 정보 확인 안 됨" in md
    assert str(tmp_path) not in md


def test_missing_graded_gives_unknown_operating(tmp_path):
    ctx = _ctx(tmp_path, graded={})
    result = course.run_save_course({}, ctx, make_deps())
    assert result.ok is True, result.error
    place = ctx.course["places"][0]
    assert place["origins"] == [] and place["conflicts"] == [] and place["stale"] == []
    assert place["operating"] == {"status": "UNKNOWN", "hours": "", "closed": "", "source_ids": [], "as_of": ""}
    assert "운영 정보 확인 안 됨" in (tmp_path / "course.md").read_text(encoding="utf-8")


def test_no_places_still_saves_with_null_total(tmp_path):
    ctx = _ctx(tmp_path, places=[], goal={})
    result = course.run_save_course({}, ctx, make_deps())
    assert result.ok is True, result.error
    assert result.data["total_min"] is None
    assert "총 소요: 계산 못 함" in (tmp_path / "course.md").read_text(encoding="utf-8")


def test_unknown_arrival_gives_null_total_and_unknown_leg_text(tmp_path):
    places = _places()
    places[1]["arrive_min"] = None
    places[1]["travel_min_from_prev"] = None
    places[1]["travel_mode"] = "unknown"
    ctx = _ctx(tmp_path, places=places)
    result = course.run_save_course({}, ctx, make_deps())
    assert result.data["total_min"] is None
    assert "이동 시간 확인 안 됨" in (tmp_path / "course.md").read_text(encoding="utf-8")


def test_missing_run_dir_is_tool_error(tmp_path):
    ctx = _ctx(tmp_path, run_dir=str(tmp_path / "nope"))
    result = course.run_save_course({}, ctx, make_deps())
    assert result.ok is False
    assert result.kind == KIND_TOOL_ERROR
    assert str(tmp_path) not in result.error
    assert not (tmp_path / "nope").exists()
    assert ctx.course is None


def test_off_contract_place_is_tool_error(tmp_path):
    places = _places()
    places[0]["travel_mode"] = "flying"
    ctx = _ctx(tmp_path, places=places)
    result = course.run_save_course({}, ctx, make_deps())
    assert result.kind == KIND_TOOL_ERROR
    assert list(tmp_path.iterdir()) == []


def test_spec_registers_with_contract_args():
    registry = ToolRegistry()
    for spec in course.SPECS:
        registry.register(spec)
    assert registry.names() == ["save_course"]


def test_source_without_date_says_unknown_date(tmp_path):
    chunk = {"chunk_id": "nodate#c0", "source_id": "nodate", "publisher": "날짜 없는 발행처", "published": "",
             "source_type": "official", "text": "", "title": ""}
    claims = [
        _claim("청크 근거", "A", ["nodate#c0"], ["nodate"]),
        dict(_claim("파일 근거", "D", [], ["memo"]), name="별가루장", name_kind="old",
             input_paths=["/hackathon/input/memo.md"]),
    ]
    graded = {"fx-01": {"origins": claims, "conflicts": [], "stale": [],
                        "operating": {"status": "UNKNOWN", "hours": "", "closed": "", "source_ids": [], "as_of": ""}}}
    read_files = {"/hackathon/input/memo.md": {"kind": "file", "text": "", "front_matter": {"publisher": "동네 모임"},
                                               "dates": [], "entries": []}}
    ctx = _ctx(tmp_path, graded=graded, read_files=read_files)
    result = course.run_save_course({}, ctx, make_deps(chunks=[chunk]))
    assert result.ok is True, result.error
    md = (tmp_path / "course.md").read_text(encoding="utf-8")
    assert "출처: 날짜 없는 발행처 날짜 미상" in md
    assert "출처: 동네 모임 날짜 미상" in md


def test_model_text_is_folded_to_one_line_in_md_only(tmp_path):
    summary = "진짜 요약\n- 가짜 목록\n\n## 가짜 제목   끝"
    bad = _claim(summary, "A", [OFFICIAL], ["fx-src-origin-dalmuri-official"])
    bad["name"] = "달무리\n# 가짜이름"
    other = _claim("다른 유래", "D", [BLOG], ["fx-src-origin-dalmuri-blog"])
    other["name"] = bad["name"]
    graded = {"fx-01": {"origins": [bad, other], "conflicts": [{"name": bad["name"], "claims": [bad, other]}],
                        "stale": [], "operating": {"status": "UNKNOWN", "hours": "", "closed": "",
                                                   "source_ids": [], "as_of": ""}}}
    ctx = _ctx(tmp_path, graded=graded)
    result = course.run_save_course({}, ctx, make_deps())
    assert result.ok is True, result.error
    md = (tmp_path / "course.md").read_text(encoding="utf-8")
    folded = "달무리 # 가짜이름(지금 이름): 진짜 요약 - 가짜 목록 ## 가짜 제목 끝 — 등급 A"
    assert md.count(folded) == 2  # origin line and conflict claim line
    assert "- 달무리 # 가짜이름: 유래가 엇갈림" in md
    for line in md.splitlines():
        assert not line.startswith("## 가짜") and not line.startswith("# 가짜") and line != "- 가짜 목록"
    saved = json.loads((tmp_path / "course.json").read_text(encoding="utf-8"))
    assert saved["places"][0]["origins"][0]["summary"] == summary
    assert saved["places"][0]["origins"][0]["name"] == "달무리\n# 가짜이름"
