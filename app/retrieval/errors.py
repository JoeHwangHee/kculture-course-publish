"""Error types. CLI maps InputError (and subclasses) to exit code 2, other RetrievalError to 3."""


class RetrievalError(Exception):
    """Runtime failure inside the retrieval layer (exit code 3)."""


class InputError(RetrievalError):
    """Bad usage or input: missing folder, bad embedder spec, bad query, unusable index (exit code 2)."""


class EmbedderMismatchError(InputError):
    """Index was built with a different embedder (type, model or dimension)."""


class TokenizerMismatchError(InputError):
    """Index was built with a different tokenizer setting (Kiwi version, POS filter, lowercasing)."""


class IndexLocationError(InputError):
    """Index folder would be inside the input folder."""
