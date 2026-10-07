"""Tool interface between the loop and the tools (spec 4.2).

A tool is `run(args: dict, ctx: RunContext, deps: Deps) -> ToolResult`.
- The model never calls a tool; the loop runs plan steps in order through a `ToolRegistry`.
- Tools pass data through fixed `RunContext` keys, so a plan never refers to an earlier step's output.
- Tools reach the outside only through `Deps`; tests swap in fakes.
- `tools.register_all(registry)` registers the eleven tools; only the names of spec 2.2 are accepted, and each
  tool's argument format must be the contract one (`TOOL_ARGS`).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Callable

from common import limits
from common.schema import (
    KIND_OK,
    KIND_TOOL_ERROR,
    RESULT_KINDS,
    TOOL_NAMES,
    Record,
    SchemaError,
    check_in,
)

# ---------------------------------------------------------------- ToolResult


@dataclass(kw_only=True)
class ToolResult(Record):
    """`{"ok", "kind", "data", "error"}`. `error` is one line or empty (newlines are folded into spaces)."""

    ok: bool
    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise SchemaError(f"ToolResult.ok: expected true or false, got {self.ok!r}")
        check_in(self.kind, RESULT_KINDS, "ToolResult.kind")
        if not isinstance(self.data, dict):
            raise SchemaError(f"ToolResult.data: expected an object, got {type(self.data).__name__}")
        if not isinstance(self.error, str):
            raise SchemaError(f"ToolResult.error: expected a string, got {type(self.error).__name__}")
        self.error = " ".join(self.error.split())

    @property
    def needs_replan(self) -> bool:
        """Only `ok` false with kind TOOL_ERROR makes the loop fix the remaining plan (BLOCKED_BY_POLICY and
        DENIED_BY_SANDBOX are facts to record, not plan errors)."""
        return not self.ok and self.kind == KIND_TOOL_ERROR

    @classmethod
    def success(cls, data: dict[str, Any] | None = None) -> ToolResult:
        return cls(ok=True, kind=KIND_OK, data=dict(data or {}))

    @classmethod
    def tool_error(cls, message: str, data: dict[str, Any] | None = None) -> ToolResult:
        return cls(ok=False, kind=KIND_TOOL_ERROR, data=dict(data or {}), error=message)


# ---------------------------------------------------------------- RunContext

NO_PLACE_KEY = "_"  # `origins` / `graded` key for a question without places

RUN_CONTEXT_KEYS = (
    "run_id", "request", "run_dir", "publish_repo",
    "goal", "places", "excluded", "evidence", "operating_evidence", "origins", "graded", "search_results",
    "input_files", "read_files", "course", "warnings", "unknowns",
)


@dataclass(kw_only=True)
class RunContext(Record):
    """Keys the tools read and write (spec 4.2 table). Values are plain JSON-ready dicts and lists.

    run_id, request      loop                   the run's id and the user request text (save_course copies them)
    run_dir              loop                   absolute path of /hackathon/output/<run_id>/ (save_course writes here)
    publish_repo         loop                   "owner/repo" from env PUBLISH_REPO (request_publish builds the URL);
                                                the auth header is added by the loop's Deps.http_post_json, not the tool
    goal                 loop (from the plan)   4.5 goal dict
    places, excluded     select_places          ordered place dicts; each later gets `station` from lookup_station.
                                                excluded: [{"place_id", "reason"}]
    evidence             lookup_origin          place_id -> name -> chunk dicts
    operating_evidence   lookup_operating       place_id -> chunk dicts
    origins              organize_names         place_id (or NO_PLACE_KEY) -> origin claim dicts
    graded               grade_evidence         place_id (or NO_PLACE_KEY) -> {"origins", "conflicts", "operating",
                                                "stale"} shaped as course.json (4.6)
    search_results       search_db              chunk dicts
    input_files          list_input             [{"path", "size"}], path relative to /hackathon/input
    read_files           read_file              absolute path -> {"kind", "text", "front_matter", "dates", "entries"}
    course               save_course            course dict (course.json), read by request_publish
    warnings, unknowns   every tool             lists of one-line strings
    """

    run_id: str = ""
    request: str = ""
    run_dir: str = ""
    publish_repo: str = ""
    goal: dict[str, Any] = field(default_factory=dict)
    places: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, dict[str, list[dict[str, Any]]]] = field(default_factory=dict)
    operating_evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    origins: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    graded: dict[str, dict[str, Any]] = field(default_factory=dict)
    search_results: list[dict[str, Any]] = field(default_factory=list)
    input_files: list[dict[str, Any]] = field(default_factory=list)
    read_files: dict[str, dict[str, Any]] = field(default_factory=dict)
    course: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)

    _optional = frozenset(RUN_CONTEXT_KEYS)  # a snapshot may carry only the keys filled so far


# ---------------------------------------------------------------- Deps

DEPS_NAMES = ("search", "get_chunk", "chunks_where", "theme_packs", "chat", "http_post_json", "read_path", "now")

# Deps.http_post_json `error` values and the markers that decide them (2.4)
HTTP_ERROR_TUNNEL_403 = "TUNNEL_403"  # the proxy refused the CONNECT tunnel (policy block)
HTTP_ERROR_NETWORK = "NETWORK"  # any other connection error
HTTP_POST_ERRORS = (HTTP_ERROR_TUNNEL_403, HTTP_ERROR_NETWORK)
TUNNEL_403_MARKER = "Tunnel connection failed: 403"  # in the urllib exception message -> TUNNEL_403
POLICY_DENIED_MARKER = "policy_denied"  # HTTP 403 body containing this -> BLOCKED_BY_POLICY


@dataclass(frozen=True, kw_only=True)
class Deps:
    """The only ways a tool meets the outside (spec 4.2). Tests pass fakes.

    search(query, k)                    -> chunk dicts (4.3 chunk keys); real: retrieval Retriever.query
    get_chunk(chunk_id)                 -> chunk dict or None
    chunks_where(kind, place_id)        -> every chunk of that kind whose place_ids holds the place
    theme_packs()                       -> theme pack dicts (4.7), from the index folder's theme_packs/*.json
    chat(messages, purpose)             -> {"text", "usage", "model"}; the loop wraps NimClient and counts calls/tokens
    http_post_json(url, headers, body)  -> {"status": int or None, "body": first 4KB or "", "error": None or
                                           "TUNNEL_403" or "NETWORK"}; never raises, never follows redirects
    read_path(path, max_bytes)          -> folder: [{"name", "is_dir", "size"}], file: bytes; OS errors propagate
    now()                               -> timezone-aware UTC datetime
    """

    search: Callable[[str, int], list[dict[str, Any]]]
    get_chunk: Callable[[str], dict[str, Any] | None]
    chunks_where: Callable[[str, str], list[dict[str, Any]]]
    theme_packs: Callable[[], list[dict[str, Any]]]
    chat: Callable[[list[dict[str, Any]], str], dict[str, Any]]
    http_post_json: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]
    read_path: Callable[[str, int], list[dict[str, Any]] | bytes]
    now: Callable[[], datetime]

    def __post_init__(self) -> None:
        for f in fields(self):
            if not callable(getattr(self, f.name)):
                raise SchemaError(f"Deps.{f.name} must be callable")


# ---------------------------------------------------------------- argument formats (4.2 "도구별 인자")

ARG_TYPES = ("str", "int", "list[str]", "list[dict]", "abs_path")


@dataclass(frozen=True, kw_only=True)
class ArgSpec:
    """Format of one plan argument. Only arguments the spec gives a default for are optional."""

    type: str
    required: bool = True
    nullable: bool = False
    default: Any = None  # for optional arguments; list types store a tuple and hand out a fresh list
    item_keys: tuple[str, ...] = ()  # list[dict]: exact keys of every item (string values)

    def __post_init__(self) -> None:
        check_in(self.type, ARG_TYPES, "ArgSpec.type")

    def fresh_default(self) -> Any:
        if self.type.startswith("list"):
            return [copy.deepcopy(v) for v in (self.default or ())]
        return copy.deepcopy(self.default)

    def problems(self, value: Any, where: str) -> list[str]:
        if value is None:
            return [] if self.nullable else [f"{where}: null is not allowed"]
        if self.type == "str":
            return [] if isinstance(value, str) else [f"{where}: expected a string"]
        if self.type == "int":
            ok = isinstance(value, int) and not isinstance(value, bool)
            return [] if ok else [f"{where}: expected an integer"]
        if self.type == "abs_path":
            # Only the form is checked here; paths outside /hackathon/ are the tool's OUT_OF_SCOPE result.
            ok = isinstance(value, str) and value.startswith("/")
            return [] if ok else [f"{where}: expected an absolute path"]
        if self.type == "list[str]":
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
            return [] if ok else [f"{where}: expected a list of strings"]
        if not isinstance(value, list):  # list[dict]
            return [f"{where}: expected a list of objects"]
        problems: list[str] = []
        for i, item in enumerate(value):
            at = f"{where}[{i}]"
            if not isinstance(item, dict):
                problems.append(f"{at}: expected an object")
                continue
            missing = [k for k in self.item_keys if k not in item]
            unknown = [k for k in item if k not in self.item_keys]
            not_str = [k for k in self.item_keys if k in item and not isinstance(item[k], str)]
            if missing:
                problems.append(f"{at}: missing keys {missing}")
            if unknown:
                problems.append(f"{at}: unknown keys {unknown}")
            if not_str:
                problems.append(f"{at}: expected string values for {not_str}")
        return problems


TOOL_ARGS: dict[str, dict[str, ArgSpec]] = {
    "select_places": {
        "pack_id": ArgSpec(type="str", required=False, default=""),  # may be empty
        "candidate_place_ids": ArgSpec(type="list[str]", required=False, default=()),  # empty = every place
        "free_places": ArgSpec(type="list[dict]", required=False, default=(), item_keys=("name", "note")),
        "time_budget_min": ArgSpec(type="int", nullable=True, required=False, default=None),
        "start": ArgSpec(type="str", required=False, default=""),  # station or place name, may be empty
    },
    "lookup_station": {},
    "lookup_origin": {"k": ArgSpec(type="int", required=False, default=limits.ORIGIN_K_DEFAULT)},
    "lookup_operating": {},
    "organize_names": {},
    "grade_evidence": {},
    "save_course": {},
    "request_publish": {"title": ArgSpec(type="str", required=False, default="")},
    "search_db": {"query": ArgSpec(type="str"), "k": ArgSpec(type="int", required=False, default=limits.ORIGIN_K_DEFAULT)},
    "list_input": {},
    "read_file": {"path": ArgSpec(type="abs_path")},
}


# ---------------------------------------------------------------- registry


@dataclass(kw_only=True)
class ToolSpec:
    """A registered tool. `args` defaults to the contract format of `name` (TOOL_ARGS)."""

    name: str
    run: Callable[[dict[str, Any], RunContext, Deps], ToolResult]
    args: dict[str, ArgSpec] | None = None
    description: str = ""  # one line for the plan prompt

    def __post_init__(self) -> None:
        if not callable(self.run):
            raise SchemaError(f"tool {self.name!r}: run must be callable")
        if self.args is None:
            self.args = dict(TOOL_ARGS.get(self.name, {}))


class ToolRegistry:
    """Name -> tool. Accepts only the eleven names of spec 2.2, each with its contract argument format."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not isinstance(spec, ToolSpec):
            raise SchemaError(f"register() takes a ToolSpec, got {type(spec).__name__}")
        check_in(spec.name, TOOL_NAMES, "tool name")
        if spec.name in self._specs:
            raise SchemaError(f"tool {spec.name!r} is already registered")
        if spec.args != TOOL_ARGS[spec.name]:
            raise SchemaError(f"tool {spec.name!r}: args differ from the contract format (spec 4.2)")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        """The registered tool; KeyError if it is not registered."""
        return self._specs[name]

    def names(self) -> list[str]:
        """Registered names in spec 2.2 order."""
        return [n for n in TOOL_NAMES if n in self._specs]

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def check_args(self, name: str, args: Any) -> list[str]:
        """Plan-check problems for one step (empty list = fine): unknown or unregistered tool, args that are not an
        object, unknown arguments, missing required arguments, wrong types."""
        if name not in TOOL_NAMES:
            return [f"tool name {name!r} is not one of {list(TOOL_NAMES)}"]
        if name not in self._specs:
            return [f"{name}: tool is not registered"]
        if not isinstance(args, dict):
            return [f"{name}: args must be an object"]
        spec_args = self._specs[name].args or {}
        problems = [f"{name}.{k}: unknown argument" for k in args if k not in spec_args]
        for arg, spec in spec_args.items():
            where = f"{name}.{arg}"
            if arg not in args:
                if spec.required:
                    problems.append(f"{where}: missing required argument")
                continue
            problems.extend(spec.problems(args[arg], where))
        return problems

    def with_defaults(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """A copy of `args` with the spec defaults filled in for absent optional arguments."""
        out = dict(args)
        for arg, spec in (self.get(name).args or {}).items():
            if arg not in out and not spec.required:
                out[arg] = spec.fresh_default()
        return out

    def describe(self) -> list[dict[str, Any]]:
        """Registered tools with their argument formats, in spec 2.2 order (input for the plan prompt)."""
        out = []
        for name in self.names():
            spec = self._specs[name]
            args: dict[str, Any] = {}
            for arg, a in (spec.args or {}).items():
                entry: dict[str, Any] = {"type": a.type, "required": a.required, "nullable": a.nullable}
                if not a.required:
                    entry["default"] = a.fresh_default()
                if a.item_keys:
                    entry["item_keys"] = list(a.item_keys)
                args[arg] = entry
            out.append({"name": name, "description": spec.description, "args": args})
        return out
