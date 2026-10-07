import json
import shutil

import numpy as np
import pytest

from retrieval.dense import dense_rank
from retrieval.embedder import HashEmbedder
from retrieval.errors import EmbedderMismatchError, IndexLocationError, InputError, TokenizerMismatchError
from retrieval.index import FORMAT_VERSION, Retriever, build_index
from retrieval.tokenize import tokenizer_config


def test_index_files_and_manifest(built_index):
    assert (built_index / "chunks.json").is_file()
    assert (built_index / "vectors.json").is_file()
    manifest = json.loads((built_index / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format_version"] == FORMAT_VERSION
    assert manifest["embedder"] == {"type": "hash", "model": "hash-char-ngram-v1", "dim": 256}
    assert manifest["tokenizer"] == tokenizer_config()
    tok = manifest["tokenizer"]
    assert tok["kiwipiepy"] and tok["kiwipiepy"] != "unknown"
    assert "SF" in tok["drop_tag_prefixes"] and "SN" not in tok["drop_tag_prefixes"]
    for prefix in ["J", "E", "XS", "VCP", "VCN"]:
        assert prefix in tok["drop_tag_prefixes"]
    for kept in ["NN", "NNG", "NNP", "VV", "VA", "MAG", "SL", "SH", "W_"]:
        assert not kept.startswith(tuple(tok["drop_tag_prefixes"]))
    assert tok["lowercase"] is True
    assert manifest["bm25"]["k1"] == 1.5 and manifest["bm25"]["b"] == 0.75
    assert manifest["doc_count"] == 8
    assert manifest["chunk_count"] >= 8
    assert {"path": "misc/brochure.pdf", "reason": "unsupported"} in manifest["skipped"]
    assert manifest["input_name"] == "input"
    assert manifest["created_at"].endswith("+00:00")

    assert manifest["chunk_files"] == ["chunks.json"] and manifest["vector_files"] == ["vectors.json"]
    recs = json.loads((built_index / "chunks.json").read_text(encoding="utf-8"))
    assert len(recs) == manifest["chunk_count"]
    rec = recs[0]
    for key in ["chunk_id", "source", "title", "mtime", "dates_in_text", "char_start", "char_end", "text", "tokens"]:
        assert key in rec
    vectors = json.loads((built_index / "vectors.json").read_text(encoding="utf-8"))
    assert len(vectors) == manifest["chunk_count"] and all(len(v) == 256 for v in vectors)
    emb = Retriever.load(built_index, HashEmbedder()).embeddings
    assert emb.shape == (manifest["chunk_count"], 256)
    assert emb.dtype == np.float32


def test_round_trip_query_hybrid(built_index):
    r = Retriever.load(built_index, HashEmbedder())
    hits = r.query("훈민정음은 언제 반포되었나", k=3, mode="hybrid")
    assert hits and len(hits) <= 3
    top = hits[0]
    assert top["source"] == "hunminjeongeum.md"
    assert top["rank"] == 1
    assert top["bm25_rank"] == 1
    assert top["dense_rank"] is not None
    assert top["score"] > 0
    assert [h["rank"] for h in hits] == list(range(1, len(hits) + 1))
    for key in ["chunk_id", "title", "mtime", "dates_in_text", "char_start", "char_end", "text",
                "bm25_score", "dense_score"]:
        assert key in top
    assert "tokens" not in top
    assert "1446-09" in top["dates_in_text"] and "1443" in top["dates_in_text"]


def test_query_modes(built_index):
    r = Retriever.load(built_index, HashEmbedder())
    bm = r.query("경회루", k=5, mode="bm25")
    assert bm and all(h["dense_rank"] is None for h in bm)
    assert bm[0]["source"] == "palace/gyeongbokgung.md"
    dn = r.query("경복궁 관람 시간", k=5, mode="dense")
    assert dn and all(h["bm25_rank"] is None for h in dn)
    assert r.query("zzzqqqxyz", k=5, mode="bm25") == []
    with pytest.raises(InputError):
        r.query("x", mode="nope")
    with pytest.raises(InputError):
        r.query("   ")
    with pytest.raises(InputError):
        r.query("세종", k=0)


def test_bm25_ignores_documents_sharing_only_particles_and_endings(built_index):
    # Neither file shares a content morpheme (훈민정음, 언제, 반포) with the query; before the POS filter
    # they matched only on 은/되/었/나-type particles and endings.
    r = Retriever.load(built_index, HashEmbedder())
    k = r.manifest["chunk_count"]
    hits = r.query("훈민정음은 언제 반포되었나", k=k, mode="bm25")
    sources = {h["source"] for h in hits}
    assert hits[0]["source"] == "hunminjeongeum.md"
    assert "misc/meeting_notes.txt" not in sources
    assert "palace/gyeongbokgung_hours_2019.txt" not in sources


def test_outdated_and_conflicting_sources_both_retrievable(built_index):
    r = Retriever.load(built_index, HashEmbedder())
    hours = {h["source"] for h in r.query("경복궁 관람 시간 휴궁일", k=5)}
    assert {"palace/gyeongbokgung_hours_2019.txt", "palace/gyeongbokgung_hours_2026.html"} <= hours
    hw = {h["source"] for h in r.query("수원 화성 완공", k=5)}
    assert {"hwaseong_a.json", "hwaseong_b.jsonl"} <= hw


def test_embedder_mismatch(built_index):
    with pytest.raises(EmbedderMismatchError):
        Retriever.load(built_index, HashEmbedder(dim=128))


def _copy_index(src, dst):
    shutil.copytree(src, dst)


def _edit_manifest(idx, fn):
    m = json.loads((idx / "manifest.json").read_text(encoding="utf-8"))
    fn(m)
    (idx / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(
    "field, value",
    [("kiwipiepy", "0.0.1"), ("lowercase", False), ("drop_tag_prefixes", ["SF"]), ("name", "other")],
)
def test_tokenizer_mismatch_is_rejected(built_index, tmp_path, field, value):
    idx = tmp_path / "idx"
    _copy_index(built_index, idx)
    _edit_manifest(idx, lambda m: m["tokenizer"].__setitem__(field, value))
    with pytest.raises(TokenizerMismatchError) as ei:
        Retriever.load(idx, HashEmbedder())
    assert field in str(ei.value)


@pytest.mark.parametrize("field", ["k1", "b"])
def test_bm25_params_missing_or_bad_is_rejected(built_index, tmp_path, field):
    idx = tmp_path / "idx"
    _copy_index(built_index, idx)
    _edit_manifest(idx, lambda m: m["bm25"].pop(field))
    with pytest.raises(InputError):
        Retriever.load(idx, HashEmbedder())


def test_bm25_params_come_from_manifest(tmp_path, fixture_input):
    build_index(fixture_input, tmp_path / "idx", HashEmbedder(), k1=1.2, b=0.5)
    r = Retriever.load(tmp_path / "idx", HashEmbedder())
    assert r.bm25.params["k1"] == 1.2 and r.bm25.params["b"] == 0.5


@pytest.mark.parametrize("version", [999, 2])
def test_format_version_mismatch_is_rejected(built_index, tmp_path, version):
    idx = tmp_path / "idx"
    _copy_index(built_index, idx)
    _edit_manifest(idx, lambda m: m.__setitem__("format_version", version))
    with pytest.raises(InputError) as ei:
        Retriever.load(idx, HashEmbedder())
    assert "형식 버전" in str(ei.value)


# Tokenizer setting of format 1 indexes (punctuation only, no POS filter).
_R1_DROP_TAG_PREFIXES = ["SF", "SP", "SS", "SE", "SO", "SW", "SB"]


def test_format_version_is_3():
    assert FORMAT_VERSION == 3


def test_format_1_index_is_rejected(built_index, tmp_path):
    # Load checks the format version first, so an R1 index fails there (InputError) before the tokenizer check.
    idx = tmp_path / "idx"
    _copy_index(built_index, idx)

    def to_r1(m):
        m["format_version"] = 1
        m["tokenizer"]["drop_tag_prefixes"] = list(_R1_DROP_TAG_PREFIXES)

    _edit_manifest(idx, to_r1)
    with pytest.raises(InputError) as ei:
        Retriever.load(idx, HashEmbedder())
    assert "형식 버전" in str(ei.value)


def test_index_without_pos_filter_is_tokenizer_mismatch(built_index, tmp_path):
    idx = tmp_path / "idx"
    _copy_index(built_index, idx)
    _edit_manifest(idx, lambda m: m["tokenizer"].__setitem__("drop_tag_prefixes", list(_R1_DROP_TAG_PREFIXES)))
    with pytest.raises(TokenizerMismatchError) as ei:
        Retriever.load(idx, HashEmbedder())
    assert "drop_tag_prefixes" in str(ei.value)


def test_load_missing_index(tmp_path):
    with pytest.raises(InputError):
        Retriever.load(tmp_path / "nothing", HashEmbedder())


def test_index_dir_inside_input_is_rejected(tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    (root / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    with pytest.raises(IndexLocationError):
        build_index(root, root / "idx", HashEmbedder())
    with pytest.raises(IndexLocationError):
        build_index(root, root, HashEmbedder())
    assert not (root / "idx").exists()


def test_same_code_indexes_any_root(tmp_path):
    # Input root is only an argument: a second, unrelated folder indexes with the same call.
    root = tmp_path / "other_corpus"
    (root / "deep" / "er").mkdir(parents=True)
    (root / "deep" / "er" / "note.txt").write_text("부석사 무량수전은 고려 시대 목조 건물이다.", encoding="utf-8")
    m = build_index(root, tmp_path / "idx", HashEmbedder())
    assert m["input_name"] == "other_corpus" and m["doc_count"] == 1
    hits = Retriever.load(tmp_path / "idx", HashEmbedder()).query("무량수전")
    assert hits[0]["source"] == "deep/er/note.txt"


def test_build_on_empty_input(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    manifest = build_index(root, tmp_path / "idx", HashEmbedder())
    assert manifest["chunk_count"] == 0
    r = Retriever.load(tmp_path / "idx", HashEmbedder())
    assert r.query("세종", mode="hybrid") == []


def test_dense_rank_topk():
    m = np.eye(3, dtype=np.float32)
    q = np.array([0.6, 0.8, 0.0], dtype=np.float32)
    ranked = dense_rank(m, q, top_k=2)
    assert [i for i, _ in ranked] == [1, 0]
    assert ranked[0][1] == pytest.approx(0.8)
