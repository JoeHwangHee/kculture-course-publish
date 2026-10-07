"""Tests for tools._shared and the shared test fakes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from common.tooling import Deps, RunContext
from tools import _shared
from tools.tests.fakes import (
    FakeChat,
    FakeFS,
    FakeHttp,
    load_fixture_chunks,
    load_fixture_packs,
    make_ctx,
    make_deps,
)


def test_add_unique_skips_duplicates():
    items: list[str] = []
    _shared.add_unique(items, "a")
    _shared.add_unique(items, "b")
    _shared.add_unique(items, "a")
    assert items == ["a", "b"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n[{"a": 1}]\n```', [{"a": 1}]),
        ('```\n{"b": [1, 2]}\n```', {"b": [1, 2]}),
        ('Here is the plan:\n{"steps": [{"x": "}"}]}\nThanks.', {"steps": [{"x": "}"}]}),
        ("sure: [1, 2, 3] done", [1, 2, 3]),
    ],
)
def test_parse_model_json(text, expected):
    assert _shared.parse_model_json(text) == expected


@pytest.mark.parametrize("text", ["", "no json here", "{broken", "```json\n{oops\n```"])
def test_parse_model_json_fails(text):
    with pytest.raises(ValueError):
        _shared.parse_model_json(text)


def test_find_pack():
    a, b = {"pack_id": "a"}, {"pack_id": "b"}
    assert _shared.find_pack([a], "") is a
    assert _shared.find_pack([a, b], "") is None
    assert _shared.find_pack([], "") is None
    assert _shared.find_pack([a, b], "b") is b
    assert _shared.find_pack([a, b], "c") is None


def test_chunk_date():
    assert _shared.chunk_date({"published": "2026-09-01"}) == "2026-09-01"
    assert _shared.chunk_date({"published": "2026-09"}) == ""
    assert _shared.chunk_date({"published": "2026-13-45"}) == ""
    assert _shared.chunk_date({"published": "2026-02-30"}) == ""
    assert _shared.chunk_date({"published": ""}) == ""
    assert _shared.chunk_date({}) == ""


def test_grade_rank():
    assert _shared.GRADE_RANK == {"A": 4, "B": 3, "C": 2, "D": 1}
    assert [_shared.grade_rank(g) for g in ("A", "B", "C", "D", None, "Z")] == [4, 3, 2, 1, 0, 0]


def test_fixture_chunks():
    chunks = load_fixture_chunks()
    assert len(chunks) == 10
    operating = [c for c in chunks if c["kind"] == "operating"]
    assert len(operating) == 4
    assert all(c["place_ids"] and "hours" in c and "closed" in c for c in operating)
    c = next(c for c in chunks if c["source_id"] == "fx-src-op-solbit-2026")
    assert c["chunk_id"] == "fx-src-op-solbit-2026#c0"
    assert c["source"] == "sources/fx-src-op-solbit-2026.md"
    assert c["place_ids"] == ["fx-03"] and c["about"] == ["솔빛고개 전망쉼터"]
    assert c["url"] == "" and c["published"] == "2026-09-01"
    assert c["char_end"] == len(c["text"]) and not c["text"].startswith("---")
    assert all(isinstance(x["about"], list) for x in chunks)


def test_fixture_packs():
    packs = load_fixture_packs()
    assert [p["pack_id"] for p in packs] == ["fx-byeolmuri"]


def test_make_deps_defaults():
    deps = make_deps()
    assert isinstance(deps, Deps)
    assert len(deps.chunks_where("operating", "fx-02")) == 2
    assert deps.get_chunk("fx-src-op-solbit-2026#c0")["kind"] == "operating"
    assert deps.get_chunk("missing") is None
    assert deps.theme_packs()[0]["pack_id"] == "fx-byeolmuri"
    hits = deps.search("달무리나루", 3)
    assert 0 < len(hits) <= 3
    assert deps.search("zzz-none", 5) == []
    assert deps.now() == datetime(2026, 10, 7, 3, 31, 5, tzinfo=timezone.utc)
    assert deps.http_post_json("u", {}, {})["error"] == "NETWORK"
    with pytest.raises(AssertionError):
        deps.chat([], "plan")


def test_fake_chat():
    chat = FakeChat(["hi", RuntimeError("boom")])
    assert chat([{"role": "user", "content": "x"}], "plan")["text"] == "hi"
    with pytest.raises(RuntimeError):
        chat([], "plan")
    assert [p for _, p in chat.calls] == ["plan", "plan"]


def test_fake_http_returns_copies():
    http = FakeHttp({"status": 201, "body": "{}", "error": None})
    r = http("https://example.invalid", {"Accept": "x"}, {"a": 1})
    r["status"] = 0
    assert http("u", {}, {})["status"] == 201
    assert len(http.calls) == 2


def test_fake_fs():
    fs = FakeFS({
        "/hackathon/input/a.md": b"0123456789",
        "/hackathon/input": [{"name": "a.md", "is_dir": False, "size": 10}],
        "/hackathon/input/locked": PermissionError(13, "Permission denied"),
    })
    assert fs("/hackathon/input/a.md", 4) == b"0123"
    assert fs("/hackathon/input", 100)[0]["name"] == "a.md"
    with pytest.raises(PermissionError):
        fs("/hackathon/input/locked", 10)
    with pytest.raises(FileNotFoundError):
        fs("/hackathon/input/none", 10)
    assert len(fs.calls) == 4


def test_make_ctx():
    ctx = make_ctx(publish_repo="owner/repo")
    assert isinstance(ctx, RunContext)
    assert ctx.run_id == "20261007T033105Z-0a1f"
    assert ctx.request == "별수단 배경지 새벽솔역에서 3시간 코스"
    assert ctx.publish_repo == "owner/repo"


def test_tools_package_exposes_register_all():
    import tools

    assert callable(tools.register_all)


def test_shown_folds_whitespace_and_cuts_to_60():
    assert _shared.SHOWN_VALUE_CHARS == 60
    assert _shared.shown("  a\n b\t c  ") == "a b c"
    assert _shared.shown("가\n" + "나" * 200) == ("가 " + "나" * 200)[:60]
    assert _shared.shown(None) == "None"
