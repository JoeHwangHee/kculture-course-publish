"""Answer files: `answer-<UTC time>.md` (human-readable) and a `.json` with the same stem. Never overwrites."""

from __future__ import annotations

import json
import os
from datetime import datetime


def _cell(v) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, (list, tuple)):
        v = ", ".join(f"[{x}]" if isinstance(x, int) else str(x) for x in v) or "-"
    elif isinstance(v, float):
        v = f"{v:.4f}"
    return " ".join(str(v).split()).replace("|", "\\|")


def _ref(n) -> str:
    return "-" if n is None else f"[{n}]"


def render_markdown(result: dict) -> str:
    req = result.get("requests") or {}
    lines = [
        "# 답변",
        "",
        f"- 질문: {_cell(result.get('question'))}",
        f"- 생성 시각(UTC): {_cell(result.get('created_at'))}",
        f"- 모델: {_cell(result.get('model'))}",
        f"- 소요 시간: {result.get('elapsed_s', 0):.3f}초, 모델 요청 {req.get('model_calls', 0)}회"
        f"(HTTP 시도 {req.get('http_attempts', 0)}회)",
        "",
    ]
    if result.get("parse_error"):
        lines += ["> 모델 응답을 JSON으로 읽지 못해 원문을 그대로 남겼습니다(parse_error). 근거 번호는 검증되지 않았습니다.", ""]
    if result.get("unknown"):
        lines += ["> 모델이 자료로는 답할 수 없다고 판단했습니다(unknown).", ""]
    lines += ["## 답", "", result.get("answer") or "(빈 응답)", ""]

    cited = set(result.get("citations") or [])
    lines += ["## 근거", "", "| 번호 | 출처 | 청크 | 제목 | 검색 순위 | 점수 | 인용 |", "|---|---|---|---|---|---|---|"]
    for c in result.get("chunks") or []:
        lines.append(
            f"| [{c.get('n')}] | {_cell(c.get('source'))} | {_cell(c.get('chunk_id'))} | {_cell(c.get('title'))} | "
            f"{_cell(c.get('rank'))} | {_cell(c.get('score'))} | {'예' if c.get('n') in cited else ''} |"
        )
    lines.append("")

    lines += ["## 충돌하는 자료", ""]
    conflicts = result.get("conflicts") or []
    if conflicts:
        lines += ["| 주제 | 자료 | 택한 자료 | 이유 |", "|---|---|---|---|"]
        for c in conflicts:
            lines.append(f"| {_cell(c.get('topic'))} | {_cell(c.get('sources'))} | {_ref(c.get('chosen'))} | "
                         f"{_cell(c.get('reason'))} |")
    else:
        lines.append("없음")
    lines.append("")

    lines += ["## 오래된 자료", ""]
    stale = result.get("stale") or []
    if stale:
        lines += ["| 자료 | 이유 |", "|---|---|"]
        for s in stale:
            lines.append(f"| {_ref(s.get('source'))} | {_cell(s.get('reason'))} |")
    else:
        lines.append("없음")
    lines.append("")

    warnings = result.get("warnings") or []
    if warnings:
        lines += ["## 경고", ""] + [f"- {_cell(w)}" for w in warnings] + [""]
    return "\n".join(lines)


def write_outputs(result: dict, out_dir, now: datetime) -> tuple[str, str]:
    """Write md + json under `out_dir` with a fresh stem; returns (md_path, json_path)."""
    out_dir = os.fspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    base = f"answer-{now:%Y%m%dT%H%M%SZ}"
    md_text = render_markdown(result)
    js_text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    for i in range(10000):
        stem = base if i == 0 else f"{base}-{i}"
        md_path = os.path.join(out_dir, stem + ".md")
        js_path = os.path.join(out_dir, stem + ".json")
        if os.path.exists(md_path) or os.path.exists(js_path):
            continue
        try:
            with open(md_path, "x", encoding="utf-8") as fh:
                fh.write(md_text)
        except FileExistsError:
            continue
        try:
            with open(js_path, "x", encoding="utf-8") as fh:
                fh.write(js_text)
        except FileExistsError:
            os.remove(md_path)  # ours, written a moment ago
            continue
        return md_path, js_path
    raise FileExistsError(f"새 답변 파일 이름을 만들지 못했습니다: {base}")
