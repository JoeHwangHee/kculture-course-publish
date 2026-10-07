"""list_input and read_file: reading under /hackathon/ through `Deps.read_path` (spec 2.2, 2.5, 5).

- read_file never asks `read_path` for a path outside /hackathon/ (OUT_OF_SCOPE without opening it).
- restricted / secrets are not filtered by the app: the sandbox refuses them (DENIED_BY_SANDBOX).
"""

from __future__ import annotations

import codecs
import posixpath
from datetime import date
import re
from typing import Any

from common.limits import READ_FILE_MAX_BYTES
from common.schema import (
    HACKATHON_DIR,
    INPUT_DIR,
    KIND_DENIED_BY_SANDBOX,
    KIND_NOT_FOUND,
    KIND_NOT_TEXT,
    KIND_OK,
    KIND_OUT_OF_SCOPE,
    KIND_TOO_LARGE,
    KIND_TOOL_ERROR,
    TEXT_DENIED_BY_SANDBOX,
)
from common.tooling import Deps, RunContext, ToolResult, ToolSpec
from tools._shared import add_unique, shown

# ctx.read_files kinds besides the ToolResult kinds below
READ_KIND_FILE = "file"
READ_KIND_DIR = "dir"

_DATE = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"
    r"|(?<!\d)(\d{4})\.(\d{1,2})\.(\d{1,2})(?!\d)"
    r"|(?<!\d)(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일"
)


