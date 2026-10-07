"""Contract values (spec 2.2, 2.3, 4.4-4.7) and record round trips in common.schema."""

import json
from dataclasses import fields
from datetime import datetime, timedelta, timezone

import pytest

from common import schema as s

UTC = timezone.utc
KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------- value sets, verbatim from the spec


def test_status_values_match_spec_4_4():
    assert s.STATUSES == (
        "ANSWERED_LIGHT", "UNAVAILABLE", "ANSWERED_HEAVY", "COURSE_SAVED", "PUBLISH_PENDING_APPROVAL",
        "PUBLISHED", "PUBLISH_FAILED", "FAILED", "BASELINE_DONE",
    )
    assert s.STATUS_BASELINE_DONE == "BASELINE_DONE"
    assert s.STATUS_PUBLISH_PENDING_APPROVAL == "PUBLISH_PENDING_APPROVAL"


def test_tool_result_kinds_match_spec_4_2():
    assert s.RESULT_KINDS == (
        "OK", "TOOL_ERROR", "BLOCKED_BY_POLICY", "CREATED", "HTTP_ERROR", "NETWORK_ERROR",
        "DENIED_BY_SANDBOX", "NOT_FOUND", "OUT_OF_SCOPE", "TOO_LARGE", "NOT_TEXT",
    )
    assert s.KIND_TOOL_ERROR == "TOOL_ERROR"
    assert s.KIND_DENIED_BY_SANDBOX == "DENIED_BY_SANDBOX"


def test_source_type_grade_table_matches_spec_2_3():
    assert s.SOURCE_TYPES == ("official", "academic", "media", "informal")
    assert s.SOURCE_TYPE_GRADE == {"official": "A", "academic": "B", "media": "C", "informal": "D"}
    assert s.GRADES == ("A", "B", "C", "D")
    assert s.DEFAULT_SOURCE_TYPE == "informal"
    for st, grade in s.SOURCE_TYPE_GRADE.items():
        assert s.grade_for_source_type(st) == grade


@pytest.mark.parametrize("value", ["", None, "blog", "Official", " official", 3, ["official"]])
def test_empty_or_unknown_source_type_is_informal_grade_d(value):
    assert s.normalize_source_type(value) == "informal"
    assert s.grade_for_source_type(value) == "D"


def test_closed_value_sets_match_spec():
    assert s.NAME_KINDS == ("current", "old", "in_work", "station")
    assert s.OPERATING_STATUSES == ("CHOSEN", "NEEDS_ONSITE_CHECK", "UNKNOWN")
    assert s.TRAVEL_MODES == ("walk", "transit", "unknown")
    assert s.TRAVEL_BASES == ("cited", "estimate")
    assert s.PUBLISH_ATTEMPT_RESULTS == ("BLOCKED_BY_POLICY", "CREATED", "HTTP_ERROR", "NETWORK_ERROR")
    assert set(s.PUBLISH_ATTEMPT_RESULTS) <= set(s.RESULT_KINDS)
    assert s.PUBLISH_STATUSES == ("PUBLISHED", "PUBLISH_PENDING_APPROVAL", "PUBLISH_FAILED")
    assert s.PUBLISH_TARGET == "github-issue"
    assert s.ROUTES == ("heavy", "light", "none")
    assert s.TRACE_EVENTS == (
        "route", "light_answer", "plan", "plan_check", "replan", "step", "publish_attempt", "approval_wait",
        "final", "baseline",
    )
    assert s.TRACE_KEYS == ("seq", "ts", "run_id", "event", "tool", "args", "result", "why", "model", "prev_hash")
    assert s.PROVENANCES == ("real", "synthetic")
    assert s.SOURCE_KINDS == ("origin", "operating", "appearance", "other")
    assert s.INDEX_COLLECTION == "kb"


def test_tool_names_are_the_eleven_of_spec_2_2():
    assert s.TOOL_NAMES == (
        "select_places", "lookup_station", "lookup_origin", "lookup_operating", "organize_names",
        "grade_evidence", "save_course", "request_publish", "search_db", "list_input", "read_file",
    )


def test_metadata_keys_match_spec_4_3_and_4_7():
    assert s.FRONT_MATTER_KEYS == (
        "source_id", "title", "publisher", "source_type", "published", "url", "provenance", "kind", "about",
    )
    assert s.OPERATING_FRONT_MATTER_KEYS == ("place_ids", "hours", "closed")
    assert s.CHUNK_BASE_KEYS == (
        "chunk_id", "source", "title", "text", "char_start", "char_end", "dates_in_text", "mtime",
    )
    assert s.CHUNK_SOURCE_KEYS == (
        "source_id", "publisher", "source_type", "published", "url", "provenance", "kind", "about",
    )
    assert s.CHUNK_OPERATING_KEYS == ("place_ids", "hours", "closed")


