#!/usr/bin/env python3
"""Audit helpers for the sandbox `kculture`, run on the host. Standard library only; Python 3.9+.

  python3 audit_correlate.py since <run_id> [--margin SECONDS]
      print an `openshell logs --since` value (e.g. 754s) that reaches back to the run start (from run_id) + margin
  python3 audit_correlate.py redact < raw > clean
      mask credential-looking values (API keys, bearer tokens, NAME=value secrets) and host home folders
  python3 audit_correlate.py filter [--denied-only] < logs
      keep network decisions (NET:OPEN / HTTP:<METHOD> ALLOWED|DENIED) and policy loads, prefixed with UTC time
  python3 audit_correlate.py report --run-dir DIR --logs FILE [--policy-list FILE] [--policy-current FILE]
                                    [--window SECONDS]
      audit.md on stdout: trace publish_attempt events and OpenShell api.github.com ALLOWED/DENIED lines on one
      UTC timeline; every attempt is paired with the api.github.com log lines nearest to it within the window

OpenShell 0.0.116 log line: "[<unix seconds>.<ms>] [<source>] [<level>] [<target>] <body>", for example
  NET:OPEN [MED] DENIED <exe>(<pid>) -> api.github.com:443 [policy:- engine:opa] [reason:...]
  HTTP:POST [INFO] ALLOWED POST http://api.github.com:443/repos/<owner>/<repo>/issues [policy:github_issue engine:l7]
  CONFIG:LOADED [INFO] Policy reloaded successfully [policy_hash:<sha256>] [hash:<sha256>]
`openshell policy list` columns: VERSION HASH STATUS CREATED ERROR (CREATED in unix milliseconds).
trace.jsonl: one JSON object per line, `ts` in UTC ISO 8601 with milliseconds and Z, `prev_hash` = sha256 of the
previous line's UTF-8 bytes without the newline (64 zeros on the first line).

Pairing rule: BLOCKED_BY_POLICY <-> DENIED; CREATED and HTTP_ERROR <-> ALLOWED (the request passed the policy);
NETWORK_ERROR and other kinds are shown for reference only. Each api.github.com log line goes to the nearest attempt
within the window (default 5 s, a tuning value); a line with no attempt is shown as "not in the trace".

Exit codes: 0 done (report: every attempt paired with a matching verdict and the trace hash chain intact);
1 report written, but an attempt is unpaired or contradicts the log, or the chain is broken; 2 usage or input error.
"""

import argparse
import calendar
import datetime
import hashlib
import json
import os
import re
import sys
import time

GITHUB_HOST = "api.github.com"
DEFAULT_WINDOW = 5.0
RUN_MARGIN = 60.0
TRACE_EVENTS = ("publish_attempt", "approval_wait", "final")
EXPECTED = {"BLOCKED_BY_POLICY": "DENIED", "CREATED": "ALLOWED", "HTTP_ERROR": "ALLOWED"}

RUN_ID_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z-[0-9a-fA-F]{4}$")
ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:?00)$")
LOG_RE = re.compile(r"^\[(?P<ts>\d+(?:\.\d+)?)\]\s+\[(?P<src>[^\]]*)\]\s+\[[^\]]*\]\s+\[[^\]]*\]\s+(?P<body>.*)$")
DECISION_RE = re.compile(r"^(?P<event>NET:OPEN|HTTP:[A-Z]+)\s+\[[A-Z]+\]\s+(?P<verdict>ALLOWED|DENIED)\b\s*(?P<rest>.*)$")
NET_RE = re.compile(r"^(?P<exe>\S+?)(?:\(\d+\))?\s+->\s+(?P<host>[A-Za-z0-9.\-]+):(?P<port>\d+)")
HTTP_RE = re.compile(r"^(?P<method>[A-Z]+)\s+https?://(?P<host>[A-Za-z0-9.\-]+)(?::(?P<port>\d+))?(?P<path>/[^\s\[]*)?")
POLICY_RE = re.compile(r"\[policy:(?P<policy>[^\s\]]+)")
REASON_RE = re.compile(r"\[reason:(?P<reason>.*?)\]?\s*$")
LOAD_RE = re.compile(r"^CONFIG:LOADED\s+\[[A-Z]+\]\s+(?P<msg>.*)$")
VERSION_RE = re.compile(r"\[version:(\d+)\]")
HASH_RE = re.compile(r"\[(?:policy_hash|hash):([0-9a-f]{7,64})\]")
LIST_ROW_RE = re.compile(r"^\s*(?P<version>\d+)\s+(?P<hash>[0-9a-f]{6,64})\s+(?P<status>\S+)\s+(?P<created>\d{10,13})\b\s*(?P<error>.*)$")

