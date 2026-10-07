"""CLI (spec 4.9): `python -m loop ask "<요청>"`, `python -m loop publish --run <run_id>`,
`python -m loop baseline "<요청>"`.

Exit codes (조정값):
- ask: ANSWERED_LIGHT, ANSWERED_HEAVY, COURSE_SAVED, PUBLISHED, PUBLISH_PENDING_APPROVAL -> 0;
  UNAVAILABLE, FAILED, PUBLISH_FAILED -> 1; usage or setup error -> 2
- publish: 0 PUBLISHED, 1 a CREATED attempt already exists (nothing sent), 2 usage / no run folder,
  3 sent but not published
- any command: an unexpected exception -> 3
- baseline: BASELINE_DONE -> 0, FAILED -> 1, usage -> 2

The real wiring (Nemotron, index, tools) is imported late inside functions; tests pass `factories`.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
import time

from common import limits
from common.schema import (
    OUTPUT_DIR,
    PUBLISH_REPO_ENV,
    STATUS_ANSWERED_HEAVY,
    STATUS_ANSWERED_LIGHT,
    STATUS_BASELINE_DONE,
    STATUS_COURSE_SAVED,
    STATUS_PUBLISH_PENDING_APPROVAL,
    STATUS_PUBLISHED,
    is_run_id,
)

OUTPUT_DIR_ENV = "KCULTURE_OUTPUT_DIR"
INDEX_DIR_ENV = "KCULTURE_INDEX_DIR"
EMBEDDER_ENV = "KCULTURE_EMBEDDER"
APPROVAL_WAIT_ENV = "KCULTURE_APPROVAL_WAIT_S"  # 0014: approval wait limit in seconds, integer 0..180
DEFAULT_INDEX_DIR = "/opt/kculture/index/kb"  # (조정값)
DEFAULT_EMBEDDER = "local:/opt/models/bge-m3"  # decision 0004: the embedder the index was built with

ASK_OK = (STATUS_ANSWERED_LIGHT, STATUS_ANSWERED_HEAVY, STATUS_COURSE_SAVED, STATUS_PUBLISHED,
          STATUS_PUBLISH_PENDING_APPROVAL)
EXIT_USAGE = 2
EXIT_UNEXPECTED = 3  # (조정값) an unexpected exception in any command


class _ChatSlot:
    """Chat stand-in handed to the real wiring before the run's Budget exists; the run plugs in the wrapped chat."""

    def __init__(self):
        self.target = None

    def __call__(self, messages, purpose, **kw):
        if self.target is None:
            raise RuntimeError("chat is not connected for this command")
        return self.target(messages, purpose, **kw)


class ConfigError(ValueError):
    """A setting the CLI reads is invalid (exit 2 before any run folder)."""


def approval_wait_from_env() -> int:
    """KCULTURE_APPROVAL_WAIT_S as an integer 0..APPROVAL_WAIT_SECONDS (default APPROVAL_WAIT_SECONDS)."""
    raw = os.environ.get(APPROVAL_WAIT_ENV)
    if raw is None or raw.strip() == "":
        return limits.APPROVAL_WAIT_SECONDS
    value = raw.strip()
    if not re.fullmatch(r"[0-9]+", value) or not 0 <= int(value) <= limits.APPROVAL_WAIT_SECONDS:
        raise ConfigError(f"{APPROVAL_WAIT_ENV}는 0~{limits.APPROVAL_WAIT_SECONDS} 정수여야 합니다")
    return int(value)


def _index_settings() -> tuple[str, str]:
    return os.environ.get(INDEX_DIR_ENV) or DEFAULT_INDEX_DIR, os.environ.get(EMBEDDER_ENV) or DEFAULT_EMBEDDER


def _real_ask(ns) -> dict:
    from loop.nemotron import NemotronChat
    from loop.wiring import build_real

    index_dir, embedder = _index_settings()
    slot = _ChatSlot()
    deps, registry, fingerprint = build_real(index_dir=index_dir, embedder_spec=embedder, chat=slot)

    def deps_factory(chat):
        slot.target = chat
        return deps

    # One Nemotron client serves the router and the plan / tools; run_ask wraps it per Budget key (router, nemotron).
    nemotron = NemotronChat()
    return {"registry": registry, "deps_factory": deps_factory, "router_chat": nemotron,
            "nemotron_chat": nemotron, "index_fingerprint": fingerprint,
            "publish_repo": os.environ.get(PUBLISH_REPO_ENV, "")}


def _real_publish(ns) -> dict:
    from loop.wiring import build_real

    index_dir, embedder = _index_settings()
    deps, registry, _ = build_real(index_dir=index_dir, embedder_spec=embedder, chat=_ChatSlot())
    return {"registry": registry, "deps": deps, "publish_repo": os.environ.get(PUBLISH_REPO_ENV, "")}


def _real_baseline(ns) -> dict:
    from loop.nemotron import NemotronChat

    return {"nemotron_chat": NemotronChat()}


