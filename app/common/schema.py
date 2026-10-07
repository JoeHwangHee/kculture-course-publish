"""Contract values and record shapes shared by every track (roadmap spec 2.2, 2.3, 4.2-4.7).

Value names and value sets are copied verbatim from the spec; docs/contracts.md section 6 is their source of truth
once merged. Changing one needs the team lead's approval.

Records are dataclasses whose field names are the JSON keys, in spec order.
- `to_dict()` returns a JSON-ready dict (nested records become dicts).
- `from_dict(data)` rejects unknown keys, missing keys (every key is required on input unless the record lists it in
  `_optional`), wrong primitive types and values outside the closed sets below.
- Constructors check the closed sets and formats too, so a record cannot hold an off-contract value.
Every rejection raises `SchemaError` (a `ValueError`).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import types
import typing
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, ClassVar, Iterable


class SchemaError(ValueError):
    """A value or a record does not match the contract."""


def check_in(value: Any, allowed: Iterable[Any], where: str) -> None:
    """Raise SchemaError unless `value` is one of `allowed` (exact match)."""
    allowed = tuple(allowed)
    if not any(value == a and type(value) is type(a) for a in allowed):
        raise SchemaError(f"{where}: {value!r} is not one of {list(allowed)}")


# ---------------------------------------------------------------- 4.4 run status

STATUS_ANSWERED_LIGHT = "ANSWERED_LIGHT"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_ANSWERED_HEAVY = "ANSWERED_HEAVY"
STATUS_COURSE_SAVED = "COURSE_SAVED"
STATUS_PUBLISH_PENDING_APPROVAL = "PUBLISH_PENDING_APPROVAL"
STATUS_PUBLISHED = "PUBLISHED"
STATUS_PUBLISH_FAILED = "PUBLISH_FAILED"
STATUS_FAILED = "FAILED"
STATUS_BASELINE_DONE = "BASELINE_DONE"  # baseline runs only (`python -m loop baseline`)
STATUSES = (
    STATUS_ANSWERED_LIGHT, STATUS_UNAVAILABLE, STATUS_ANSWERED_HEAVY, STATUS_COURSE_SAVED,
    STATUS_PUBLISH_PENDING_APPROVAL, STATUS_PUBLISHED, STATUS_PUBLISH_FAILED, STATUS_FAILED, STATUS_BASELINE_DONE,
)

# ---------------------------------------------------------------- 4.2 ToolResult.kind

KIND_OK = "OK"
KIND_TOOL_ERROR = "TOOL_ERROR"
KIND_BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
KIND_CREATED = "CREATED"
KIND_HTTP_ERROR = "HTTP_ERROR"
KIND_NETWORK_ERROR = "NETWORK_ERROR"
KIND_DENIED_BY_SANDBOX = "DENIED_BY_SANDBOX"
KIND_NOT_FOUND = "NOT_FOUND"
KIND_OUT_OF_SCOPE = "OUT_OF_SCOPE"
KIND_TOO_LARGE = "TOO_LARGE"
KIND_NOT_TEXT = "NOT_TEXT"
RESULT_KINDS = (
    KIND_OK, KIND_TOOL_ERROR, KIND_BLOCKED_BY_POLICY, KIND_CREATED, KIND_HTTP_ERROR, KIND_NETWORK_ERROR,
    KIND_DENIED_BY_SANDBOX, KIND_NOT_FOUND, KIND_OUT_OF_SCOPE, KIND_TOO_LARGE, KIND_NOT_TEXT,
)

# ---------------------------------------------------------------- 2.4 / 4.4 publish

PUBLISH_ATTEMPT_RESULTS = (KIND_BLOCKED_BY_POLICY, KIND_CREATED, KIND_HTTP_ERROR, KIND_NETWORK_ERROR)  # attempts[].result
PUBLISH_STATUSES = (STATUS_PUBLISHED, STATUS_PUBLISH_PENDING_APPROVAL, STATUS_PUBLISH_FAILED)  # publish.json status
PUBLISH_TARGET = "github-issue"
PUBLISH_REPO_ENV = "PUBLISH_REPO"  # environment variable holding `owner/repo` (not a secret)
GITHUB_ISSUES_URL = "https://api.github.com/repos/{repo}/issues"  # POST target; fill with str.format(repo=...)

# ---------------------------------------------------------------- 4.4 run.json route, trace.jsonl

ROUTE_HEAVY = "heavy"
ROUTE_LIGHT = "light"
ROUTE_NONE = "none"
ROUTES = (ROUTE_HEAVY, ROUTE_LIGHT, ROUTE_NONE)

EVENT_ROUTE = "route"
EVENT_LIGHT_ANSWER = "light_answer"
EVENT_PLAN = "plan"
EVENT_PLAN_CHECK = "plan_check"
EVENT_REPLAN = "replan"
EVENT_STEP = "step"
EVENT_PUBLISH_ATTEMPT = "publish_attempt"
EVENT_APPROVAL_WAIT = "approval_wait"
EVENT_FINAL = "final"
EVENT_BASELINE = "baseline"
TRACE_EVENTS = (
    EVENT_ROUTE, EVENT_LIGHT_ANSWER, EVENT_PLAN, EVENT_PLAN_CHECK, EVENT_REPLAN, EVENT_STEP, EVENT_PUBLISH_ATTEMPT,
    EVENT_APPROVAL_WAIT, EVENT_FINAL, EVENT_BASELINE,
)
TRACE_KEYS = ("seq", "ts", "run_id", "event", "tool", "args", "result", "why", "model", "prev_hash")
GENESIS_HASH = "0" * 64  # prev_hash of the first trace line

# ---------------------------------------------------------------- 2.2 tool names (the only names a plan may use)

TOOL_NAMES = (
    "select_places", "lookup_station", "lookup_origin", "lookup_operating", "organize_names", "grade_evidence",
    "save_course", "request_publish", "search_db", "list_input", "read_file",
)

# ---------------------------------------------------------------- 2.3 source types and evidence grades

SOURCE_TYPES = ("official", "academic", "media", "informal")
SOURCE_TYPE_GRADE = {"official": "A", "academic": "B", "media": "C", "informal": "D"}
DEFAULT_SOURCE_TYPE = "informal"  # empty or unknown source_type counts as informal (grade D)
GRADES = ("A", "B", "C", "D")  # highest first


def normalize_source_type(source_type: object) -> str:
    """The source type itself if it is one of the four, else `informal` (spec 2.3)."""
    if isinstance(source_type, str) and source_type in SOURCE_TYPE_GRADE:
        return source_type
    return DEFAULT_SOURCE_TYPE


def grade_for_source_type(source_type: object) -> str:
    """Evidence grade A-D of one source; empty or unknown types get D (spec 2.3)."""
    return SOURCE_TYPE_GRADE[normalize_source_type(source_type)]


# ---------------------------------------------------------------- 4.6 course value sets

NAME_KINDS = ("current", "old", "in_work", "station")
OPERATING_CHOSEN = "CHOSEN"
OPERATING_NEEDS_ONSITE_CHECK = "NEEDS_ONSITE_CHECK"
OPERATING_UNKNOWN = "UNKNOWN"
OPERATING_STATUSES = (OPERATING_CHOSEN, OPERATING_NEEDS_ONSITE_CHECK, OPERATING_UNKNOWN)
TRAVEL_MODES = ("walk", "transit", "unknown")
TRAVEL_BASES = ("cited", "estimate")

# ---------------------------------------------------------------- 4.3 index chunks, 4.7 source front matter

PROVENANCES = ("real", "synthetic")
SOURCE_KINDS = ("origin", "operating", "appearance", "other")
DEFAULT_SOURCE_KIND = "other"
FRONT_MATTER_KEYS = ("source_id", "title", "publisher", "source_type", "published", "url", "provenance", "kind",
                     "about")
OPERATING_FRONT_MATTER_KEYS = ("place_ids", "hours", "closed")  # only for kind: operating
CHUNK_BASE_KEYS = ("chunk_id", "source", "title", "text", "char_start", "char_end", "dates_in_text", "mtime")
CHUNK_SOURCE_KEYS = ("source_id", "publisher", "source_type", "published", "url", "provenance", "kind", "about")
CHUNK_OPERATING_KEYS = ("place_ids", "hours", "closed")  # only for kind: operating
INDEX_COLLECTION = "kb"  # 2.7 index bundle name (조정값), run.json index.collection

# ---------------------------------------------------------------- 2.2 / 2.5 / 4.4 sandbox paths and run files

HACKATHON_DIR = "/hackathon"
INPUT_DIR = "/hackathon/input"
OUTPUT_DIR = "/hackathon/output"
RESTRICTED_DIR = "/hackathon/restricted"
SECRETS_DIR = "/hackathon/secrets"

RUN_JSON = "run.json"
TRACE_JSONL = "trace.jsonl"
COURSE_MD = "course.md"
COURSE_JSON = "course.json"
ANSWER_MD = "answer.md"
ANSWER_JSON = "answer.json"
PUBLISH_JSON = "publish.json"
BASELINE_JSON = "baseline.json"
RUN_FILES = (RUN_JSON, TRACE_JSONL, COURSE_MD, COURSE_JSON, ANSWER_MD, ANSWER_JSON, PUBLISH_JSON, BASELINE_JSON)

# ---------------------------------------------------------------- contract phrases (verbatim)

EVIDENCE_LABEL_LIGHT = "자료 근거 없음(일반 안내)"  # 2.1 first line of a light answer, answer.json evidence_label
TEXT_UNAVAILABLE = "지금은 판단할 수 없어 응답하지 않습니다"  # 2.1 router failed twice
TEXT_DENIED_BY_SANDBOX = "접근이 거부됨(인프라 차단)"  # 2.2 / 2.5 read refused by the sandbox
TEXT_USER_SAID_DO_NOT_SEND = "사용자가 보내지 말라고 함"  # 2.2 trace note when publish is not planned
TEXT_UNCONFIRMED = "확인 안 됨"  # 2.2 unknowns entry for facts missing from the data
TEXT_NO_EVIDENCE = "근거 없음"  # 2.3 claim whose evidence all failed the existence check (no grade)
TEXT_ONSITE_CHECK = "현장 확인 필요"  # 2.3 meaning of NEEDS_ONSITE_CHECK
REASON_OVER_BUDGET = "시간 예산 초과"  # 4.6 excluded[].reason
TEXT_ESTIMATE = "추정"  # 4.6 label for estimate legs in course.md and on screen
TEXT_NO_PLACES_FOR_WORK = "자료에 해당 작품의 배경지가 없음"  # 5 no place found for the requested work

# ---------------------------------------------------------------- run_id, timestamps, trace hash chain

_RUN_ID = re.compile(r"([0-9]{8}T[0-9]{6}Z)-[0-9a-fA-F]{4}")
_HEX4 = re.compile(r"[0-9a-fA-F]{4}")
_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")
_HEX64 = re.compile(r"[0-9a-f]{64}")
# Characters str.splitlines() breaks on that json.dumps(ensure_ascii=False) leaves raw.
_RAW_LINE_BREAKS = {"\x85": "\\u0085", " ": "\\u2028", " ": "\\u2029"}


def _as_utc(when: datetime | None) -> datetime:
    if when is None:
        return datetime.now(timezone.utc)
    if when.tzinfo is None:  # naive values are taken as UTC, never as local time
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def new_run_id(now: datetime | None = None, rand_hex: str | None = None) -> str:
    """`YYYYMMDDTHHMMSSZ-<4 hex>` in UTC (spec 4.4). `rand_hex` fixes the suffix for tests; default is random.

    The caller draws a new id when the run folder already exists (never overwrite).
    """
    suffix = secrets.token_hex(2) if rand_hex is None else rand_hex
    if not isinstance(suffix, str) or not _HEX4.fullmatch(suffix):
        raise SchemaError(f"run_id suffix must be 4 hex digits, got {suffix!r}")
    return f"{_as_utc(now):%Y%m%dT%H%M%SZ}-{suffix}"


def is_run_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    m = _RUN_ID.fullmatch(value)
    if not m:
        return False
    try:
        datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True


def utc_ts(now: datetime | None = None) -> str:
    """UTC ISO 8601 with milliseconds and `Z`, e.g. `2026-10-07T03:31:05.123Z` (trace ts, run.json times)."""
    dt = _as_utc(now)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def is_utc_ts(value: object) -> bool:
    if not isinstance(value, str) or not _TS.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def parse_utc_ts(value: str) -> datetime:
    if not is_utc_ts(value):
        raise SchemaError(f"not a UTC timestamp like 2026-10-07T03:31:05.123Z: {value!r}")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def trace_hash(line: str) -> str:
    """sha256 (64 hex digits) of one trace line's UTF-8 bytes, without its line break."""
    if line.endswith("\n"):
        line = line[:-1]
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def prev_hash_for(previous_line: str | None) -> str:
    """`prev_hash` for the next line: hash of the previous line, or 64 zeros for the first line."""
    return GENESIS_HASH if previous_line is None else trace_hash(previous_line)


