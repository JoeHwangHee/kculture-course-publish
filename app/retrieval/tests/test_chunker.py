import re

import pytest

from retrieval.chunker import chunk_document, extract_dates
from retrieval.loader import Document


@pytest.mark.parametrize(
    "text, expected",
    [
        ("작성일: 2019-03-01", ["2019-03-01"]),
        ("작성일 2019-3-5 기준", ["2019-03-05"]),
        ("작성일: 2026.03.01.", ["2026-03-01"]),
        ("2026. 3. 1. 개정", ["2026-03-01"]),
        ("2019년 3월 1일에 썼다", ["2019-03-01"]),
        ("1446년 9월에 반포", ["1446-09"]),
        ("세종은 1443년에 창제", ["1443"]),
        ("2019년과 2026년, 그리고 2019년", ["2019", "2026"]),
        ("2019-13-01 은 잘못된 날짜", []),
        ("12345년 같은 숫자는 연도가 아니다", []),
        ("전화 02-1234-5678", []),
        ("날짜 없음", []),
    ],
)
def test_extract_dates_normalizes(text, expected):
    assert extract_dates(text) == expected


def test_extract_dates_does_not_double_count_long_form():
    # "2019년 3월 1일" must not also yield "2019" or "2019-03"
    assert extract_dates("2019년 3월 1일, 그리고 1443년") == ["2019-03-01", "1443"]


def _doc(text, source="a/b.md", title="b.md"):
    return Document(source=source, text=text, title=title, mtime="2026-01-01T00:00:00+00:00", fmt="md")


def test_chunk_invariant_and_metadata():
    paras = [f"문단 {i}. " + ("가나다라마바사 " * 12) for i in range(10)]
    text = "\n\n".join(paras)
    doc = _doc(text)
    chunks = chunk_document(doc, max_chars=300, overlap_chars=120)
    assert len(chunks) >= 2
    for i, c in enumerate(chunks):
        assert text[c.char_start:c.char_end] == c.text
        assert c.char_end - c.char_start <= 300
        assert c.source == "a/b.md"
        assert c.title == "b.md"
        assert c.mtime == "2026-01-01T00:00:00+00:00"
        assert re.match(r".+#\d{4}$", c.chunk_id)
    ids = [c.chunk_id for c in chunks]
    assert len(set(ids)) == len(ids)
    # coverage: every paragraph appears in some chunk
    for p in paras:
        assert any(p.strip() in c.text for c in chunks)
    # some overlap between consecutive chunks
    assert any(chunks[i + 1].char_start < chunks[i].char_end for i in range(len(chunks) - 1))


def test_long_paragraph_is_split_and_terminates():
    text = "가" * 1300
    chunks = chunk_document(_doc(text), max_chars=500, overlap_chars=50)
    assert len(chunks) >= 3
    for c in chunks:
        assert text[c.char_start:c.char_end] == c.text
        assert len(c.text) <= 500
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == 1300


def test_dates_are_per_chunk():
    text = "첫 문단 2019-03-01 작성.\n\n" + ("나" * 600) + "\n\n마지막 문단 2026년 3월 1일 개정."
    chunks = chunk_document(_doc(text), max_chars=500, overlap_chars=0)
    assert "2019-03-01" in chunks[0].dates_in_text
    assert "2026-03-01" in chunks[-1].dates_in_text
    assert "2026-03-01" not in chunks[0].dates_in_text


def test_empty_document_has_no_chunks():
    assert chunk_document(_doc("   \n\n  ")) == []
