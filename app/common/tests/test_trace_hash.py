"""trace.jsonl line format and hash chain (spec 4.4): prev_hash = sha256 of the previous line's UTF-8 bytes."""

import hashlib
import json

import pytest

from common import schema as s

RUN_ID = "20261007T033105Z-0a1f"


def _line(seq, prev_hash, **kw):
    base = dict(seq=seq, ts=f"2026-10-07T03:31:0{seq}.123Z", run_id=RUN_ID, event="step", tool="lookup_station",
                args={}, result=s.TraceResult(kind="OK", summary=f"{seq}단계 완료"), why="계획 순서",
                model=None, prev_hash=prev_hash)
    base.update(kw)
    return s.TraceLine(**base)


def _chain(n):
    lines, prev = [], None
    for seq in range(1, n + 1):
        text = _line(seq, s.prev_hash_for(prev)).to_json_line()
        lines.append(text)
        prev = text
    return lines


def test_first_line_prev_hash_is_sixty_four_zeros():
    assert s.GENESIS_HASH == "0" * 64
    assert s.prev_hash_for(None) == "0" * 64


def test_prev_hash_is_sha256_of_previous_line_utf8_without_line_break():
    line = _line(1, s.GENESIS_HASH, why="한글 이유 — 유니코드").to_json_line()
    expected = hashlib.sha256(line.encode("utf-8")).hexdigest()
    assert s.trace_hash(line) == expected
    assert s.prev_hash_for(line) == expected
    assert s.prev_hash_for(line + "\n") == expected  # the line break is not hashed
    assert len(expected) == 64


def test_trace_line_is_one_json_line_with_spec_keys_in_order():
    model = s.TraceModel(name="nvidia/nemotron", purpose="plan", latency_ms=812, usage={"input": 10, "output": 3})
    text = _line(1, s.GENESIS_HASH, event="plan", tool="", model=model, why="모델이 준 이유").to_json_line()
    assert "\n" not in text
    obj = json.loads(text)
    assert tuple(obj) == s.TRACE_KEYS
    assert obj["result"] == {"kind": "OK", "summary": "1단계 완료"}
    assert obj["model"] == {"name": "nvidia/nemotron", "purpose": "plan", "latency_ms": 812,
                            "usage": {"input": 10, "output": 3}}
    assert "모델이 준 이유" in text  # Korean stays readable (no ASCII escaping)
    assert s.TraceLine.from_dict(obj) == _line(1, s.GENESIS_HASH, event="plan", tool="", model=model,
                                               why="모델이 준 이유")


def test_valid_chain_verifies():
    lines = _chain(4)
    assert s.verify_trace(lines) == []
    assert s.verify_trace([ln + "\n" for ln in lines]) == []
    assert s.verify_trace(s.split_trace_lines("\n".join(lines) + "\n")) == []


def test_editing_a_line_breaks_the_chain_at_the_next_line():
    lines = _chain(3)
    lines[1] = lines[1].replace("2단계 완료", "2단계 실패")
    problems = s.verify_trace(lines)
    assert len(problems) == 1
    assert problems[0].startswith("line 3:")


def test_dropping_a_line_is_detected():
    lines = _chain(3)
    problems = s.verify_trace([lines[0], lines[2]])
    assert any(p.startswith("line 2:") for p in problems)


def test_bad_lines_are_reported_not_raised():
    good = _chain(1)
    assert s.verify_trace(good + ["not json"]) != []
    assert s.verify_trace(["[1, 2]"]) != []
    obj = json.loads(good[0])
    del obj["why"]
    assert any("keys" in p for p in s.verify_trace([json.dumps(obj, ensure_ascii=False)]))


def test_line_separator_characters_cannot_split_a_line():
    why = "첫 줄 둘째 줄 셋째\r넷째\x85다섯째\x0b\x1c끝"
    text = _line(1, s.GENESIS_HASH, why=why).to_json_line()
    for ch in (" ", " ", "\r", "\x85", "\x0b", "\x1c"):
        assert ch not in text
    assert len(text.splitlines()) == 1
    assert json.loads(text)["why"] == why
    assert s.split_trace_lines(text + "\n" + text + "\n") == [text, text]


@pytest.mark.parametrize("kw", [
    {"event": "tool_call"},
    {"tool": "web_search"},
    {"seq": 0},
    {"ts": "2026-10-07T03:31:05Z"},
    {"run_id": "run-1"},
    {"prev_hash": "0" * 63},
    {"prev_hash": "G" * 64},
])
def test_trace_line_rejects_values_outside_the_contract(kw):
    base = dict(seq=1, ts="2026-10-07T03:31:05.123Z", run_id=RUN_ID, event="step", tool="read_file",
                prev_hash=s.GENESIS_HASH)
    base.update(kw)
    with pytest.raises(s.SchemaError):
        s.TraceLine(**base)


def test_every_trace_event_and_empty_tool_are_accepted():
    for event in s.TRACE_EVENTS:
        s.TraceLine(seq=1, ts="2026-10-07T03:31:05.123Z", run_id=RUN_ID, event=event, prev_hash=s.GENESIS_HASH)
