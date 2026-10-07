"""Source metadata (spec 4.3): front matter > same-folder _collection.json > defaults."""

import json

import pytest

from common.schema import CHUNK_OPERATING_KEYS, CHUNK_SOURCE_KEYS
from retrieval.embedder import HashEmbedder
from retrieval.index import Retriever, build_index
from retrieval.source_meta import parse_front_matter, resolve_source_meta


# ---------------------------------------------------------------- parse_front_matter


def test_parse_front_matter_lists_and_strings():
    text = "---\nsource_id: a-1\ntitle: 제목: 부제\nabout: [가, 나 ,, 다 ]\nempty_list: []\n---\n# 본문\n\n내용\n"
    meta, body = parse_front_matter(text)
    assert meta == {
        "source_id": "a-1",
        "title": "제목: 부제",  # split on the first ':' only
        "about": ["가", "나", "다"],
        "empty_list": [],
    }
    assert body == "# 본문\n\n내용\n"


def _fm(line):
    return parse_front_matter(f"---\n{line}\n---\n본문")[0]


@pytest.mark.parametrize(
    "line, key, expected",
    [
        ('source_type: "official"', "source_type", "official"),
        ('about: ["혜화", "혜화역"]', "about", ["혜화", "혜화역"]),
        ('about: ["a, b", "c"]', "about", ["a, b", "c"]),
        ('about: [" 공백 ", ""]', "about", ["공백"]),
        ("about: [a, b]", "about", ["a", "b"]),
        ('title: "[공지] a: b"', "title", "[공지] a: b"),
        ('title: "abc', "title", '"abc'),
        ('published: "2026-01-01"', "published", "2026-01-01"),
        ("url: 'https://example.invalid/a'", "url", "'https://example.invalid/a'"),  # single quotes stay
        ("about: [1, 2]", "about", ["1", "2"]),  # JSON list of non-strings -> comma split
        ('about: ["a", b]', "about", ['"a"', "b"]),  # broken JSON -> comma split as written
    ],
)
def test_parse_front_matter_json_values(line, key, expected):
    assert _fm(line)[key] == expected


def test_json_quoted_published_resolves():
    assert resolve_source_meta(_fm('published: "2026-01-01"'), {})["published"] == "2026-01-01"


def test_bracketed_title_stays_a_string(tmp_path):
    # Unquoted, the comma-split fallback applies (the contract rule); quoted as JSON, the title stays whole.
    meta, _ = parse_front_matter("---\ntitle: [공지] 변경 [최종]\n---\n본문")
    assert meta["title"] == ["공지] 변경 [최종"]
    root = tmp_path / "in"
    root.mkdir()
    (root / "a.md").write_text("---\ntitle: [공지] 변경 [최종]\n---\n공지 본문.\n", encoding="utf-8")
    (root / "b.md").write_text('---\ntitle: "[공지] 10월 휴궁 조정"\n---\n휴궁 본문.\n', encoding="utf-8")
    build_index(root, tmp_path / "idx", HashEmbedder())
    r = Retriever.load(tmp_path / "idx", HashEmbedder())
    titles = {c["source"]: c["title"] for c in r.chunks}
    assert titles == {"a.md": "공지] 변경 [최종", "b.md": "[공지] 10월 휴궁 조정"}


def test_lists_in_string_fields_are_joined():
    meta = resolve_source_meta(_fm("kind: operating") | _fm("hours: [09:00~12:00, 13:00~18:00]")
                               | _fm('closed: ["월", "화"]') | _fm("publisher: []") | _fm("place_ids: [fx-02]"), {})
    assert meta["hours"] == "09:00~12:00, 13:00~18:00"
    assert meta["closed"] == "월, 화"
    assert meta["publisher"] == ""  # [] is an empty value
    assert meta["place_ids"] == ["fx-02"]
    coll = resolve_source_meta({"kind": "operating"}, {"hours": ["10:00", "20:00"]})
    assert coll["hours"] == "10:00, 20:00"
    from retrieval.source_meta import document_title
    assert document_title(_fm('title: ["가", "나"]')) == "가, 나"


