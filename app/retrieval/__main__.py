"""CLI.

  python -m retrieval index --input DIR --index DIR --embedder SPEC
  python -m retrieval query --index DIR --embedder SPEC [-k 5] [--mode hybrid] [--json] "질문"

SPEC: hash | local:<model folder> | nim:<model id> (base URL from env NIM_BASE_URL).
Exit codes: 0 success, 1 no results, 2 usage/input error (missing folder, embedder or tokenizer mismatch,
bad spec), 3 other runtime error. Human-readable errors go to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from retrieval.errors import InputError, RetrievalError

EXIT_OK, EXIT_NO_RESULT, EXIT_INPUT, EXIT_RUNTIME = 0, 1, 2, 3


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT, f"사용법 오류: {message}\n")


def _build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m retrieval", description="로컬 자료 하이브리드 검색(Kiwi BM25 + 임베딩, RRF)")
    p.add_argument("-v", "--verbose", action="store_true", help="건너뛴 파일 등 진행 기록을 stderr에")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)

    pi = sub.add_parser("index", help="입력 폴더를 색인한다")
    pi.add_argument("--input", required=True, help="참고 자료 폴더(읽기 전용)")
    pi.add_argument("--index", required=True, help="인덱스를 쓸 폴더(입력 폴더 밖)")
    pi.add_argument("--embedder", required=True, help="hash | local:<모델 폴더> | nim:<모델ID>")
    pi.add_argument("--max-chars", type=int, default=500, help="청크 최대 글자 수")
    pi.add_argument("--overlap-chars", type=int, default=100, help="청크 겹침 상한 글자 수")
    pi.add_argument("--json", action="store_true", help="manifest를 JSON으로 출력")

    pq = sub.add_parser("query", help="인덱스에서 검색한다")
    pq.add_argument("--index", required=True)
    pq.add_argument("--embedder", required=True, help="색인 때와 같은 임베더")
    pq.add_argument("-k", type=int, default=5, help="돌려줄 결과 수")
    pq.add_argument("--mode", choices=["hybrid", "bm25", "dense"], default="hybrid")
    pq.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    pq.add_argument("question", help="질문")
    return p


def _cmd_index(args) -> int:
    from retrieval.embedder import make_embedder
    from retrieval.index import build_index

    emb = make_embedder(args.embedder)
    m = build_index(args.input, args.index, emb, max_chars=args.max_chars, overlap_chars=args.overlap_chars)
    if args.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
    else:
        print(f"색인 완료: 문서 {m['doc_count']}개, 청크 {m['chunk_count']}개, 건너뜀 {len(m['skipped'])}개")
        print(f"임베더: {m['embedder']['type']}:{m['embedder']['model']} (차원 {m['embedder']['dim']})")
        for s in m["skipped"]:
            print(f"  skipped: {s['reason']}  {s['path']}")
    if m["chunk_count"] == 0:
        print("색인할 내용이 없습니다(지원 형식 문서 0개)", file=sys.stderr)
        return EXIT_NO_RESULT
    return EXIT_OK


def _cmd_query(args) -> int:
    from retrieval.embedder import make_embedder
    from retrieval.index import Retriever

    emb = make_embedder(args.embedder)
    hits = Retriever.load(args.index, emb).query(args.question, k=args.k, mode=args.mode)
    if args.json:
        print(json.dumps({"query": args.question, "mode": args.mode, "k": args.k, "hits": hits},
                         ensure_ascii=False, indent=2))
    else:
        for h in hits:
            dates = ", ".join(h["dates_in_text"]) or "-"
            print(f"[{h['rank']}] {h['source']}  (rrf {h['score']:.4f}, bm25 {h['bm25_rank']}, dense {h['dense_rank']})")
            print(f"    제목: {h['title']} | 수정: {h['mtime']} | 본문 날짜: {dates}")
            print(f"    출처: {h.get('source_id') or '-'} | 종류: {h.get('kind') or '-'} | "
                  f"출처 종류: {h.get('source_type') or '-'}")
            snippet = h["text"].replace("\n", " ")
            print(f"    {snippet[:200]}{'…' if len(snippet) > 200 else ''}")
    if not hits:
        print("검색 결과가 없습니다", file=sys.stderr)
        return EXIT_NO_RESULT
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    try:
        if args.cmd == "index":
            return _cmd_index(args)
        return _cmd_query(args)
    except InputError as e:
        print(f"입력 오류: {e}", file=sys.stderr)
        return EXIT_INPUT
    except RetrievalError as e:
        print(f"실행 오류: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    except Exception as e:  # noqa: BLE001 - last-resort mapping to exit 3
        print(f"실행 오류: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
