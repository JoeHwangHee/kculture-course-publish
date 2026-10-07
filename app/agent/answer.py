"""Grounded answer: retrieve -> prompt -> chat -> parse and validate the JSON answer.

`answer(question, retriever, client, k=5)` never crashes on a bad model reply: if the reply is not the requested
JSON it asks once more, and if that also fails the raw text is kept as the answer with "parse_error": true.
Model call failures (HTTP errors after retries, connection errors) propagate as ModelCallError.

The retriever only needs `.query(question, k=k) -> list[dict]` (retrieval.index.Retriever). The client only needs
`.chat(messages, response_format=...) -> ChatResult`, `.model` and a cumulative `.http_attempts` (NimClient).
"""

from __future__ import annotations

import json
import re
import time

from agent.prompt import RESPONSE_FORMAT, RETRY_NOTE, build_messages

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?```$", re.S)


def parse_model_json(text: str | None) -> dict | None:
    """The answer object, or None if `text` is not a JSON object with a string "answer"."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    m = _FENCE_RE.match(s)
    if m:
        s = m.group(1).strip()
    candidates = [s]
    lo, hi = s.find("{"), s.rfind("}")
    if 0 <= lo < hi and (lo, hi) != (0, len(s) - 1):
        candidates.append(s[lo:hi + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
            return obj
    return None


def _is_ref(v, n_chunks: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= n_chunks


def _refs(values, n_chunks: int, where: str, warnings: list[str]) -> list[int]:
    if values is None:
        return []
    if not isinstance(values, list):
        warnings.append(f"{where}가 목록이 아니어서 비웠습니다")
        return []
    out: list[int] = []
    for v in values:
        if _is_ref(v, n_chunks):
            if v not in out:
                out.append(v)
        else:
            warnings.append(f"없는 근거 번호를 뺐습니다: {where} {v!r}")
    return out


def _text(v) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def normalize(obj: dict, n_chunks: int) -> tuple[dict, list[str]]:
    """Keep only well-formed fields; drop chunk numbers outside 1..n_chunks with a warning."""
    warnings: list[str] = []
    citations = _refs(obj.get("citations"), n_chunks, "citations", warnings)

    conflicts = []
    raw_conflicts = obj.get("conflicts") or []
    if not isinstance(raw_conflicts, list):
        warnings.append("conflicts가 목록이 아니어서 비웠습니다")
        raw_conflicts = []
    for i, c in enumerate(raw_conflicts):
        if not isinstance(c, dict):
            warnings.append(f"conflicts[{i}] 형식이 잘못되어 뺐습니다")
            continue
        chosen = c.get("chosen")
        if chosen is not None and not _is_ref(chosen, n_chunks):
            warnings.append(f"없는 근거 번호를 뺐습니다: conflicts[{i}].chosen {chosen!r}")
            chosen = None
        conflicts.append({
            "topic": _text(c.get("topic")),
            "sources": _refs(c.get("sources"), n_chunks, f"conflicts[{i}].sources", warnings),
            "chosen": chosen,
            "reason": _text(c.get("reason")),
        })

    stale = []
    raw_stale = obj.get("stale") or []
    if not isinstance(raw_stale, list):
        warnings.append("stale이 목록이 아니어서 비웠습니다")
        raw_stale = []
    for i, s in enumerate(raw_stale):
        if not isinstance(s, dict):
            warnings.append(f"stale[{i}] 형식이 잘못되어 뺐습니다")
            continue
        src = s.get("source")
        if not _is_ref(src, n_chunks):
            warnings.append(f"없는 근거 번호를 뺐습니다: stale[{i}].source {src!r}")
            continue
        stale.append({"source": src, "reason": _text(s.get("reason"))})

    unknown = obj.get("unknown")
    if not isinstance(unknown, bool):
        if unknown is not None:
            warnings.append("unknown이 참거짓 값이 아니어서 false로 두었습니다")
        unknown = False

    return {
        "answer": obj["answer"],
        "citations": citations,
        "conflicts": conflicts,
        "stale": stale,
        "unknown": unknown,
    }, warnings


def _chunk_meta(n: int, h: dict) -> dict:
    return {
        "n": n,
        "source": h.get("source"),
        "chunk_id": h.get("chunk_id"),
        "title": h.get("title"),
        "rank": h.get("rank"),
        "score": h.get("score"),
    }


def answer(question: str, retriever, client, k: int = 5) -> dict:
    t0 = time.perf_counter()
    hits = retriever.query(question, k=k)
    chunks = [_chunk_meta(n, h) for n, h in enumerate(hits, start=1)]
    result = {
        "question": question,
        "answer": "",
        "citations": [],
        "conflicts": [],
        "stale": [],
        "unknown": True,
        "parse_error": False,
        "warnings": [],
        "chunks": chunks,
        "model": getattr(client, "model", None),
        "k": k,
        "no_results": not hits,
        "finish_reason": None,
        "requests": {"model_calls": 0, "http_attempts": 0},
        "elapsed_s": 0.0,
    }
    if not hits:
        result["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return result

    start_attempts = getattr(client, "http_attempts", 0)
    messages = build_messages(question, hits)
    calls = 0
    parsed = None
    res = None
    warnings: list[str] = []
    try:
        for attempt in range(2):
            msgs = messages if attempt == 0 else messages + [{"role": "user", "content": RETRY_NOTE}]
            calls += 1
            res = client.chat(msgs, response_format=RESPONSE_FORMAT)
            if res.finish_reason == "length":
                warnings.append("응답이 길이 한도(max_tokens)에서 잘렸습니다")
            parsed = parse_model_json(res.text)
            if parsed is not None:
                break
            warnings.append(f"모델 응답을 JSON으로 읽지 못했습니다({attempt + 1}번째 응답)")
    finally:
        result["requests"] = {
            "model_calls": calls,
            "http_attempts": getattr(client, "http_attempts", 0) - start_attempts,
        }
        result["elapsed_s"] = round(time.perf_counter() - t0, 3)

    result["model"] = res.model or result["model"]
    result["finish_reason"] = res.finish_reason
    if parsed is None:
        result.update(answer=res.text, parse_error=True, unknown=None)
    else:
        fields, more = normalize(parsed, len(hits))
        result.update(fields)
        warnings.extend(more)
    result["warnings"] = warnings
    return result