def split_trace_lines(text: str) -> list[str]:
    """Split trace.jsonl text on "\\n" only (str.splitlines() also breaks on other characters)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def verify_trace(lines: Iterable[str]) -> list[str]:
    """Problems in a trace (empty list = keys present, seq runs 1.., every prev_hash matches). Never raises."""
    problems: list[str] = []
    previous: str | None = None
    for number, raw in enumerate(lines, start=1):
        line = raw[:-1] if raw.endswith("\n") else raw
        where = f"line {number}"
        try:
            obj = json.loads(line)
        except ValueError:
            problems.append(f"{where}: not JSON")
            obj = None
        if obj is not None and not isinstance(obj, dict):
            problems.append(f"{where}: not a JSON object")
        elif isinstance(obj, dict):
            if set(obj) != set(TRACE_KEYS):
                problems.append(f"{where}: keys {sorted(obj)} differ from {list(TRACE_KEYS)}")
            seq = obj.get("seq")
            if type(seq) is not int or seq != number:
                problems.append(f"{where}: seq {seq!r}, expected {number}")
            if obj.get("prev_hash") != prev_hash_for(previous):
                problems.append(f"{where}: prev_hash does not match the previous line")
        previous = line
    return problems


# ---------------------------------------------------------------- record base

_NONE_TYPE = type(None)
_HINTS: dict[type, dict[str, Any]] = {}


def _type_hints(cls: type) -> dict[str, Any]:
    hints = _HINTS.get(cls)
    if hints is None:
        hints = _HINTS[cls] = typing.get_type_hints(cls)
    return hints


def _dump(value: Any) -> Any:
    if isinstance(value, Record):
        return value.to_dict()
    if isinstance(value, (list, tuple)):
        return [_dump(v) for v in value]
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    return value


def _expect(ok: bool, where: str, what: str, value: Any) -> None:
    if not ok:
        raise SchemaError(f"{where}: expected {what}, got {type(value).__name__}")


def _load(tp: Any, value: Any, where: str) -> Any:
    if tp is Any:
        return value
    origin = typing.get_origin(tp)
    if origin is typing.Union or origin is types.UnionType:
        options = [a for a in typing.get_args(tp) if a is not _NONE_TYPE]
        if value is None:
            if len(options) < len(typing.get_args(tp)):
                return None
            raise SchemaError(f"{where}: null is not allowed")
        error: SchemaError | None = None
        for option in options:
            try:
                return _load(option, value, where)
            except SchemaError as exc:
                error = error or exc
        raise error if error else SchemaError(f"{where}: no type matches")
    if value is None:
        raise SchemaError(f"{where}: null is not allowed")
    if origin is list:
        _expect(isinstance(value, list), where, "a list", value)
        item = (typing.get_args(tp) or (Any,))[0]
        return [_load(item, v, f"{where}[{i}]") for i, v in enumerate(value)]
    if origin is dict:
        _expect(isinstance(value, dict), where, "an object", value)
        val_tp = (typing.get_args(tp) or (Any, Any))[1]
        return {k: _load(val_tp, v, f"{where}.{k}") for k, v in value.items()}
    if isinstance(tp, type) and issubclass(tp, Record):
        try:
            return tp.from_dict(value)
        except SchemaError as exc:
            raise SchemaError(f"{where}: {exc}") from None
    if tp is bool:
        _expect(isinstance(value, bool), where, "true or false", value)
    elif tp is int:
        _expect(isinstance(value, int) and not isinstance(value, bool), where, "an integer", value)
    elif tp is float:
        _expect(isinstance(value, (int, float)) and not isinstance(value, bool), where, "a number", value)
    elif tp is str:
        _expect(isinstance(value, str), where, "a string", value)
    elif tp is dict:
        _expect(isinstance(value, dict), where, "an object", value)
    elif tp is list:
        _expect(isinstance(value, list), where, "a list", value)
    else:
        raise SchemaError(f"{where}: unsupported field type {tp!r}")
    return value


class Record:
    """Base for contract records (dataclasses). Field names are the JSON keys, in spec order."""

    _optional: ClassVar[frozenset[str]] = frozenset()  # keys that may be absent on input
    _omit_none: ClassVar[frozenset[str]] = frozenset()  # keys left out of to_dict() while None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):  # type: ignore[arg-type]
            value = getattr(self, f.name)
            if value is None and f.name in self._omit_none:
                continue
            out[f.name] = _dump(value)
        return out

    @classmethod
    def from_dict(cls, data: Any):
        name = cls.__name__
        if not isinstance(data, dict):
            raise SchemaError(f"{name}: expected an object, got {type(data).__name__}")
        known = [f.name for f in fields(cls)]  # type: ignore[arg-type]
        unknown = [k for k in data if k not in known]
        if unknown:
            raise SchemaError(f"{name}: unknown keys {unknown}")
        missing = [k for k in known if k not in data and k not in cls._optional]
        if missing:
            raise SchemaError(f"{name}: missing keys {missing}")
        hints = _type_hints(cls)
        kwargs = {k: _load(hints[k], data[k], f"{name}.{k}") for k in known if k in data}
        try:
            return cls(**kwargs)
        except TypeError as exc:
            raise SchemaError(f"{name}: {exc}") from None


def _check_run_id(value: Any, where: str) -> None:
    if not is_run_id(value):
        raise SchemaError(f"{where}: {value!r} is not a run_id like 20261007T033105Z-0a1f")


def _check_ts(value: Any, where: str) -> None:
    if not is_utc_ts(value):
        raise SchemaError(f"{where}: {value!r} is not a UTC timestamp like 2026-10-07T03:31:05.123Z")


# ---------------------------------------------------------------- 4.5 plan


@dataclass(kw_only=True)
class Goal(Record):
    """Goal of a plan (spec 4.5); course.json `goal` has the same shape."""

    work: str
    time_budget_min: int | None
    start: str
    constraints: list[str] = field(default_factory=list)
    publish_requested: bool


@dataclass(kw_only=True)
class PlanStep(Record):
    """One plan step. `tool` and `args` are checked by the plan check (ToolRegistry), not here."""

    id: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    why: str = ""


@dataclass(kw_only=True)
class Plan(Record):
    goal: Goal
    steps: list[PlanStep] = field(default_factory=list)


# ---------------------------------------------------------------- 4.4 trace.jsonl


@dataclass(kw_only=True)
class TraceResult(Record):
    kind: str = ""
    summary: str = ""


@dataclass(kw_only=True)
class TraceModel(Record):
    name: str
    purpose: str
    latency_ms: float
    usage: dict[str, Any] | None = None


@dataclass(kw_only=True)
class TraceLine(Record):
    """One trace.jsonl line. Never put key or token values, full response bodies or local paths in it."""

    seq: int
    ts: str
    run_id: str
    event: str
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: TraceResult = field(default_factory=TraceResult)
    why: str = ""
    model: TraceModel | None = None
    prev_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.seq, bool) or not isinstance(self.seq, int) or self.seq < 1:
            raise SchemaError(f"TraceLine.seq: must be an integer from 1, got {self.seq!r}")
        _check_ts(self.ts, "TraceLine.ts")
        _check_run_id(self.run_id, "TraceLine.run_id")
        check_in(self.event, TRACE_EVENTS, "TraceLine.event")
        if self.tool != "":
            check_in(self.tool, TOOL_NAMES, "TraceLine.tool")
        if not isinstance(self.prev_hash, str) or not _HEX64.fullmatch(self.prev_hash):
            raise SchemaError(f"TraceLine.prev_hash: expected 64 lowercase hex digits, got {self.prev_hash!r}")

    def to_json_line(self) -> str:
        """One JSON line without the line break; hash exactly this text for the next line's prev_hash."""
        text = json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
        for raw, escaped in _RAW_LINE_BREAKS.items():
            text = text.replace(raw, escaped)
        return text


