"""Tests for tools.files (list_input, read_file, spec 2.2 / 2.5 / 5)."""

from __future__ import annotations

import pytest

from common.limits import READ_FILE_MAX_BYTES
from common.schema import (
    KIND_DENIED_BY_SANDBOX,
    KIND_NOT_FOUND,
    KIND_NOT_TEXT,
    KIND_OK,
    KIND_OUT_OF_SCOPE,
    KIND_TOO_LARGE,
    KIND_TOOL_ERROR,
    TEXT_DENIED_BY_SANDBOX,
)
from common.tooling import ToolRegistry
from tools import files
from tools.tests.fakes import FakeFS, make_ctx, make_deps

DOC = """---
source_id: in-memo
title: 현장 메모
publisher: 가상 동네 모임
source_type: informal
published: 2026-09-30
about: [달무리나루, 별가루 골목시장]
hours: 09:00~18:00
---
# 메모

2026년 9월 3일에 들렀고, 2026.10.1 다시 갔다. 공지는 2026-08-01부터 바뀌었다.
다시 2026-08-01 이야기. 틀린 날짜 2026-13-40은 버린다.
"""


def _read(tree: dict, path: str):
    fs = FakeFS(tree)
    ctx = make_ctx()
    result = files.run_read_file({"path": path}, ctx, make_deps(fs=fs))
    return result, ctx, fs


# ---------------------------------------------------------------- read_file


def test_secrets_denied_by_sandbox():
    result, ctx, fs = _read({"/hackathon/secrets": PermissionError(13, "Permission denied")}, "/hackathon/secrets")
    assert result.ok is False
    assert result.kind == KIND_DENIED_BY_SANDBOX
    assert not result.needs_replan
    assert result.data["note"] == TEXT_DENIED_BY_SANDBOX == "접근이 거부됨(인프라 차단)"
    assert result.data["path"] == "/hackathon/secrets"
    assert fs.calls == [("/hackathon/secrets", READ_FILE_MAX_BYTES + 1)]
    assert ctx.read_files["/hackathon/secrets"] == {
        "kind": "DENIED_BY_SANDBOX", "text": "", "front_matter": {}, "dates": [], "entries": [],
    }


@pytest.mark.parametrize("path", ["/etc/passwd", "/hackathon/../etc/passwd", "/hackathonX/a", "hackathon/input/a",
                                  "input/a.md", "//etc/passwd", "/"])
def test_out_of_scope_paths_are_not_opened(path):
    result, ctx, fs = _read({}, path)
    assert result.ok is False
    assert result.kind == KIND_OUT_OF_SCOPE
    assert fs.calls == []
    assert len(ctx.read_files) == 1
    assert next(iter(ctx.read_files.values()))["kind"] == "OUT_OF_SCOPE"


def test_normalized_path_inside_is_read():
    result, ctx, fs = _read({"/hackathon/input/a.md": b"hello"}, "/hackathon/input/./x/../a.md")
    assert result.kind == KIND_OK
    assert fs.calls[0][0] == "/hackathon/input/a.md"
    assert "/hackathon/input/a.md" in ctx.read_files


def test_not_found():
    result, ctx, _ = _read({}, "/hackathon/input/none.md")
    assert result.ok is False
    assert result.kind == KIND_NOT_FOUND
    assert ctx.read_files["/hackathon/input/none.md"]["kind"] == "NOT_FOUND"


def test_other_os_error_is_tool_error():
    result, _, _ = _read({"/hackathon/input/a": OSError(5, "I/O error")}, "/hackathon/input/a")
    assert result.kind == KIND_TOOL_ERROR


