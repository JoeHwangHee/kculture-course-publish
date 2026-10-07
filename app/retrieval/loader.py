"""Walk one input root and turn supported files into plain-text documents.

Safety rules (the input folder is untrusted):
- Only the given root is walked; symlinked files and folders are never followed (lstat check).
- Anything whose real path is outside the real root is skipped.
- Permission and read errors are recorded as skipped entries, never raised.

Spec 4.3 rules applied while walking:
- Files under any `theme_packs` path part (reason "theme pack") and files named `_collection.json`
  (reason "collection defaults") are never documents; they are recorded in `skipped`.
- `.md` front matter is cut off before parsing (only the body becomes document text), and every document carries
  its resolved source metadata in `Document.meta` (front matter > same-folder `_collection.json` > defaults,
  see `retrieval.source_meta`).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from retrieval.errors import InputError
from retrieval.source_meta import (
    COLLECTION_FILE,
    THEME_PACK_DIR,
    document_title,
    parse_front_matter,
    resolve_source_meta,
)

log = logging.getLogger("retrieval")

ENCODINGS = ("utf-8-sig", "cp949")
DEFAULT_MAX_BYTES = 20 * 1024 * 1024

_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_TITLE_KEYS = ("title", "제목", "name", "이름")


@dataclass
class Document:
    source: str  # path relative to the input root, "/" separated
    text: str
    title: str
    mtime: str  # ISO 8601, UTC
    fmt: str
    # Resolved source keys (common.schema.CHUNK_SOURCE_KEYS, plus the operating keys for kind "operating").
    meta: dict = field(default_factory=lambda: resolve_source_meta({}, {}))


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _inside(real_root: str, path: str) -> bool:
    real = os.path.realpath(path)
    try:
        return os.path.commonpath([real_root, real]) == real_root
    except ValueError:
        return False


# ---------------------------------------------------------------- format parsers


class _HTMLText(HTMLParser):
    BLOCK = {
        "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "dd", "dt", "hr", "main", "nav",
    }
    SKIP = {"script", "style", "noscript", "template", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.in_title = False
        self.in_h1 = False
        self.title = ""
        self.h1 = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        elif tag in self.SKIP:
            self.skip_depth += 1
        elif tag == "h1":
            self.in_h1 = True
        if tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_startendtag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag == "h1":
            self.in_h1 = False
        if tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.skip_depth:
            return
        if self.in_h1:
            self.h1 += data
        self.parts.append(data)


def _normalize_ws(text: str) -> str:
    lines = [re.sub(r"[ \t\f\v ]+", " ", ln).strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _parse_html(raw: str) -> tuple[str, str | None]:
    p = _HTMLText()
    p.feed(raw)
    p.close()
    title = _normalize_ws(p.title) or _normalize_ws(p.h1) or None
    return _normalize_ws("".join(p.parts)), title


def _flatten_json(obj, prefix: str = "") -> list[str]:
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            lines.extend(_flatten_json(v, key))
    elif isinstance(obj, list):
        for v in obj:
            lines.extend(_flatten_json(v, prefix))
    elif obj is None:
        pass
    else:
        lines.append(f"{prefix}: {obj}" if prefix else str(obj))
    return lines


def _json_title(obj) -> str | None:
    if isinstance(obj, dict):
        for k in _TITLE_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _parse_json(raw: str) -> tuple[str, str | None]:
    try:
        obj = json.loads(raw)
    except ValueError:
        return _normalize_ws(raw), None
    records = obj if isinstance(obj, list) else [obj]
    title = _json_title(records[0]) if records else None
    text = "\n\n".join("\n".join(_flatten_json(r)) for r in records)
    return _normalize_ws(text), title


def _parse_jsonl(raw: str) -> tuple[str, str | None]:
    blocks: list[str] = []
    title = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            blocks.append(line.strip())
            continue
        if title is None:
            title = _json_title(obj)
        blocks.append("\n".join(_flatten_json(obj)))
    return _normalize_ws("\n\n".join(blocks)), title


def _parse_csv(raw: str) -> tuple[str, str | None]:
    try:
        rows = list(csv.reader(io.StringIO(raw)))
    except csv.Error:
        return _normalize_ws(raw), None
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return _normalize_ws(raw), None
    header = [h.strip() for h in rows[0]]
    blocks = []
    for r in rows[1:]:
        pairs = []
        for i, cell in enumerate(r):
            name = header[i] if i < len(header) and header[i] else f"col{i + 1}"
            if cell.strip():
                pairs.append(f"{name}: {cell.strip()}")
        blocks.append("\n".join(pairs))
    return _normalize_ws("\n\n".join(blocks)), None


def _parse_text(raw: str) -> tuple[str, str | None]:
    text = _normalize_ws(raw)
    for line in text.split("\n"):
        if not line.strip():
            continue
        m = _MD_HEADING.match(line)
        return text, (m.group(1).strip() if m else None)
    return text, None


# Format registry: lowercase extension (with dot) -> parser(decoded text) -> (plain text, title or None).
# Files whose extension is not registered are skipped with reason "unsupported".
Parser = Callable[[str], "tuple[str, str | None]"]
PARSERS: dict[str, Parser] = {
    ".txt": _parse_text,
    ".md": _parse_text,
    ".json": _parse_json,
    ".jsonl": _parse_jsonl,
    ".csv": _parse_csv,
    ".html": _parse_html,
    ".htm": _parse_html,
}


def register_parser(ext: str, parser: Parser) -> None:
    """Add or replace the parser for one extension (e.g. ".xml")."""
    ext = ext.lower()
    if not ext.startswith("."):
        ext = "." + ext
    PARSERS[ext] = parser


def supported_extensions() -> list[str]:
    return sorted(PARSERS)


def _decode(data: bytes) -> str | None:
    for enc in ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


# ---------------------------------------------------------------- walk


def load_documents(root, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[list[Document], list[dict]]:
    """Return (documents, skipped). skipped entries are {"path": <relative>, "reason": <str>}."""
    root = os.fspath(root)
    if not os.path.isdir(root):
        raise InputError(f"입력 폴더가 없거나 폴더가 아닙니다: {root}")
    real_root = os.path.realpath(root)
    docs: list[Document] = []
    skipped: list[dict] = []
    collections: dict[str, dict] = {}

    def collection_for(dirpath: str) -> dict:
        if dirpath not in collections:
            collections[dirpath] = read_collection(dirpath, real_root, max_bytes)
        return collections[dirpath]

    def skip(path: str, reason: str) -> None:
        rel = _rel(root, path)
        skipped.append({"path": rel, "reason": reason})
        if reason in ("permission denied", "unreadable", "outside root"):
            log.warning("skipped %s: %s", rel, reason)
        else:
            log.info("skipped %s: %s", rel, reason)

    def on_error(err: OSError) -> None:
        path = err.filename or root
        reason = "permission denied" if isinstance(err, PermissionError) else "unreadable"
        skip(path, reason)

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=on_error, followlinks=False):
        keep = []
        for d in sorted(dirnames):
            full = os.path.join(dirpath, d)
            try:
                st = os.lstat(full)
            except PermissionError:
                skip(full, "permission denied")
                continue
            except OSError:
                skip(full, "unreadable")
                continue
            if stat.S_ISLNK(st.st_mode):
                skip(full, "symlink")
            elif not _inside(real_root, full):
                skip(full, "outside root")
            else:
                keep.append(d)
        dirnames[:] = keep

        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            doc = _load_file(full, root, real_root, max_bytes, skip, collection_for)
            if doc is not None:
                docs.append(doc)
    return docs, skipped


def _read_regular(full: str, real_root: str, max_bytes: int) -> bytes | None:
    """Bytes of a regular, non-symlinked file inside the root and not over max_bytes, else None (never raises)."""
    try:
        st = os.lstat(full)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or not _inside(real_root, full) or st.st_size > max_bytes:
        return None
    try:
        fd = os.open(full, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError:
        return None
    return data if len(data) <= max_bytes else None


def read_collection(dirpath: str, real_root: str, max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    """The flat object in `<dirpath>/_collection.json`, or {} if it is missing, unreadable or not an object."""
    data = _read_regular(os.path.join(dirpath, COLLECTION_FILE), real_root, max_bytes)
    raw = _decode(data) if data is not None else None
    if raw is None:
        return {}
    try:
        obj = json.loads(raw)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _excluded_reason(rel: str) -> str | None:
    if THEME_PACK_DIR in rel.split("/"):
        return "theme pack"
    if rel.rsplit("/", 1)[-1] == COLLECTION_FILE:
        return "collection defaults"
    return None


def _load_file(full, root, real_root, max_bytes, skip, collection_for=None) -> Document | None:
    reason = _excluded_reason(_rel(root, full))
    if reason is not None:
        skip(full, reason)
        return None
    try:
        st = os.lstat(full)
    except PermissionError:
        skip(full, "permission denied")
        return None
    except OSError:
        skip(full, "unreadable")
        return None
    if stat.S_ISLNK(st.st_mode):
        skip(full, "symlink")
        return None
    if not stat.S_ISREG(st.st_mode):
        skip(full, "not a regular file")
        return None
    if not _inside(real_root, full):
        skip(full, "outside root")
        return None
    ext = os.path.splitext(full)[1].lower()
    if ext not in PARSERS:
        skip(full, "unsupported")
        return None
    if st.st_size > max_bytes:
        skip(full, "too large")
        return None
    try:
        # O_NOFOLLOW closes the race between lstat and open on platforms that have it.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(full, flags)
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(max_bytes + 1)
    except PermissionError:
        skip(full, "permission denied")
        return None
    except OSError:
        skip(full, "unreadable")
        return None
    raw = _decode(data)
    if raw is None:
        skip(full, "undecodable")
        return None
    front_matter: dict = {}
    if ext == ".md":
        front_matter, raw = parse_front_matter(raw, source=_rel(root, full))
    text, title = PARSERS[ext](raw)
    if not text.strip():
        skip(full, "empty")
        return None
    collection = collection_for(os.path.dirname(full)) if collection_for else {}
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    return Document(
        source=_rel(root, full),
        text=text,
        title=document_title(front_matter) or title or Path(full).name,
        mtime=mtime,
        fmt=ext.lstrip("."),
        meta=resolve_source_meta(front_matter, collection),
    )
