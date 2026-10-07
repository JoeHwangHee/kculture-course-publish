"""Wiring helpers that run without the tools package or a real index."""

from __future__ import annotations

import json

from loop.wiring import _chunk_lookups, _load_theme_packs, _read_fingerprint


def test_theme_packs_sorted_by_file_name(tmp_path):
    packs = tmp_path / "theme_packs"
    packs.mkdir()
    (packs / "b.json").write_text(json.dumps({"pack_id": "b"}), encoding="utf-8")
    (packs / "a.json").write_text(json.dumps({"pack_id": "a", "work_title": "가상 작품"}, ensure_ascii=False),
                                  encoding="utf-8")
    (packs / "notes.txt").write_text("skip", encoding="utf-8")
    assert _load_theme_packs(tmp_path) == [{"pack_id": "a", "work_title": "가상 작품"}, {"pack_id": "b"}]


def test_theme_packs_missing_folder(tmp_path):
    assert _load_theme_packs(tmp_path) == []


def test_theme_packs_from_common_fixtures(common_fixtures):
    packs = _load_theme_packs(common_fixtures)
    assert packs and all("pack_id" in p for p in packs)


def test_fingerprint(tmp_path):
    assert _read_fingerprint(tmp_path) == ""
    (tmp_path / "manifest.json").write_text(json.dumps({"source_fingerprint": "abc123"}), encoding="utf-8")
    assert _read_fingerprint(tmp_path) == "abc123"
    (tmp_path / "manifest.json").write_text(json.dumps({"format_version": 3}), encoding="utf-8")
    assert _read_fingerprint(tmp_path) == ""


CHUNKS = [
    {"chunk_id": "c1", "kind": "origin", "text": "t1", "tokens": ["t"]},
    {"chunk_id": "c2", "kind": "operating", "place_ids": ["p1", "p2"], "text": "t2", "tokens": ["t"]},
    {"chunk_id": "c3", "kind": "operating", "place_ids": ["p2"], "text": "t3"},
    {"chunk_id": "c4", "kind": "origin", "place_ids": ["p1"], "text": "t4"},
]


class PlainRetriever:
    def __init__(self):
        self.chunks = [dict(c) for c in CHUNKS]


def test_chunk_lookup_fallback():
    get_chunk, chunks_where = _chunk_lookups(PlainRetriever())
    c1 = get_chunk("c1")
    assert c1 == {"chunk_id": "c1", "kind": "origin", "text": "t1"}
    assert get_chunk("missing") is None
    assert [c["chunk_id"] for c in chunks_where("operating", "p1")] == ["c2"]
    assert [c["chunk_id"] for c in chunks_where("operating", "p2")] == ["c2", "c3"]
    assert chunks_where("operating", "p9") == []
    assert all("tokens" not in c for c in chunks_where("operating", "p2"))
    c1["text"] = "changed"
    assert get_chunk("c1")["text"] == "t1"  # copies, not the index's own dicts


class MethodRetriever(PlainRetriever):
    def get_chunk(self, chunk_id):
        return {"chunk_id": chunk_id, "via": "method"}

    def chunks_where(self, kind, place_id):
        return [{"via": "method", "kind": kind, "place_id": place_id}]


def test_chunk_lookup_uses_retriever_methods():
    get_chunk, chunks_where = _chunk_lookups(MethodRetriever())
    assert get_chunk("x") == {"chunk_id": "x", "via": "method"}
    assert chunks_where("operating", "p1") == [{"via": "method", "kind": "operating", "place_id": "p1"}]