# ---------------------------------------------------------------- 4.6 course.json


@dataclass(kw_only=True)
class Station(Record):
    name: str = ""
    line: str = ""


@dataclass(kw_only=True)
class OriginClaim(Record):
    """One origin claim for a name. `grade` is None when no evidence survived the existence check."""

    name: str
    name_kind: str
    summary: str = ""
    grade: str | None = None
    source_ids: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    input_paths: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        check_in(self.name_kind, NAME_KINDS, "OriginClaim.name_kind")
        if self.grade is not None:
            check_in(self.grade, GRADES, "OriginClaim.grade")


@dataclass(kw_only=True)
class Conflict(Record):
    name: str
    claims: list[OriginClaim] = field(default_factory=list)  # higher grade first, then newer first (2.3)


@dataclass(kw_only=True)
class Operating(Record):
    """Operating info of a place. `candidates` exists only when no conclusion is drawn (NEEDS_ONSITE_CHECK)."""

    status: str
    hours: Any = ""  # value as written by the chosen source
    closed: Any = ""  # value as written by the chosen source
    source_ids: list[str] = field(default_factory=list)
    as_of: str = ""
    candidates: list[dict[str, Any]] | None = None

    _optional = frozenset({"candidates"})
    _omit_none = frozenset({"candidates"})

    def __post_init__(self) -> None:
        check_in(self.status, OPERATING_STATUSES, "Operating.status")