def test_too_large_keeps_first_64kb_and_drops_cut_character():
    # 64KB - 1 ASCII bytes, then Korean (3 bytes each): the cut lands inside a character.
    data = b"a" * (READ_FILE_MAX_BYTES - 1) + "가나다".encode("utf-8")
    result, ctx, fs = _read({"/hackathon/input/big.txt": data}, "/hackathon/input/big.txt")
    assert result.ok is True
    assert result.kind == KIND_TOO_LARGE
    assert result.data["truncated"] is True
    assert result.data["bytes"] == READ_FILE_MAX_BYTES
    text = ctx.read_files["/hackathon/input/big.txt"]["text"]
    assert len(text) == READ_FILE_MAX_BYTES - 1
    assert set(text) == {"a"}
    assert ctx.warnings == ["/hackathon/input/big.txt: TOO_LARGE(앞 64KB만 사용)"]
    assert "text" not in result.data


def test_too_large_cut_on_character_boundary_keeps_it():
    data = b"a" * (READ_FILE_MAX_BYTES - 3) + "가나".encode("utf-8")
    result, ctx, _ = _read({"/hackathon/input/big.txt": data}, "/hackathon/input/big.txt")
    assert result.kind == KIND_TOO_LARGE
    assert ctx.read_files["/hackathon/input/big.txt"]["text"].endswith("a가")


def test_exactly_64kb_is_not_too_large():
    data = b"a" * READ_FILE_MAX_BYTES
    result, ctx, _ = _read({"/hackathon/input/f.txt": data}, "/hackathon/input/f.txt")
    assert result.kind == KIND_OK
    assert result.data["truncated"] is False
    assert ctx.warnings == []


def test_nul_byte_is_not_text():
    result, ctx, _ = _read({"/hackathon/input/b.bin": b"abc\x00def"}, "/hackathon/input/b.bin")
    assert result.ok is False
    assert result.kind == KIND_NOT_TEXT
    assert ctx.read_files["/hackathon/input/b.bin"]["kind"] == "NOT_TEXT"
    assert ctx.read_files["/hackathon/input/b.bin"]["text"] == ""


def test_invalid_utf8_is_not_text():
    result, _, _ = _read({"/hackathon/input/b.txt": b"ab\xff\xfecd"}, "/hackathon/input/b.txt")
    assert result.kind == KIND_NOT_TEXT


def test_folder_lists_entry_names():
    tree = {"/hackathon": [
        {"name": "secrets", "is_dir": True, "size": 0},
        {"name": "input", "is_dir": True, "size": 0},
        {"name": "output", "is_dir": True, "size": 0},
    ]}
    result, ctx, _ = _read(tree, "/hackathon")
    assert result.ok is True
    assert result.kind == KIND_OK
    assert result.data["kind"] == "dir"
    assert result.data["entries"] == ["input", "output", "secrets"]
    assert ctx.read_files["/hackathon"] == {
        "kind": "dir", "text": "", "front_matter": {}, "dates": [], "entries": ["input", "output", "secrets"],
    }


def test_front_matter_and_dates():
    result, ctx, _ = _read({"/hackathon/input/memo.md": DOC.encode("utf-8")}, "/hackathon/input/memo.md")
    assert result.kind == KIND_OK
    fm = result.data["front_matter"]
    assert fm["publisher"] == "가상 동네 모임"
    assert fm["published"] == "2026-09-30"
    assert fm["hours"] == "09:00~18:00"
    assert fm["about"] == ["달무리나루", "별가루 골목시장"]
    # body dates only (the front matter's published date is not a body date), normalized, unique, in order
    assert result.data["dates"] == ["2026-09-03", "2026-10-01", "2026-08-01"]
    entry = ctx.read_files["/hackathon/input/memo.md"]
    assert entry["kind"] == "file"
    assert entry["text"] == DOC
    assert entry["front_matter"] == fm
    assert set(result.data) == {"path", "kind", "bytes", "truncated", "front_matter", "dates", "entries"}


def test_no_front_matter():
    text = "제목\n\n2025년 11월 2일 기록\n"
    result, _, _ = _read({"/hackathon/input/a.txt": text.encode("utf-8")}, "/hackathon/input/a.txt")
    assert result.data["front_matter"] == {}
    assert result.data["dates"] == ["2025-11-02"]


