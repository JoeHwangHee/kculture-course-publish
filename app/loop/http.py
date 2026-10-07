"""Standard-library implementations of Deps.http_post_json, Deps.read_path and Deps.now (spec 4.2, 2.4)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from common import limits
from common.schema import HACKATHON_DIR, KIND_OUT_OF_SCOPE
from common.tooling import HTTP_ERROR_NETWORK, HTTP_ERROR_TUNNEL_403, TUNNEL_403_MARKER

GITHUB_API_PREFIX = "https://api.github.com/"
GITHUB_ACCEPT = "application/vnd.github+json"
GITHUB_API_VERSION = "2022-11-28"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect; urllib then raises HTTPError with the 3xx status."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Default ProxyHandler stays in (inside the sandbox the proxy injects the real token and enforces the policy).
_OPENER = urllib.request.build_opener(_NoRedirect)


def _text(raw: bytes) -> str:
    return (raw or b"")[: limits.HTTP_BODY_MAX_BYTES].decode("utf-8", errors="replace")


def http_post_json(url: str, headers: dict, body: dict, *, opener=None, timeout: float = 30) -> dict:
    """POST `body` as JSON. -> {"status": int|None, "body": first 4KB|"", "error": None|"TUNNEL_403"|"NETWORK"}.

    HTTP errors (and 3xx, never followed) come back as their status; no exception ever leaves this function.
    """
    try:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        for name, value in (headers or {}).items():
            if str(name).lower() == "authorization":
                # Never forwarded if a redirect were ever followed.
                req.add_unredirected_header(name, value)
            else:
                req.add_header(name, value)
        with (opener or _OPENER).open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None)
            if status is None:
                status = resp.getcode()
            raw = resp.read(limits.HTTP_BODY_MAX_BYTES)
        return {"status": int(status), "body": _text(raw), "error": None}
    except urllib.error.HTTPError as e:  # subclass of URLError: must come first
        try:
            raw = e.read(limits.HTTP_BODY_MAX_BYTES) if e.fp is not None else b""
        except Exception:
            raw = b""
        finally:
            try:
                e.close()
            except Exception:
                pass
        return {"status": int(e.code), "body": _text(raw), "error": None}
    except Exception as e:
        message = f"{e} {getattr(e, 'reason', '')}"
        error = HTTP_ERROR_TUNNEL_403 if TUNNEL_403_MARKER in message else HTTP_ERROR_NETWORK
        return {"status": None, "body": "", "error": error}


def make_github_post(token_env: str = "GITHUB_TOKEN", *, post=http_post_json, environ=os.environ):
    """Deps.http_post_json that adds GitHub headers (bearer token from `token_env`, read per call) only for
    https://api.github.com/. Inside the sandbox the token is a placeholder the proxy replaces."""

    def github_post(url: str, headers: dict, body: dict) -> dict:
        merged = dict(headers or {})
        if isinstance(url, str) and url.startswith(GITHUB_API_PREFIX):
            merged["Accept"] = GITHUB_ACCEPT
            merged["X-GitHub-Api-Version"] = GITHUB_API_VERSION
            token = (environ.get(token_env) or "").strip()
            if token:
                merged["Authorization"] = f"Bearer {token}"
        return post(url, merged, body)

    return github_post


class OutOfScopePath(ValueError):
    """The real path (symlinks resolved) is outside the allowed root; nothing was opened."""

    kind = KIND_OUT_OF_SCOPE


def _inside(real: str, real_root: str) -> bool:
    # Compare on separator boundaries so "/hackathonX" is not inside "/hackathon".
    return real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep)


def read_path(path: str, max_bytes: int, *, root: str = HACKATHON_DIR):
    """Folder -> [{"name", "is_dir", "size"}] sorted by name; file -> its first `max_bytes` bytes.

    The real path (symlinks and ".." resolved) must be `root` or under it, else OutOfScopePath and nothing is
    opened. OS errors (PermissionError from Landlock, FileNotFoundError, ...) propagate."""
    real = os.path.realpath(path)
    if not _inside(real, os.path.realpath(root)):
        raise OutOfScopePath("허용된 폴더 밖의 경로라 열지 않습니다")
    if os.path.isdir(real):
        entries = []
        with os.scandir(real) as it:
            for entry in it:
                is_dir = entry.is_dir(follow_symlinks=False)
                size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
                entries.append({"name": entry.name, "is_dir": is_dir, "size": size})
        return sorted(entries, key=lambda e: e["name"])
    with open(real, "rb") as fh:
        return fh.read(max_bytes)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
