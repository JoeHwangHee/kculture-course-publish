"""request_publish: one POST of the course to a GitHub issue; returns only the attempt result (spec 2.4, 4.2).

The tool reads no environment variable and adds no auth header (the loop's Deps.http_post_json does).
Waiting for approval, resending and publish.json belong to the loop. Response bodies and headers are never
put in `data` or `error`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from common.schema import (
    GITHUB_ISSUES_URL,
    KIND_BLOCKED_BY_POLICY,
    KIND_CREATED,
    KIND_HTTP_ERROR,
    KIND_NETWORK_ERROR,
)
from common.tooling import (
    HTTP_ERROR_NETWORK,
    HTTP_ERROR_TUNNEL_403,
    POLICY_DENIED_MARKER,
    Deps,
    RunContext,
    ToolResult,
    ToolSpec,
)
from tools.course import render_course_md

_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_HTML_URL = re.compile(r'"html_url"\s*:\s*"([^"]+)"')
DEFAULT_TITLE_PREFIX = "K-콘텐츠 배경지 코스: "


def _issue_url(body: Any) -> str | None:
    """Top-level `html_url` of a 201 body. If the body does not parse (cut at 4KB), the first `"html_url"` value
    holding "/issues/" (the response also has `user.html_url`, a profile link); else None."""
    if not isinstance(body, str) or not body:
        return None
    try:
        obj = json.loads(body)
    except (ValueError, TypeError):
        for match in _HTML_URL.finditer(body):
            if "/issues/" in match.group(1):
                return match.group(1)
        return None
    if isinstance(obj, dict) and isinstance(obj.get("html_url"), str):
        return obj["html_url"]
    return None


def run_request_publish(args: dict[str, Any], ctx: RunContext, deps: Deps) -> ToolResult:
    course = ctx.course
    if not isinstance(course, dict) or not course:
        return ToolResult.tool_error("저장된 코스가 없음(save_course 먼저)")
    repo = ctx.publish_repo
    if not isinstance(repo, str) or not _REPO.fullmatch(repo) or ".." in repo:
        return ToolResult.tool_error("게시 저장소가 owner/repo 모양이 아님")

    goal = course.get("goal") if isinstance(course.get("goal"), dict) else {}
    work = goal.get("work") or "이름 없는 작품"
    title = args.get("title") if isinstance(args.get("title"), str) else ""
    title = title.strip() or f"{DEFAULT_TITLE_PREFIX}{work}"
    try:
        summary = render_course_md(course, deps, ctx)
    except Exception as exc:  # noqa: BLE001 - one-line tool error instead of a crash
        return ToolResult.tool_error(f"게시 본문을 만들지 못함: {type(exc).__name__}")

    url = GITHUB_ISSUES_URL.format(repo=repo)
    headers = {"Accept": "application/vnd.github+json"}
    response = deps.http_post_json(url, headers, {"title": title, "body": summary})
    if not isinstance(response, dict):
        response = {}

    status = response.get("status")
    if isinstance(status, bool) or not isinstance(status, int):
        status = None
    error = response.get("error")
    body = response.get("body")
    body = body if isinstance(body, str) else ""

    def result(kind: str, message: str, issue_url: str | None = None) -> ToolResult:
        return ToolResult(ok=kind == KIND_CREATED, kind=kind,
                          data={"http_status": status, "issue_url": issue_url}, error=message)

    if error == HTTP_ERROR_TUNNEL_403:
        return result(KIND_BLOCKED_BY_POLICY, "게시 요청이 정책에 막힘")
    if error == HTTP_ERROR_NETWORK or error is not None or status is None:
        return result(KIND_NETWORK_ERROR, "게시 요청 연결 실패")
    if status == 403 and POLICY_DENIED_MARKER in body:
        return result(KIND_BLOCKED_BY_POLICY, "게시 요청이 정책에 막힘")
    if status == 201:
        return result(KIND_CREATED, "", _issue_url(body))
    return result(KIND_HTTP_ERROR, f"HTTP {status}")


SPECS = [
    ToolSpec(name="request_publish", run=run_request_publish,
             description="저장한 코스를 GitHub 이슈로 한 번 보내고 결과 종류만 돌려준다"),
]
