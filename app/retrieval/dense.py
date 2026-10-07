"""Dense top-k by inner product of L2-normalized vectors (= cosine similarity)."""

from __future__ import annotations

import numpy as np


def dense_rank(
    matrix: np.ndarray, query_vec: np.ndarray, top_k: int | None = None, min_score: float = 0.0
) -> list[tuple[int, float]]:
    """(row index, cosine) sorted desc; rows with cosine <= min_score are not hits."""
    if matrix.size == 0 or matrix.shape[0] == 0:
        return []
    scores = matrix @ query_vec.astype(np.float32)
    order = np.argsort(-scores, kind="stable")
    hits = [(int(i), float(scores[i])) for i in order if scores[i] > min_score]
    return hits[:top_k] if top_k else hits
