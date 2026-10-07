"""CLI.

  python -m agent ask --index DIR --embedder SPEC [-k 5] [--mode hybrid] [--out DIR] [--json] "질문"

Searches the index, sends the top-k chunks and the question to the chat model (NIM_BASE_URL, NIM_MODEL,
key from NVIDIA_API_KEY) and prints the grounded answer. With --out, writes answer-<UTC time>.md and .json there
(never overwrites existing files).

Exit codes: 0 success (also when the reply was kept raw with parse_error), 1 no search results (model not called),
2 usage/input error (including a missing NVIDIA_API_KEY), 3 model call failure or other runtime error.
Human-readable errors go to stderr in Korean.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from agent.errors import AgentError, ConfigError

EXIT_OK, EXIT_NO_RESULT, EXIT_INPUT, EXIT_RUNTIME = 0, 1, 2, 3


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT, f"사용법 오류: {message}\n")


def _build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m agent", description="검색한 근거로 Nemotron에게 답을 받는다(RAG)")
    p.add_argument("-v", "--verbose", action="store_true", help="진행 기록을 stderr에")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    pa = sub.add_parser("ask", help="질문에 근거 있는 답을 받는다")
    pa.add_argument("--index", required=True, help="python -m retrieval index로 만든 인덱스 폴더")
    pa.add_argument("--embedder", required=True, help="색인 때와 같은 임베더: hash | local:<폴더> | nim:<모델ID>")
    pa.add_argument("-k", type=int, default=5, help="모델에 보낼 근거 청크 수")
    pa.add_argument("--mode", choices=["hybrid", "bm25", "dense"], default="hybrid", help="검색 방식")
    pa.add_argument("--out", help="답변 파일(md, json)을 쓸 폴더. 기존 파일은 덮어쓰지 않는다")
    pa.add_argument("--json", action="store_true", help="결과를 JSON으로 stdout에")
    pa.add_argument("question", help="질문")
    return p


class _ModeRetriever:
    """Adapter so answer() can call .query(q, k=k) with the chosen search mode."""

    def __init__(self, retriever, mode: str):
        self._r = retriever
        self._mode = mode

    def query(self, q: str, k: int = 5):
        return self._r.query(q, k=k, mode=self._mode)


def _print_text(result: dict) -> None:
    print(result.get("answer") or "(빈 응답)")
    print()
    cited = set(result.get("citations") or [])
    for c in result.get("chunks") or []:
        mark = "*" if c["n"] in cited else " "
        print(f"{mark}[{c['n']}] {c.get('source')}  ({c.get('chunk_id')})")
    for w in result.get("warnings") or []:
        print(f"경고: {w}", file=sys.stderr)


def _cmd_ask(args, transport, sleep, now) -> int:
    from retrieval.embedder import make_embedder
    from retrieval.index import Retriever

    from agent.answer import answer
    from agent.nim_client import NimClient
    from agent.output import write_outputs

    client = NimClient.from_env(transport=transport, sleep=sleep)  # key checked before any work
    retriever = Retriever.load(args.index, make_embedder(args.embedder))
    result = answer(args.question, _ModeRetriever(retriever, args.mode), client, k=args.k)
    if result["no_results"]:
        print("검색 결과가 없습니다(모델을 부르지 않았습니다)", file=sys.stderr)
        return EXIT_NO_RESULT
    stamp = now().astimezone(timezone.utc)
    result["created_at"] = stamp.isoformat(timespec="seconds")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_text(result)
    if result.get("parse_error"):
        print("경고: 모델 응답을 JSON으로 읽지 못해 원문을 남겼습니다", file=sys.stderr)
    if args.out:
        md_path, js_path = write_outputs(result, args.out, stamp)
        print(f"저장: {md_path}", file=sys.stderr)
        print(f"저장: {js_path}", file=sys.stderr)
    return EXIT_OK


def main(argv: list[str] | None = None, *, transport=None, sleep=None, now=None) -> int:
    """`transport`, `sleep` and `now` are injection points for tests (no network, no waiting, fixed clock)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_INPUT
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    now = now or (lambda: datetime.now(timezone.utc))

    from retrieval.errors import InputError, RetrievalError

    try:
        return _cmd_ask(args, transport, sleep, now)
    except (ConfigError, InputError) as e:
        print(f"입력 오류: {e}", file=sys.stderr)
        return EXIT_INPUT
    except (AgentError, RetrievalError) as e:
        print(f"실행 오류: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    except Exception as e:  # noqa: BLE001 - last-resort mapping to exit 3
        print(f"실행 오류: {type(e).__name__}", file=sys.stderr)
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
