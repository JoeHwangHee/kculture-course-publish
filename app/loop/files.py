"""Run folder `/hackathon/output/<run_id>/` and the files the loop writes there (spec 4.4)."""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import datetime
from typing import Any, Callable

from common.schema import (
    ANSWER_JSON,
    ANSWER_MD,
    PUBLISH_JSON,
    RUN_JSON,
    TEXT_NO_EVIDENCE,
    AnswerRecord,
    OriginClaim,
    PublishRecord,
    Record,
    RunRecord,
    new_run_id,
)

RUN_DIR_DRAWS = 100  # random suffixes tried before giving up


def new_run_dir(output_root: pathlib.Path, now: datetime,
                rand_hex: str | Callable[[], str] | None = None) -> tuple[str, pathlib.Path]:
    """Create a fresh run folder and return (run_id, path). Never reuses an existing folder.

    `rand_hex`: None = random suffix, a callable = called on each draw, a string = that suffix only (tests).
    """
    root = pathlib.Path(output_root)
    draws = 1 if isinstance(rand_hex, str) else RUN_DIR_DRAWS
    for _ in range(draws):
        suffix = rand_hex() if callable(rand_hex) else rand_hex
        run_id = new_run_id(now, suffix)
        run_dir = root / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        return run_id, run_dir
    raise FileExistsError(f"새 실행 폴더를 만들지 못했습니다(이미 있음): {run_id}")


def _file_mode() -> int:
    # Mode a plain open() would give (mkstemp makes 0600; the host-side audit reads these files).
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def _atomic_write_text(path: pathlib.Path, text: str) -> None:
    """Write `text` (UTF-8) to a temp file in the same folder, then move it into place."""
    path = pathlib.Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(tmp, _file_mode())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: pathlib.Path, obj: Any) -> None:
    """UTF-8 JSON (indent 2), written to a temp file in the same folder and moved into place."""
    if isinstance(obj, Record):
        obj = obj.to_dict()
    _atomic_write_text(pathlib.Path(path), json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_json(path: pathlib.Path) -> Any:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def write_run(run_dir, record: RunRecord) -> None:
    write_json(pathlib.Path(run_dir) / RUN_JSON, record.to_dict())


def write_publish(run_dir, record: PublishRecord) -> None:
    write_json(pathlib.Path(run_dir) / PUBLISH_JSON, record.to_dict())


def _claim_line(claim: OriginClaim) -> str:
    grade = f"등급 {claim.grade}" if claim.grade else TEXT_NO_EVIDENCE
    refs = []
    if claim.source_ids:
        refs.append("출처 " + ", ".join(claim.source_ids))
    if claim.chunk_ids:
        refs.append("청크 " + ", ".join(claim.chunk_ids))
    if claim.input_paths:
        refs.append("입력 파일 " + ", ".join(claim.input_paths))
    ref_text = "; ".join(refs) if refs else "출처 없음"
    summary = " ".join(claim.summary.split())
    return f"**{claim.name}**({claim.name_kind}): {summary} [{grade}] ({ref_text})"


def render_answer_md(record: AnswerRecord) -> str:
    """Human-readable answer.md: answer, origin claims with grade and source ids, conflicts, files read,
    unknowns, warnings."""
    out: list[str] = []
    if record.evidence_label:
        out += [record.evidence_label, ""]
    out += ["# 답변", "", f"- 실행: {record.run_id}", f"- 요청: {' '.join(record.request.split())}",
            f"- 경로: {record.route}, 상태: {record.status}", "", record.answer.rstrip(), ""]
    if record.origins:
        out += ["## 이름 유래", ""] + [f"- {_claim_line(c)}" for c in record.origins] + [""]
    if record.conflicts:
        out += ["## 유래 충돌", ""]
        for conflict in record.conflicts:
            out.append(f"- **{conflict.name}**: 서로 다른 주장 {len(conflict.claims)}개(등급순)")
            out += [f"  - {_claim_line(c)}" for c in conflict.claims]
        out.append("")
    if record.read_files:
        out += ["## 읽은 파일", ""] + [f"- `{r.path}` ({r.kind})" for r in record.read_files] + [""]
    if record.unknowns:
        out += ["## 확인 안 된 것", ""] + [f"- {u}" for u in record.unknowns] + [""]
    if record.warnings:
        out += ["## 경고", ""] + [f"- {w}" for w in record.warnings] + [""]
    return "\n".join(out).rstrip() + "\n"


def write_answer(run_dir, record: AnswerRecord) -> None:
    run_dir = pathlib.Path(run_dir)
    write_json(run_dir / ANSWER_JSON, record.to_dict())
    _atomic_write_text(run_dir / ANSWER_MD, render_answer_md(record))


def list_run_files(run_dir) -> list[str]:
    """Names of the files in the run folder, sorted (run.json `files`). Temp and hidden files are left out."""
    return sorted(p.name for p in pathlib.Path(run_dir).iterdir() if p.is_file() and not p.name.startswith("."))
