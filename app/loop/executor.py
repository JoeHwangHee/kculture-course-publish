"""Heavy path (spec 2.2): list_input, plan (Nemotron), plan check, run steps in code, one re-plan, publish, answer.

The model never calls a tool. The code runs the checked steps in order through the registry; tools pass data
through RunContext keys.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any

from common import limits
from common.schema import (
    EVENT_PLAN,
    EVENT_PLAN_CHECK,
    EVENT_REPLAN,
    EVENT_STEP,
    KIND_DENIED_BY_SANDBOX,
    KIND_NOT_FOUND,
    KIND_NOT_TEXT,
    KIND_OK,
    KIND_OUT_OF_SCOPE,
    KIND_TOOL_ERROR,
    ROUTE_HEAVY,
    STATUS_ANSWERED_HEAVY,
    STATUS_COURSE_SAVED,
    STATUS_FAILED,
    TEXT_DENIED_BY_SANDBOX,
    TEXT_NO_EVIDENCE,
    TEXT_NO_PLACES_FOR_WORK,
    TEXT_USER_SAID_DO_NOT_SEND,
    AnswerRecord,
    Conflict,
    OriginClaim,
    PlanStep,
    ReadFileRef,
    SchemaError,
)
from common.tooling import RunContext, ToolResult

from loop import files, publish
from loop.budget import LimitHit
from loop.planner import (
    PLAN_RESPONSE_FORMAT,
    WHY_REQUIRED_STEP,
    build_plan_messages,
    build_replan_messages,
    fill_course_steps,
    move_evidence_steps,
    parse_and_check,
)

PUBLISH_TOOL = publish.PUBLISH_TOOL
LIST_INPUT = "list_input"
WHY_CODE_RULE = "코드 규칙"
WHY_LIST_INPUT = "코드 규칙: 계획 전 입력 목록"
WHY_AUTO_PUBLISH = "코드 규칙: 코스를 만든 실행은 마지막에 게시 요청"
TEXT_NOTHING_FOUND = "자료에서 답을 찾지 못함"
READ_KIND_TEXT = {KIND_NOT_FOUND: "없음", KIND_OUT_OF_SCOPE: "범위 밖 경로(열지 않음)", KIND_NOT_TEXT: "텍스트 파일이 아님"}
SAVE_COURSE = "save_course"
TEXT_CUT_ANSWER = "모델 답이 출력 한도에서 잘림"
TEXT_CUT_ANSWER_REASON = "length"
TEXT_ALREADY_PUBLISHED = "이 실행의 게시 요청은 이미 끝남(다시 보내지 않음)"


def one_line(text: Any, limit: int = 300) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


@dataclass
class HeavyOutcome:
    status: str
    text: str  # screen summary
    reason: str = ""  # one line for FAILED


class _Failed(Exception):
    """End the heavy run as FAILED with a one-line reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _result_summary(result: ToolResult) -> str:
    """Short summary without free strings from `data` (they may hold local paths)."""
    if result.error:
        return one_line(publish.mask_local_paths(result.error))
    parts = [result.kind]
    for k, v in (result.data or {}).items():
        if isinstance(v, bool) or isinstance(v, int):
            parts.append(f"{k}={v}")
        elif isinstance(v, (list, dict)):
            parts.append(f"{k}={len(v)}개")
    return one_line(" ".join(parts))


def _plan_size_problems(plan, registry) -> list[str]:
    """Checks again after the course fill: step count and the filled steps' tools."""
    problems = []
    if len(plan.steps) > limits.PLAN_STEPS_MAX:
        problems.append(f"채운 뒤 단계 수 {len(plan.steps)}가 한도 {limits.PLAN_STEPS_MAX}를 넘음")
    for step in plan.steps:
        if step.why == WHY_REQUIRED_STEP:
            problems.extend(f"{step.id}: {p}" for p in registry.check_args(step.tool, step.args))
    return problems


def _filled_note(filled: list[str], shown: int = 6) -> str:
    if not filled:
        return ""
    names = ", ".join(filled[:shown]) + (f" 외 {len(filled) - shown}개" if len(filled) > shown else "")
    return f"; 기본값 채움: {names}"


