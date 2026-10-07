"""Real-run assembly: Deps over the JSON index, standard-library HTTP and the given chat, plus the tool registry.

`retrieval` and `tools` are imported inside the functions: they belong to other tracks, and a top-level import
would break test collection while they are being built.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any, Callable

from common.tooling import Deps, ToolRegistry
from loop.http import make_github_post, read_path, utc_now

MANIFEST_FILE = "manifest.json"
THEME_PACKS_DIR = "theme_packs"


def _load_theme_packs(index_dir) -> list[dict[str, Any]]:
    """`<index_dir>/theme_packs/*.json` as dicts, by file name. A missing folder gives an empty list."""
    folder = pathlib.Path(index_dir) / THEME_PACKS_DIR
    if not folder.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json")) if p.is_file()]


def _read_fingerprint(index_dir) -> str:
    """manifest.json `source_fingerprint`, or "" when absent."""
    path = pathlib.Path(index_dir) / MANIFEST_FILE
    if not path.is_file():
        return ""
    value = json.loads(path.read_text(encoding="utf-8")).get("source_fingerprint")
    return value if isinstance(value, str) else ""


def _public_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    # Same shape as Retriever.query hits: internal "tokens" left out; a copy so tools cannot edit the index.
    return {k: copy.deepcopy(v) for k, v in chunk.items() if k != "tokens"}


def _chunk_lookups(retriever) -> tuple[Callable[[str], dict | None], Callable[[str, str], list[dict]]]:
    """(get_chunk, chunks_where): the retriever's own methods when it has them, else filters over `.chunks`."""
    own_get = getattr(retriever, "get_chunk", None)
    own_where = getattr(retriever, "chunks_where", None)

    if callable(own_get):
        get_chunk = own_get
    else:
        def get_chunk(chunk_id: str) -> dict | None:
            for chunk in retriever.chunks:
                if chunk.get("chunk_id") == chunk_id:
                    return _public_chunk(chunk)
            return None

    if callable(own_where):
        chunks_where = own_where
    else:
        def chunks_where(kind: str, place_id: str) -> list[dict]:
            return [
                _public_chunk(c) for c in retriever.chunks
                if c.get("kind") == kind and place_id in (c.get("place_ids") or [])
            ]

    return get_chunk, chunks_where


def build_real(*, index_dir: str, embedder_spec: str, chat) -> tuple[Deps, ToolRegistry, str]:
    """-> (Deps, registry with the eleven tools, index source_fingerprint). `chat` goes into Deps as given
    (the loop passes Nemotron wrapped by its Budget)."""
    from retrieval.embedder import make_embedder
    from retrieval.index import Retriever

    import tools

    retriever = Retriever.load(index_dir, make_embedder(embedder_spec))

    def search(query: str, k: int) -> list[dict]:
        return retriever.query(query, k=k, mode="hybrid")

    def theme_packs() -> list[dict]:
        return _load_theme_packs(index_dir)

    get_chunk, chunks_where = _chunk_lookups(retriever)
    deps = Deps(
        search=search,
        get_chunk=get_chunk,
        chunks_where=chunks_where,
        theme_packs=theme_packs,
        chat=chat,
        http_post_json=make_github_post(),
        read_path=read_path,
        now=utc_now,
    )
    registry = ToolRegistry()
    tools.register_all(registry)
    return deps, registry, _read_fingerprint(index_dir)
