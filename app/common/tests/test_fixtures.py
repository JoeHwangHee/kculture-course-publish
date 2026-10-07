"""Fake input in app/common/fixtures/ follows the spec 4.7 format and holds the scenarios the tracks develop against.

The front-matter reader here is a test helper only; the real metadata reader belongs to the retrieval track.
"""

import json
import re
from collections import defaultdict

import pytest

from common import FIXTURES_DIR
from common.schema import (
    FRONT_MATTER_KEYS,
    GRADES,
    OPERATING_FRONT_MATTER_KEYS,
    SOURCE_KINDS,
    SOURCE_TYPES,
    ThemePack,
    grade_for_source_type,
)

PACK_DIR = FIXTURES_DIR / "theme_packs"
SOURCES_DIR = FIXTURES_DIR / "sources"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def read_front_matter(text):
    """`---` block of `key: value` lines (lists as `[a, b]`) followed by the body."""
    lines = text.split("\n")
    assert lines[0] == "---", "front matter must start on the first line"
    end = lines.index("---", 1)
    meta = {}
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        key, sep, value = raw.partition(":")
        assert sep, f"not a key: value line: {raw!r}"
        key, value = key.strip(), value.strip()
        assert key not in meta, f"duplicate key {key}"
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [v.strip() for v in inner.split(",")] if inner else []
        else:
            meta[key] = value
    return meta, "\n".join(lines[end + 1:])


@pytest.fixture(scope="module")
def pack_raw():
    files = sorted(PACK_DIR.glob("*.json"))
    assert len(files) == 1, files
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert files[0].stem == data["pack_id"]
    return data


@pytest.fixture(scope="module")
def pack(pack_raw):
    return ThemePack.from_dict(pack_raw)


@pytest.fixture(scope="module")
def sources():
    files = sorted(SOURCES_DIR.glob("*.md"))
    out = {}
    for f in files:
        meta, body = read_front_matter(f.read_text(encoding="utf-8"))
        assert meta["source_id"] == f.stem
        out[f.stem] = (meta, body)
    return out


def _pack_names(pack):
    names = {pack.work_title, *pack.aliases}
    for st in pack.stations:
        names |= {st.name, *st.aliases}
    for p in pack.places:
        names |= {p.current_name, p.in_work_name, *p.old_names}
    names.discard("")
    return names


def _grade_rank(source_type):
    return GRADES.index(grade_for_source_type(source_type))  # 0 = A (highest)


# ---------------------------------------------------------------- theme pack


def test_theme_pack_has_spec_keys_and_sizes(pack_raw, pack):
    assert list(pack_raw) == ["pack_id", "work_title", "aliases", "provenance", "stations", "places"]
    assert pack.provenance == "synthetic"
    assert pack.aliases
    assert len(pack.stations) == 3
    assert len(pack.places) == 6
    for st in pack_raw["stations"]:
        assert {"name", "aliases", "line"} <= set(st)
    for p in pack_raw["places"]:
        assert {"place_id", "current_name", "in_work_name", "scene", "old_names", "station", "stay_min",
                "appearance_source_ids", "priority"} <= set(p)


def test_theme_pack_references_resolve(pack, sources):
    station_names = {st.name for st in pack.stations}
    place_ids = [p.place_id for p in pack.places]
    assert len(set(place_ids)) == len(place_ids)
    for p in pack.places:
        assert p.station in station_names
        assert isinstance(p.priority, int) and not isinstance(p.priority, bool)
        assert isinstance(p.stay_min, int) and p.stay_min > 0
        assert p.appearance_source_ids and set(p.appearance_source_ids) <= set(sources)
        for sid in p.appearance_source_ids:
            assert sources[sid][0]["kind"] == "appearance"
    assert len({p.priority for p in pack.places}) < len(pack.places), "keep one priority tie for the cut rule"


# ---------------------------------------------------------------- sources