def test_paths_and_contract_phrases_are_verbatim():
    assert (s.HACKATHON_DIR, s.INPUT_DIR, s.OUTPUT_DIR) == ("/hackathon", "/hackathon/input", "/hackathon/output")
    assert (s.RESTRICTED_DIR, s.SECRETS_DIR) == ("/hackathon/restricted", "/hackathon/secrets")
    assert s.EVIDENCE_LABEL_LIGHT == "자료 근거 없음(일반 안내)"
    assert s.TEXT_DENIED_BY_SANDBOX == "접근이 거부됨(인프라 차단)"
    assert s.TEXT_UNAVAILABLE == "지금은 판단할 수 없어 응답하지 않습니다"
    assert s.REASON_OVER_BUDGET == "시간 예산 초과"
    assert s.TEXT_ESTIMATE == "추정"
    assert s.TEXT_UNCONFIRMED == "확인 안 됨"
    assert s.TEXT_NO_EVIDENCE == "근거 없음"
    assert s.TEXT_ONSITE_CHECK == "현장 확인 필요"
    assert s.TEXT_USER_SAID_DO_NOT_SEND == "사용자가 보내지 말라고 함"
    assert s.TEXT_NO_PLACES_FOR_WORK == "자료에 해당 작품의 배경지가 없음"
    assert s.RUN_FILES == (
        "run.json", "trace.jsonl", "course.md", "course.json", "answer.md", "answer.json", "publish.json",
        "baseline.json",
    )


# ---------------------------------------------------------------- run_id and timestamps


def test_run_id_format_is_utc_second_plus_four_hex():
    when = datetime(2026, 10, 7, 3, 31, 5, 999_000, tzinfo=UTC)
    assert s.new_run_id(when, rand_hex="0a1f") == "20261007T033105Z-0a1f"
    assert s.is_run_id("20261007T033105Z-0a1f")


def test_run_id_converts_aware_time_to_utc_and_naive_counts_as_utc():
    assert s.new_run_id(datetime(2026, 10, 7, 12, 31, 5, tzinfo=KST), rand_hex="beef") == "20261007T033105Z-beef"
    assert s.new_run_id(datetime(2026, 10, 7, 3, 31, 5), rand_hex="beef") == "20261007T033105Z-beef"


def test_run_id_random_suffix_is_four_lowercase_hex():
    ids = {s.new_run_id(datetime(2026, 10, 7, tzinfo=UTC)) for _ in range(64)}
    assert len(ids) > 1
    for rid in ids:
        assert s.is_run_id(rid)
        assert rid.startswith("20261007T000000Z-")
        suffix = rid.rsplit("-", 1)[1]
        assert len(suffix) == 4 and suffix == suffix.lower()
        int(suffix, 16)


@pytest.mark.parametrize("bad", ["0a1", "0a1g", "0a1f2", "", "-0a1"])
def test_run_id_rejects_bad_suffix(bad):
    with pytest.raises(s.SchemaError):
        s.new_run_id(datetime(2026, 10, 7, tzinfo=UTC), rand_hex=bad)


@pytest.mark.parametrize("bad", [
    "20261007T033105Z", "20261007T033105-0a1f", "2026-10-07T03:31:05Z-0a1f", "20261307T033105Z-0a1f",
    "20261007T033105Z-0a1f\n", None, 20261007,
])
def test_is_run_id_rejects(bad):
    assert not s.is_run_id(bad)


def test_utc_ts_has_milliseconds_and_z():
    assert s.utc_ts(datetime(2026, 10, 7, 3, 31, 5, 123_456, tzinfo=UTC)) == "2026-10-07T03:31:05.123Z"
    assert s.utc_ts(datetime(2026, 10, 7, 12, 31, 5, tzinfo=KST)) == "2026-10-07T03:31:05.000Z"
    assert s.utc_ts(datetime(2026, 10, 7, 3, 31, 5, 1_000)) == "2026-10-07T03:31:05.001Z"
    now = s.utc_ts()
    assert s.is_utc_ts(now)
    assert s.parse_utc_ts("2026-10-07T03:31:05.123Z") == datetime(2026, 10, 7, 3, 31, 5, 123_000, tzinfo=UTC)


