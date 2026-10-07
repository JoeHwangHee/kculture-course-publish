"""Source metadata of reference files (spec 4.3, 4.7) and the input fingerprint.

Fill order for every chunk's source keys (`common.schema.CHUNK_SOURCE_KEYS`), decided key by key:
1. the Markdown front matter (`.md` only),
2. the `_collection.json` in the same folder as the file (a flat JSON object, same key names),
3. defaults: `source_type=informal`, `kind=other`; keys the contract gives no default get "" (lists: []).

Value forms (front matter values are parsed by `parse_front_matter`, JSON notation first): list keys (`about`,
`place_ids`) take a list as is and a plain string as a one-item list; every other key (`title`, `hours`,
`closed`, ...) turns a list into its items joined with ", ".
An empty value (empty or blank string, `[]`, empty list, a value that is neither a string nor a list of strings)
counts as "no value" and falls through to the next step. A non-empty but invalid value does not fall through;
it is normalized: unknown `source_type` -> `informal`, unknown `kind` -> `other`, `published` not a real
`YYYY-MM-DD` date -> "", `provenance` not in `real|synthetic` -> "" (never invented).
The operating keys (`place_ids`, `hours`, `closed`) exist only when the resolved kind is `operating`.
Front matter keys outside the contract are kept by `parse_front_matter` but never reach chunks.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import stat

from common.schema import (
    CHUNK_OPERATING_KEYS,
    CHUNK_SOURCE_KEYS,
    DEFAULT_SOURCE_KIND,
    PROVENANCES,
    SOURCE_KINDS,
    normalize_source_type,
)

COLLECTION_FILE = "_collection.json"
THEME_PACK_DIR = "theme_packs"
FRONT_MATTER_FENCE = "---"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LIST_KEYS = ("about", "place_ids")

log = logging.getLogger("retrieval")


def parse_front_matter_value(value: str) -> str | list[str]:
    """One front matter value (already stripped) -> string or list of strings.

    1. Starts with `"`: try `json.loads`; a string result is used (`"official"` -> official).
    2. Starts with `[` and ends with `]`: try `json.loads`; a list of strings is used, items stripped and
       empty items dropped (`["a, b", "c"]` -> ["a, b", "c"]).
    3. Otherwise (or when the JSON attempt fails or gives another shape): a value starting with `[` and ending
       with `]` is split on commas between the outer brackets, items stripped, empty items dropped
       (`[]` -> []); anything else stays the string as written (`"abc` keeps its quote).
       So an unquoted `[공지] 변경 [최종]` becomes ["공지] 변경 [최종"]; write such titles as JSON strings.
    """
    if value.startswith('"'):
        try:
            loaded = json.loads(value)
        except (ValueError, RecursionError):
            loaded = None
        if isinstance(loaded, str):
            return loaded
    if value.startswith("[") and value.endswith("]"):
        try:
            loaded = json.loads(value)
        except (ValueError, RecursionError):
            loaded = None
        if isinstance(loaded, list) and all(isinstance(v, str) for v in loaded):
            return [v.strip() for v in loaded if v.strip()]
    if value.startswith("[") and value.endswith("]"):
        return [item.strip() for item in value[1:-1].split(",") if item.strip()]
    return value


def parse_front_matter(text: str, source: str | None = None) -> tuple[dict, str]:
    """Split `---` front matter from the body: returns (meta: dict[str, str | list[str]], body: str).

    The first line must be exactly `---`; meta runs to the next line that is `---` after trailing whitespace is
    stripped. Each line is `key: value`, split at the first `:`, both sides stripped (lines without `:` or with
    an empty key are ignored, a repeated key keeps the last value). Each value is read by
    `parse_front_matter_value` (JSON notation first, then `[a, b]` lists, else the string as written).
    All keys are returned, including keys outside the contract. Without front matter, or without the closing
    line (logged as a warning naming `source`, the file's relative path, when given), returns ({}, text)
    unchanged. Line ends may be `\\n` or `\\r\\n`.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != FRONT_MATTER_FENCE:
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].rstrip() == FRONT_MATTER_FENCE:
            break
    else:
        where = f"{source}: " if source else ""
        log.warning("%sfront matter has no closing '---' line; read without front matter", where)
        return {}, text
    meta: dict = {}
    for raw in lines[1:end]:
        key, sep, value = raw.rstrip("\r\n").partition(":")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        meta[key] = parse_front_matter_value(value)
    return meta, "".join(lines[end + 1:])


