"""Tool interface of spec 4.2: ToolResult, RunContext, Deps, ToolSpec/ArgSpec and ToolRegistry."""

import json
from dataclasses import fields
from datetime import datetime, timezone

import pytest

from common import limits
from common.schema import TOOL_NAMES, SchemaError
from common.tooling import (
    DEPS_NAMES,
    HTTP_ERROR_NETWORK,
    HTTP_ERROR_TUNNEL_403,
    NO_PLACE_KEY,
    POLICY_DENIED_MARKER,
    RUN_CONTEXT_KEYS,
    TOOL_ARGS,
    TUNNEL_403_MARKER,
    ArgSpec,
    Deps,
    RunContext,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)


def _fake_deps(**overrides):
    funcs = dict(
        search=lambda query, k: [],
        get_chunk=lambda chunk_id: None,
        chunks_where=lambda kind, place_id: [],
        theme_packs=lambda: [],
        chat=lambda messages, purpose: {"text": "{}", "usage": {}, "model": "fake"},
        http_post_json=lambda url, headers, body: {"status": None, "body": "", "error": "NETWORK"},
        read_path=lambda path, max_bytes: b"",
        now=lambda: datetime(2026, 10, 7, 3, 31, 5, tzinfo=timezone.utc),
    )
    funcs.update(overrides)
    return Deps(**funcs)


def _fake_search_db(args, ctx, deps):
    hits = deps.search(args["query"], args["k"])
    ctx.search_results = hits
    return ToolResult(ok=True, kind="OK", data={"count": len(hits)})


# ---------------------------------------------------------------- ToolResult


def test_tool_result_round_trip_and_keys():
    res = ToolResult(ok=True, kind="OK", data={"places": ["fx-01"]})
    d = res.to_dict()
    assert d == {"ok": True, "kind": "OK", "data": {"places": ["fx-01"]}, "error": ""}
    assert ToolResult.from_dict(json.loads(json.dumps(d))) == res
    err = ToolResult.tool_error("index missing")
    assert err.to_dict() == {"ok": False, "kind": "TOOL_ERROR", "data": {}, "error": "index missing"}
    assert ToolResult.success({"n": 1}) == ToolResult(ok=True, kind="OK", data={"n": 1})


@pytest.mark.parametrize("kind", ["ok", "ERROR", "", "PUBLISHED"])
def test_tool_result_kind_must_be_in_contract(kind):
    with pytest.raises(SchemaError):
        ToolResult(ok=False, kind=kind)


def test_tool_result_error_is_a_single_line():
    res = ToolResult(ok=False, kind="TOOL_ERROR", error="first line\n  second\tline\r\n")
    assert res.error == "first line second line"
    with pytest.raises(SchemaError):
        ToolResult(ok="yes", kind="OK")
    with pytest.raises(SchemaError):
        ToolResult(ok=True, kind="OK", data=["not", "a", "dict"])


def test_only_tool_error_with_ok_false_asks_for_a_plan_fix():
    assert ToolResult(ok=False, kind="TOOL_ERROR").needs_replan
    assert not ToolResult(ok=True, kind="TOOL_ERROR").needs_replan
    for kind in ("BLOCKED_BY_POLICY", "DENIED_BY_SANDBOX", "NOT_FOUND", "OUT_OF_SCOPE", "HTTP_ERROR"):
        assert not ToolResult(ok=False, kind=kind).needs_replan


# ---------------------------------------------------------------- RunContext and Deps


def test_run_context_keys_match_spec_table():
    assert RUN_CONTEXT_KEYS == (
        "run_id", "request", "run_dir", "publish_repo",
        "goal", "places", "excluded", "evidence", "operating_evidence", "origins", "graded", "search_results",
        "input_files", "read_files", "course", "warnings", "unknowns",
    )
    assert tuple(f.name for f in fields(RunContext)) == RUN_CONTEXT_KEYS
    assert NO_PLACE_KEY == "_"


def test_run_context_defaults_are_empty_and_independent():
    a, b = RunContext(), RunContext()
    a.warnings.append("x")
    a.places.append({"place_id": "fx-01"})
    assert b.warnings == [] and b.places == []
    assert a.course is None and a.goal == {}