# ---------------------------------------------------------------- text helpers


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [v.strip() for v in inner.split(",") if v.strip()] if inner else []
    return raw


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """(front matter, body). Front matter is the leading `---` ... `---` block of `key: value` lines; else {}."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, Any] = {}
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:])
        if ":" in line:
            key, _, value = line.partition(":")
            if key.strip():
                meta[key.strip()] = _parse_value(value)
    return {}, text  # no closing line: not front matter


def extract_dates(text: str) -> list[str]:
    """Dates in text as YYYY-MM-DD, in order of appearance, without duplicates. Impossible dates are skipped."""
    out: list[str] = []
    for m in _DATE.finditer(text):
        groups = [g for g in m.groups() if g is not None]
        year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
        try:
            date(year, month, day)
        except ValueError:
            continue
        value = f"{year:04d}-{month:02d}-{day:02d}"
        if value not in out:
            out.append(value)
    return out


def _decode(data: bytes, truncated: bool) -> str | None:
    """UTF-8 text, or None if it is not text. A cut file may end in a partial character; that tail is dropped."""
    if b"\x00" in data:
        return None
    decoder = codecs.getincrementaldecoder("utf-8-sig")()  # drops a leading BOM
    try:
        return decoder.decode(data, final=not truncated)
    except UnicodeDecodeError:
        return None


def _is_out_of_scope(exc: BaseException) -> bool:
    """read_path refused a path whose real location is outside /hackathon (the loop's error carries `kind`)."""
    return getattr(exc, "kind", None) == KIND_OUT_OF_SCOPE


def _in_scope(path: str) -> bool:
    return path == HACKATHON_DIR or path.startswith(HACKATHON_DIR + "/")


def _record(kind: str, text: str = "", front_matter: dict | None = None, dates: list | None = None,
            entries: list | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "text": text,
        "front_matter": front_matter or {},
        "dates": dates or [],
        "entries": entries or [],
    }


def _data(path: str, kind: str, size: int = 0, truncated: bool = False, front_matter: dict | None = None,
          dates: list | None = None, entries: list | None = None) -> dict[str, Any]:
    return {
        "path": path,
        "kind": kind,
        "bytes": size,
        "truncated": truncated,
        "front_matter": front_matter or {},
        "dates": dates or [],
        "entries": entries or [],
    }


# ---------------------------------------------------------------- read_file


def run_read_file(args: dict[str, Any], ctx: RunContext, deps: Deps) -> ToolResult:
    raw = args.get("path")
    if not isinstance(raw, str) or not raw.startswith("/"):
        key = posixpath.normpath(raw) if isinstance(raw, str) and raw else ""
        ctx.read_files[key] = _record(KIND_OUT_OF_SCOPE)
        return ToolResult(ok=False, kind=KIND_OUT_OF_SCOPE, data=_data(key, KIND_OUT_OF_SCOPE),
                          error="/hackathon/ 밖 경로라 열지 않음")
    path = posixpath.normpath(raw)
    if path.startswith("//"):  # posix keeps a leading double slash
        path = "/" + path.lstrip("/")
    if not _in_scope(path):
        ctx.read_files[path] = _record(KIND_OUT_OF_SCOPE)
        return ToolResult(ok=False, kind=KIND_OUT_OF_SCOPE, data=_data(path, KIND_OUT_OF_SCOPE),
                          error="/hackathon/ 밖 경로라 열지 않음")
    if "\x00" in path:
        ctx.read_files[path] = _record(KIND_TOOL_ERROR)
        return ToolResult.tool_error("경로에 NUL 문자가 있음", data=_data(path, KIND_TOOL_ERROR))

    try:
        value = deps.read_path(path, READ_FILE_MAX_BYTES + 1)
    except (OSError, ValueError) as exc:
        if _is_out_of_scope(exc):  # checked before the OS error kinds
            ctx.read_files[path] = _record(KIND_OUT_OF_SCOPE)
            return ToolResult(ok=False, kind=KIND_OUT_OF_SCOPE, data=_data(path, KIND_OUT_OF_SCOPE),
                              error="실제 위치가 /hackathon/ 밖이라 열지 않음")
        if isinstance(exc, PermissionError):
            ctx.read_files[path] = _record(KIND_DENIED_BY_SANDBOX)
            data = _data(path, KIND_DENIED_BY_SANDBOX)
            data["note"] = TEXT_DENIED_BY_SANDBOX
            return ToolResult(ok=False, kind=KIND_DENIED_BY_SANDBOX, data=data, error=TEXT_DENIED_BY_SANDBOX)
        if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
            ctx.read_files[path] = _record(KIND_NOT_FOUND)
            return ToolResult(ok=False, kind=KIND_NOT_FOUND, data=_data(path, KIND_NOT_FOUND), error="경로가 없음")
        ctx.read_files[path] = _record(KIND_TOOL_ERROR)
        return ToolResult.tool_error(f"읽기 실패: {type(exc).__name__}", data=_data(path, KIND_TOOL_ERROR))

    if isinstance(value, list):
        entries = sorted(str(e.get("name", "")) for e in value if isinstance(e, dict))
        ctx.read_files[path] = _record(READ_KIND_DIR, entries=entries)
        return ToolResult(ok=True, kind=KIND_OK, data=_data(path, READ_KIND_DIR, entries=entries))

    if not isinstance(value, (bytes, bytearray)):
        ctx.read_files[path] = _record(KIND_TOOL_ERROR)
        return ToolResult.tool_error("읽기 결과가 폴더도 파일도 아님", data=_data(path, KIND_TOOL_ERROR))

    content = bytes(value)
    truncated = len(content) > READ_FILE_MAX_BYTES
    if truncated:
        content = content[:READ_FILE_MAX_BYTES]
    text = _decode(content, truncated)
    if text is None:
        ctx.read_files[path] = _record(KIND_NOT_TEXT)
        return ToolResult(ok=False, kind=KIND_NOT_TEXT, data=_data(path, KIND_NOT_TEXT, size=len(content),
                                                                     truncated=truncated),
                          error="텍스트 파일이 아님")

    front_matter, body = split_front_matter(text)
    dates = extract_dates(body)
    ctx.read_files[path] = _record(READ_KIND_FILE, text=text, front_matter=front_matter, dates=dates)
    data = _data(path, READ_KIND_FILE, size=len(content), truncated=truncated, front_matter=front_matter,
                 dates=dates)
    if truncated:
        add_unique(ctx.warnings, f"{shown(path)}: TOO_LARGE(앞 {READ_FILE_MAX_BYTES // 1024}KB만 사용)")
        return ToolResult(ok=True, kind=KIND_TOO_LARGE, data=data)
    return ToolResult(ok=True, kind=KIND_OK, data=data)


# ---------------------------------------------------------------- list_input


def _walk(dir_path: str, rel: str, deps: Deps, ctx: RunContext, files: list[dict[str, Any]]) -> None:
    """Add the files under one sub-folder; a sub-folder that cannot be read is skipped with a warning."""
    try:
        value = deps.read_path(dir_path, READ_FILE_MAX_BYTES)
    except (OSError, ValueError) as exc:
        if _is_out_of_scope(exc):
            add_unique(ctx.warnings, f"input/{shown(rel)}: 범위 밖 링크라 건너뜀")
        else:
            add_unique(ctx.warnings, f"input/{shown(rel)}: 폴더를 읽지 못해 건너뜀({type(exc).__name__})")
        return
    if not isinstance(value, list):
        add_unique(ctx.warnings, f"input/{shown(rel)}: 폴더가 아니라 건너뜀")
        return
    _collect(value, dir_path, rel, deps, ctx, files)


def _collect(entries: list, dir_path: str, rel: str, deps: Deps, ctx: RunContext,
             files: list[dict[str, Any]]) -> None:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if not name or name in (".", "..") or "/" in name:
            continue
        child_rel = f"{rel}/{name}" if rel else name
        child_path = f"{dir_path}/{name}"
        if entry.get("is_dir"):
            _walk(child_path, child_rel, deps, ctx, files)
        else:
            size = entry.get("size", 0)
            if isinstance(size, bool) or not isinstance(size, int):
                size = 0
            files.append({"path": child_rel, "size": size})


def run_list_input(args: dict[str, Any], ctx: RunContext, deps: Deps) -> ToolResult:
    ctx.input_files = []
    try:
        value = deps.read_path(INPUT_DIR, READ_FILE_MAX_BYTES)
    except ValueError as exc:
        if _is_out_of_scope(exc):
            return ToolResult(ok=False, kind=KIND_OUT_OF_SCOPE, data={"count": 0, "files": []},
                              error="입력 폴더의 실제 위치가 /hackathon/ 밖임")
        return ToolResult.tool_error(f"입력 폴더 읽기 실패: {type(exc).__name__}", data={"count": 0, "files": []})
    except PermissionError:
        return ToolResult(ok=False, kind=KIND_DENIED_BY_SANDBOX,
                          data={"count": 0, "files": [], "note": TEXT_DENIED_BY_SANDBOX},
                          error=TEXT_DENIED_BY_SANDBOX)
    except (FileNotFoundError, NotADirectoryError):
        return ToolResult(ok=False, kind=KIND_NOT_FOUND, data={"count": 0, "files": []},
                          error="입력 폴더가 없음")
    except OSError as exc:
        return ToolResult.tool_error(f"입력 폴더 읽기 실패: {type(exc).__name__}", data={"count": 0, "files": []})
    if not isinstance(value, list):
        return ToolResult(ok=False, kind=KIND_NOT_FOUND, data={"count": 0, "files": []},
                          error="입력 폴더가 폴더가 아님")

    files: list[dict[str, Any]] = []
    _collect(value, INPUT_DIR, "", deps, ctx, files)
    files.sort(key=lambda f: f["path"])
    ctx.input_files = [dict(f) for f in files]
    return ToolResult.success({"count": len(files), "files": [dict(f) for f in files]})


SPECS = [
    ToolSpec(name="list_input", run=run_list_input,
             description="/hackathon/input 아래 파일 목록(입력 폴더 기준 상대 경로, 크기)을 낸다"),
    ToolSpec(name="read_file", run=run_read_file,
             description="/hackathon/ 아래 경로 하나를 연다: 폴더면 항목 이름, 파일이면 본문(64KB까지)·머리 정보·날짜"),
]
