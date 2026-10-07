import pytest

from retrieval.fusion import rrf_fuse


def test_rrf_scores_and_ranks():
    fused = rrf_fuse({"bm25": [10, 20, 30], "dense": [20, 10]}, k=60)
    by_id = {f["idx"]: f for f in fused}

    assert by_id[10]["rrf"] == pytest.approx(1 / 61 + 1 / 62)
    assert by_id[20]["rrf"] == pytest.approx(1 / 62 + 1 / 61)
    assert by_id[30]["rrf"] == pytest.approx(1 / 63)

    assert by_id[10]["bm25_rank"] == 1 and by_id[10]["dense_rank"] == 2
    assert by_id[20]["bm25_rank"] == 2 and by_id[20]["dense_rank"] == 1
    assert by_id[30]["bm25_rank"] == 3 and by_id[30]["dense_rank"] is None

    # 30 is last; ties (10, 20) break deterministically by best rank then idx
    assert [f["idx"] for f in fused][-1] == 30
    assert len(fused) == 3


def test_rrf_default_k_is_60():
    fused = rrf_fuse({"bm25": [1]})
    assert fused[0]["rrf"] == pytest.approx(1 / 61)
    assert fused[0]["dense_rank"] is None


def test_rrf_empty():
    assert rrf_fuse({"bm25": [], "dense": []}) == []