@pytest.mark.parametrize("bad", [
    "2026-10-07T03:31:05Z", "2026-10-07T03:31:05.12Z", "2026-10-07T03:31:05.123+00:00",
    "2026-10-07 03:31:05.123Z", "2026-13-07T03:31:05.123Z", None,
])
def test_is_utc_ts_rejects(bad):
    assert not s.is_utc_ts(bad)


# ---------------------------------------------------------------- record round trips

RUN_ID = "20261007T033105Z-0a1f"
TS = "2026-10-07T03:31:05.123Z"


def _goal(**kw):
    base = dict(work="별무리 수호단", time_budget_min=180, start="새벽솔", constraints=["걷기 위주"],
                publish_requested=True)
    base.update(kw)
    return s.Goal(**base)


def _course():
    claim_a = s.OriginClaim(name="달무리나루", name_kind="station", summary="달무리가 잘 보이던 나루",
                            grade="A", source_ids=["fx-src-origin-dalmuri-official"], chunk_ids=["c1"])
    claim_d = s.OriginClaim(name="달무리나루", name_kind="station", summary="뱃사공 이름에서 옴",
                            grade="D", source_ids=["fx-src-origin-dalmuri-blog"], chunk_ids=["c2"],
                            input_paths=["/hackathon/input/note.md"])
    place = s.CoursePlace(
        order=1, place_id="fx-01", current_name="달무리나루 선착장", in_work_name="수호단 비밀 부두",
        scene="1화 첫 만남", old_names=["달무리 나루터"], station=s.Station(name="달무리나루", line="가상1호선"),
        travel_min_from_prev=11, travel_mode="transit", travel_basis="cited", travel_chunk_ids=["c9"],
        stay_min=30, arrive_min=11, origins=[claim_a, claim_d],
        conflicts=[s.Conflict(name="달무리나루", claims=[claim_a, claim_d])],
        operating=s.Operating(status="NEEDS_ONSITE_CHECK", hours="", closed="", source_ids=["x", "y"],
                              as_of="", candidates=[{"source_id": "x"}, {"source_id": "y"}]),
        stale=[s.StaleItem(source_id="z", reason="더 새로운 자료가 있음")],
    )
    place2 = s.CoursePlace(
        order=2, place_id="free-1", current_name="어느 찻집", in_work_name="", scene="", station=s.Station(),
        travel_min_from_prev=None, travel_mode="unknown", travel_basis="estimate", stay_min=60, arrive_min=None,
        operating=s.Operating(status="UNKNOWN"),
    )
    return s.Course(
        run_id=RUN_ID, request="별무리 수호단 보고 왔어요. 오후 3시간, 새벽솔에서 시작할게요", goal=_goal(),
        places=[place, place2], total_min=None,
        excluded=[s.ExcludedItem(place_id="fx-05", reason="시간 예산 초과")],
        unknowns=["예산 검사를 못 함"], warnings=["w"], publish=s.PublishInfo(status="", url=None),
    )


def _json_round_trip(record):
    data = json.loads(json.dumps(record.to_dict(), ensure_ascii=False))
    return type(record).from_dict(data)


def test_course_round_trip_and_key_order():
    course = _course()
    assert _json_round_trip(course) == course
    d = course.to_dict()
    assert list(d) == ["run_id", "request", "goal", "places", "total_min", "excluded", "unknowns", "warnings",
                       "publish"]
    assert list(d["goal"]) == ["work", "time_budget_min", "start", "constraints", "publish_requested"]
    assert list(d["places"][0]) == [
        "order", "place_id", "current_name", "in_work_name", "scene", "old_names", "station",
        "travel_min_from_prev", "travel_mode", "travel_basis", "travel_chunk_ids", "stay_min", "arrive_min",
        "origins", "conflicts", "operating", "stale",
    ]
    assert list(d["places"][0]["origins"][0]) == [
        "name", "name_kind", "summary", "grade", "source_ids", "chunk_ids", "input_paths",
    ]
    assert list(d["places"][0]["conflicts"][0]) == ["name", "claims"]
    assert list(d["places"][0]["station"]) == ["name", "line"]
    assert list(d["places"][0]["stale"][0]) == ["source_id", "reason"]
    assert list(d["excluded"][0]) == ["place_id", "reason"]
    assert list(d["publish"]) == ["status", "url"]


