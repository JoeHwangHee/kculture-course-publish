"""BM25Okapi wrapper over pre-tokenized chunks (tokens are stored in the index, not re-analyzed on load)."""

from __future__ import annotations

from rank_bm25 import BM25Okapi

DEFAULT_K1 = 1.5
DEFAULT_B = 0.75
DEFAULT_EPSILON = 0.25


class BM25Index:
    def __init__(
        self,
        corpus_tokens: list[list[str]],
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
        epsilon: float = DEFAULT_EPSILON,
    ):
        self.corpus_tokens = corpus_tokens
        self.params = {"k1": k1, "b": b, "epsilon": epsilon}
        self._token_sets = [set(t) for t in corpus_tokens]
        # BM25Okapi divides by corpus size; an empty corpus has no model.
        self._bm25 = BM25Okapi(corpus_tokens, k1=k1, b=b, epsilon=epsilon) if any(corpus_tokens) else None

    def rank(self, query_tokens: list[str], top_k: int | None = None) -> list[tuple[int, float]]:
        """(chunk index, score) sorted by score desc. Only chunks sharing at least one query token count as hits."""
        if self._bm25 is None or not query_tokens:
            return []
        q = set(query_tokens)
        scores = self._bm25.get_scores(query_tokens)
        hits = [(i, float(scores[i])) for i, ts in enumerate(self._token_sets) if ts & q]
        hits.sort(key=lambda x: (-x[1], x[0]))
        return hits[:top_k] if top_k else hits
