"""Reciprocal Rank Fusion: score(d) = sum over methods of 1 / (k + rank), rank starting at 1."""

from __future__ import annotations

DEFAULT_RRF_K = 60
METHODS = ("bm25", "dense")


def rrf_fuse(rankings: dict[str, list[int]], k: int = DEFAULT_RRF_K) -> list[dict]:
    """rankings: method name -> ordered list of item ids (best first).

    Returns [{"idx", "rrf", "bm25_rank", "dense_rank"}] sorted by rrf desc; a method that did not
    return the item leaves its rank as None.
    """
    acc: dict[int, dict] = {}
    for method, ids in rankings.items():
        for rank, idx in enumerate(ids, start=1):
            entry = acc.setdefault(idx, {"idx": idx, "rrf": 0.0, **{f"{m}_rank": None for m in METHODS}})
            entry["rrf"] += 1.0 / (k + rank)
            entry[f"{method}_rank"] = rank

    def best_rank(e):
        ranks = [e[f"{m}_rank"] for m in METHODS if e[f"{m}_rank"] is not None]
        return min(ranks) if ranks else float("inf")

    return sorted(acc.values(), key=lambda e: (-e["rrf"], best_rank(e), e["idx"]))