def test_run_context_round_trip():
    ctx = RunContext(
        goal={"work": "별무리 수호단", "time_budget_min": 180, "start": "새벽솔", "constraints": [],
              "publish_requested": True},
        places=[{"place_id": "fx-01", "station": {"name": "달무리나루", "line": "가상1호선"}}],
        evidence={"fx-01": {"달무리나루": [{"chunk_id": "c1"}]}},
        operating_evidence={"fx-02": [{"chunk_id": "c4"}]},
        origins={NO_PLACE_KEY: [{"name": "달무리나루"}]},
        graded={"fx-01": {"origins": [], "conflicts": [], "operating": {}, "stale": []}},
        input_files=[{"path": "notes/a.md", "size": 12}],
        read_files={"/hackathon/input/notes/a.md": {"kind": "OK", "text": "t", "front_matter": {}, "dates": [],
                                                    "entries": []}},
        warnings=["w"], unknowns=["u"],
    )
    assert RunContext.from_dict(json.loads(json.dumps(ctx.to_dict(), ensure_ascii=False))) == ctx
    assert RunContext.from_dict({}) == RunContext()


def test_deps_holds_exactly_the_eight_functions_of_spec_4_2():
    assert DEPS_NAMES == ("search", "get_chunk", "chunks_where", "theme_packs", "chat", "http_post_json",
                          "read_path", "now")
    assert tuple(f.name for f in fields(Deps)) == DEPS_NAMES
    deps = _fake_deps()
    assert deps.search("q", 3) == []
    assert deps.now().tzinfo is timezone.utc


def test_deps_rejects_missing_or_non_callable():
    with pytest.raises(SchemaError):
        _fake_deps(search="not callable")
    funcs = {name: (lambda *a: None) for name in DEPS_NAMES}
    del funcs["now"]
    with pytest.raises(TypeError):
        Deps(**funcs)


def test_http_post_json_error_values_and_markers():
    assert (HTTP_ERROR_TUNNEL_403, HTTP_ERROR_NETWORK) == ("TUNNEL_403", "NETWORK")
    assert TUNNEL_403_MARKER == "Tunnel connection failed: 403"
    assert POLICY_DENIED_MARKER == "policy_denied"


# ---------------------------------------------------------------- registry


def test_register_fake_tool_lookup_and_run():
    reg = ToolRegistry()
    reg.register(ToolSpec(name="search_db", run=_fake_search_db, description="색인 전체 검색"))
    assert "search_db" in reg and len(reg) == 1
    assert reg.names() == ["search_db"]
    spec = reg.get("search_db")
    assert spec.args == TOOL_ARGS["search_db"]
    ctx = RunContext()
    deps = _fake_deps(search=lambda query, k: [{"chunk_id": f"c{i}"} for i in range(k)])
    res = spec.run({"query": "달무리나루 유래", "k": 2}, ctx, deps)
    assert res == ToolResult(ok=True, kind="OK", data={"count": 2})
    assert [c["chunk_id"] for c in ctx.search_results] == ["c0", "c1"]
    with pytest.raises(KeyError):
        reg.get("read_file")


@pytest.mark.parametrize("name", ["web_search", "", "Search_DB", "search_db ", "run_shell", "publish"])
def test_registry_rejects_names_outside_the_eleven(name):
    reg = ToolRegistry()
    with pytest.raises(SchemaError, match="not one of"):
        reg.register(ToolSpec(name=name, run=_fake_search_db))
    assert len(reg) == 0
    assert reg.check_args(name, {}) != []


def test_registry_rejects_duplicates_non_callables_and_off_contract_args():
    reg = ToolRegistry()
    reg.register(ToolSpec(name="list_input", run=lambda a, c, d: ToolResult.success()))
    with pytest.raises(SchemaError, match="already"):
        reg.register(ToolSpec(name="list_input", run=lambda a, c, d: ToolResult.success()))
    with pytest.raises(SchemaError):
        reg.register(ToolSpec(name="read_file", run="not callable"))
    with pytest.raises(SchemaError, match="contract"):
        reg.register(ToolSpec(name="search_db", run=_fake_search_db, args={"query": ArgSpec(type="str")}))
    with pytest.raises(SchemaError):
        reg.register("search_db")


def test_registry_names_follow_spec_order_and_cover_all_eleven():
    reg = ToolRegistry()
    for name in reversed(TOOL_NAMES):
        reg.register(ToolSpec(name=name, run=lambda a, c, d: ToolResult.success()))
    assert reg.names() == list(TOOL_NAMES)
    assert set(TOOL_ARGS) == set(TOOL_NAMES)
    described = reg.describe()
    assert [d["name"] for d in described] == list(TOOL_NAMES)
    by_name = {d["name"]: d for d in described}
    assert by_name["read_file"]["args"] == {"path": {"type": "abs_path", "required": True, "nullable": False}}
    assert by_name["lookup_origin"]["args"]["k"] == {"type": "int", "required": False, "nullable": False,
                                                     "default": 5}


# ---------------------------------------------------------------- argument check (plan check uses this)