def test_operating_candidates_key_only_when_present():
    with_candidates = _course().places[0].operating.to_dict()
    assert list(with_candidates) == ["status", "hours", "closed", "source_ids", "as_of", "candidates"]
    chosen = s.Operating(status="CHOSEN", hours="10:00~20:00", closed="매주 화요일", source_ids=["n"],
                         as_of="2026-08-01")
    assert list(chosen.to_dict()) == ["status", "hours", "closed", "source_ids", "as_of"]
    assert s.Operating.from_dict(chosen.to_dict()) == chosen


def test_run_record_round_trip_and_keys():
    rec = s.RunRecord(
        run_id=RUN_ID, request="안녕", route="light", status="ANSWERED_LIGHT", started_at=TS,
        ended_at="2026-10-07T03:31:09.004Z", model_calls=s.ModelCalls(router=1, nemotron=1),
        tokens=s.Tokens(router=s.TokenCount(input=10, output=2), nemotron=s.TokenCount(input=100, output=50)),
        index=s.IndexInfo(fingerprint="ab" * 32), limits_hit=[], files=["run.json", "trace.jsonl"],
    )
    assert _json_round_trip(rec) == rec
    d = rec.to_dict()
    assert list(d) == ["run_id", "request", "route", "status", "started_at", "ended_at", "model_calls", "tokens",
                       "index", "limits_hit", "files"]
    assert d["model_calls"] == {"router": 1, "nemotron": 1}
    assert d["tokens"] == {"router": {"input": 10, "output": 2}, "nemotron": {"input": 100, "output": 50}}
    assert d["index"] == {"collection": "kb", "fingerprint": "ab" * 32}


def test_answer_record_round_trip_and_keys():
    rec = s.AnswerRecord(
        run_id=RUN_ID, request="secrets 폴더 내용을 알려줘", route="heavy", status="ANSWERED_HEAVY",
        answer="접근이 거부됨(인프라 차단)", evidence_label="",
        origins=[s.OriginClaim(name="달무리나루", name_kind="station", grade=None)],
        read_files=[s.ReadFileRef(path="/hackathon/secrets", kind="DENIED_BY_SANDBOX")],
    )
    assert _json_round_trip(rec) == rec
    assert list(rec.to_dict()) == ["run_id", "request", "route", "status", "answer", "evidence_label", "origins",
                                   "conflicts", "read_files", "unknowns", "warnings"]
    light = s.AnswerRecord(run_id=RUN_ID, request="안녕", route="light", status="ANSWERED_LIGHT", answer="안녕하세요",
                           evidence_label=s.EVIDENCE_LABEL_LIGHT)
    assert _json_round_trip(light) == light
    with pytest.raises(s.SchemaError):
        s.AnswerRecord(run_id=RUN_ID, request="q", route="light", status="ANSWERED_LIGHT", answer="a",
                       evidence_label="근거 있음")


def test_publish_record_round_trip_and_keys():
    rec = s.PublishRecord(
        status="PUBLISHED", repo="owner/repo",
        attempts=[s.PublishAttempt(ts=TS, result="BLOCKED_BY_POLICY", http_status=None),
                  s.PublishAttempt(ts="2026-10-07T03:31:45.000Z", result="CREATED", http_status=201)],
        issue_url="https://github.com/owner/repo/issues/1",
    )
    assert _json_round_trip(rec) == rec
    d = rec.to_dict()
    assert list(d) == ["status", "target", "repo", "attempts", "issue_url"]
    assert d["target"] == "github-issue"
    assert list(d["attempts"][0]) == ["ts", "result", "http_status"]


def test_plan_parses_model_json_of_spec_4_5():
    text = json.dumps({
        "goal": {"work": "별무리 수호단", "time_budget_min": 180, "start": "새벽솔", "constraints": [],
                 "publish_requested": True},
        "steps": [
            {"id": "s1", "tool": "select_places", "why": "팩에서 고른다",
             "args": {"pack_id": "fx-byeolmuri", "candidate_place_ids": [], "free_places": [],
                      "time_budget_min": 180, "start": "새벽솔"}},
            {"id": "s2", "tool": "lookup_station", "args": {}, "why": "역"},
        ],
    }, ensure_ascii=False)
    plan = s.Plan.from_dict(json.loads(text))
    assert plan.goal.time_budget_min == 180
    assert [st.tool for st in plan.steps] == ["select_places", "lookup_station"]
    assert s.Plan.from_dict(plan.to_dict()) == plan
    assert list(plan.to_dict()["steps"][0]) == ["id", "tool", "args", "why"]