def test_ten_sources_with_every_front_matter_key(sources, pack):
    assert len(sources) == 10
    place_ids = {p.place_id for p in pack.places}
    for sid, (meta, body) in sources.items():
        missing = [k for k in FRONT_MATTER_KEYS if k not in meta]
        assert not missing, (sid, missing)
        extra = set(meta) - set(FRONT_MATTER_KEYS) - set(OPERATING_FRONT_MATTER_KEYS)
        assert not extra, (sid, extra)
        assert meta["provenance"] == "synthetic", sid
        assert meta["source_type"] in SOURCE_TYPES, sid
        assert meta["kind"] in SOURCE_KINDS, sid
        assert DATE.match(meta["published"]), sid
        assert meta["url"] == "", sid  # made-up content, no real URL
        assert isinstance(meta["about"], list) and meta["about"], sid
        assert body.strip(), sid
        if meta["kind"] == "operating":
            for k in OPERATING_FRONT_MATTER_KEYS:
                assert k in meta, (sid, k)
            assert isinstance(meta["place_ids"], list) and set(meta["place_ids"]) <= place_ids, sid
            assert meta["hours"] and meta["closed"], sid
        else:
            assert not set(OPERATING_FRONT_MATTER_KEYS) & set(meta), sid


def test_collection_defaults_file(sources):
    data = json.loads((SOURCES_DIR / "_collection.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data
    assert set(data) <= set(FRONT_MATTER_KEYS)
    assert data.get("provenance") == "synthetic"


def test_same_name_with_two_origins_from_different_source_types(sources):
    by_name = defaultdict(list)
    for meta, _ in sources.values():
        if meta["kind"] == "origin":
            for name in meta["about"]:
                by_name[name].append(meta)
    pairs = [name for name, metas in by_name.items() if len({m["source_type"] for m in metas}) >= 2]
    assert pairs, "need one name whose origin is told differently by two source types"


def _operating_groups(sources):
    groups = defaultdict(list)
    for meta, _ in sources.values():
        if meta["kind"] == "operating":
            for pid in meta["place_ids"]:
                groups[pid].append(meta)
    return groups


def test_operating_pairs_cover_both_newest_source_rules(sources):
    """Spec 2.3: newest source wins only if its grade >= every disagreeing source's grade."""
    newest_wins, needs_onsite_check = [], []
    for pid, metas in _operating_groups(sources).items():
        if len(metas) < 2:
            continue
        newest = max(metas, key=lambda m: m["published"])
        disagreeing = [m for m in metas if (m["hours"], m["closed"]) != (newest["hours"], newest["closed"])]
        assert disagreeing, pid
        assert all(m["published"] < newest["published"] for m in disagreeing), pid
        if all(_grade_rank(newest["source_type"]) <= _grade_rank(m["source_type"]) for m in disagreeing):
            newest_wins.append(pid)
        else:
            needs_onsite_check.append(pid)
    assert newest_wins, "need a pair where the newer source has the same or higher grade"
    assert needs_onsite_check, "need a pair where the newer source has a lower grade"
    assert not set(newest_wins) & set(needs_onsite_check)


def test_one_unrelated_source(sources, pack):
    names = _pack_names(pack)
    unrelated = [
        sid for sid, (meta, body) in sources.items()
        if meta["kind"] == "other" and not set(meta["about"]) & names and not any(n in body for n in names)
    ]
    assert len(unrelated) == 1, unrelated


def test_route_source_gives_station_to_place_walking_minutes(sources, pack):
    minutes = re.compile(r"걸어서 약 (\d+)분")
    station_aliases = {a for st in pack.stations for a in st.aliases}
    found = []
    for sid, (meta, body) in sources.items():
        if meta["kind"] not in ("other", "operating"):  # spec 4.7: route info lives in other/operating bodies
            continue
        for line in body.split("\n"):
            m = minutes.search(line)
            if not m:
                continue
            if any(a in line for a in station_aliases) and any(p.current_name in line for p in pack.places):
                found.append((sid, int(m.group(1))))
    assert found, "need a source whose body states walking minutes from a station to a place"
    assert len({sid for sid, _ in found}) == 1
    assert all(1 <= n <= 180 for _, n in found)