GOOD_SELECT = {"pack_id": "fx-byeolmuri", "candidate_place_ids": [], "free_places": [], "time_budget_min": 180,
               "start": "새벽솔"}


@pytest.fixture()
def reg():
    r = ToolRegistry()
    for name in TOOL_NAMES:
        r.register(ToolSpec(name=name, run=lambda a, c, d: ToolResult.success()))
    return r


@pytest.mark.parametrize("name, args", [
    ("select_places", GOOD_SELECT),
    ("select_places", {**GOOD_SELECT, "pack_id": "", "time_budget_min": None, "start": ""}),
    ("select_places", {k: v for k, v in GOOD_SELECT.items() if k != "free_places"}),
    ("select_places", {**GOOD_SELECT, "candidate_place_ids": ["fx-01", "fx-02"],
                       "free_places": [{"name": "어느 찻집", "note": "자료에서 찾음"}]}),
    ("lookup_origin", {}),
    ("lookup_origin", {"k": 3}),
    ("search_db", {"query": "달무리나루 유래", "k": 5}),
    ("read_file", {"path": "/hackathon/secrets"}),
    ("read_file", {"path": "/etc/passwd"}),  # out-of-scope paths are the tool's OUT_OF_SCOPE, not a plan error
    ("request_publish", {"title": "별무리 수호단 코스"}),
    ("request_publish", {}),
    ("search_db", {"query": "달무리나루 유래"}),
    ("select_places", {}),
    ("select_places", {"pack_id": "fx-byeolmuri", "time_budget_min": 180}),
    ("lookup_station", {}), ("lookup_operating", {}), ("organize_names", {}), ("grade_evidence", {}),
    ("save_course", {}), ("list_input", {}),
])
def test_check_args_accepts_contract_arguments(reg, name, args):
    assert reg.check_args(name, args) == []


@pytest.mark.parametrize("name, args, needle", [
    ("select_places", {**GOOD_SELECT, "time_budget_min": "180"}, "time_budget_min"),
    ("select_places", {**GOOD_SELECT, "time_budget_min": True}, "time_budget_min"),
    ("select_places", {**GOOD_SELECT, "pack_id": None}, "pack_id"),
    ("select_places", {**GOOD_SELECT, "candidate_place_ids": "fx-01"}, "candidate_place_ids"),
    ("select_places", {**GOOD_SELECT, "candidate_place_ids": [1]}, "candidate_place_ids"),
    ("select_places", {**GOOD_SELECT, "free_places": [{"name": "찻집"}]}, "free_places"),
    ("select_places", {**GOOD_SELECT, "free_places": [{"name": "찻집", "note": "", "x": 1}]}, "free_places"),
    ("select_places", {**GOOD_SELECT, "free_places": ["찻집"]}, "free_places"),
    ("select_places", {**GOOD_SELECT, "budget": 180}, "budget"),
    ("lookup_origin", {"k": "5"}, "k"),
    ("search_db", {"k": 5}, "query"),
    ("read_file", {"path": "hackathon/input/a.md"}, "path"),
    ("read_file", {"path": ""}, "path"),
    ("read_file", {}, "path"),
    ("list_input", {"path": "/hackathon/input"}, "path"),
    ("save_course", {"anything": 1}, "anything"),
    ("web_search", {}, "web_search"),
])
def test_check_args_reports_contract_violations(reg, name, args, needle):
    problems = reg.check_args(name, args)
    assert problems, (name, args)
    assert any(needle in p for p in problems), problems


def test_check_args_rejects_non_object_args(reg):
    assert reg.check_args("list_input", None) != []
    assert reg.check_args("list_input", []) != []


def test_check_args_reports_contract_tools_that_are_not_registered():
    problems = ToolRegistry().check_args("lookup_station", {})
    assert len(problems) == 1 and "not registered" in problems[0]


def test_with_defaults_fills_only_spec_defaults(reg):
    assert reg.with_defaults("lookup_origin", {}) == {"k": limits.ORIGIN_K_DEFAULT}
    assert reg.with_defaults("lookup_origin", {"k": 2}) == {"k": 2}
    without_free = {k: v for k, v in GOOD_SELECT.items() if k != "free_places"}
    filled = reg.with_defaults("select_places", without_free)
    assert filled["free_places"] == []
    filled["free_places"].append({"name": "x", "note": ""})
    assert reg.with_defaults("select_places", without_free)["free_places"] == []  # fresh list each time
    assert "free_places" not in without_free  # input is not modified
    assert reg.with_defaults("search_db", {"query": "q", "k": 1}) == {"query": "q", "k": 1}
