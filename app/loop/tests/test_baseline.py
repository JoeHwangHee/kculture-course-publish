"""Baseline run: Nemotron alone, baseline.json in the course.json top-level shape (spec 4.4, 4.6)."""

import json

from common.schema import Course

from loop.baseline import TEXT_NOT_JSON, run_baseline

COURSE_KEYS = {"run_id", "request", "goal", "places", "total_min", "excluded", "unknowns", "warnings", "publish"}


def _run(kit, tmp_path, replies):
    chat = kit.ScriptedChat(replies, model="fake-nemotron")
    clock = kit.FakeClock()
    out = run_baseline("별무리 코스 짜줘", nemotron_chat=chat, output_root=tmp_path, clock=clock, now=kit.FakeNow())
    return out, chat, kit.check_run(out["run_dir"], tmp_path)


def _baseline(out):
    with open(f"{out['run_dir']}/baseline.json", encoding="utf-8") as fh:
        return json.load(fh)


def test_baseline_file_has_exactly_the_course_keys(kit, tmp_path):
    reply = json.dumps({"goal": {"work": "별무리", "time_budget_min": 180, "start": "혜화", "constraints": [],
                                 "publish_requested": True},
                        "places": [{"order": 1, "current_name": "별무리공원", "travel_min_from_prev": 999}],
                        "total_min": 1060, "extra": "버림"}, ensure_ascii=False)
    out, chat, r = _run(kit, tmp_path, [reply])
    assert out["status"] == "BASELINE_DONE"
    b = _baseline(out)
    assert set(b) == COURSE_KEYS == {f.name for f in Course.__dataclass_fields__.values()}
    assert b["run_id"] == out["run_id"] and b["request"] == "별무리 코스 짜줘"
    assert b["places"][0]["travel_min_from_prev"] == 999  # model values are not fixed
    assert b["total_min"] == 1060
    assert b["publish"] == {"status": "", "url": None}
    assert b["excluded"] == [] and b["unknowns"] == []
    assert len(chat.calls) == 1
    assert chat.calls[0]["purpose"] == "baseline"
    assert chat.calls[0]["kw"] == {"response_format": {"type": "json_object"}}
    assert r["run"].route == "none" and r["run"].status == "BASELINE_DONE"
    assert r["model_calls"] == {"router": 0, "nemotron": 1}
    assert [t["event"] for t in r["trace"]] == ["baseline", "final"]
    assert r["trace"][0]["model"]["name"] == "fake-nemotron"
    assert "baseline.json" in r["run"].files


def test_baseline_defaults_when_not_json(kit, tmp_path):
    out, _, _ = _run(kit, tmp_path, ["코스는 이렇습니다"])
    b = _baseline(out)
    assert out["status"] == "BASELINE_DONE"
    assert b["places"] == [] and b["warnings"] == [TEXT_NOT_JSON]
    assert b["goal"] == {"work": "", "time_budget_min": None, "start": "", "constraints": [],
                         "publish_requested": False}
    assert b["total_min"] is None


def test_baseline_model_failure_is_failed_without_file(kit, tmp_path):
    out, _, r = _run(kit, tmp_path, [TimeoutError()])
    assert out["status"] == "FAILED"
    assert "baseline.json" not in r["run"].files
    assert r["model_calls"]["nemotron"] == 1
