import os
import stat

import pytest

from retrieval.errors import InputError
from retrieval.loader import load_documents


def _by_source(docs):
    return {d.source: d for d in docs}


def _skipped(skipped):
    return {s["path"]: s["reason"] for s in skipped}


def test_fixture_corpus_loads_with_relative_paths(fixture_input):
    docs, skipped = load_documents(fixture_input)
    srcs = _by_source(docs)
    assert "hunminjeongeum.md" in srcs
    assert "palace/gyeongbokgung_hours_2019.txt" in srcs
    assert "palace/gyeongbokgung_hours_2026.html" in srcs
    assert "hwaseong_a.json" in srcs and "hwaseong_b.jsonl" in srcs
    assert "misc/meeting_notes.txt" in srcs and "misc/festival.csv" in srcs
    for d in docs:
        assert not os.path.isabs(d.source)
        assert d.mtime.endswith("+00:00")
    assert _skipped(skipped).get("misc/brochure.pdf") == "unsupported"


def test_titles(fixture_input):
    srcs = _by_source(load_documents(fixture_input)[0])
    assert srcs["hunminjeongeum.md"].title == "훈민정음 창제와 반포"
    assert srcs["palace/gyeongbokgung_hours_2026.html"].title == "경복궁 관람 시간 안내 (2026년 개정)"
    assert srcs["palace/gyeongbokgung_hours_2019.txt"].title == "gyeongbokgung_hours_2019.txt"
    assert srcs["hwaseong_a.json"].title == "수원 화성 안내 A"


def test_html_tags_and_scripts_removed(fixture_input):
    srcs = _by_source(load_documents(fixture_input)[0])
    text = srcs["palace/gyeongbokgung_hours_2026.html"].text
    assert "<p>" not in text and "<b>" not in text
    assert "do-not-index" not in text
    assert "font-family" not in text
    assert "3,000원" in text
    assert "\n\n" in text  # block tags become paragraph breaks


def test_json_and_csv_flattened(fixture_input):
    srcs = _by_source(load_documents(fixture_input)[0])
    assert "1796년에 완공" in srcs["hwaseong_a.json"].text
    assert "거중기" in srcs["hwaseong_b.jsonl"].text
    csv_text = srcs["misc/festival.csv"].text
    assert "축제: 진해군항제" in csv_text and "지역: 충청남도 보령시" in csv_text


def test_symlinks_not_followed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.txt").write_text("정상 문서 경복궁", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("밖에 있는 비밀 문서", encoding="utf-8")
    (root / "link_file.txt").symlink_to(outside / "secret.txt")
    (root / "link_inside.txt").symlink_to(root / "real.txt")
    (root / "link_dir").symlink_to(outside, target_is_directory=True)

    docs, skipped = load_documents(root)
    srcs = _by_source(docs)
    assert set(srcs) == {"real.txt"}
    sk = _skipped(skipped)
    assert sk["link_file.txt"] == "symlink"
    assert sk["link_inside.txt"] == "symlink"
    assert sk["link_dir"] == "symlink"
    assert all("밖에 있는" not in d.text for d in docs)


def test_root_given_through_symlinked_parent(tmp_path):
    # Root path itself may traverse a symlink (e.g. tmp dirs on macOS); files inside are still "inside".
    real = tmp_path / "real_root"
    real.mkdir()
    (real / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    alias = tmp_path / "alias_root"
    alias.symlink_to(real, target_is_directory=True)
    docs, skipped = load_documents(alias)
    assert [d.source for d in docs] == ["a.md"]


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_file_and_dir_are_skipped_not_crash(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.txt").write_text("읽을 수 있는 문서", encoding="utf-8")
    locked = root / "locked.txt"
    locked.write_text("읽을 수 없는 문서", encoding="utf-8")
    locked_dir = root / "locked_dir"
    locked_dir.mkdir()
    (locked_dir / "inner.txt").write_text("안쪽 문서", encoding="utf-8")
    locked.chmod(0)
    locked_dir.chmod(0)
    try:
        docs, skipped = load_documents(root)
    finally:
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)
        locked_dir.chmod(stat.S_IRWXU)
    assert [d.source for d in docs] == ["ok.txt"]
    sk = _skipped(skipped)
    assert sk["locked.txt"] == "permission denied"
    assert sk["locked_dir"] == "permission denied"


def test_encodings(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "cp949.txt").write_bytes("경복궁 관람 안내".encode("cp949"))
    (root / "bom.csv").write_bytes("﻿이름,지역\n경복궁,서울\n".encode("utf-8"))
    (root / "binary.txt").write_bytes(bytes([0xFF, 0xFE, 0xFA, 0x80, 0x81]) * 10)
    docs, skipped = load_documents(root)
    srcs = _by_source(docs)
    assert srcs["cp949.txt"].text == "경복궁 관람 안내"
    assert "이름: 경복궁" in srcs["bom.csv"].text
    assert "﻿" not in srcs["bom.csv"].text
    assert _skipped(skipped)["binary.txt"] == "undecodable"


def test_parser_registry_is_extensible(tmp_path, monkeypatch):
    from retrieval import loader

    root = tmp_path / "root"
    root.mkdir()
    (root / "a.xml").write_text("<doc>향원정</doc>", encoding="utf-8")
    docs, skipped = load_documents(root)
    assert docs == [] and _skipped(skipped)["a.xml"] == "unsupported"

    monkeypatch.setattr(loader, "PARSERS", dict(loader.PARSERS))
    loader.register_parser("XML", lambda raw: (raw.replace("<doc>", "").replace("</doc>", ""), "xml 제목"))
    assert ".xml" in loader.supported_extensions()
    docs, skipped = load_documents(root)
    assert [(d.source, d.text, d.title) for d in docs] == [("a.xml", "향원정", "xml 제목")]


def test_missing_root_is_input_error(tmp_path):
    with pytest.raises(InputError):
        load_documents(tmp_path / "nope")