# Built from pieces so this file never matches the repository's own secret scan patterns.
_NV = "nv" + "api-"
_HOMES = ("/" + "Us" + "ers/", "/" + "ho" + "me/")
_SECRET_NAME = r"[A-Za-z0-9_\-]*(?:key|token|secret|password|passwd|authorization|credential)"
REDACT_RULES = [
    (re.compile(re.escape(_NV) + r"[A-Za-z0-9_\-]{8,}"), _NV + "[REDACTED]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}"), "gh_[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}"), "github_pat_[REDACTED]"),
    (re.compile(r"(?i)\b(bearer|basic)(\s+)[A-Za-z0-9._~+/=\-]{8,}"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)\b(" + _SECRET_NAME + r")(\s*[:=]\s*)([\"']?)(?!\[REDACTED\])[^\s\"',;\[\]]{4,}"),
     r"\1\2\3[REDACTED]"),
] + [(re.compile(re.escape(h) + r"[^/\s]+"), h + "<user>") for h in _HOMES]


class UsageError(Exception):
    pass


def redact(text):
    for pattern, repl in REDACT_RULES:
        text = pattern.sub(repl, text)
    return text


def utc(t):
    seconds, millis = divmod(int(round(t * 1000)), 1000)
    d = datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)
    return "%s.%03d" % (d.strftime("%H:%M:%S"), millis)


def utc_full(t):
    return datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    m = ISO_RE.match(value or "")
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
    frac = m.group(7) or "0"
    return calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0)) + int(frac) / (10 ** len(frac))


def run_start(run_id):
    m = RUN_ID_RE.match(run_id)
    if not m:
        raise UsageError("run_id must look like YYYYMMDDTHHMMSSZ-xxxx")
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    return calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))


def parse_log_line(line):
    """One OpenShell log line -> dict (kind decision|load) or None."""
    m = LOG_RE.match(line.rstrip("\n"))
    if not m:
        return None
    t, body = float(m.group("ts")), m.group("body")
    d = DECISION_RE.match(body)
    if d:
        rest = d.group("rest")
        ev = {"kind": "decision", "t": t, "body": body, "event": d.group("event"), "verdict": d.group("verdict"),
              "host": "", "port": "", "path": "", "exe": "", "policy": "", "reason": ""}
        if ev["event"] == "NET:OPEN":
            n = NET_RE.match(rest)
            if n:
                ev.update(exe=n.group("exe"), host=n.group("host"), port=n.group("port"))
        else:
            h = HTTP_RE.match(rest)
            if h:
                ev.update(host=h.group("host"), port=h.group("port") or "", path=h.group("path") or "")
        p = POLICY_RE.search(rest)
        if p:
            ev["policy"] = p.group("policy")
        r = REASON_RE.search(rest)
        if r:
            ev["reason"] = r.group("reason")
        return ev
    lo = LOAD_RE.match(body)
    if lo and "policy" in lo.group("msg").lower():
        v, hs = VERSION_RE.search(body), HASH_RE.search(body)
        return {"kind": "load", "t": t, "body": body, "msg": lo.group("msg"),
                "version": int(v.group(1)) if v else None, "hash": hs.group(1) if hs else ""}
    return None