def test_unclosed_front_matter_is_not_front_matter():
    text = "---\ntitle: x\n본문 2024-01-02\n"
    result, _, _ = _read({"/hackathon/input/a.txt": text.encode("utf-8")}, "/hackathon/input/a.txt")
    assert result.data["front_matter"] == {}
    assert result.data["dates"] == ["2024-01-02"]


# ---------------------------------------------------------------- list_input


def test_list_input_recursive_sorted_relative():
    tree = {
        "/hackathon/input": [
            {"name": "z.md", "is_dir": False, "size": 30},
            {"name": "sub", "is_dir": True, "size": 0},
            {"name": "a.md", "is_dir": False, "size": 10},
        ],
        "/hackathon/input/sub": [
            {"name": "b.txt", "is_dir": False, "size": 20},
            {"name": "deep", "is_dir": True, "size": 0},
        ],
        "/hackathon/input/sub/deep": [{"name": "c.md", "is_dir": False, "size": 5}],
    }
    fs = FakeFS(tree)
    ctx = make_ctx()
    result = files.run_list_input({}, ctx, make_deps(fs=fs))
    expected = [
        {"path": "a.md", "size": 10},
        {"path": "sub/b.txt", "size": 20},
        {"path": "sub/deep/c.md", "size": 5},
        {"path": "z.md", "size": 30},
    ]
    assert result.ok is True
    assert result.kind == KIND_OK
    assert result.data == {"count": 4, "files": expected}
    assert ctx.input_files == expected
    assert all(call[0].startswith("/hackathon/input") for call in fs.calls)


def test_list_input_skips_unreadable_subfolder_with_warning():
    tree = {
        "/hackathon/input": [
            {"name": "a.md", "is_dir": False, "size": 1},
            {"name": "locked", "is_dir": True, "size": 0},
        ],
        "/hackathon/input/locked": PermissionError(13, "Permission denied"),
    }
    ctx = make_ctx()
    result = files.run_list_input({}, ctx, make_deps(fs=FakeFS(tree)))
    assert result.ok is True
    assert ctx.input_files == [{"path": "a.md", "size": 1}]
    assert len(ctx.warnings) == 1 and "locked" in ctx.warnings[0]


def test_list_input_denied():
    ctx = make_ctx(input_files=[{"path": "old", "size": 1}])
    fs = FakeFS({"/hackathon/input": PermissionError(13, "Permission denied")})
    result = files.run_list_input({}, ctx, make_deps(fs=fs))
    assert result.ok is False
    assert result.kind == KIND_DENIED_BY_SANDBOX
    assert ctx.input_files == []


def test_list_input_missing():
    ctx = make_ctx()
    result = files.run_list_input({}, ctx, make_deps(fs=FakeFS({})))
    assert result.ok is False
    assert result.kind == KIND_NOT_FOUND
    assert ctx.input_files == []
    assert result.data == {"count": 0, "files": []}


def test_specs_register_with_contract_args():
    registry = ToolRegistry()
    for spec in files.SPECS:
        registry.register(spec)
    assert registry.names() == ["list_input", "read_file"]


def test_impossible_dates_are_skipped():
    assert files.extract_dates("2026-02-31, 2024.2.29, 2025년 2월 29일, 2026년 10월 7일") == ["2024-02-29", "2026-10-07"]


def test_nul_in_path_is_tool_error_without_read():
    result, ctx, fs = _read({}, "/hackathon/input/a\x00")
    assert result.ok is False
    assert result.kind == KIND_TOOL_ERROR
    assert result.error == "경로에 NUL 문자가 있음"
    assert fs.calls == []
    assert [entry["kind"] for entry in ctx.read_files.values()] == ["TOOL_ERROR"]


def test_value_error_from_read_path_is_tool_error():
    result, ctx, _ = _read({"/hackathon/input/a": ValueError("bad path")}, "/hackathon/input/a")
    assert result.ok is False
    assert result.kind == KIND_TOOL_ERROR
    assert ctx.read_files["/hackathon/input/a"]["kind"] == "TOOL_ERROR"


