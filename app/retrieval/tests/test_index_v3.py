"""JSON index format 3 (spec 4.3): files, split pieces, theme pack copies, fingerprint, Deps methods."""

import hashlib
import json
import os
import shutil

import numpy as np
import pytest

from common.schema import CHUNK_OPERATING_KEYS, CHUNK_SOURCE_KEYS
from retrieval.embedder import HashEmbedder
from retrieval.errors import InputError
from retrieval.index import FORMAT_VERSION, MAX_FILE_BYTES, Retriever, build_index
from retrieval.source_meta import parse_front_matter, source_fingerprint

SCORE_KEYS = {"score", "rank", "bm25_rank", "dense_rank", "bm25_score", "dense_score"}


def _gather(common_fixtures, dst):
    """Same as build_kb.sh: only sources/ and theme_packs/ go into the input folder."""
    dst.mkdir(parents=True)
    shutil.copytree(common_fixtures / "sources", dst / "sources")
    shutil.copytree(common_fixtures / "theme_packs", dst / "theme_packs")
    return dst


@pytest.fixture(scope="module")
def fx_input(tmp_path_factory, common_fixtures):
    return _gather(common_fixtures, tmp_path_factory.mktemp("fx") / "in")


@pytest.fixture(scope="module")
def fx_index(tmp_path_factory, fx_input):
    idx = tmp_path_factory.mktemp("fx_idx") / "idx"
    manifest = build_index(fx_input, idx, HashEmbedder())
    return idx, manifest


@pytest.fixture(scope="module")
def fx_retriever(fx_index):
    return Retriever.load(fx_index[0], HashEmbedder())


def _front_matter(common_fixtures, source_id):
    text = (common_fixtures / "sources" / f"{source_id}.md").read_text(encoding="utf-8")
    return parse_front_matter(text)[0]


# ---------------------------------------------------------------- completion conditions


def test_search_results_carry_source_keys(fx_retriever, common_fixtures):
    hits = fx_retriever.query("달무리나루 이름 유래", k=5)
    assert hits
    for h in hits:
        for key in CHUNK_SOURCE_KEYS:
            assert key in h, key
        assert isinstance(h["about"], list)
    official = [h for h in hits if h["source_id"] == "fx-src-origin-dalmuri-official"]
    assert official, [h["source_id"] for h in hits]
    h = official[0]
    fm = _front_matter(common_fixtures, "fx-src-origin-dalmuri-official")
    assert h["source"] == "sources/fx-src-origin-dalmuri-official.md"
    assert h["title"] == fm["title"]
    assert h["source_type"] == fm["source_type"] == "official"
    assert h["publisher"] == fm["publisher"]
    assert h["published"] == fm["published"]
    assert h["provenance"] == "synthetic"
    assert h["kind"] == "origin"
    assert h["about"] == fm["about"]
    assert h["url"] == ""
    for key in CHUNK_OPERATING_KEYS:
        assert key not in h


def test_theme_pack_and_collection_not_in_chunks(fx_index, fx_retriever, common_fixtures):
    idx, manifest = fx_index
    for c in fx_retriever.chunks:
        parts = c["source"].split("/")
        assert "theme_packs" not in parts and not c["source"].startswith("theme_packs/")
        assert not c["source"].endswith("_collection.json")
    assert {"path": "theme_packs/fx-byeolmuri.json", "reason": "theme pack"} in manifest["skipped"]
    assert {"path": "sources/_collection.json", "reason": "collection defaults"} in manifest["skipped"]
    assert manifest["doc_count"] == 10
    src = common_fixtures / "theme_packs" / "fx-byeolmuri.json"
    copy = idx / "theme_packs" / "fx-byeolmuri.json"
    assert copy.read_bytes() == src.read_bytes()
    assert fx_retriever.theme_packs() == [json.loads(src.read_text(encoding="utf-8"))]


# ---------------------------------------------------------------- files and manifest