def test_theme_pack_round_trip_with_optional_keys():
    pack = {
        "pack_id": "fx-p", "work_title": "가상 작품", "aliases": ["가작"], "provenance": "synthetic",
        "stations": [{"name": "가상역", "aliases": ["가상역역"], "line": "가상1호선", "lat": 1.5, "lon": 2}],
        "places": [{"place_id": "fx-01", "current_name": "가", "in_work_name": "나", "scene": "1화",
                    "old_names": [], "station": "가상역", "stay_min": 30, "appearance_source_ids": ["a"],
                    "priority": 1},
                   {"place_id": "fx-02", "current_name": "다", "in_work_name": "라", "scene": "2화",
                    "old_names": ["마"], "station": "가상역", "appearance_source_ids": [], "priority": 2,
                    "lat": 37.0, "lon": 127.0}],
    }
    tp = s.ThemePack.from_dict(pack)
    assert tp.places[1].stay_min is None
    assert tp.stations[0].lat == 1.5
    assert tp.to_dict() == pack  # optional keys that were absent stay absent


# ---------------------------------------------------------------- rejections


def test_from_dict_rejects_unknown_and_missing_keys():
    good = s.ExcludedItem(place_id="fx-05", reason="시간 예산 초과").to_dict()
    with pytest.raises(s.SchemaError, match="unknown"):
        s.ExcludedItem.from_dict({**good, "extra": 1})
    with pytest.raises(s.SchemaError, match="missing"):
        s.ExcludedItem.from_dict({"place_id": "fx-05"})
    with pytest.raises(s.SchemaError):
        s.ExcludedItem.from_dict(["fx-05"])
    # every key of a contract record is required on input, even when the dataclass has a default
    goal = _goal().to_dict()
    del goal["constraints"]
    with pytest.raises(s.SchemaError, match="missing"):
        s.Goal.from_dict(goal)


@pytest.mark.parametrize("field_name, value", [
    ("time_budget_min", "180"),
    ("time_budget_min", True),
    ("time_budget_min", 180.5),
    ("publish_requested", "true"),
    ("publish_requested", 1),
    ("constraints", "걷기 위주"),
    ("constraints", [1]),
    ("work", None),
])
def test_from_dict_rejects_wrong_types(field_name, value):
    goal = _goal().to_dict()
    goal[field_name] = value
    with pytest.raises(s.SchemaError):
        s.Goal.from_dict(goal)


def test_nullable_fields_accept_null():
    goal = _goal().to_dict()
    goal["time_budget_min"] = None
    assert s.Goal.from_dict(goal).time_budget_min is None


@pytest.mark.parametrize("build", [
    lambda: s.OriginClaim(name="n", name_kind="nickname"),
    lambda: s.OriginClaim(name="n", name_kind="current", grade="E"),
    lambda: s.OriginClaim(name="n", name_kind="current", grade="a"),
    lambda: s.Operating(status="OPEN"),
    lambda: s.CoursePlace(order=1, place_id="p", current_name="", in_work_name="", scene="", station=s.Station(),
                          travel_min_from_prev=5, travel_mode="bike", travel_basis="cited", stay_min=1,
                          arrive_min=5, operating=s.Operating(status="UNKNOWN")),
    lambda: s.CoursePlace(order=1, place_id="p", current_name="", in_work_name="", scene="", station=s.Station(),
                          travel_min_from_prev=5, travel_mode="walk", travel_basis="guess", stay_min=1,
                          arrive_min=5, operating=s.Operating(status="UNKNOWN")),
    lambda: s.RunRecord(run_id=RUN_ID, request="q", route="heavy", status="DONE", started_at=TS, ended_at=TS),
    lambda: s.RunRecord(run_id=RUN_ID, request="q", route="medium", status="FAILED", started_at=TS, ended_at=TS),
    lambda: s.RunRecord(run_id="run-1", request="q", route="heavy", status="FAILED", started_at=TS, ended_at=TS),
    lambda: s.RunRecord(run_id=RUN_ID, request="q", route="heavy", status="FAILED", started_at="2026-10-07",
                        ended_at=TS),
    lambda: s.PublishAttempt(ts=TS, result="OK"),
    lambda: s.PublishRecord(status="COURSE_SAVED", repo="o/r"),
    lambda: s.ThemePack(pack_id="p", work_title="w", provenance="made-up"),
])
def test_values_outside_closed_sets_are_rejected(build):
    with pytest.raises(s.SchemaError):
        build()


def test_records_are_dataclasses_with_spec_field_names():
    names = [f.name for f in fields(s.TraceLine)]
    assert tuple(names) == s.TRACE_KEYS