def _as_list(value) -> list[str]:
    """A list -> its non-empty strings, stripped; a non-empty string -> one-item list; anything else -> []."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [v.strip() for v in value if isinstance(v, str) and v.strip()]
    return []


def _as_str(value) -> str:
    """A string, stripped; a list becomes its items joined with ", "; anything else counts as no value."""
    if isinstance(value, list):
        return ", ".join(_as_list(value))
    return value.strip() if isinstance(value, str) else ""


def _real_date(value: str) -> str:
    if not _DATE.match(value):
        return ""
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return ""
    return value


def _pick(key: str, layers: tuple[dict, ...]):
    conv = _as_list if key in _LIST_KEYS else _as_str
    for layer in layers:
        value = conv(layer.get(key))
        if value:
            return value
    return conv(None)


def resolve_source_meta(front_matter: dict | None, collection: dict | None) -> dict:
    """Source keys of one file: front matter > collection defaults > defaults (see module docstring)."""
    layers = (front_matter or {}, collection or {})
    kind = _pick("kind", layers)
    kind = kind if kind in SOURCE_KINDS else DEFAULT_SOURCE_KIND
    published = _pick("published", layers)
    provenance = _pick("provenance", layers)
    normalized = {
        "source_type": normalize_source_type(_pick("source_type", layers)),
        "published": _real_date(published),
        "provenance": provenance if provenance in PROVENANCES else "",
        "kind": kind,
    }
    out = {key: normalized[key] if key in normalized else _pick(key, layers) for key in CHUNK_SOURCE_KEYS}
    if kind == "operating":
        for key in CHUNK_OPERATING_KEYS:
            out[key] = _pick(key, layers)
    return out


def document_title(front_matter: dict | None) -> str:
    """The front matter `title` (a list is joined with ", ") or ""; collection defaults never give a title."""
    return _as_str((front_matter or {}).get("title"))


# ---------------------------------------------------------------- input fingerprint


def _inside(real_root: str, path: str) -> bool:
    try:
        return os.path.commonpath([real_root, os.path.realpath(path)]) == real_root
    except ValueError:
        return False


def _hash_file(path: str) -> tuple[int, str] | None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as fh:
            h = hashlib.sha256()
            size = 0
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
                size += len(block)
    except OSError:
        return None
    return size, h.hexdigest()


def source_fingerprint(root) -> str:
    """sha256 hex identifying the input folder's content (manifest `source_fingerprint`).

    Definition: for every regular file under `root` (theme packs, `_collection.json` and unsupported formats
    included), make the line f"{relative path}\\t{size in bytes}\\t{sha256 hex of the bytes}\\n", where the
    relative path is from `root` and `/`-separated. Sort the lines by relative path, join them, and take the
    sha256 hex of the UTF-8 bytes. Modification times are not part of it.
    Same safety rules as the loader: symlinked files and folders are not followed and not counted, anything
    whose real path is outside the real root is not counted, and files or folders that cannot be read
    (permission or OS errors) are left out instead of raising.
    """
    root = os.fspath(root)
    real_root = os.path.realpath(root)
    entries: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None, followlinks=False):
        keep = []
        for d in sorted(dirnames):
            full = os.path.join(dirpath, d)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISLNK(st.st_mode) and _inside(real_root, full):
                keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or not _inside(real_root, full):
                continue
            hashed = _hash_file(full)
            if hashed is None:
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            entries.append((rel, f"{rel}\t{hashed[0]}\t{hashed[1]}\n"))
    entries.sort(key=lambda e: e[0])
    return hashlib.sha256("".join(line for _, line in entries).encode("utf-8")).hexdigest()
