"""Hybrid retrieval (Kiwi BM25 + embeddings, fused with RRF) over a local folder of reference files.

"Training" here means indexing: `build_index` reads the input folder once and writes an index folder;
`Retriever.load` opens it for queries. Nothing modifies model weights.
"""

from retrieval.errors import (
    EmbedderMismatchError,
    IndexLocationError,
    InputError,
    RetrievalError,
    TokenizerMismatchError,
)

__all__ = [
    "EmbedderMismatchError",
    "IndexLocationError",
    "InputError",
    "RetrievalError",
    "TokenizerMismatchError",
]