REAL_FACTORIES = {"ask": _real_ask, "publish": _real_publish, "baseline": _real_baseline}


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--output-dir", default=None, help="실행 폴더를 만들 곳(기본: KCULTURE_OUTPUT_DIR 또는 /hackathon/output)")
    p = argparse.ArgumentParser(prog="python -m loop", description="K-콘텐츠 배경지 코스 에이전트")
    sub = p.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", parents=[common], help="요청 하나를 실행")
    ask.add_argument("request")
    pub = sub.add_parser("publish", parents=[common], help="실행 하나의 코스를 나중에 게시")
    pub.add_argument("--run", required=True, dest="run_id")
    base = sub.add_parser("baseline", parents=[common], help="기준선(Nemotron 단독) 실행")
    base.add_argument("request")
    return p


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


NO_RUN_ID = "-"  # last-line value when the command stopped before a run folder existed


def main(argv=None, *, factories=None) -> int:
    """Run one command. The last stdout line is always `run_id: <run_id>` (or `run_id: -`); errors go to stderr."""
    holder = {"run_id": NO_RUN_ID}
    code = EXIT_UNEXPECTED
    try:
        code = _main(argv, factories, holder)
    except Exception as exc:  # last line of defence: never exit 1 here (1 means "already CREATED" for publish)
        _err(f"예상하지 못한 오류: {type(exc).__name__}")
        code = EXIT_UNEXPECTED
    finally:
        sys.stdout.flush()
        print(f"run_id: {holder['run_id']}")
        sys.stdout.flush()
    return code


def _main(argv, factories, holder: dict) -> int:
    try:
        ns = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    facts = dict(REAL_FACTORIES)
    facts.update(factories or {})
    clock = facts.get("clock", time.monotonic)
    sleep = facts.get("sleep", time.sleep)
    extra = {k: facts[k] for k in ("now", "rand_hex") if k in facts}
    output_root = ns.output_dir or os.environ.get(OUTPUT_DIR_ENV) or OUTPUT_DIR
    request = getattr(ns, "request", "")
    if ns.command in ("ask", "baseline") and not request.strip():
        _err("요청 문장이 비었습니다.")
        return EXIT_USAGE

    approval_wait_s = limits.APPROVAL_WAIT_SECONDS
    if ns.command in ("ask", "publish"):
        try:
            approval_wait_s = approval_wait_from_env()
        except ConfigError as exc:
            _err(f"설정 오류: {exc}")
            return EXIT_USAGE

    if ns.command == "publish":
        # Check the run first: an already CREATED run ends with 1 before any repo or index setup.
        from loop.publish import EXIT_ALREADY_CREATED, has_created

        if not is_run_id(ns.run_id) or not (pathlib.Path(output_root) / ns.run_id).is_dir():
            _err("실행 폴더를 찾지 못했습니다. run_id를 확인하세요.")
            return EXIT_USAGE
        holder["run_id"] = ns.run_id
        if has_created(pathlib.Path(output_root) / ns.run_id):
            _err("이미 게시된 실행입니다. 다시 보내지 않습니다.")
            return EXIT_ALREADY_CREATED

    try:
        wired = facts[ns.command](ns)
    except Exception as exc:  # setup error: missing env, index, client (message left out: it may hold local paths)
        _err(f"설정 오류({type(exc).__name__}): 실행에 필요한 설정·색인·모델 연결을 준비하지 못했습니다.")
        return EXIT_USAGE

    if ns.command == "ask":
        from loop.runner import run_ask

        out = run_ask(request, output_root=output_root, clock=clock, sleep=sleep, approval_wait_s=approval_wait_s,
                      **extra, **wired)
        holder["run_id"] = out["run_id"]
        print(f"상태: {out['status']}")
        if out["text"]:
            print(out["text"])
        return 0 if out["status"] in ASK_OK else 1

    if ns.command == "baseline":
        from loop.baseline import run_baseline

        out = run_baseline(request, output_root=output_root, clock=clock, **extra, **wired)
        holder["run_id"] = out["run_id"]
        print(f"상태: {out['status']}")
        if out["text"]:
            print(out["text"])
        return 0 if out["status"] == STATUS_BASELINE_DONE else 1

    from loop.publish import EXIT_ALREADY_CREATED, EXIT_USAGE as PUB_USAGE, publish_run
    from loop.runner import utc_now

    if not wired.get("publish_repo"):
        _err(f"게시 저장소가 정해지지 않았습니다. 환경변수 {PUBLISH_REPO_ENV}(owner/repo)를 넣으세요.")
        return EXIT_USAGE
    code, status = publish_run(ns.run_id, output_root=output_root, registry=wired["registry"], deps=wired["deps"],
                               sleep=sleep, clock=clock, now=facts.get("now") or utc_now,
                               publish_repo=wired["publish_repo"], approval_wait_s=approval_wait_s)
    if code == PUB_USAGE:
        _err("실행 폴더의 run.json·course.json·trace.jsonl을 읽지 못했습니다.")
    elif code == EXIT_ALREADY_CREATED:
        _err("이미 게시된 실행입니다. 다시 보내지 않습니다.")
    else:
        print(f"상태: {status}")
    return code


if __name__ == "__main__":
    sys.exit(main())