class HeavyRun:
    def __init__(self, ctx: RunContext, *, registry, deps, nemotron_chat, budget, trace, sleep, clock, now,
                 run_dir: pathlib.Path, approval_wait_s: int = limits.APPROVAL_WAIT_SECONDS):
        self.ctx = ctx
        self.approval_wait_s = approval_wait_s
        self.registry = registry
        self.deps = deps
        self.chat = nemotron_chat
        self.budget = budget
        self.trace = trace
        self.sleep = sleep
        self.clock = clock
        self.now = now
        self.run_dir = pathlib.Path(run_dir)
        # One re-plan per run, shared by a failed plan check and a TOOL_ERROR (조정값 해석 of 2.2 / limits).
        self.replans_left = limits.REPLANS_PER_RUN
        self.executed: list[dict[str, Any]] = []
        self.publish_outcome: publish.PublishOutcome | None = None
        self.publish_done = False  # one publish procedure per run; never resend after CREATED
        self.base_messages: list[dict] = []

    # ------------------------------------------------------------ helpers

    def _mark(self) -> tuple[int, int]:
        return len(self.budget.call_log), len(self.budget.limits_hit)

    def _model_since(self, mark: tuple[int, int]):
        return self.budget.call_log[-1] if len(self.budget.call_log) > mark[0] else None

    def _cut_note(self, mark: tuple[int, int], where: str) -> str:
        """0025: a model answer cut at max_tokens (finish_reason "length") since `mark` -> trace note + warning."""
        reasons = getattr(self.budget, "finish_reasons", [])[mark[0]:]
        if TEXT_CUT_ANSWER_REASON not in reasons:
            return ""
        warning = f"{where}: {TEXT_CUT_ANSWER}"
        if warning not in self.budget.warnings:
            self.budget.warnings.append(warning)
        return f"; {TEXT_CUT_ANSWER}"

    def _raise_if_limit(self, mark: tuple[int, int]) -> None:
        # A real tool may turn a LimitHit from deps.chat into TOOL_ERROR; a new limits_hit entry still ends the run.
        if len(self.budget.limits_hit) > mark[1]:
            raise LimitHit(self.budget.limits_hit[-1])

    def _publish_requested(self) -> bool:
        return bool(self.ctx.goal.get("publish_requested"))

    # ------------------------------------------------------------ plan

    def _ask_plan(self, messages: list[dict], event: str):
        mark = self._mark()
        try:
            reply = self.chat(messages, event, response_format=PLAN_RESPONSE_FORMAT)
        except LimitHit:
            raise
        except Exception as exc:
            self._raise_if_limit(mark)
            self.trace.append(event, kind="", summary=f"모델 호출 실패: {type(exc).__name__}",
                              model=self._model_since(mark))
            problems = [f"모델 호출 실패: {type(exc).__name__}"]
            self.trace.append(EVENT_PLAN_CHECK, kind=KIND_TOOL_ERROR, summary=one_line("; ".join(problems)),
                              why=WHY_CODE_RULE)
            return None, problems
        filled: list[str] = []
        plan, problems = parse_and_check(reply.get("text") if isinstance(reply, dict) else None, self.registry,
                                         filled=filled)
        model = self._model_since(mark)
        note = _filled_note(filled)
        if plan is not None:
            summary = " → ".join(s.tool for s in plan.steps) or "단계 없음"
            why = "; ".join(f"{s.id}: {one_line(s.why, 80)}" for s in plan.steps)
            self.trace.append(event, kind=KIND_OK, summary=one_line(summary) + self._cut_note(mark, event),
                              why=one_line(why, 600), model=model)
            # 0022: a course plan gets its missing required steps from the code (after the check, before running).
            done = {e["tool"] for e in self.executed if e.get("kind") == KIND_OK}
            course_filled, dropped = fill_course_steps(plan, done=done)
            if course_filled:
                note += f"; 코드 규칙: 코스 계획의 빠진 단계를 채움: [{', '.join(course_filled)}]"
            if dropped:
                note += f"; 단계 수 한도로 뺀 선택 단계: [{', '.join(dropped)}]"
            moved = move_evidence_steps(plan, done=done)
            if moved:
                note += f"; 코드 규칙: 근거 수집 단계를 정리 앞으로 옮김: [{', '.join(moved)}]"
            problems = _plan_size_problems(plan, self.registry)
            if problems:
                self.trace.append(EVENT_PLAN_CHECK, kind=KIND_TOOL_ERROR,
                                  summary=one_line("; ".join(problems) + note, 600), why=WHY_CODE_RULE)
                return None, problems
            self.trace.append(EVENT_PLAN_CHECK, kind=KIND_OK,
                              summary=one_line(f"단계 {len(plan.steps)}개 통과" + note, 600), why=WHY_CODE_RULE)
        else:
            self.trace.append(event, kind="", summary="계획을 받았으나 검사에 떨어짐" + self._cut_note(mark, event),
                              model=model)
            self.trace.append(EVENT_PLAN_CHECK, kind=KIND_TOOL_ERROR,
                              summary=one_line(publish.mask_local_paths("; ".join(problems)) + note),
                              why=WHY_CODE_RULE)
        return plan, problems

    def _replan(self, **what) -> list[PlanStep]:
        if self.replans_left <= 0:
            raise _Failed("다시 계획은 실행에 한 번뿐인데 이미 씀")
        self.replans_left -= 1
        messages = build_replan_messages(self.base_messages, **what)
        plan, problems = self._ask_plan(messages, EVENT_REPLAN)
        if plan is None:
            raise _Failed(one_line("다시 받은 계획도 검사에 떨어짐: " + "; ".join(problems), 200))
        if not self.ctx.goal:
            self.ctx.goal = plan.goal.to_dict()
        # After a TOOL_ERROR the goal of the first accepted plan stays: a re-plan fixes the remaining steps only and
        # cannot flip publish_requested.
        return list(plan.steps)

    # ------------------------------------------------------------ steps

    def _pre_list_input(self) -> None:
        if LIST_INPUT not in self.registry:
            return
        args = self.registry.with_defaults(LIST_INPUT, {})
        mark = self._mark()
        result = self._run_tool(LIST_INPUT, args)
        self._raise_if_limit(mark)
        self.trace.append(EVENT_STEP, tool=LIST_INPUT, args=args, kind=result.kind, summary=_result_summary(result),
                          why=WHY_LIST_INPUT, model=self._model_since(mark))

    def _run_tool(self, name: str, args: dict) -> ToolResult:
        try:
            result = self.registry.get(name).run(args, self.ctx, self.deps)
        except LimitHit:
            raise
        except Exception as exc:  # a crashing tool is a tool error (re-plan matter)
            return ToolResult.tool_error(f"도구 예외: {type(exc).__name__}")
        if not isinstance(result, ToolResult):
            return ToolResult.tool_error("도구가 ToolResult를 돌려주지 않음")
        return result

    def _note_read(self, args: dict, result: ToolResult) -> None:
        if result.kind == KIND_DENIED_BY_SANDBOX:
            line = f"{TEXT_DENIED_BY_SANDBOX}: {args.get('path', '')}"
            if line not in self.ctx.warnings:
                self.ctx.warnings.append(line)

    def _carry_budget_warnings(self) -> None:
        # course.json carries ctx.warnings; a course run writes no answer.json, so move budget warnings here.
        for w in list(getattr(self.budget, "warnings", []) or []):
            if w not in self.ctx.warnings:
                self.ctx.warnings.append(w)

    def _skip_publish(self, step: PlanStep, summary: str) -> None:
        self.trace.append(EVENT_STEP, tool=PUBLISH_TOOL, args=dict(step.args), kind="", summary=summary,
                          why=WHY_CODE_RULE)

    def _do_publish(self, args: dict, why: str) -> ToolResult | None:
        """Run the publish procedure; returns a ToolResult needing a re-plan, else None."""
        mark = self._mark()
        outcome = publish.PublishOutcome(status=None)
        try:
            publish.attempt_with_wait(args, self.ctx, self.deps, registry=self.registry, trace=self.trace,
                                      budget=self.budget, sleep=self.sleep, clock=self.clock, now=self.now,
                                      why=one_line(why), outcome=outcome, wait_limit_s=self.approval_wait_s)
        except BaseException:
            # Keep the attempts already sent in publish.json before the run ends FAILED.
            outcome.status = publish.status_from_attempts(outcome.attempts)
            if outcome.status is not None:
                self.publish_done = True
                publish.write_outcome(self.run_dir, self.ctx, outcome)
            raise
        self._raise_if_limit(mark)
        if outcome.status is None:
            result = outcome.tool_result or ToolResult.tool_error("게시 도구 결과를 읽지 못함")
            self.trace.append(EVENT_STEP, tool=PUBLISH_TOOL, args=args, kind=result.kind,
                              summary=_result_summary(result), why=one_line(why))
            return result if result.needs_replan else None
        self.publish_done = True
        self.publish_outcome = outcome
        publish.write_outcome(self.run_dir, self.ctx, outcome)
        last = outcome.attempts[-1].result if outcome.attempts else ""
        self.trace.append(EVENT_STEP, tool=PUBLISH_TOOL, args=args, kind=last,
                          summary=f"{outcome.status}, 시도 {len(outcome.attempts)}회", why=one_line(why))
        return None

    def _execute(self, steps: list[PlanStep]) -> None:
        pending = list(steps)
        while pending:
            step = pending.pop(0)
            if step.tool == PUBLISH_TOOL:
                if not self._publish_requested():
                    self._skip_publish(step, TEXT_USER_SAID_DO_NOT_SEND)
                    continue
                if self.publish_done:
                    self._skip_publish(step, TEXT_ALREADY_PUBLISHED)
                    continue
            self.budget.check_time()
            self.budget.count_step()
            args = self.registry.with_defaults(step.tool, step.args)
            if step.tool == PUBLISH_TOOL:
                result = self._do_publish(args, step.why)
                if result is None:
                    self.executed.append({"id": step.id, "tool": step.tool, "kind": KIND_OK, "summary": ""})
                    continue
            else:
                if step.tool == SAVE_COURSE:
                    self._carry_budget_warnings()
                mark = self._mark()
                result = self._run_tool(step.tool, args)
                self._raise_if_limit(mark)
                self.trace.append(EVENT_STEP, tool=step.tool, args=args, kind=result.kind,
                                  summary=_result_summary(result) + self._cut_note(mark, step.tool),
                                  why=one_line(step.why), model=self._model_since(mark))
                self._note_read(args, result)
            self.executed.append({"id": step.id, "tool": step.tool, "kind": result.kind,
                                  "summary": _result_summary(result)})
            if result.needs_replan:
                pending = self._replan(executed=list(self.executed), error=f"{step.id} {step.tool}: {result.error}")
            # DENIED_BY_SANDBOX, NOT_FOUND, OUT_OF_SCOPE, TOO_LARGE, NOT_TEXT: facts to record, no re-plan.

    # ------------------------------------------------------------ run

    def run(self) -> HeavyOutcome:
        try:
            self._pre_list_input()
            try:
                packs = self.deps.theme_packs()
            except LimitHit:
                raise
            except Exception as exc:
                packs = []
                self.ctx.warnings.append(f"테마 팩을 읽지 못함: {type(exc).__name__}")
            self.base_messages = build_plan_messages(self.ctx.request, packs, self.ctx.input_files,
                                                     self.registry.describe())
            plan, problems = self._ask_plan(self.base_messages, EVENT_PLAN)
            if plan is not None:
                self.ctx.goal = plan.goal.to_dict()
                steps = list(plan.steps)
            else:
                steps = self._replan(problems=problems)
            self._execute(steps)
            if self.ctx.course and self._publish_requested() and not self.publish_done:
                # Not a tool step: 4.10 counts executed plan steps only.
                self.budget.check_time()
                args = self.registry.with_defaults(PUBLISH_TOOL, {})
                result = self._do_publish(args, WHY_AUTO_PUBLISH)
                if result is not None:
                    raise _Failed(one_line(publish.mask_local_paths(f"게시 요청 실패: {result.error}"), 200))
        except LimitHit as exc:
            if exc.name not in self.budget.limits_hit:
                self.budget.limits_hit.append(exc.name)
            return self._failed(f"한도 초과: {exc.name}")
        except _Failed as exc:
            return self._failed(exc.reason)
        return self._finish()

    # ------------------------------------------------------------ endings

    def _warnings(self) -> list[str]:
        out: list[str] = []
        for w in list(self.ctx.warnings) + list(getattr(self.budget, "warnings", []) or []):
            if w not in out:
                out.append(w)
        return out

    def _collect_claims(self) -> tuple[list[OriginClaim], list[Conflict]]:
        origins: list[OriginClaim] = []
        conflicts: list[Conflict] = []
        bad = 0
        for graded in self.ctx.graded.values():
            if not isinstance(graded, dict):
                continue
            for o in graded.get("origins") or []:
                try:
                    origins.append(OriginClaim.from_dict(o))
                except SchemaError:
                    bad += 1
            for c in graded.get("conflicts") or []:
                try:
                    conflicts.append(Conflict.from_dict(c))
                except SchemaError:
                    bad += 1
        if bad:
            self.ctx.warnings.append(f"꼴이 틀린 유래 항목 {bad}개를 답에서 뺌")
        return origins, conflicts

    def _read_refs(self) -> list[ReadFileRef]:
        refs = []
        for path, info in self.ctx.read_files.items():
            kind = info.get("kind", "") if isinstance(info, dict) else ""
            refs.append(ReadFileRef(path=str(path), kind=str(kind)))
        return refs

    def _answer_text(self, origins: list[OriginClaim], conflicts: list[Conflict], refs: list[ReadFileRef]) -> str:
        lines: list[str] = []
        if self.ctx.goal.get("work") and not self.ctx.places and not self.ctx.course:
            lines.append(TEXT_NO_PLACES_FOR_WORK)
        for o in origins:
            grade = f"등급 {o.grade}" if o.grade else TEXT_NO_EVIDENCE
            lines.append(f"- {o.name}: {one_line(o.summary)} [{grade}]")
        for c in conflicts:
            lines.append(f"- {c.name}: 서로 다른 유래 주장 {len(c.claims)}개(등급순)")
        for ref in refs:
            info = self.ctx.read_files.get(ref.path) or {}
            if ref.kind == KIND_DENIED_BY_SANDBOX:
                lines.append(f"- {ref.path}: {TEXT_DENIED_BY_SANDBOX}")
            elif ref.kind == "dir":
                names = []
                for e in info.get("entries") or []:
                    names.append(e.get("name", "") if isinstance(e, dict) else str(e))
                lines.append(f"- {ref.path}: 폴더 항목 {', '.join(names) if names else '없음'}")
            elif ref.kind == "file":
                lines.append(f"- {ref.path}: 파일을 읽음")
            else:
                lines.append(f"- {ref.path}: {READ_KIND_TEXT.get(ref.kind, '읽지 못함')}")
        if not origins and self.ctx.search_results:
            for chunk in self.ctx.search_results[:5]:
                if isinstance(chunk, dict):
                    lines.append(f"- 찾은 자료: {one_line(chunk.get('title', ''), 80)}")
        if not lines:
            lines.append(TEXT_NOTHING_FOUND)
        return "\n".join(lines)

    def _write_answer(self, status: str, answer: str, origins=(), conflicts=(), refs=()) -> None:
        record = AnswerRecord(run_id=self.ctx.run_id, request=self.ctx.request, route=ROUTE_HEAVY, status=status,
                              answer=answer, evidence_label="", origins=list(origins), conflicts=list(conflicts),
                              read_files=list(refs), unknowns=list(self.ctx.unknowns), warnings=self._warnings())
        files.write_answer(self.run_dir, record)

    def _failed(self, reason: str) -> HeavyOutcome:
        reason = publish.mask_local_paths(reason)
        self._write_answer(STATUS_FAILED, reason, refs=self._read_refs())
        return HeavyOutcome(status=STATUS_FAILED, text=reason, reason=reason)

    def _course_text(self, status: str) -> str:
        course = self.ctx.course or {}
        places = course.get("places") or []
        total = course.get("total_min")
        lines = [f"코스 {len(places)}곳, 총 {total if total is not None else '알 수 없음'}분"]
        for p in places:
            if isinstance(p, dict):
                lines.append(f"{p.get('order', '')}. {p.get('current_name', '')}")
        if status == STATUS_COURSE_SAVED:
            lines.append(TEXT_USER_SAID_DO_NOT_SEND)
        elif self.publish_outcome is not None:
            lines.append(f"게시: {status}" + (f" {self.publish_outcome.issue_url}"
                                              if self.publish_outcome.issue_url else ""))
        return "\n".join(lines)

    def _finish(self) -> HeavyOutcome:
        if self.ctx.course:
            if self.publish_outcome is not None:
                status = self.publish_outcome.status
            else:
                status = STATUS_COURSE_SAVED
            return HeavyOutcome(status=status, text=self._course_text(status))
        origins, conflicts = self._collect_claims()
        refs = self._read_refs()
        answer = self._answer_text(origins, conflicts, refs)
        self._write_answer(STATUS_ANSWERED_HEAVY, answer, origins, conflicts, refs)
        return HeavyOutcome(status=STATUS_ANSWERED_HEAVY, text=answer)


def run_heavy(ctx: RunContext, *, registry, deps, nemotron_chat, budget, trace, sleep, clock, now,
              run_dir, approval_wait_s: int = limits.APPROVAL_WAIT_SECONDS) -> HeavyOutcome:
    return HeavyRun(ctx, registry=registry, deps=deps, nemotron_chat=nemotron_chat, budget=budget, trace=trace,
                    sleep=sleep, clock=clock, now=now, run_dir=run_dir, approval_wait_s=approval_wait_s).run()
