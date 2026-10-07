"""Test fakes for `Deps`, built from the shared fake input in `common/fixtures/`.

Import as `from tools.tests.fakes import make_deps` (no `__init__.py` here; namespace package).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

from common import FIXTURES_DIR
from common.tooling import Deps, RunContext

FAKE_NOW = datetime(2026, 10, 7, 3, 31, 5, tzinfo=timezone.utc)
DEFAULT_RUN_ID = "20261007T033105Z-0a1f"
DEFAULT_REQUEST = "별수단 배경지 새벽솔역에서 3시간 코스"

_LIST_KEYS = ("about", "place_ids")


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [v.strip() for v in inner.split(",") if v.strip()] if inner else []
    return raw


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, Any] = {}
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:]).strip("\n")
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = _parse_value(value)
    return {}, text


def load_fixture_chunks() -> list[dict]:
    """One chunk per `sources/*.md` file (files starting with "_" skipped), with the spec 4.3 chunk keys."""
    chunks: list[dict] = []
    for path in sorted((FIXTURES_DIR / "sources").glob("*.md")):
        if path.name.startswith("_"):
            continue
        meta, body = _split_front_matter(path.read_text(encoding="utf-8"))
        for key in _LIST_KEYS:
            if key in meta and not isinstance(meta[key], list):
                meta[key] = [meta[key]] if meta[key] else []
        source_id = meta.get("source_id", path.stem)
        chunk: dict[str, Any] = {
            "chunk_id": f"{source_id}#c0",
            "source": f"sources/{path.name}",
            "title": meta.get("title", ""),
            "text": body,
            "char_start": 0,
            "char_end": len(body),
            "dates_in_text": [],
            "mtime": 0.0,
            "source_id": source_id,
            "publisher": meta.get("publisher", ""),
            "source_type": meta.get("source_type", ""),
            "published": meta.get("published", ""),
            "url": meta.get("url", ""),
            "provenance": meta.get("provenance", ""),
            "kind": meta.get("kind", ""),
            "about": meta.get("about", []),
        }
        if chunk["kind"] == "operating":
            chunk["place_ids"] = meta.get("place_ids", [])
            chunk["hours"] = meta.get("hours", "")
            chunk["closed"] = meta.get("closed", "")
        chunks.append(chunk)
    return chunks


def load_fixture_packs() -> list[dict]:
    """Every `theme_packs/*.json`."""
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((FIXTURES_DIR / "theme_packs").glob("*.json"))
    ]


class FakeChat:
    """Hands out scripted answers in order; an exception instance in `responses` is raised."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict], str]] = []

    def __call__(self, messages: list[dict], purpose: str) -> dict:
        self.calls.append((messages, purpose))
        if not self.responses:
            raise AssertionError("unexpected chat call")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return {"text": item, "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "model": "fake-nemotron"}


class FakeHttp:
    """Records calls and returns a copy of one fixed response."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, headers: dict, body: dict) -> dict:
        self.calls.append((url, headers, body))
        return copy.deepcopy(self.response)


class FakeFS:
    """`read_path` over a dict tree: bytes = file, list = folder entries, exception instance = raised."""

    def __init__(self, tree: dict[str, object]) -> None:
        self.tree = tree
        self.calls: list[tuple[str, int]] = []

    def __call__(self, path: str, max_bytes: int) -> list[dict] | bytes:
        self.calls.append((path, max_bytes))
        if path not in self.tree:
            raise FileNotFoundError(2, "No such file", path)
        value = self.tree[path]
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, bytes):
            return value[:max_bytes]
        return copy.deepcopy(value)


def _overlap_score(words: list[str], chunk: dict) -> int:
    hay = " ".join([chunk.get("title", ""), chunk.get("text", ""), " ".join(chunk.get("about", []))])
    return sum(1 for w in words if w in hay)


def make_deps(*, chunks=None, packs=None, chat=None, http=None, fs=None, now=None) -> Deps:
    """Fake Deps; defaults: fixture chunks and packs, no chat answers, NETWORK error for http, empty fs."""
    chunk_list = load_fixture_chunks() if chunks is None else chunks
    pack_list = load_fixture_packs() if packs is None else packs
    by_id = {c["chunk_id"]: c for c in chunk_list}

    def search(query: str, k: int) -> list[dict]:
        words = query.split()
        scored = [(_overlap_score(words, c), c) for c in chunk_list]
        scored = [sc for sc in scored if sc[0] > 0]
        scored.sort(key=lambda sc: -sc[0])
        return [copy.deepcopy(c) for _, c in scored[:k]]

    def get_chunk(chunk_id: str) -> dict | None:
        c = by_id.get(chunk_id)
        return copy.deepcopy(c) if c is not None else None

    def chunks_where(kind: str, place_id: str) -> list[dict]:
        return [
            copy.deepcopy(c) for c in chunk_list
            if c.get("kind") == kind and place_id in c.get("place_ids", [])
        ]

    def theme_packs() -> list[dict]:
        return copy.deepcopy(pack_list)

    # `now` may be a datetime or a zero-argument function returning one.
    now_fn = now if callable(now) else (lambda: FAKE_NOW if now is None else now)

    return Deps(
        search=search,
        get_chunk=get_chunk,
        chunks_where=chunks_where,
        theme_packs=theme_packs,
        chat=chat if chat is not None else FakeChat([]),
        http_post_json=http if http is not None else FakeHttp({"status": None, "body": "", "error": "NETWORK"}),
        read_path=fs if fs is not None else FakeFS({}),
        now=now_fn,
    )


def make_ctx(**kwargs) -> RunContext:
    """RunContext with a fixed run_id and request; other keys from kwargs."""
    kwargs.setdefault("run_id", DEFAULT_RUN_ID)
    kwargs.setdefault("request", DEFAULT_REQUEST)
    return RunContext(**kwargs)
