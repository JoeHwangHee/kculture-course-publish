"""Paragraph-based chunking with small overlap, plus date extraction.

Each chunk keeps the metadata needed later for freshness and conflict judgement:
source, title, file mtime, dates found in the text, and character offsets into the document text
(invariant: document.text[char_start:char_end] == chunk.text).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from retrieval.loader import Document

DEFAULT_MAX_CHARS = 500
DEFAULT_OVERLAP_CHARS = 100

# Longest forms first; one combined pattern so each span is consumed once
# ("2019년 3월 1일" yields only "2019-03-01", never also "2019").
_DATE_RE = re.compile(
    r"(?<!\d)(?:"
    r"(?P<y1>\d{4})-(?P<m1>\d{1,2})-(?P<d1>\d{1,2})(?!\d)"
    r"|(?P<y2>\d{4})\.\s?(?P<m2>\d{1,2})\.\s?(?P<d2>\d{1,2})(?!\d)\.?"
    r"|(?P<y3>\d{4})/(?P<m3>\d{1,2})/(?P<d3>\d{1,2})(?!\d)"
    r"|(?P<y4>\d{4})년\s*(?P<m4>\d{1,2})월\s*(?P<d4>\d{1,2})일"
    r"|(?P<y5>\d{4})년\s*(?P<m5>\d{1,2})월"
    r"|(?P<y6>\d{4})년"
    r")"
)


def _valid(m: int | None, d: int | None) -> bool:
    if m is not None and not 1 <= m <= 12:
        return False
    if d is not None and not 1 <= d <= 31:
        return False
    return True


def extract_dates(text: str) -> list[str]:
    """Return normalized dates in order of first appearance, without duplicates.

    Forms: YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, YYYY년 M월 D일 -> "YYYY-MM-DD";
    YYYY년 M월 -> "YYYY-MM"; YYYY년 -> "YYYY". Invalid month/day values are dropped.
    """
    out: list[str] = []
    for m in _DATE_RE.finditer(text):
        g = m.groupdict()
        for i in range(1, 7):
            y = g.get(f"y{i}")
            if y is None:
                continue
            mo = g.get(f"m{i}")
            d = g.get(f"d{i}")
            mo_i = int(mo) if mo else None
            d_i = int(d) if d else None
            if not _valid(mo_i, d_i):
                break
            if d_i is not None:
                val = f"{y}-{mo_i:02d}-{d_i:02d}"
            elif mo_i is not None:
                val = f"{y}-{mo_i:02d}"
            else:
                val = y
            if val not in out:
                out.append(val)
            break
    return out


@dataclass
class Chunk:
    chunk_id: str
    source: str
    title: str
    mtime: str
    char_start: int
    char_end: int
    text: str
    dates_in_text: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Spans of non-blank paragraphs (separated by one or more blank lines), stripped of edge whitespace."""
    spans = []
    for m in re.finditer(r"\S(?:.*?\S)?(?=[ \t]*\n[ \t]*\n|\s*\Z)", text, flags=re.S):
        spans.append((m.start(), m.end()))
    return spans


def _split_long(start: int, end: int, max_chars: int, overlap: int) -> list[tuple[int, int]]:
    step = max(1, max_chars - overlap)
    out = []
    s = start
    while True:
        e = min(s + max_chars, end)
        out.append((s, e))
        if e >= end:
            break
        s += step
    return out


def _windows(spans: list[tuple[int, int]], max_chars: int, overlap: int) -> list[tuple[int, int]]:
    # Break oversized paragraphs into pieces first.
    pieces: list[tuple[int, int]] = []
    for s, e in spans:
        if e - s > max_chars:
            pieces.extend(_split_long(s, e, max_chars, overlap))
        else:
            pieces.append((s, e))

    windows: list[tuple[int, int]] = []
    i = 0
    n = len(pieces)
    while i < n:
        start = pieces[i][0]
        j = i
        while j + 1 < n and pieces[j + 1][1] - start <= max_chars:
            j += 1
        windows.append((start, pieces[j][1]))
        if j + 1 >= n:
            break
        # Overlap: repeat the last piece of this window if it is short and the window had more than one piece
        # (guarantees progress).
        last_len = pieces[j][1] - pieces[j][0]
        i = j if (j > i and last_len <= overlap) else j + 1
    return windows


def chunk_document(
    doc: Document,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    overlap_chars = max(0, min(overlap_chars, max_chars - 1))
    text = doc.text
    chunks = []
    for n, (s, e) in enumerate(_windows(_paragraph_spans(text), max_chars, overlap_chars)):
        body = text[s:e]
        chunks.append(
            Chunk(
                chunk_id=f"{doc.source}#{n:04d}",
                source=doc.source,
                title=doc.title,
                mtime=doc.mtime,
                char_start=s,
                char_end=e,
                text=body,
                dates_in_text=extract_dates(body),
            )
        )
    return chunks