@dataclass(kw_only=True)
class StaleItem(Record):
    source_id: str
    reason: str


@dataclass(kw_only=True)
class ExcludedItem(Record):
    place_id: str
    reason: str


@dataclass(kw_only=True)
class CoursePlace(Record):
    order: int
    place_id: str
    current_name: str
    in_work_name: str
    scene: str
    old_names: list[str] = field(default_factory=list)
    station: Station
    travel_min_from_prev: int | None
    travel_mode: str
    travel_basis: str
    travel_chunk_ids: list[str] = field(default_factory=list)
    stay_min: int
    arrive_min: int | None
    origins: list[OriginClaim] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    operating: Operating
    stale: list[StaleItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        check_in(self.travel_mode, TRAVEL_MODES, "CoursePlace.travel_mode")
        check_in(self.travel_basis, TRAVEL_BASES, "CoursePlace.travel_basis")


@dataclass(kw_only=True)
class PublishInfo(Record):
    """course.json `publish`. The loop updates it after publishing; empty until then."""

    status: str = ""
    url: str | None = None


@dataclass(kw_only=True)
class Course(Record):
    run_id: str
    request: str
    goal: Goal
    places: list[CoursePlace] = field(default_factory=list)
    total_min: int | None = None
    excluded: list[ExcludedItem] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    publish: PublishInfo = field(default_factory=PublishInfo)

    def __post_init__(self) -> None:
        _check_run_id(self.run_id, "Course.run_id")


# ---------------------------------------------------------------- 4.4 run.json


@dataclass(kw_only=True)
class ModelCalls(Record):
    router: int = 0  # Nemotron weight-judgment calls (2.1), counted apart from the rest
    nemotron: int = 0


@dataclass(kw_only=True)
class TokenCount(Record):
    input: int = 0
    output: int = 0


@dataclass(kw_only=True)
class Tokens(Record):
    router: TokenCount = field(default_factory=TokenCount)  # Nemotron weight-judgment calls
    nemotron: TokenCount = field(default_factory=TokenCount)


@dataclass(kw_only=True)
class IndexInfo(Record):
    collection: str = INDEX_COLLECTION
    fingerprint: str = ""  # manifest source_fingerprint


@dataclass(kw_only=True)
class RunRecord(Record):
    """run.json."""

    run_id: str
    request: str
    route: str
    status: str
    started_at: str
    ended_at: str
    model_calls: ModelCalls = field(default_factory=ModelCalls)
    tokens: Tokens = field(default_factory=Tokens)
    index: IndexInfo = field(default_factory=IndexInfo)
    limits_hit: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _check_run_id(self.run_id, "RunRecord.run_id")
        check_in(self.route, ROUTES, "RunRecord.route")
        check_in(self.status, STATUSES, "RunRecord.status")
        _check_ts(self.started_at, "RunRecord.started_at")
        _check_ts(self.ended_at, "RunRecord.ended_at")


# ---------------------------------------------------------------- 4.4 answer.json


@dataclass(kw_only=True)
class ReadFileRef(Record):
    path: str
    kind: str


@dataclass(kw_only=True)
class AnswerRecord(Record):
    """answer.json. `evidence_label` is EVIDENCE_LABEL_LIGHT for a light answer, else empty."""

    run_id: str
    request: str
    route: str
    status: str
    answer: str
    evidence_label: str = ""
    origins: list[OriginClaim] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    read_files: list[ReadFileRef] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _check_run_id(self.run_id, "AnswerRecord.run_id")
        check_in(self.route, ROUTES, "AnswerRecord.route")
        check_in(self.status, STATUSES, "AnswerRecord.status")
        check_in(self.evidence_label, ("", EVIDENCE_LABEL_LIGHT), "AnswerRecord.evidence_label")


# ---------------------------------------------------------------- 4.4 publish.json


@dataclass(kw_only=True)
class PublishAttempt(Record):
    ts: str
    result: str
    http_status: int | None = None

    def __post_init__(self) -> None:
        _check_ts(self.ts, "PublishAttempt.ts")
        check_in(self.result, PUBLISH_ATTEMPT_RESULTS, "PublishAttempt.result")


@dataclass(kw_only=True)
class PublishRecord(Record):
    """publish.json. At most one issue per run: no resend after a CREATED attempt."""

    status: str
    target: str = PUBLISH_TARGET
    repo: str
    attempts: list[PublishAttempt] = field(default_factory=list)
    issue_url: str | None = None

    def __post_init__(self) -> None:
        check_in(self.status, PUBLISH_STATUSES, "PublishRecord.status")


# ---------------------------------------------------------------- 4.7 theme pack (Hustler data, read by code)


@dataclass(kw_only=True)
class PackStation(Record):
    name: str
    aliases: list[str] = field(default_factory=list)
    line: str
    lat: float | None = None
    lon: float | None = None

    _optional = frozenset({"lat", "lon"})
    _omit_none = frozenset({"lat", "lon"})


@dataclass(kw_only=True)
class PackPlace(Record):
    """`stay_min` may be absent: select_places then uses limits.DEFAULT_STAY_MIN and marks it estimate (4.6)."""

    place_id: str
    current_name: str
    in_work_name: str
    scene: str
    old_names: list[str] = field(default_factory=list)
    station: str  # a stations[].name of the same pack
    stay_min: int | None = None
    appearance_source_ids: list[str] = field(default_factory=list)
    priority: int  # smaller comes first
    lat: float | None = None
    lon: float | None = None

    _optional = frozenset({"stay_min", "lat", "lon"})
    _omit_none = frozenset({"stay_min", "lat", "lon"})


@dataclass(kw_only=True)
class ThemePack(Record):
    pack_id: str
    work_title: str
    aliases: list[str] = field(default_factory=list)
    provenance: str
    stations: list[PackStation] = field(default_factory=list)
    places: list[PackPlace] = field(default_factory=list)

    def __post_init__(self) -> None:
        check_in(self.provenance, PROVENANCES, "ThemePack.provenance")
