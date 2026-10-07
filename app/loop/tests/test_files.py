"""Run folder files (spec 4.4)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from common.schema import (
    EVIDENCE_LABEL_LIGHT,
    TEXT_NO_EVIDENCE,
    AnswerRecord,
    Conflict,
    OriginClaim,
    PublishAttempt,
    PublishRecord,
    ReadFileRef,
    RunRecord,
    is_run_id,
)
from loop.files import (
    list_run_files,
    new_run_dir,
    read_json,
    write_answer,
    write_json,
    write_publish,
    write_run,
)

NOW = datetime(2026, 10, 7, 3, 31, 5, tzinfo=timezone.utc)
TS = "2026-10-07T03:31:05.000Z"


def test_new_run_dir_creates_folder(tmp_path):
    root = tmp_path / "output"
    run_id, run_dir = new_run_dir(root, NOW, rand_hex="0a1f")
    assert run_id == "20261007T033105Z-0a1f"
    assert is_run_id(run_id)
    assert run_dir == root / run_id and run_dir.is_dir()


def test_new_run_dir_random_suffix(tmp_path):
    run_id, run_dir = new_run_dir(tmp_path, NOW)
    assert is_run_id(run_id) and run_dir.is_dir()


def test_new_run_dir_draws_again_when_taken(tmp_path):
    (tmp_path / "20261007T033105Z-aaaa").mkdir()
    (tmp_path / "20261007T033105Z-aaaa" / "keep.txt").write_text("x", encoding="utf-8")
    draws = iter(["aaaa", "bbbb"])
    run_id, run_dir = new_run_dir(tmp_path, NOW, rand_hex=lambda: next(draws))
    assert run_id == "20261007T033105Z-bbbb"
    assert (tmp_path / "20261007T033105Z-aaaa" / "keep.txt").read_text(encoding="utf-8") == "x"


def test_new_run_dir_fixed_suffix_taken_raises(tmp_path):
    (tmp_path / "20261007T033105Z-aaaa").mkdir()
    with pytest.raises(FileExistsError):
        new_run_dir(tmp_path, NOW, rand_hex="aaaa")


def test_write_json_and_read_json(tmp_path):
    path = tmp_path / "x.json"
    write_json(path, {"이름": "혜화문", "n": [1, 2]})
    text = path.read_text(encoding="utf-8")
    assert "혜화문" in text and '\n  "n"' in text
    assert read_json(path) == {"이름": "혜화문", "n": [1, 2]}
    write_json(path, {"a": 1})
    assert read_json(path) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def _run_record(run_id):
    return RunRecord(run_id=run_id, request="안녕", route="light", status="ANSWERED_LIGHT",
                     started_at=TS, ended_at=TS, files=["run.json"])


def test_write_run_and_publish(tmp_path):
    run_id = "20261007T033105Z-0a1f"
    write_run(tmp_path, _run_record(run_id))
    data = read_json(tmp_path / "run.json")
    assert RunRecord.from_dict(data).run_id == run_id
    rec = PublishRecord(status="PUBLISH_PENDING_APPROVAL", repo="o/r",
                        attempts=[PublishAttempt(ts=TS, result="BLOCKED_BY_POLICY", http_status=None)])
    write_publish(tmp_path, rec)
    assert PublishRecord.from_dict(read_json(tmp_path / "publish.json")) == rec


def test_write_answer_json_and_md(tmp_path):
    run_id = "20261007T033105Z-0a1f"
    graded = OriginClaim(name="혜화문", name_kind="current", summary="은혜를 베푼다는 뜻", grade="A",
                         source_ids=["src-1"], chunk_ids=["c1"])
    ungraded = OriginClaim(name="혜화문", name_kind="old", summary="옛 이름 홍화문", grade=None)
    rec = AnswerRecord(
        run_id=run_id, request="혜화문 이름 유래", route="heavy", status="ANSWERED_HEAVY",
        answer="혜화문은 ...", origins=[graded, ungraded],
        conflicts=[Conflict(name="혜화문", claims=[graded, ungraded])],
        read_files=[ReadFileRef(path="/hackathon/input/a.md", kind="text")],
        unknowns=["운영 시간 확인 안 됨"], warnings=["근거 c9 없음"],
    )
    write_answer(tmp_path, rec)
    assert AnswerRecord.from_dict(read_json(tmp_path / "answer.json")) == rec
    md = (tmp_path / "answer.md").read_text(encoding="utf-8")
    for piece in ("혜화문은 ...", "은혜를 베푼다는 뜻", "src-1", TEXT_NO_EVIDENCE, "/hackathon/input/a.md",
                  "운영 시간 확인 안 됨", "근거 c9 없음", "충돌"):
        assert piece in md, piece


def test_write_answer_light_label(tmp_path):
    rec = AnswerRecord(run_id="20261007T033105Z-0a1f", request="안녕", route="light", status="ANSWERED_LIGHT",
                       answer="안녕하세요", evidence_label=EVIDENCE_LABEL_LIGHT)
    write_answer(tmp_path, rec)
    md = (tmp_path / "answer.md").read_text(encoding="utf-8")
    assert md.splitlines()[0] == EVIDENCE_LABEL_LIGHT
    assert "안녕하세요" in md


def test_list_run_files(tmp_path):
    write_json(tmp_path / "run.json", {})
    (tmp_path / "trace.jsonl").write_text("", encoding="utf-8")
    (tmp_path / ".tmp-x").write_text("", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    assert list_run_files(tmp_path) == ["run.json", "trace.jsonl"]
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8")) == {}


def test_written_files_have_plain_open_mode(tmp_path):
    (tmp_path / "plain.txt").write_text("", encoding="utf-8")
    plain_mode = (tmp_path / "plain.txt").stat().st_mode & 0o777
    write_run(tmp_path, _run_record("20261007T033105Z-0a1f"))
    write_answer(tmp_path, AnswerRecord(run_id="20261007T033105Z-0a1f", request="q", route="heavy",
                                        status="ANSWERED_HEAVY", answer="a"))
    for name in ("run.json", "answer.json", "answer.md"):
        assert (tmp_path / name).stat().st_mode & 0o777 == plain_mode, name