def test_utf8_bom_file_keeps_front_matter():
    data = b"\xef\xbb\xbf" + DOC.encode("utf-8")
    result, ctx, _ = _read({"/hackathon/input/bom.md": data}, "/hackathon/input/bom.md")
    assert result.kind == KIND_OK
    assert result.data["front_matter"]["publisher"] == "가상 동네 모임"
    assert result.data["front_matter"]["published"] == "2026-09-30"
    assert "2026-09-30" not in result.data["dates"]
    assert result.data["dates"] == ["2026-09-03", "2026-10-01", "2026-08-01"]
    assert not ctx.read_files["/hackathon/input/bom.md"]["text"].startswith("﻿")


def test_too_large_warning_with_long_path_is_one_line():
    path = "/hackathon/input/" + "긴\n이름 " * 40 + ".txt"
    result, ctx, _ = _read({path: b"a" * (READ_FILE_MAX_BYTES + 10)}, path)
    assert result.kind == KIND_TOO_LARGE
    assert len(ctx.warnings) == 1
    assert "\n" not in ctx.warnings[0] and len(ctx.warnings[0]) <= 200
    assert ctx.warnings[0].endswith("TOO_LARGE(앞 64KB만 사용)")


def test_list_input_warning_with_long_folder_name_is_one_line():
    name = "긴\n폴더 " * 40
    tree = {
        "/hackathon/input": [{"name": name, "is_dir": True, "size": 0}],
        f"/hackathon/input/{name}": PermissionError(13, "Permission denied"),
    }
    ctx = make_ctx()
    assert files.run_list_input({}, ctx, make_deps(fs=FakeFS(tree))).ok is True
    assert len(ctx.warnings) == 1
    assert "\n" not in ctx.warnings[0] and len(ctx.warnings[0]) <= 200


class _OutOfScopePath(ValueError):
    """Stand-in for the loop's realpath check error (matched by its `kind` attribute only)."""

    kind = "OUT_OF_SCOPE"


def test_read_path_out_of_scope_error_is_out_of_scope():
    result, ctx, fs = _read({"/hackathon/input/link": _OutOfScopePath("resolved path is outside")},
                            "/hackathon/input/link")
    assert result.ok is False
    assert result.kind == KIND_OUT_OF_SCOPE
    assert not result.needs_replan
    assert result.data["kind"] == "OUT_OF_SCOPE"
    assert ctx.read_files["/hackathon/input/link"] == {
        "kind": "OUT_OF_SCOPE", "text": "", "front_matter": {}, "dates": [], "entries": [],
    }


def test_plain_value_error_is_still_tool_error():
    result, ctx, _ = _read({"/hackathon/input/a": ValueError("x")}, "/hackathon/input/a")
    assert result.kind == KIND_TOOL_ERROR
    assert ctx.read_files["/hackathon/input/a"]["kind"] == "TOOL_ERROR"


def test_list_input_skips_out_of_scope_link_subfolder():
    tree = {
        "/hackathon/input": [
            {"name": "a.md", "is_dir": False, "size": 1},
            {"name": "escape", "is_dir": True, "size": 0},
        ],
        "/hackathon/input/escape": _OutOfScopePath("resolved path is outside"),
    }
    ctx = make_ctx()
    result = files.run_list_input({}, ctx, make_deps(fs=FakeFS(tree)))
    assert result.ok is True
    assert ctx.input_files == [{"path": "a.md", "size": 1}]
    assert len(ctx.warnings) == 1
    assert "escape" in ctx.warnings[0] and "범위 밖 링크" in ctx.warnings[0]


def test_list_input_top_level_out_of_scope():
    ctx = make_ctx()
    fs = FakeFS({"/hackathon/input": _OutOfScopePath("resolved path is outside")})
    result = files.run_list_input({}, ctx, make_deps(fs=fs))
    assert result.ok is False
    assert result.kind == KIND_OUT_OF_SCOPE
    assert ctx.input_files == []
    assert result.data == {"count": 0, "files": []}