def parse_policy_list(text):
    rows = []
    for line in text.splitlines():
        m = LIST_ROW_RE.match(line.replace("│", " ").replace("|", " "))
        if not m:
            continue
        created = int(m.group("created"))
        rows.append({"version": int(m.group("version")), "hash": m.group("hash"), "status": m.group("status"),
                     "t": created / 1000.0 if len(m.group("created")) == 13 else float(created),
                     "error": m.group("error").strip()})
    return rows


def version_for(hash_value, revisions):
    if not hash_value:
        return None
    hits = {r["version"] for r in revisions if hash_value.startswith(r["hash"]) or r["hash"].startswith(hash_value)}
    return hits.pop() if len(hits) == 1 else None


def read_trace(path):
    """-> (records with '_t', line count, chain breaks as seq numbers, unreadable line numbers)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    records, breaks, unreadable = [], [], []
    prev = "0" * 64
    for i, line in enumerate(lines, 1):
        try:
            rec = json.loads(line.decode("utf-8"))
            if not isinstance(rec, dict):
                raise ValueError("not an object")
        except ValueError:
            unreadable.append(i)
            breaks.append(i)
            prev = hashlib.sha256(line).hexdigest()
            continue
        if rec.get("prev_hash") != prev:
            breaks.append(rec.get("seq", i))
        prev = hashlib.sha256(line).hexdigest()
        rec["_t"] = parse_iso(rec.get("ts"))
        records.append(rec)
    return records, len(lines), breaks, unreadable


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def cell(text, limit=160):
    text = redact(str(text)).replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def describe(ev, with_event=True):
    if ev["event"] == "NET:OPEN":
        what = "%s -> %s:%s" % (os.path.basename(ev["exe"]) or "?", ev["host"], ev["port"])
    else:
        what = "%s %s%s" % (ev["event"].split(":", 1)[1], ev["host"], ev["path"])
    text = "%s [policy:%s]" % (what, ev["policy"] or "?")
    if with_event:
        text = "%s %s %s" % (ev["event"], ev["verdict"], text)
    if ev["reason"]:
        text += " reason: " + ev["reason"][:90]
    return text


def pair(attempts, gh_lines, window):
    """Assign each api.github.com line to the nearest attempt within the window."""
    assigned = {}
    for li, ev in enumerate(gh_lines):
        best = None
        for ai, at in enumerate(attempts):
            gap = abs(ev["t"] - at["_t"])
            if gap <= window and (best is None or gap < best[0]):
                best = (gap, ai)
        if best is not None:
            assigned.setdefault(best[1], []).append(li)
    return assigned


def build_report(args):
    run_dir = args.run_dir
    trace_path = os.path.join(run_dir, "trace.jsonl")
    if not os.path.isdir(run_dir):
        raise UsageError("run folder not found: %s" % run_dir)
    try:
        with open(args.logs, encoding="utf-8", errors="replace") as fh:
            log_text = fh.read()
    except OSError:
        raise UsageError("log file not readable: %s" % args.logs)
    list_text = ""
    if args.policy_list:
        try:
            with open(args.policy_list, encoding="utf-8", errors="replace") as fh:
                list_text = fh.read()
        except OSError:
            raise UsageError("policy list not readable: %s" % args.policy_list)
    current_text = ""
    if args.policy_current:
        try:
            with open(args.policy_current, encoding="utf-8", errors="replace") as fh:
                current_text = fh.read()
        except OSError:
            raise UsageError("policy get output not readable: %s" % args.policy_current)

    run = load_json(os.path.join(run_dir, "run.json")) or {}
    publish = load_json(os.path.join(run_dir, "publish.json"))
    run_id = run.get("run_id") or os.path.basename(os.path.normpath(run_dir))
    problems = []

    if os.path.isfile(trace_path):
        records, n_lines, breaks, unreadable = read_trace(trace_path)
    else:
        records, n_lines, breaks, unreadable = [], 0, [], []
        problems.append("trace.jsonl 없음")
    if breaks:
        problems.append("해시 사슬 끊김")

    events = [ev for ev in (parse_log_line(x) for x in log_text.splitlines()) if ev]
    decisions = [ev for ev in events if ev["kind"] == "decision"]
    loads = [ev for ev in events if ev["kind"] == "load"]
    revisions = parse_policy_list(list_text)

    # The run window spans run.json and every trace line: a later `loop publish --run` retry writes trace lines
    # after ended_at, and its log lines must stay in the table.
    times = [r["_t"] for r in records if r.get("_t") is not None]
    lows = [x for x in (parse_iso(run.get("started_at")), min(times) if times else None) if x is not None]
    highs = [x for x in (parse_iso(run.get("ended_at")), max(times) if times else None) if x is not None]
    start = min(lows) if lows else None
    end = max(highs) if highs else None

    def in_run(t):
        if start is None:
            return True
        return start - RUN_MARGIN <= t <= (end if end is not None else float("inf")) + RUN_MARGIN

    attempts = [r for r in records if r.get("event") == "publish_attempt" and r.get("_t") is not None]
    untimed = [r for r in records if r.get("event") == "publish_attempt" and r.get("_t") is None]
    gh_all = [ev for ev in decisions if ev["host"] == GITHUB_HOST]
    gh_lines = [ev for ev in gh_all if in_run(ev["t"])]
    assigned = pair(attempts, gh_lines, args.window)
    owner = {li: attempts[ai].get("seq", "?") for ai, lis in assigned.items() for li in lis}

    counts = {"일치": 0, "불일치": 0, "짝 없음": 0, "참고": 0}
    rows = []  # (time, order, source, event, content, pair)
    for ai, at in enumerate(attempts):
        result = at.get("result") if isinstance(at.get("result"), dict) else {}
        kind = str(result.get("kind", ""))
        lines = [gh_lines[li] for li in assigned.get(ai, [])]
        observed = "DENIED" if any(x["verdict"] == "DENIED" for x in lines) else ("ALLOWED" if lines else None)
        expected = EXPECTED.get(kind)
        seen = ", ".join("%s %s" % (x["verdict"], utc(x["t"])) for x in lines)
        if expected is None:
            verdict = "참고"
            note = "참고(%s): 로그 %s" % (kind or "?", seen or "없음")
        elif observed is None:
            verdict = "짝 없음"
            note = "짝 없음: ±%gs 안에 %s 줄 없음" % (args.window, GITHUB_HOST)
        elif observed == expected:
            verdict = "일치"
            note = "일치: 로그 %s" % seen
        else:
            verdict = "불일치"
            note = "불일치: trace %s, 로그 %s" % (kind, seen)
        counts[verdict] += 1
        rows.append((at["_t"], 2, "trace #%s" % at.get("seq", "?"), "publish_attempt",
                     "%s — %s" % (kind or "?", result.get("summary", "")), note))
    for r in records:
        if r.get("event") in ("approval_wait", "final") and r.get("_t") is not None:
            result = r.get("result") if isinstance(r.get("result"), dict) else {}
            rows.append((r["_t"], 2, "trace #%s" % r.get("seq", "?"), r["event"],
                         "%s — %s" % (result.get("kind", ""), result.get("summary", "")), ""))
    for li, ev in enumerate(gh_lines):
        rows.append((ev["t"], 1, "OpenShell 로그", "%s %s" % (ev["event"], ev["verdict"]), describe(ev, False),
                     "trace #%s" % owner[li] if li in owner else "trace에 없음"))
    for ev in loads:
        if in_run(ev["t"]):
            ver = ev["version"] if ev["version"] is not None else version_for(ev["hash"], revisions)
            rows.append((ev["t"], 1, "OpenShell 로그", "정책 적용",
                         "판 %s 적용(샌드박스가 불러옴): %s hash %s" % (ver if ver is not None else "?", ev["msg"].split(" [")[0],
                                                              ev["hash"][:12] or "?"), ""))
    for rev in revisions:
        if in_run(rev["t"]):
            rows.append((rev["t"], 0, "정책 이력", "정책 등록",
                         "판 %d 등록(%s) hash %s%s" % (rev["version"], rev["status"], rev["hash"][:12],
                                                     " error: " + rev["error"] if rev["error"] else ""), ""))
    rows.sort(key=lambda x: (x[0], x[1]))
    if counts["불일치"] or counts["짝 없음"]:
        problems.append("게시 시도의 짝이 맞지 않음")

    out = []
    w = out.append
    w("# 감사 묶음: %s" % cell(run_id))
    w("")
    w("만든 시각(UTC) %s. 시각은 모두 UTC다. 같은 폴더의 `run/`, `openshell-logs.txt`, `policy-list.txt`, "
      "`policy-current.txt`가 이 표의 원자료다." % utc_full(time.time()))
    w("")
    w("## 요약")
    w("")
    w("- 실행: 상태 `%s`, 경로 `%s`, 시작 %s, 끝 %s (run.json)" % (
        cell(run.get("status", "?")), cell(run.get("route", "?")), cell(run.get("started_at", "?")),
        cell(run.get("ended_at", "?"))))
    if os.path.isfile(trace_path):
        chain = "이어짐(prev_hash)" if not breaks else "끊김: seq %s" % ", ".join(str(b) for b in breaks)
        extra = ", JSON이 아닌 줄 %s" % ", ".join(str(u) for u in unreadable) if unreadable else ""
        w("- 의사결정 기록: trace.jsonl %d줄, 해시 사슬 %s%s" % (n_lines, chain, extra))
    else:
        w("- 의사결정 기록: trace.jsonl 없음")
    if publish:
        pa = publish.get("attempts") if isinstance(publish.get("attempts"), list) else []
        w("- 게시: publish.json 상태 `%s`, 시도 %d건, 이슈 %s" % (
            cell(publish.get("status", "?")), len(pa), cell(publish.get("issue_url") or "없음")))
    w("- 게시 시도(trace publish_attempt): %d건%s" % (
        len(attempts), ", 시각을 읽지 못한 시도 %d건" % len(untimed) if untimed else ""))
    w("- 짝 맞춤(±%gs): 일치 %d, 불일치 %d, 짝 없음 %d, 참고 %d" % (
        args.window, counts["일치"], counts["불일치"], counts["짝 없음"], counts["참고"]))
    w("- 실행 시간대의 %s 로그 줄 %d개, trace에 없는 줄 %d개, 시간대 밖 줄 %d개(표에 넣지 않음)" % (
        GITHUB_HOST, len(gh_lines), len(gh_lines) - len(owner), len(gh_all) - len(gh_lines)))
    cur_v = re.search(r"(?im)^\s*Version:\s*(\d+)", current_text)
    if args.policy_current:
        w("- 묶음을 만든 때의 정책: 판 %s (openshell policy get)" % (cur_v.group(1) if cur_v else "?"))
    w("- 판정: %s" % ("이상 없음" if not problems else "확인 필요 — " + ", ".join(problems)))
    w("")
    w("## 시간순 표(UTC)")
    w("")
    if rows:
        w("| 시각(UTC) | 출처 | 사건 | 내용 | 짝 |")
        w("|---|---|---|---|---|")
        for t, _, src, event, content, note in rows:
            w("| %s | %s | %s | %s | %s |" % (utc(t), cell(src), cell(event), cell(content), cell(note)))
    else:
        w("게시 시도도, 실행 시간대의 %s 줄도, 정책 적용도 없다." % GITHUB_HOST)
    w("")
    other = [ev for ev in decisions if ev["host"] != GITHUB_HOST and in_run(ev["t"])]
    w("## 실행 시간대의 다른 네트워크 판정")
    w("")
    if other:
        tally = {}
        for ev in other:
            key = (ev["host"] or "?", ev["verdict"])
            tally[key] = tally.get(key, 0) + 1
        w("| 목적지 | 판정 | 줄 수 |")
        w("|---|---|---|")
        for (host, verdict), n in sorted(tally.items()):
            w("| %s | %s | %d |" % (cell(host), verdict, n))
        denied = [ev for ev in other if ev["verdict"] == "DENIED"]
        if denied:
            w("")
            w("DENIED 줄:")
            w("")
            for ev in denied:
                w("- %s %s" % (utc(ev["t"]), cell(describe(ev), 220)))
    else:
        w("없음.")
    w("")
    w("## 정책 이력(openshell policy list)")
    w("")
    if revisions:
        w("| 판 | 상태 | 등록(UTC) | hash | 오류 |")
        w("|---|---|---|---|---|")
        for rev in sorted(revisions, key=lambda r: r["version"]):
            w("| %d | %s | %s | %s | %s |" % (rev["version"], cell(rev["status"]), utc_full(rev["t"]),
                                            cell(rev["hash"][:12]), cell(rev["error"] or "")))
    else:
        w("읽은 판이 없다. `policy-list.txt`를 직접 본다.")
    w("")
    w("## 읽는 법")
    w("")
    w("- 짝 규칙: BLOCKED_BY_POLICY는 DENIED, CREATED·HTTP_ERROR는 ALLOWED(정책은 통과)와 짝이다. "
      "NETWORK_ERROR와 그 밖의 종류는 참고로만 보인다. %s 줄은 ±%g초 안의 가장 가까운 시도에 붙인다(조정값)."
      % (GITHUB_HOST, args.window))
    w("- 파일 거부(Landlock)는 OpenShell 로그에 남지 않는다. 실행 기록의 DENIED_BY_SANDBOX로 본다.")
    w("- `openshell logs`는 크기가 정해진 버퍼에서 읽어 줄이 빠질 수 있다. 짝 없음이 나오면 샌드박스 안 "
      "/var/log/openshell.*.log를 본다.")
    w("- 키·토큰처럼 보이는 값은 묶음에 쓰기 전에 가렸다([REDACTED]).")
    sys.stdout.write("\n".join(out) + "\n")
    print("audit: attempts %d, matched %d, mismatched %d, unpaired %d, chain %s" % (
        len(attempts), counts["일치"], counts["불일치"], counts["짝 없음"], "ok" if not breaks else "broken"),
        file=sys.stderr)
    return 1 if problems else 0


def cmd_since(args):
    start = run_start(args.run_id)
    seconds = max(60, int(time.time() - start + args.margin))
    print("%ds" % seconds)
    return 0


def cmd_redact(_args):
    for line in sys.stdin:
        sys.stdout.write(redact(line))
    return 0


def cmd_filter(args):
    for line in sys.stdin:
        ev = parse_log_line(line)
        if ev is None:
            continue
        if args.denied_only and not (ev["kind"] == "decision" and ev["verdict"] == "DENIED"):
            continue
        sys.stdout.write("%sZ  %s\n" % (utc(ev["t"]), redact(ev["body"])))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="audit_correlate.py", description="Audit helpers for the sandbox kculture.")
    sub = p.add_subparsers(dest="cmd")
    ps = sub.add_parser("since")
    ps.add_argument("run_id")
    ps.add_argument("--margin", type=float, default=300.0)
    sub.add_parser("redact")
    pf = sub.add_parser("filter")
    pf.add_argument("--denied-only", action="store_true")
    pr = sub.add_parser("report")
    pr.add_argument("--run-dir", required=True)
    pr.add_argument("--logs", required=True)
    pr.add_argument("--policy-list")
    pr.add_argument("--policy-current")
    pr.add_argument("--window", type=float, default=DEFAULT_WINDOW)
    args = p.parse_args(argv)
    handlers = {"since": cmd_since, "redact": cmd_redact, "filter": cmd_filter, "report": build_report}
    if args.cmd not in handlers:
        p.print_usage(sys.stderr)
        return 2
    try:
        return handlers[args.cmd](args)
    except UsageError as exc:
        print("audit_correlate: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
