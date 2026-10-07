"""Publish attempts and the approval wait (spec 2.4).

One attempt = one call of the registered `request_publish` tool. A policy block is a fact to record: the loop waits
for the human approval and resends every PUBLISH_RETRY_INTERVAL_SECONDS for at most APPROVAL_WAIT_SECONDS. At most
one issue per run: nothing is sent after a CREATED attempt.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

from common import limits
from common.schema import (
    COURSE_JSON,
    EVENT_APPROVAL_WAIT,
    EVENT_FINAL,
    EVENT_PUBLISH_ATTEMPT,
    KIND_BLOCKED_BY_POLICY,
    KIND_CREATED,
    ModelCalls,
    PUBLISH_ATTEMPT_RESULTS,
    PUBLISH_JSON,
    PUBLISH_TARGET,
    RUN_JSON,
    STATUS_PUBLISH_FAILED,
    STATUS_PUBLISH_PENDING_APPROVAL,
    STATUS_PUBLISHED,
    TRACE_JSONL,
    PublishAttempt,
    PublishRecord,
    RunRecord,
    Tokens,
    SchemaError,
    is_run_id,
    utc_ts,
)
from common.tooling import RunContext, ToolResult

from loop import files
from loop.budget import Budget
from loop.trace import TraceWriter

PUBLISH_TOOL = "request_publish"

# publish_run exit codes (조정값)
EXIT_PUBLISHED = 0
EXIT_ALREADY_CREATED = 1
EXIT_USAGE = 2
EXIT_NOT_PUBLISHED = 3


@dataclass
class PublishOutcome:
    """status: PUBLISHED / PUBLISH_PENDING_APPROVAL / PUBLISH_FAILED, or None when the tool gave a non-publish
    result (`tool_result`, e.g. TOOL_ERROR for a missing course or repo: a re-plan matter for the executor)."""

    status: str | None
    attempts: list[PublishAttempt] = field(default_factory=list)
    issue_url: str | None = None
    tool_result: ToolResult | None = None


# An absolute-path-shaped token: "/" not preceded by a word char, ":", "/" or "." (so URLs stay), up to a space or
# a closing quote / bracket.
_ABS_PATH_RE = re.compile(r"(?<![\w:/.])/[^\s'\"`,;()\[\]{}<>]+")
SANDBOX_PREFIX = "/hackathon"
MASK = "<경로>"


def mask_local_paths(text: str) -> str:
    """Replace absolute-path-shaped tokens outside /hackathon/ with <경로> (tool errors may carry local paths)."""
    def sub(m: re.Match) -> str:
        token = m.group(0)
        if token == SANDBOX_PREFIX or token.startswith(SANDBOX_PREFIX + "/"):
            return token
        return MASK

    return _ABS_PATH_RE.sub(sub, str(text or ""))


def status_from_attempts(attempts: list[PublishAttempt]) -> str | None:
    """Publish status implied by the last attempt (used when sending stopped on an exception)."""
    if not attempts:
        return None
    last = attempts[-1].result
    if last == KIND_CREATED:
        return STATUS_PUBLISHED
    if last == KIND_BLOCKED_BY_POLICY:
        return STATUS_PUBLISH_PENDING_APPROVAL
    return STATUS_PUBLISH_FAILED


def _attempt_summary(result: ToolResult) -> str:
    status = result.data.get("http_status") if isinstance(result.data, dict) else None
    if result.kind == KIND_BLOCKED_BY_POLICY:
        return "정책 차단" + (f" (HTTP {status})" if isinstance(status, int) else "")
    if isinstance(status, int):
        return f"HTTP {status}"
    return result.kind


def _http_status(result: ToolResult) -> int | None:
    v = result.data.get("http_status") if isinstance(result.data, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def attempt_with_wait(args: dict[str, Any], ctx: RunContext, deps, *, registry, trace, budget, sleep, clock,
                      now, why: str = "", outcome: PublishOutcome | None = None,
                      wait_limit_s: int = limits.APPROVAL_WAIT_SECONDS) -> PublishOutcome:
    """Send once; on BLOCKED_BY_POLICY wait for approval (resending) up to APPROVAL_WAIT_SECONDS.

    The wait is excluded from run time (budget.pause/resume) and resends are not tool steps.
    Pass `outcome` to keep the attempts made so far if an exception escapes.
    `wait_limit_s` (env KCULTURE_APPROVAL_WAIT_S, 0..180): a resend happens only if it fits in the limit; below one
    interval there is no wait at all.
    """
    tool = registry.get(PUBLISH_TOOL)
    outcome = outcome if outcome is not None else PublishOutcome(status=None)

    def send() -> ToolResult | None:
        result = tool.run(args, ctx, deps)
        if result.kind not in PUBLISH_ATTEMPT_RESULTS:
            trace.append(EVENT_PUBLISH_ATTEMPT, tool=PUBLISH_TOOL, args=args, kind=result.kind,
                         summary=mask_local_paths(result.error or result.kind), why=why)
            outcome.tool_result = result
            return None
        outcome.attempts.append(PublishAttempt(ts=utc_ts(now()), result=result.kind, http_status=_http_status(result)))
        if result.kind == KIND_CREATED:  # keep the URL at once, so a later exception cannot lose it
            url = result.data.get("issue_url") if isinstance(result.data, dict) else None
            outcome.issue_url = url if isinstance(url, str) else None
        trace.append(EVENT_PUBLISH_ATTEMPT, tool=PUBLISH_TOOL, args=args, kind=result.kind,
                     summary=_attempt_summary(result), why=why)
        return result

    result = send()
    if result is None:
        return outcome
    if result.kind == KIND_BLOCKED_BY_POLICY:
        budget.pause()
        try:
            start = clock()
            interval = limits.PUBLISH_RETRY_INTERVAL_SECONDS
            first = True
            if wait_limit_s < interval:
                trace.append(EVENT_APPROVAL_WAIT, tool=PUBLISH_TOOL, args={"wait_limit_s": wait_limit_s},
                             kind=KIND_BLOCKED_BY_POLICY, summary=f"승인 대기 한도 {wait_limit_s}초: 기다리지 않음",
                             why="코드 규칙: 대기 한도가 다시 보내는 간격보다 짧음")
            while result.kind == KIND_BLOCKED_BY_POLICY:
                waited = clock() - start
                if waited + interval > wait_limit_s:
                    break
                trace.append(EVENT_APPROVAL_WAIT, tool=PUBLISH_TOOL,
                             args={"wait_limit_s": wait_limit_s} if first else {}, kind=KIND_BLOCKED_BY_POLICY,
                             summary=f"승인 대기 {int(waited)}초", why="코드 규칙: 차단되면 승인을 기다리며 다시 보냄")
                first = False
                sleep(interval)
                result = send()
                if result is None:
                    break
        finally:
            budget.resume()
        if result is None:  # a non-publish result while waiting: stop waiting, keep what was sent
            outcome.status = STATUS_PUBLISH_PENDING_APPROVAL
            return outcome
    if result.kind == KIND_CREATED:
        outcome.status = STATUS_PUBLISHED
    elif result.kind == KIND_BLOCKED_BY_POLICY:
        outcome.status = STATUS_PUBLISH_PENDING_APPROVAL
    else:  # HTTP_ERROR / NETWORK_ERROR: no wait
        outcome.status = STATUS_PUBLISH_FAILED
    return outcome


def write_outcome(run_dir: pathlib.Path, ctx: RunContext, outcome: PublishOutcome,
                  prior: list[PublishAttempt] | None = None) -> None:
    """publish.json (attempts appended after `prior`) and course.json `publish` = {"status", "url"}."""
    if outcome.status is None:
        return
    record = PublishRecord(status=outcome.status, target=PUBLISH_TARGET, repo=ctx.publish_repo,
                           attempts=list(prior or []) + list(outcome.attempts), issue_url=outcome.issue_url)
    files.write_publish(run_dir, record)
    info = {"status": outcome.status, "url": outcome.issue_url}
    if isinstance(ctx.course, dict):
        ctx.course["publish"] = dict(info)
    course_path = run_dir / COURSE_JSON
    if course_path.is_file():
        course = files.read_json(course_path)
        if isinstance(course, dict):
            course["publish"] = dict(info)
            files.write_json(course_path, course)


def has_created(run_dir: pathlib.Path) -> bool:
    path = run_dir / PUBLISH_JSON
    if not path.is_file():
        return False
    try:
        data = files.read_json(path)
    except (ValueError, OSError):
        return False  # unreadable publish.json: publish_run rejects it when reading the run
    attempts = data.get("attempts") if isinstance(data, dict) else None
    if not isinstance(attempts, list):
        return False
    return any(isinstance(a, dict) and a.get("result") == KIND_CREATED for a in attempts)


def publish_run(run_id: str, *, output_root, registry, deps, sleep, clock, now, publish_repo: str = "",
                title: str = "", approval_wait_s: int = limits.APPROVAL_WAIT_SECONDS) -> tuple[int, str]:
    """`python -m loop publish --run <run_id>`. Returns (exit code, status).

    Exit codes (조정값): 0 PUBLISHED, 1 a CREATED attempt already exists (nothing sent), 2 usage / no run folder or
    course.json, 3 sent but not published (approval timeout or failure).
    """
    if not is_run_id(run_id):
        return EXIT_USAGE, ""
    run_dir = pathlib.Path(output_root) / run_id
    if not run_dir.is_dir() or not (run_dir / COURSE_JSON).is_file() or not (run_dir / RUN_JSON).is_file():
        return EXIT_USAGE, ""
    if has_created(run_dir):
        return EXIT_ALREADY_CREATED, STATUS_PUBLISHED
    try:
        run_data = files.read_json(run_dir / RUN_JSON)
        if not isinstance(run_data, dict):
            return EXIT_USAGE, ""
        # Check the other keys with the common record; model_calls / tokens ({"router", "nemotron"}, 0010) are kept
        # as they are and never rewritten from the record.
        run = RunRecord.from_dict({**run_data, "model_calls": ModelCalls().to_dict(), "tokens": Tokens().to_dict()})
        course = files.read_json(run_dir / COURSE_JSON)
        prior = []
        if (run_dir / PUBLISH_JSON).is_file():
            prior = PublishRecord.from_dict(files.read_json(run_dir / PUBLISH_JSON)).attempts
    except (SchemaError, ValueError, OSError):
        return EXIT_USAGE, ""
    if not isinstance(course, dict):
        return EXIT_USAGE, ""
    try:
        trace = TraceWriter(run_dir / TRACE_JSONL, run_id, now=now)
    except (SchemaError, ValueError, OSError):
        return EXIT_USAGE, ""
    goal = course.get("goal") if isinstance(course.get("goal"), dict) else {}
    ctx = RunContext(run_id=run_id, request=run.request, run_dir=str(run_dir.resolve()), publish_repo=publish_repo,
                     goal=dict(goal), course=course)
    budget = Budget(clock=clock)
    outcome = PublishOutcome(status=None)
    error = ""
    try:
        args = registry.with_defaults(PUBLISH_TOOL, {"title": title} if title else {})
        attempt_with_wait(args, ctx, deps, registry=registry, trace=trace, budget=budget, sleep=sleep, clock=clock,
                          now=now, why="사람 명령: 나중에 게시", outcome=outcome, wait_limit_s=approval_wait_s)
    except Exception as exc:  # keep what was sent; never end with 1 (that means "already CREATED")
        error = type(exc).__name__
        outcome.status = status_from_attempts(outcome.attempts)
    try:
        write_outcome(run_dir, ctx, outcome, prior)
        status = outcome.status or run.status
        if error:
            summary = f"게시 중 예외: {error}"
        elif outcome.status is None:
            reason = outcome.tool_result.error if outcome.tool_result else ""
            summary = mask_local_paths(f"게시 요청 못 함: {reason}".strip())
        else:
            summary = f"{status}" + (f" {outcome.issue_url}" if outcome.issue_url else "")
        trace.append(EVENT_FINAL, kind=status, summary=summary, why="코드 규칙: 나중에 게시 끝")
        run_data["status"] = status
        run_data["ended_at"] = utc_ts(now())
        files.write_json(run_dir / RUN_JSON, run_data)
        run_data["files"] = files.list_run_files(run_dir)
        files.write_json(run_dir / RUN_JSON, run_data)
    except Exception:
        return EXIT_NOT_PUBLISHED, outcome.status or run.status
    if error:
        return EXIT_NOT_PUBLISHED, status
    return (EXIT_PUBLISHED if status == STATUS_PUBLISHED else EXIT_NOT_PUBLISHED), status