def test_json_front_matter_through_index(tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    (root / "hyehwa.md").write_text(
        '---\nsource_id: "src-hyehwa"\ntitle: "혜화 이름 유래"\npublisher: "가상 지명위원회"\n'
        'source_type: "official"\npublished: "2026-01-01"\nurl: ""\nprovenance: "synthetic"\nkind: "origin"\n'
        'about: ["혜화", "혜화역"]\n---\n혜화라는 이름은 가상의 유래를 가진다.\n',
        encoding="utf-8",
    )
    build_index(root, tmp_path / "idx", HashEmbedder())
    hit = Retriever.load(tmp_path / "idx", HashEmbedder()).query("혜화 이름 유래", k=1)[0]
    assert hit["source_type"] == "official" and hit["kind"] == "origin" and hit["provenance"] == "synthetic"
    assert hit["source_id"] == "src-hyehwa" and hit["publisher"] == "가상 지명위원회"
    assert hit["published"] == "2026-01-01" and hit["url"] == "" and hit["title"] == "혜화 이름 유래"
    assert hit["about"] == ["혜화", "혜화역"]
    for key in CHUNK_SOURCE_KEYS:
        values = hit[key] if isinstance(hit[key], list) else [hit[key]]
        assert all('"' not in v for v in values), (key, hit[key])


def test_unclosed_front_matter_warns(caplog):
    with caplog.at_level("WARNING", logger="retrieval"):
        parse_front_matter("---\nsource_id: x\n본문\n")
    assert any(r.levelname == "WARNING" for r in caplog.records)
    caplog.clear()
    with caplog.at_level("WARNING", logger="retrieval"):
        parse_front_matter("# 머리 정보 없음\n")
    assert not caplog.records


def test_closing_line_with_trailing_spaces():
    meta, body = parse_front_matter("---\nsource_id: x\n---   \n본문")
    assert meta == {"source_id": "x"} and body == "본문"


@pytest.mark.parametrize("value, expected", [("2026-13-45", ""), ("2026-02-30", ""), ("2024-02-29", "2024-02-29")])
def test_published_must_be_a_real_date(value, expected):
    assert resolve_source_meta({"published": value}, {})["published"] == expected


def test_parse_front_matter_empty_value_is_empty_string():
    meta, _ = parse_front_matter("---\nurl:\npublisher:   \n---\n본문")
    assert meta == {"url": "", "publisher": ""}


def test_parse_front_matter_absent_or_unclosed_returns_original():
    plain = "# 제목\n\nsource_id: x\n"
    assert parse_front_matter(plain) == ({}, plain)
    unclosed = "---\nsource_id: x\n본문인데 닫는 줄이 없다\n"
    assert parse_front_matter(unclosed) == ({}, unclosed)
    not_first = "\n---\nsource_id: x\n---\n본문"
    assert parse_front_matter(not_first) == ({}, not_first)
    assert parse_front_matter("") == ({}, "")


# ---------------------------------------------------------------- resolve_source_meta


def test_resolve_defaults_when_nothing_given():
    meta = resolve_source_meta({}, {})
    assert list(meta) == list(CHUNK_SOURCE_KEYS)
    assert meta == {
        "source_id": "", "publisher": "", "source_type": "informal", "published": "", "url": "",
        "provenance": "", "kind": "other", "about": [],
    }


def test_resolve_normalizes_values():
    meta = resolve_source_meta(
        {"source_type": "rumor", "kind": "story", "published": "2026-3-1", "provenance": "made-up",
         "about": "달무리나루"},
        {},
    )
    assert meta["source_type"] == "informal"
    assert meta["kind"] == "other"
    assert meta["published"] == ""
    assert meta["provenance"] == ""
    assert meta["about"] == ["달무리나루"]


def test_resolve_operating_keys_only_for_operating():
    op = resolve_source_meta({"kind": "operating", "place_ids": ["fx-02"], "hours": "09:00~18:00"}, {})
    assert op["place_ids"] == ["fx-02"] and op["hours"] == "09:00~18:00" and op["closed"] == ""
    other = resolve_source_meta({"kind": "origin", "place_ids": ["fx-02"], "hours": "x"}, {})
    for key in CHUNK_OPERATING_KEYS:
        assert key not in other


def test_resolve_order_and_empty_values_fall_through():
    fm = {"publisher": "머리 정보 발행처", "url": "", "about": []}
    coll = {"publisher": "묶음 발행처", "url": "https://example.invalid/x", "about": ["묶음 이름"],
            "provenance": "synthetic", "source_type": 3}
    meta = resolve_source_meta(fm, coll)
    assert meta["publisher"] == "머리 정보 발행처"
    assert meta["url"] == "https://example.invalid/x"
    assert meta["about"] == ["묶음 이름"]
    assert meta["provenance"] == "synthetic"
    assert meta["source_type"] == "informal"  # non-string collection value counts as no value


# ---------------------------------------------------------------- through the index


def _chunks_of(retriever, source):
    return [c for c in retriever.chunks if c["source"] == source]


@pytest.fixture()
def mixed_index(tmp_path):
    root = tmp_path / "in"
    with_coll = root / "with_coll"
    no_coll = root / "no_coll"
    with_coll.mkdir(parents=True)
    no_coll.mkdir(parents=True)
    (with_coll / "_collection.json").write_text(
        json.dumps({"publisher": "묶음 발행처", "provenance": "synthetic", "url": "https://example.invalid/c",
                    "source_type": "media", "kind": "appearance", "title": "묶음 제목"}, ensure_ascii=False),
        encoding="utf-8",
    )
    full = "---\nsource_id: w-full\ntitle: 머리 제목\npublisher: 머리 발행처\nsource_type: official\n" \
           "published: 2025-01-02\nurl:\nprovenance: real\nkind: origin\nabout: [가람]\n---\n# 본문 제목\n\n가람 이야기 본문.\n"
    (with_coll / "full.md").write_text(full, encoding="utf-8")
    (with_coll / "partial.md").write_text("---\nsource_id: w-part\n---\n누리 이야기 본문.\n", encoding="utf-8")
    (with_coll / "bare.md").write_text("# 맨 문서\n\n다솜 이야기 본문.\n", encoding="utf-8")
    (with_coll / "note.txt").write_text("한결 이야기 본문.\n", encoding="utf-8")
    (no_coll / "bare.md").write_text("# 맨 문서\n\n보람 이야기 본문.\n", encoding="utf-8")
    (no_coll / "partial.md").write_text("---\nsource_id: n-part\nurl:\nkind: operating\nplace_ids: [p-1]\n---\n"
                                        "새봄 운영 본문.\n", encoding="utf-8")
    (no_coll / "note.txt").write_text("이슬 이야기 본문.\n", encoding="utf-8")
    idx = tmp_path / "idx"
    manifest = build_index(root, idx, HashEmbedder())
    return manifest, Retriever.load(idx, HashEmbedder())


def test_fill_order_front_matter_then_collection_then_defaults(mixed_index):
    manifest, r = mixed_index
    for c in r.chunks:
        for key in CHUNK_SOURCE_KEYS:
            assert key in c, (c["source"], key)

    full = _chunks_of(r, "with_coll/full.md")[0]
    assert full["title"] == "머리 제목"
    assert full["source_id"] == "w-full"
    assert full["publisher"] == "머리 발행처"
    assert full["source_type"] == "official"
    assert full["published"] == "2025-01-02"
    assert full["url"] == "https://example.invalid/c"  # empty in front matter -> collection
    assert full["provenance"] == "real"
    assert full["kind"] == "origin"
    assert full["about"] == ["가람"]

    part = _chunks_of(r, "with_coll/partial.md")[0]
    assert part["source_id"] == "w-part"
    assert part["publisher"] == "묶음 발행처"
    assert part["source_type"] == "media"
    assert part["kind"] == "appearance"
    assert part["provenance"] == "synthetic"
    assert part["title"] == "partial.md"  # collection title is not a document title

    bare = _chunks_of(r, "with_coll/bare.md")[0]
    assert bare["title"] == "맨 문서"
    assert bare["source_id"] == "" and bare["publisher"] == "묶음 발행처"

    txt = _chunks_of(r, "with_coll/note.txt")[0]
    assert txt["publisher"] == "묶음 발행처" and txt["kind"] == "appearance" and txt["source_type"] == "media"


def test_defaults_without_collection(mixed_index):
    _, r = mixed_index
    for src in ("no_coll/bare.md", "no_coll/note.txt"):
        c = _chunks_of(r, src)[0]
        assert c["source_type"] == "informal" and c["kind"] == "other"
        assert c["source_id"] == "" and c["publisher"] == "" and c["url"] == ""
        assert c["provenance"] == "" and c["published"] == "" and c["about"] == []
        for key in CHUNK_OPERATING_KEYS:
            assert key not in c
    part = _chunks_of(r, "no_coll/partial.md")[0]
    assert part["source_id"] == "n-part" and part["url"] == "" and part["kind"] == "operating"
    assert part["place_ids"] == ["p-1"] and part["hours"] == "" and part["closed"] == ""
    assert part["source_type"] == "informal" and part["provenance"] == ""


def test_front_matter_lines_not_in_chunk_text_and_offsets_hold(mixed_index):
    _, r = mixed_index
    full = _chunks_of(r, "with_coll/full.md")
    assert full
    for c in full:
        assert "source_id:" not in c["text"] and "---" not in c["text"]
    assert full[0]["text"].startswith("# 본문 제목")
    assert full[0]["char_start"] == 0


def test_collection_file_is_skipped_not_indexed(mixed_index):
    manifest, r = mixed_index
    assert {"path": "with_coll/_collection.json", "reason": "collection defaults"} in manifest["skipped"]
    assert manifest["doc_count"] == 7
    assert not any(c["source"].endswith("_collection.json") for c in r.chunks)


def test_extra_front_matter_keys_are_ignored(tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    text = ("---\nsource_id: x-1\ntitle: 추가 키 자료\nsource_type: official\npublished: 2020-01-01\n"
            "published_precision: year\nline: 2호선\nstation_id: 0201\nkind: operating\nplace_ids: [p-9]\n"
            "hours: 09:00~18:00\nclosed: 없음\n---\n여울 역 안내 본문.\n")
    (root / "extra.md").write_text(text, encoding="utf-8")
    meta, _ = parse_front_matter(text)
    assert meta["published_precision"] == "year" and meta["line"] == "2호선" and meta["station_id"] == "0201"
    manifest = build_index(root, tmp_path / "idx", HashEmbedder())
    assert manifest["doc_count"] == 1 and manifest["skipped"] == []
    r = Retriever.load(tmp_path / "idx", HashEmbedder())
    base = {"chunk_id", "source", "title", "text", "char_start", "char_end", "dates_in_text", "mtime"}
    allowed = base | set(CHUNK_SOURCE_KEYS) | set(CHUNK_OPERATING_KEYS)
    for c in r.chunks:
        assert set(c) - {"tokens"} == allowed
        for key in ("published_precision", "line", "station_id"):
            assert key not in c
    assert r.chunks[0]["source_id"] == "x-1" and r.chunks[0]["place_ids"] == ["p-9"]
    hit = r.query("여울 역 안내", k=1)[0]
    assert "station_id" not in hit and "line" not in hit


def test_offsets_index_into_body_without_front_matter(common_fixtures):
    from retrieval.chunker import chunk_document
    from retrieval.loader import load_documents

    docs, _ = load_documents(common_fixtures / "sources")
    assert len(docs) == 10
    for d in docs:
        assert "source_id:" not in d.text and "---" not in d.text
        chunks = chunk_document(d)
        assert chunks
        for c in chunks:
            assert d.text[c.char_start:c.char_end] == c.text


def test_deeply_nested_bracket_value_falls_back():
    deep = "[" * 100000 + "]" * 100000
    meta, body = parse_front_matter(f"---\nabout: {deep}\n---\n본문")
    assert body == "본문"
    assert meta["about"] == ["[" * 99999 + "]" * 99999]


def test_unclosed_front_matter_warning_names_the_file(tmp_path, caplog):
    root = tmp_path / "in"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "open.md").write_text("---\nsource_id: x\n열린 머리 정보 본문.\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="retrieval"):
        build_index(root, tmp_path / "idx", HashEmbedder())
    assert any("sub/open.md" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert parse_front_matter("---\nsource_id: x\n본문\n") == ({}, "---\nsource_id: x\n본문\n")
