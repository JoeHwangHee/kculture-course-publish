"""TraceWriter: hash-chained trace.jsonl lines (spec 2.6, 4.4)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from common.schema import GENESIS_HASH, SchemaError, split_trace_lines, trace_hash, verify_trace
from loop.trace import TraceWriter

RUN_ID = "20261007T033105Z-0a1f"


def fixed_now():
    return datetime(2026, 10, 7, 3, 31, 5, 123456, tzinfo=timezone.utc)


def read_lines(path):
    return split_trace_lines(path.read_text(encoding="utf-8"))


def test_first_lines_chain(tmp_path):
    path = tmp_path / "trace.jsonl"
    w = TraceWriter(path, RUN_ID, now=fixed_now)
    first = w.append("route", kind="OK", summary="heavy", why="needs data",
                     model={"name": "nemotron-test-model", "purpose": "route", "latency_ms": 10.0,
                            "usage": {"input": 5, "output": 1}})
    w.append("step", tool="list_input", args={}, kind="OK", summary="3 files")
    w.append("final", kind="ANSWERED_HEAVY", summary="done")
    lines = read_lines(path)
    assert len(lines) == 3
    assert verify_trace(lines) == []
    assert first["seq"] == 1 and first["prev_hash"] == GENESIS_HASH
    assert first["ts"] == "2026-10-07T03:31:05.123Z"
    assert first["result"] == {"kind": "OK", "summary": "heavy"}
    assert first["model"]["usage"] == {"input": 5, "output": 1}
    assert json.loads(lines[0]) == first
    second = json.loads(lines[1])
    assert second["prev_hash"] == trace_hash(lines[0])
    assert second["tool"] == "list_input" and second["model"] is None


def test_continue_existing_file(tmp_path):
    path = tmp_path / "trace.jsonl"
    w = TraceWriter(path, RUN_ID, now=fixed_now)
    w.append("route", kind="OK")
    w.append("final", kind="PUBLISH_PENDING_APPROVAL")
    w2 = TraceWriter(path, RUN_ID, now=fixed_now)
    line = w2.append("publish_attempt", tool="request_publish", kind="CREATED", summary="201")
    lines = read_lines(path)
    assert len(lines) == 3
    assert line["seq"] == 3
    assert verify_trace(lines) == []


def test_empty_existing_file_starts_from_genesis(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    line = TraceWriter(path, RUN_ID, now=fixed_now).append("route")
    assert line["seq"] == 1 and line["prev_hash"] == GENESIS_HASH


def test_summary_and_why_folded_and_cut(tmp_path):
    path = tmp_path / "trace.jsonl"
    w = TraceWriter(path, RUN_ID, now=fixed_now)
    line = w.append("plan", summary="a\nb\r\n  c d", why="x" * 600 + "\ny")
    assert line["result"]["summary"] == "a b c d"
    assert len(line["why"]) == 500
    lines = read_lines(path)
    assert len(lines) == 1
    assert verify_trace(lines) == []


def test_written_immediately(tmp_path):
    path = tmp_path / "trace.jsonl"
    w = TraceWriter(path, RUN_ID, now=fixed_now)
    w.append("route")
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert len(read_lines(path)) == 1


def test_bad_event_rejected(tmp_path):
    w = TraceWriter(tmp_path / "trace.jsonl", RUN_ID, now=fixed_now)
    with pytest.raises(SchemaError):
        w.append("not-an-event")


def test_continue_file_without_final_newline(tmp_path):
    path = tmp_path / "trace.jsonl"
    TraceWriter(path, RUN_ID, now=fixed_now).append("route", kind="OK")
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")
    line = TraceWriter(path, RUN_ID, now=fixed_now).append("final", kind="ANSWERED_HEAVY")
    lines = read_lines(path)
    assert len(lines) == 2 and line["seq"] == 2
    assert verify_trace(lines) == []


def test_continue_other_run_rejected(tmp_path):
    path = tmp_path / "trace.jsonl"
    TraceWriter(path, RUN_ID, now=fixed_now).append("route")
    before = path.read_text(encoding="utf-8")
    with pytest.raises(SchemaError):
        TraceWriter(path, "20261007T033106Z-beef", now=fixed_now)
    assert path.read_text(encoding="utf-8") == before