def test_format_3_files_and_manifest(fx_index):
    idx, manifest = fx_index
    assert FORMAT_VERSION == 3
    assert MAX_FILE_BYTES == 50 * 1024 * 1024
    on_disk = json.loads((idx / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert manifest["format_version"] == 3
    for key in ["format_version", "created_at", "embedder", "tokenizer", "bm25", "chunker", "input_name",
                "doc_count", "chunk_count", "skipped", "source_fingerprint", "chunk_files", "vector_files"]:
        assert key in manifest, key
    assert manifest["chunk_files"] == ["chunks.json"]
    assert manifest["vector_files"] == ["vectors.json"]
    assert not (idx / "chunks.jsonl").exists() and not (idx / "embeddings.npy").exists()

    raw = (idx / "chunks.json").read_text(encoding="utf-8")
    lines = raw.split("\n")
    assert lines[0] == "[" and lines[-2] == "]" and lines[-1] == ""
    assert len(lines) == manifest["chunk_count"] + 3  # one chunk per line
    chunks = json.loads(raw)
    assert len(chunks) == manifest["chunk_count"]
    assert all("tokens" in c for c in chunks)
    assert "가상" in raw  # ensure_ascii=False

    vectors = json.loads((idx / "vectors.json").read_text(encoding="utf-8"))
    assert len(vectors) == manifest["chunk_count"]
    assert all(len(v) == manifest["embedder"]["dim"] for v in vectors)


def test_vector_values_have_at_most_6_decimals(fx_index):
    idx, _ = fx_index
    vectors = json.loads((idx / "vectors.json").read_text(encoding="utf-8"))
    assert any(x != 0 for v in vectors for x in v)
    for v in vectors:
        for x in v:
            assert round(x, 6) == x


def test_operating_keys_only_on_operating_chunks(fx_retriever):
    for c in fx_retriever.chunks:
        if c["kind"] == "operating":
            assert isinstance(c["place_ids"], list) and isinstance(c["hours"], str) and isinstance(c["closed"], str)
        else:
            for key in CHUNK_OPERATING_KEYS:
                assert key not in c, (c["source"], key)


def test_chunks_where(fx_retriever):
    got = fx_retriever.chunks_where("operating", "fx-02")
    assert {c["source_id"] for c in got} == {"fx-src-op-byeolgaru-2024", "fx-src-op-byeolgaru-2026"}
    order = [c["chunk_id"] for c in fx_retriever.chunks]
    assert [c["chunk_id"] for c in got] == sorted((c["chunk_id"] for c in got), key=order.index)
    two026 = [c for c in got if c["source_id"] == "fx-src-op-byeolgaru-2026"][0]
    assert two026["hours"] == "10:00~20:00" and two026["closed"] == "매주 화요일"
    assert all("tokens" not in c for c in got)
    assert fx_retriever.chunks_where("operating", "fx-01") == []
    assert fx_retriever.chunks_where("origin", "fx-02") == []
    got[0]["place_ids"].append("변조")
    assert "변조" not in fx_retriever.chunks_where("operating", "fx-02")[0]["place_ids"]


def test_get_chunk(fx_retriever):
    hit = fx_retriever.query("달무리나루 이름 유래", k=1)[0]
    chunk = fx_retriever.get_chunk(hit["chunk_id"])
    assert chunk == {k: v for k, v in hit.items() if k not in SCORE_KEYS}
    assert "tokens" not in chunk
    assert fx_retriever.get_chunk("없는/청크#0000") is None
    chunk["about"].append("변조")
    chunk["text"] = "변조"
    again = fx_retriever.get_chunk(hit["chunk_id"])
    assert again["text"] == hit["text"] and "변조" not in again["about"]


def test_query_results_do_not_leak_internal_lists(fx_retriever):
    hit = fx_retriever.query("달무리나루 이름 유래", k=1)[0]
    hit["about"].append("변조")
    hit["dates_in_text"].append("변조")
    again = fx_retriever.query("달무리나루 이름 유래", k=1)[0]
    assert "변조" not in again["about"] and "변조" not in again["dates_in_text"]


def test_theme_packs_empty_without_folder(tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    build_index(root, tmp_path / "idx", HashEmbedder())
    assert not (tmp_path / "idx" / "theme_packs").exists()
    assert Retriever.load(tmp_path / "idx", HashEmbedder()).theme_packs() == []


def test_theme_pack_symlink_not_copied(tmp_path):
    root = tmp_path / "in"
    (root / "theme_packs").mkdir(parents=True)
    (root / "theme_packs" / "real.json").write_text('{"pack_id": "real"}', encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text('{"pack_id": "outside"}', encoding="utf-8")
    (root / "theme_packs" / "link.json").symlink_to(outside)
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    build_index(root, tmp_path / "idx", HashEmbedder())
    assert sorted(os.listdir(tmp_path / "idx" / "theme_packs")) == ["real.json"]


# ---------------------------------------------------------------- split pieces


def test_split_pieces_match_unsplit(tmp_path, fx_input, fx_index):
    idx = tmp_path / "split"
    manifest = build_index(fx_input, idx, HashEmbedder(), max_file_bytes=2000)
    assert len(manifest["chunk_files"]) > 1 and len(manifest["vector_files"]) > 1
    assert manifest["chunk_files"][0] == "chunks-0001.json"
    assert manifest["vector_files"][0] == "vectors-0001.json"
    for name in manifest["chunk_files"] + manifest["vector_files"]:
        assert (idx / name).is_file()
    assert not (idx / "chunks.json").exists() and not (idx / "vectors.json").exists()

    split = Retriever.load(idx, HashEmbedder())
    whole = Retriever.load(fx_index[0], HashEmbedder())
    assert split.chunks == whole.chunks
    assert np.array_equal(split.embeddings, whole.embeddings)
    for q in ["달무리나루 이름 유래", "별가루 골목시장 운영 시간", "감자전"]:
        assert split.query(q, k=5) == whole.query(q, k=5)

    # Re-index without splitting: old pieces are removed, unrelated files stay.
    (idx / "keep.txt").write_text("남겨 둘 파일", encoding="utf-8")
    manifest2 = build_index(fx_input, idx, HashEmbedder())
    assert manifest2["chunk_files"] == ["chunks.json"]
    names = sorted(os.listdir(idx))
    assert names == ["chunks.json", "keep.txt", "manifest.json", "theme_packs", "vectors.json"]


def test_oversized_single_item_is_its_own_piece(tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    (root / "a.md").write_text("# 가\n\n" + "가나다 " * 50, encoding="utf-8")
    (root / "b.md").write_text("# 나\n\n" + "라마바 " * 50, encoding="utf-8")
    m = build_index(root, tmp_path / "idx", HashEmbedder(), max_file_bytes=10)
    assert m["chunk_files"] == [f"chunks-{i:04d}.json" for i in range(1, m["chunk_count"] + 1)]
    assert len(m["vector_files"]) == m["chunk_count"]
    r = Retriever.load(tmp_path / "idx", HashEmbedder())
    assert len(r.chunks) == m["chunk_count"]


def test_reindex_removes_v2_leftovers(tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    idx = tmp_path / "idx"
    (idx / "theme_packs").mkdir(parents=True)
    for name in ["chunks.jsonl", "embeddings.npy", "chunks-0003.json", "vectors-0007.json", "other.json"]:
        (idx / name).write_text("old", encoding="utf-8")
    (idx / "theme_packs" / "old-pack.json").write_text("{}", encoding="utf-8")
    (idx / "manifest.json").write_text('{"format_version": 2}', encoding="utf-8")
    build_index(root, idx, HashEmbedder())
    assert sorted(os.listdir(idx)) == ["chunks.json", "manifest.json", "other.json", "vectors.json"]


@pytest.mark.parametrize("manifest", [None, "not json", '["format_version"]', '{"version": 3}'])
def test_no_cleanup_without_index_manifest(tmp_path, manifest):
    root = tmp_path / "in"
    (root / "theme_packs").mkdir(parents=True)
    (root / "theme_packs" / "same.json").write_text('{"pack_id": "new"}', encoding="utf-8")
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    idx = tmp_path / "idx"
    (idx / "theme_packs").mkdir(parents=True)
    (idx / "theme_packs" / "x.json").write_text('{"pack_id": "x"}', encoding="utf-8")
    (idx / "theme_packs" / "same.json").write_text('{"pack_id": "old"}', encoding="utf-8")
    (idx / "chunks-0003.json").write_text("old", encoding="utf-8")
    (idx / "embeddings.npy").write_text("old", encoding="utf-8")
    if manifest is not None:
        (idx / "manifest.json").write_text(manifest, encoding="utf-8")
    build_index(root, idx, HashEmbedder())
    assert (idx / "theme_packs" / "x.json").is_file()
    assert (idx / "chunks-0003.json").is_file() and (idx / "embeddings.npy").is_file()
    assert json.loads((idx / "theme_packs" / "same.json").read_text(encoding="utf-8")) == {"pack_id": "new"}


@pytest.mark.parametrize("content", ["{깨진", "[1, 2]", "\"문자열\""])
def test_broken_theme_pack_fails_indexing(tmp_path, content):
    root = tmp_path / "in"
    (root / "theme_packs").mkdir(parents=True)
    (root / "theme_packs" / "bad-pack.json").write_text(content, encoding="utf-8")
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    with pytest.raises(InputError) as ei:
        build_index(root, tmp_path / "idx", HashEmbedder())
    assert "bad-pack.json" in str(ei.value)


def test_broken_theme_pack_cli_exit_2(tmp_path):
    from conftest import run_cli

    root = tmp_path / "in"
    (root / "theme_packs").mkdir(parents=True)
    (root / "theme_packs" / "bad-pack.json").write_text("{깨진", encoding="utf-8")
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    res = run_cli(["index", "--input", str(root), "--index", str(tmp_path / "idx"), "--embedder", "hash"])
    assert res.returncode == 2 and "bad-pack.json" in res.stderr


def test_theme_pack_broken_after_load_raises(tmp_path, fx_index):
    from retrieval.errors import RetrievalError

    idx = tmp_path / "idx"
    shutil.copytree(fx_index[0], idx)
    r = Retriever.load(idx, HashEmbedder())
    (idx / "theme_packs" / "fx-byeolmuri.json").write_text("{깨진", encoding="utf-8")
    with pytest.raises(RetrievalError):
        r.theme_packs()


def test_skipped_theme_packs_are_recorded(tmp_path):
    root = tmp_path / "in"
    (root / "theme_packs").mkdir(parents=True)
    (root / "theme_packs" / "ok.json").write_text('{"pack_id": "ok"}', encoding="utf-8")
    (root / "theme_packs" / "big.json").write_text('{"pack_id": "big", "pad": "' + "x" * 200 + '"}',
                                                   encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text('{"pack_id": "outside"}', encoding="utf-8")
    (root / "theme_packs" / "link.json").symlink_to(outside)
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    m = build_index(root, tmp_path / "idx", HashEmbedder(), max_theme_pack_bytes=100)
    assert {"path": "theme_packs/big.json", "reason": "theme pack not copied: too large"} in m["skipped"]
    assert {"path": "theme_packs/link.json", "reason": "theme pack not copied: symlink"} in m["skipped"]
    assert sorted(os.listdir(tmp_path / "idx" / "theme_packs")) == ["ok.json"]


@pytest.mark.parametrize("bad", ["../chunks.json", "sub/chunks.json", "..", "a\\b.json", "", 3])
def test_bad_piece_names_rejected(tmp_path, fx_index, bad):
    idx = tmp_path / "idx"
    shutil.copytree(fx_index[0], idx)
    m = json.loads((idx / "manifest.json").read_text(encoding="utf-8"))
    m["chunk_files"] = [bad]
    (idx / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(InputError):
        Retriever.load(idx, HashEmbedder())


def test_missing_piece_list_or_file_rejected(tmp_path, fx_index):
    idx = tmp_path / "idx"
    shutil.copytree(fx_index[0], idx)
    m = json.loads((idx / "manifest.json").read_text(encoding="utf-8"))
    m.pop("vector_files")
    (idx / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(InputError):
        Retriever.load(idx, HashEmbedder())
    idx2 = tmp_path / "idx2"
    shutil.copytree(fx_index[0], idx2)
    (idx2 / "vectors.json").unlink()
    with pytest.raises(InputError):
        Retriever.load(idx2, HashEmbedder())


def test_count_and_dim_mismatch_rejected(tmp_path, fx_index):
    from retrieval.errors import RetrievalError

    idx = tmp_path / "idx"
    shutil.copytree(fx_index[0], idx)
    vectors = json.loads((idx / "vectors.json").read_text(encoding="utf-8"))
    (idx / "vectors.json").write_text(json.dumps(vectors[:-1]), encoding="utf-8")
    with pytest.raises(RetrievalError):
        Retriever.load(idx, HashEmbedder())
    vectors[0] = vectors[0][:-1]
    (idx / "vectors.json").write_text(json.dumps(vectors), encoding="utf-8")
    with pytest.raises(RetrievalError):
        Retriever.load(idx, HashEmbedder())


def test_empty_input_round_trip(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    m = build_index(root, tmp_path / "idx", HashEmbedder())
    assert m["chunk_files"] == ["chunks.json"] and m["vector_files"] == ["vectors.json"]
    r = Retriever.load(tmp_path / "idx", HashEmbedder())
    assert r.embeddings.shape == (0, 256)
    assert r.query("세종") == [] and r.chunks_where("operating", "x") == [] and r.get_chunk("x") is None


# ---------------------------------------------------------------- format 2 rejected


def test_format_2_index_is_rejected(tmp_path, fx_index):
    idx = tmp_path / "v2"
    idx.mkdir()
    m = json.loads((fx_index[0] / "manifest.json").read_text(encoding="utf-8"))
    m["format_version"] = 2
    for key in ("chunk_files", "vector_files", "source_fingerprint"):
        m.pop(key)
    (idx / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    chunks = json.loads((fx_index[0] / "chunks.json").read_text(encoding="utf-8"))
    (idx / "chunks.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks),
                                      encoding="utf-8")
    np.save(idx / "embeddings.npy", np.zeros((len(chunks), 256), dtype=np.float32))
    with pytest.raises(InputError) as ei:
        Retriever.load(idx, HashEmbedder())
    assert "형식 버전" in str(ei.value)


# ---------------------------------------------------------------- source_fingerprint


def _expected_fingerprint(root):
    lines = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            data = open(full, "rb").read()
            lines.append((rel, f"{rel}\t{len(data)}\t{hashlib.sha256(data).hexdigest()}\n"))
    lines.sort()
    return hashlib.sha256("".join(line for _, line in lines).encode("utf-8")).hexdigest()


def test_source_fingerprint(tmp_path, common_fixtures, fx_index, fx_input):
    a = _gather(common_fixtures, tmp_path / "a")
    b = _gather(common_fixtures, tmp_path / "b")
    os.utime(b / "sources" / "fx-src-unrelated.md", (1_000_000, 1_000_000))
    (a / "notes.pdf").write_bytes(b"%PDF")
    (b / "notes.pdf").write_bytes(b"%PDF")
    fa, fb = source_fingerprint(a), source_fingerprint(b)
    assert fa == fb == _expected_fingerprint(a)
    assert len(fa) == 64
    p = b / "sources" / "fx-src-unrelated.md"
    data = p.read_bytes()
    i = data.rindex("다".encode("utf-8")[:1])
    swapped = data[:i] + bytes([data[i] ^ 0x01]) + data[i + 1:]
    assert len(swapped) == len(data)
    p.write_bytes(swapped)  # same size, one byte changed
    assert source_fingerprint(b) != fa
    p.write_bytes(data)
    assert source_fingerprint(b) == fa
    tp = b / "theme_packs" / "fx-byeolmuri.json"
    tp.write_bytes(tp.read_bytes() + b" ")
    assert source_fingerprint(b) != fa
    assert fx_index[1]["source_fingerprint"] == source_fingerprint(fx_input)


def test_source_fingerprint_ignores_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("가", encoding="utf-8")
    before = source_fingerprint(root)
    outside = tmp_path / "outside.txt"
    outside.write_text("밖", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    (root / "linkdir").symlink_to(tmp_path, target_is_directory=True)
    assert source_fingerprint(root) == before


def test_symlinked_index_theme_packs_fails_before_writing(tmp_path):
    root = tmp_path / "in"
    (root / "theme_packs").mkdir(parents=True)
    (root / "theme_packs" / "p.json").write_text('{"pack_id": "p"}', encoding="utf-8")
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    idx = tmp_path / "idx"
    idx.mkdir()
    (idx / "theme_packs").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(InputError):
        build_index(root, idx, HashEmbedder())
    assert not (idx / "chunks.json").exists() and not (idx / "vectors.json").exists()
    assert os.listdir(elsewhere) == []


def test_theme_pack_with_bom(tmp_path):
    root = tmp_path / "in"
    (root / "theme_packs").mkdir(parents=True)
    data = b"\xef\xbb\xbf" + '{"pack_id": "bom", "work_title": "가상"}'.encode("utf-8")
    (root / "theme_packs" / "bom.json").write_bytes(data)
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    build_index(root, tmp_path / "idx", HashEmbedder())
    assert (tmp_path / "idx" / "theme_packs" / "bom.json").read_bytes() == data
    packs = Retriever.load(tmp_path / "idx", HashEmbedder()).theme_packs()
    assert packs == [{"pack_id": "bom", "work_title": "가상"}]
