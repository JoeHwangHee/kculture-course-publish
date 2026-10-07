#!/usr/bin/env python3
"""Run the evaluation cases inside the OpenShell sandbox and collect each run folder (host side; no scoring).

  python3 app/sandbox/run_cases.py --cases <JSONL> --out <folder> [--mode ask|baseline|both]
      [--split dev|holdout|all] [--only E01,E02] [--sandbox kculture] [--timeout 420] [--env NAME=VALUE ...] [--force]

Standard library only; Python 3.9+ (the macOS system python3 works). No key passes through this script: the OpenShell
provider injects keys inside the sandbox, so --env refuses names containing KEY, TOKEN or SECRET, values with a line
break, and values that look like a key. Messages name a variable, never its value.

Input: JSONL, one case per line. Only `case_id`, `split` (dev|holdout) and `request` are read; every other key
(`expect`, ...) is neither used nor written anywhere. The console and runs.jsonl show case_id only, never case content.

For each selected case (file order) and mode (with --mode both: ask, then baseline):
  1. openshell sandbox exec -n <sandbox> --workdir /opt/kculture --no-tty --timeout <timeout> [--env NAME=VALUE ...]
       -- /opt/kculture/.venv/bin/python -m loop <ask|baseline> <request>
  2. run_id = the last non-empty stdout line `run_id: <run_id>`. `run_id: -` or no such line: no run folder (failure).
  3. Fetch. `sandbox download` refuses paths outside /sandbox (OpenShell 0.0.116, measured), so the run folder is first
     copied into the sandbox workspace and downloaded from there:
       openshell sandbox exec -n <sandbox> --no-tty --timeout 60 -- sh -c
         'rm -rf /sandbox/work/dl/<run_id> && mkdir -p /sandbox/work/dl && cp -R /hackathon/output/<run_id> /sandbox/work/dl/'
       openshell sandbox download <sandbox> /sandbox/work/dl/<run_id> <temporary folder inside --out>
       openshell sandbox exec -n <sandbox> --no-tty --timeout 60 -- rm -rf /sandbox/work/dl/<run_id>
     The cleanup runs after every fetch attempt; when it fails, that is logged and warned about, nothing more. The
     download may put the files right under the temporary folder or under <run_id>/ in it; both are accepted when
     run.json or trace.jsonl is there. Links and special files are refused (download overwrites silently and keeps
     symlinks).
  4. Place: ask -> <out>/system/<case_id>/<run_id>/, baseline -> <out>/baseline/<case_id>/<run_id>/. The case folder is
     staged outside system/ and baseline/ and moved in with one rename, so it holds exactly one run folder. An
     existing case folder is skipped (`skipped_existing`); --force deletes it first and runs the case again.
Every openshell call runs from an argument list (no host shell) with stdin closed (an open stdin keeps openshell from
returning) under a host watchdog (the call's own --timeout + 60 s; download 120 s) that kills its process group. A
case killed by the watchdog is a failure and its run folder is not fetched.

Outputs under --out:
  runs.jsonl                  appended, one line per case and mode: case_id, split, mode, exit_code (of the loop exec;
                              null when killed or skipped), run_id, seconds, downloaded, error (short text or null),
                              started_at (UTC). No stdout/stderr bodies.
  logs/<mode>-<case_id>.txt   full stdout/stderr of every openshell call for that case and mode, for people. Chunks of
                              20+ characters starting with a key prefix (NVIDIA, Anthropic, GitHub) become ***
  system/, baseline/          the run folders

Exit codes: 0 every selected case and mode has its run folder (fetched now, or skipped with exactly one run folder;
the loop's own exit code does not matter); 1 at least one has none; 2 argument or input error (nothing ran).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, NamedTuple, Optional, Tuple

PROG = "run_cases.py"
SANDBOX_DEFAULT = "kculture"
SANDBOX_WORKDIR = "/opt/kculture"
SANDBOX_PYTHON = "/opt/kculture/.venv/bin/python"
SANDBOX_OUTPUT = "/hackathon/output"
WORKSPACE_DL = "/sandbox/work/dl"
TIMEOUT_DEFAULT = 420
HELPER_TIMEOUT_S = 60  # openshell --timeout of the copy and cleanup execs
HOST_MARGIN_S = 60  # host watchdog = the call's --timeout + this; `sandbox exec` has been seen not to return
DOWNLOAD_TIMEOUT_S = 120  # host watchdog of `sandbox download` (tuning value)
KILL_GRACE_S = 10  # after the process group is killed, how long its pipes may take to close
MODE_DIRS = {"ask": "system", "baseline": "baseline"}
SPLITS = ("dev", "holdout")
SKIPPED = "skipped_existing"

RUN_ID_LINE_RE = re.compile(r"^run_id: (\d{8}T\d{6}Z-[0-9a-z]{4}|-)$", re.ASCII)
RUN_ID_RE = re.compile(r"\d{8}T\d{6}Z-[0-9a-z]{4}", re.ASCII)  # goes into a path and a sandbox shell line
CASE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", re.ASCII)  # becomes a folder name and a file name
SANDBOX_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", re.ASCII)
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$", re.ASCII)
ENV_NAME_REFUSED = ("KEY", "TOKEN", "SECRET")

# Key-shaped chunk: a key prefix and key characters, 20 characters or more in all. The prefixes are built from pieces
# so this file never matches the repository's own secret scan.
KEY_PREFIXES = ("nv" + "api-", "sk-" + "ant-", "gh" + "p_", "github_" + "pat_")
KEY_CHUNK_RE = re.compile("(?:%s)[A-Za-z0-9_-]*" % "|".join(re.escape(p) for p in KEY_PREFIXES),
                          re.IGNORECASE | re.ASCII)
KEY_CHUNK_MIN = 20
MASK = "***"


class UsageError(Exception):
    """Argument or input error: exit 2 before anything runs."""


class CommandResult(NamedTuple):
    returncode: Optional[int]  # None when the host watchdog killed the command
    stdout: bytes
    stderr: bytes
    timed_out: bool


class Settings(NamedTuple):
    openshell: str
    sandbox: str
    timeout: int
    env: List[str]
    out: str
    force: bool


def utc_now() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (now.microsecond // 1000)


def decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def mask_keys(text: str) -> str:
    """Replace key-shaped chunks with ***."""
    return KEY_CHUNK_RE.sub(lambda m: MASK if len(m.group(0)) >= KEY_CHUNK_MIN else m.group(0), text)


def looks_like_key(text: str) -> bool:
    return any(len(m.group(0)) >= KEY_CHUNK_MIN for m in KEY_CHUNK_RE.finditer(text))


def warn(text: str) -> None:
    print("%s: warning: %s" % (PROG, text), file=sys.stderr, flush=True)


# --- arguments and input ----------------------------------------------------------------------------------------


def parse_env(items: Optional[List[str]]) -> List[str]:
    """Check the --env items and return them as NAME=VALUE strings. Messages may name a variable, never a value."""
    pairs: List[str] = []
    seen = set()
    for item in items or []:
        name, sep, value = item.partition("=")
        if not ENV_NAME_RE.fullmatch(name):
            raise UsageError("--env expects NAME=VALUE with NAME matching %s (the item is not shown)"
                             % ENV_NAME_RE.pattern)
        if not sep:
            raise UsageError("--env %s: expected NAME=VALUE" % name)
        if any(part in name for part in ENV_NAME_REFUSED):
            raise UsageError("--env %s refused: names containing KEY, TOKEN or SECRET are not passed "
                             "(the OpenShell provider injects keys)" % name)
        if "\n" in value or "\r" in value:
            raise UsageError("--env %s refused: the value has a line break" % name)
        if looks_like_key(value):
            raise UsageError("--env %s refused: the value looks like a key (the OpenShell provider injects keys)"
                             % name)
        if name in seen:
            raise UsageError("--env %s given twice" % name)
        seen.add(name)
        pairs.append(name + "=" + value)
    return pairs


def load_cases(path: str) -> List[Dict[str, str]]:
    """case_id, split and request of every case, nothing else. Messages give line numbers, never case content."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = list(fh)
    except FileNotFoundError:
        raise UsageError("--cases file not found") from None
    except UnicodeDecodeError:
        raise UsageError("--cases file is not UTF-8") from None
    except OSError as exc:
        raise UsageError("--cases file cannot be read (%s)" % (exc.strerror or type(exc).__name__)) from None
    cases: List[Dict[str, str]] = []
    seen = set()
    for lineno, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            raise UsageError("cases line %d: not valid JSON" % lineno) from None
        if not isinstance(obj, dict):
            raise UsageError("cases line %d: not a JSON object" % lineno)
        case_id, split, request = obj.get("case_id"), obj.get("split"), obj.get("request")
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
            raise UsageError("cases line %d: case_id must match %s" % (lineno, CASE_ID_RE.pattern))
        if not isinstance(split, str) or split not in SPLITS:
            raise UsageError("cases line %d (%s): split must be dev or holdout" % (lineno, case_id))
        if not isinstance(request, str) or not request.strip() or "\x00" in request:
            raise UsageError("cases line %d (%s): request must be non-empty text" % (lineno, case_id))
        if case_id.lower() in seen:  # folder names: macOS file systems ignore case
            raise UsageError("cases line %d: case_id %s appears twice (case is ignored)" % (lineno, case_id))
        seen.add(case_id.lower())
        cases.append({"case_id": case_id, "split": split, "request": request})
    if not cases:
        raise UsageError("--cases file has no cases")
    return cases


def select_cases(cases: List[Dict[str, str]], split: str, only: Optional[str]) -> List[Dict[str, str]]:
    wanted = None
    if only is not None:
        wanted = [item.strip() for item in only.split(",") if item.strip()]
        if not wanted:
            raise UsageError("--only needs case ids such as E01,E02")
        known = {c["case_id"] for c in cases}
        unknown = [item for item in wanted if item not in known]
        if unknown:
            shown = ", ".join(item if CASE_ID_RE.fullmatch(item) else "<id not shown>" for item in unknown)
            raise UsageError("--only: not in the cases file: %s" % shown)
    selected = [c for c in cases
                if (split == "all" or c["split"] == split) and (wanted is None or c["case_id"] in wanted)]
    if not selected:
        raise UsageError("no case left after --split %s%s" % (split, "" if only is None else " and --only"))
    return selected


# --- running openshell ------------------------------------------------------------------------------------------


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run_command(argv: List[str], timeout_s: float) -> CommandResult:
    """Run argv (no shell) with stdin closed. When timeout_s passes, the whole process group is killed and the output
    read so far is kept (returncode None, timed_out True)."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)
    try:
        try:
            out, err = proc.communicate(timeout=timeout_s)
            return CommandResult(proc.returncode, out, err, False)
        except subprocess.TimeoutExpired:
            pass
        _kill_group(proc)
        try:
            out, err = proc.communicate(timeout=KILL_GRACE_S)
        except subprocess.TimeoutExpired as exc:  # a process outside the group still holds a pipe
            out, err = exc.stdout, exc.stderr
        return CommandResult(None, out or b"", err or b"", True)
    except BaseException:
        _kill_group(proc)
        raise
    finally:
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass
        try:
            proc.wait(timeout=KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            pass


def status_text(result: CommandResult) -> str:
    return "killed by the host watchdog" if result.timed_out else "exit %d" % result.returncode


def loop_argv(s: Settings, mode: str, request: str) -> List[str]:
    argv = [s.openshell, "sandbox", "exec", "-n", s.sandbox, "--workdir", SANDBOX_WORKDIR, "--no-tty",
            "--timeout", str(s.timeout)]
    for pair in s.env:
        argv += ["--env", pair]
    return argv + ["--", SANDBOX_PYTHON, "-m", "loop", mode, request]


def copy_argv(s: Settings, run_id: str) -> List[str]:
    script = "rm -rf {dl}/{rid} && mkdir -p {dl} && cp -R {src}/{rid} {dl}/".format(
        dl=WORKSPACE_DL, rid=run_id, src=SANDBOX_OUTPUT)
    return [s.openshell, "sandbox", "exec", "-n", s.sandbox, "--no-tty", "--timeout", str(HELPER_TIMEOUT_S),
            "--", "sh", "-c", script]


def download_argv(s: Settings, run_id: str, dest: str) -> List[str]:
    return [s.openshell, "sandbox", "download", s.sandbox, WORKSPACE_DL + "/" + run_id, dest]


def cleanup_argv(s: Settings, run_id: str) -> List[str]:
    return [s.openshell, "sandbox", "exec", "-n", s.sandbox, "--no-tty", "--timeout", str(HELPER_TIMEOUT_S),
            "--", "rm", "-rf", WORKSPACE_DL + "/" + run_id]


def find_run_id(stdout: str) -> Tuple[Optional[str], Optional[str]]:
    """(run_id, None), or (None, why there is no run folder). Only the last non-empty line counts."""
    lines = [line for line in stdout.split("\n") if line.strip()]
    if not lines:
        return None, "no run_id line (stdout is empty)"
    match = RUN_ID_LINE_RE.fullmatch(lines[-1].rstrip())
    if match is None:
        return None, "no run_id line at the end of stdout"
    if match.group(1) == "-":
        return None, "run_id: - (the loop made no run folder)"
    return match.group(1), None


# --- the run folder ---------------------------------------------------------------------------------------------


class RunLog:
    """What openshell printed for one case and mode; written to logs/<mode>-<case_id>.txt with keys masked.
    The request is not repeated here."""

    def __init__(self, case_id: str, mode: str, started_at: str):
        self.lines = ["case_id: %s" % case_id, "mode: %s" % mode, "started_at: %s" % started_at]
        self.used = False

    def add(self, label: str, result: CommandResult) -> None:
        self.used = True
        self.lines += ["", "== %s: %s ==" % (label, status_text(result)),
                       "--- stdout ---", decode(result.stdout).rstrip("\n"),
                       "--- stderr ---", decode(result.stderr).rstrip("\n")]

    def note(self, text: str) -> None:
        self.used = True
        self.lines += ["", text]

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(mask_keys("\n".join(self.lines)) + "\n")


def find_special(root: str) -> Optional[str]:
    """Relative path of the first entry that is not a regular file or folder (links are not followed), or None."""
    if not stat.S_ISDIR(os.lstat(root).st_mode):
        return "."

    def fail(exc: OSError) -> None:
        raise exc

    for dirpath, dirnames, filenames in os.walk(root, onerror=fail):
        for name in dirnames + filenames:  # a link to a folder is listed in dirnames and not walked into
            path = os.path.join(dirpath, name)
            mode = os.lstat(path).st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                return os.path.relpath(path, root)
    return None


def locate_run_folder(landing: str, run_id: str) -> Optional[str]:
    """<landing>/<run_id>/ or <landing>/ itself, whichever holds run.json or trace.jsonl (checked in that order)."""
    for folder in (os.path.join(landing, run_id), landing):
        if os.path.isdir(folder) and any(os.path.isfile(os.path.join(folder, name))
                                         for name in ("run.json", "trace.jsonl")):
            return folder
    return None


def place(s: Settings, case_id: str, mode: str, run_id: str, source: str, tmp: str) -> Optional[str]:
    """Move the run folder into <out>/<system|baseline>/<case_id>/<run_id>/ with one rename of the case folder."""
    stage = os.path.join(tmp, "case")
    os.mkdir(stage)
    os.rename(source, os.path.join(stage, run_id))
    dest = os.path.join(s.out, MODE_DIRS[mode], case_id)
    if os.path.lexists(dest):
        return "a case folder appeared during the run; nothing was moved"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.rename(stage, dest)
    return None


def copy_download_place(s: Settings, case_id: str, mode: str, run_id: str, log: RunLog) -> Optional[str]:
    result = run_command(copy_argv(s, run_id), HELPER_TIMEOUT_S + HOST_MARGIN_S)
    log.add("copy into " + WORKSPACE_DL, result)
    if result.timed_out or result.returncode != 0:
        return "copy into %s failed (%s)" % (WORKSPACE_DL, status_text(result))
    try:
        tmp = tempfile.mkdtemp(prefix=".run_cases-", dir=s.out)  # same file system as the target: renames are atomic
    except OSError as exc:
        return "local file error (%s)" % (exc.strerror or type(exc).__name__)
    try:
        landing = os.path.join(tmp, "dl")
        os.mkdir(landing)
        result = run_command(download_argv(s, run_id, landing), DOWNLOAD_TIMEOUT_S)
        log.add("download", result)
        if result.timed_out or result.returncode != 0:
            return "download failed (%s)" % status_text(result)
        special = find_special(landing)
        if special is not None:
            log.note("download refused: %s is a link or special file" % special)
            return "download refused: it holds a link or special file"
        source = locate_run_folder(landing, run_id)
        if source is None:
            return "download has no run.json or trace.jsonl"
        return place(s, case_id, mode, run_id, source, tmp)
    except OSError as exc:  # starting the download, checking the files or the renames
        return "download or placing failed (%s)" % (exc.strerror or type(exc).__name__)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def fetch(s: Settings, case_id: str, mode: str, run_id: str, log: RunLog) -> Optional[str]:
    """Copy the run folder into the sandbox workspace, download it and place it, then clean the workspace copy up.
    None when the run folder is in place, otherwise a short reason."""
    if not RUN_ID_RE.fullmatch(run_id):  # it goes into a shell line inside the sandbox
        raise ValueError("refusing an unchecked run_id")
    error = copy_download_place(s, case_id, mode, run_id, log)
    try:
        result = run_command(cleanup_argv(s, run_id), HELPER_TIMEOUT_S + HOST_MARGIN_S)
    except OSError as exc:  # the run folder may already be in place; the cleanup never changes the outcome
        log.note("cleanup could not be run (%s)" % (exc.strerror or type(exc).__name__))
        warn("%s %s: cleanup of %s/%s could not be run" % (mode, case_id, WORKSPACE_DL, run_id))
        return error
    log.add("cleanup", result)
    if result.timed_out or result.returncode != 0:
        warn("%s %s: cleanup of %s/%s failed (%s); the copy stays in the sandbox"
             % (mode, case_id, WORKSPACE_DL, run_id, status_text(result)))
    return error


def run_folders(case_dir: str) -> List[str]:
    try:
        names = sorted(os.listdir(case_dir))
    except OSError:
        return []
    return [name for name in names if stat.S_ISDIR(os.lstat(os.path.join(case_dir, name)).st_mode)]


def remove_path(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)


def execute(s: Settings, case: Dict[str, str], mode: str, record: Dict, log: RunLog) -> None:
    watchdog = s.timeout + HOST_MARGIN_S
    result = run_command(loop_argv(s, mode, case["request"]), watchdog)
    log.add("exec", result)
    if result.timed_out:
        record["error"] = "exec killed by the host watchdog after %d s" % watchdog
        return
    record["exit_code"] = result.returncode
    run_id, why = find_run_id(decode(result.stdout))
    if run_id is None:
        record["error"] = why
        return
    record["run_id"] = run_id
    error = fetch(s, case["case_id"], mode, run_id, log)
    if error is None:
        record["downloaded"] = True
    else:
        record["error"] = error


def run_one(s: Settings, case: Dict[str, str], mode: str) -> Dict:
    case_id = case["case_id"]
    started_at = utc_now()
    started = time.monotonic()
    record = {"case_id": case_id, "split": case["split"], "mode": mode, "exit_code": None, "run_id": None,
              "seconds": 0.0, "downloaded": False, "error": None, "started_at": started_at}
    case_dir = os.path.join(s.out, MODE_DIRS[mode], case_id)
    if os.path.lexists(case_dir):
        if not s.force:
            runs = run_folders(case_dir)
            if len(runs) == 1:
                record["run_id"], record["error"] = runs[0], SKIPPED
            else:
                record["error"] = "%s: the case folder holds %d run folders" % (SKIPPED, len(runs))
            return record
        try:
            remove_path(case_dir)
        except OSError as exc:
            record["error"] = "--force could not remove the case folder (%s)" % (exc.strerror or type(exc).__name__)
            return record
    log = RunLog(case_id, mode, started_at)
    try:
        execute(s, case, mode, record, log)
    except OSError as exc:
        record["error"] = "openshell could not be run (%s)" % (exc.strerror or type(exc).__name__)
    finally:
        record["seconds"] = round(time.monotonic() - started, 1)
        if log.used:
            log.note("result: " + outcome(record))
            try:
                log.write(os.path.join(s.out, "logs", "%s-%s.txt" % (mode, case_id)))
            except OSError as exc:
                warn("%s %s: the log could not be written (%s)" % (mode, case_id, exc.strerror or "error"))
    return record


# --- records and summary ----------------------------------------------------------------------------------------


def code_text(code: Optional[int]) -> str:
    return "none" if code is None else str(code)


def is_failure(record: Dict) -> bool:
    return not record["downloaded"] and record["error"] != SKIPPED


def outcome(record: Dict) -> str:
    if record["downloaded"]:
        return "received %s (exit %s, %.1f s)" % (record["run_id"], code_text(record["exit_code"]), record["seconds"])
    if record["error"] == SKIPPED:
        return "skipped, the case folder exists (run_id %s)" % record["run_id"]
    return "FAILED: %s (exit %s, %.1f s)" % (record["error"], code_text(record["exit_code"]), record["seconds"])


def append_record(out: str, record: Dict) -> None:
    with open(os.path.join(out, "runs.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def summary(records: List[Dict], modes: List[str], elapsed: float) -> List[str]:
    lines = ["summary"]
    failures = []
    for mode in modes:
        mine = [r for r in records if r["mode"] == mode]
        failed = [r for r in mine if is_failure(r)]
        codes: Dict[Optional[int], int] = {}
        for r in failed:
            codes[r["exit_code"]] = codes.get(r["exit_code"], 0) + 1
        order = sorted(codes, key=lambda c: (c is None, c or 0))
        by_code = ", ".join("exit %s: %d" % (code_text(c), codes[c]) for c in order)
        lines.append("  %-8s  cases %d  received %d  skipped %d  failed %d%s  %.1f s" % (
            mode, len(mine), sum(1 for r in mine if r["downloaded"]), sum(1 for r in mine if r["error"] == SKIPPED),
            len(failed), " [%s]" % by_code if by_code else "", sum(r["seconds"] for r in mine)))
        failures += ["  failed: %s %s: %s" % (mode, r["case_id"], r["error"]) for r in failed]
    return lines + failures + ["  total %.1f s" % elapsed]


# --- main -------------------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="Run the evaluation cases inside the OpenShell sandbox and collect each run folder "
                               "(no scoring). See the module docstring for the full contract.")
    parser.add_argument("--cases", required=True, help="JSONL, one case per line; only case_id, split, request are read")
    parser.add_argument("--out", required=True, help="output folder: runs.jsonl, logs/, system/, baseline/")
    parser.add_argument("--mode", choices=("ask", "baseline", "both"), default="both")
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="all")
    parser.add_argument("--only", help="comma-separated case ids, e.g. E01,E02")
    parser.add_argument("--sandbox", default=SANDBOX_DEFAULT)
    parser.add_argument("--timeout", type=int, default=TIMEOUT_DEFAULT,
                        help="openshell exec --timeout in seconds (host watchdog: +%d)" % HOST_MARGIN_S)
    parser.add_argument("--env", action="append", metavar="NAME=VALUE",
                        help="passed to the loop exec; repeatable; never keys")
    parser.add_argument("--force", action="store_true", help="delete an existing case folder and run the case again")
    return parser


def prepare(args: argparse.Namespace) -> Tuple[Settings, List[Dict[str, str]], List[str]]:
    env = parse_env(args.env)
    if not SANDBOX_RE.fullmatch(args.sandbox):
        raise UsageError("--sandbox must match %s" % SANDBOX_RE.pattern)
    if args.timeout <= 0:
        raise UsageError("--timeout must be a positive number of seconds")
    cases = select_cases(load_cases(args.cases), args.split, args.only)
    openshell = shutil.which("openshell")
    if openshell is None:
        raise UsageError("openshell CLI not found on PATH")
    modes = ["ask", "baseline"] if args.mode == "both" else [args.mode]
    out = os.path.abspath(args.out)
    if os.path.exists(out) and not os.path.isdir(out):
        raise UsageError("--out exists and is not a folder")
    try:
        for sub in ["logs"] + [MODE_DIRS[m] for m in modes]:
            os.makedirs(os.path.join(out, sub), exist_ok=True)
    except OSError as exc:
        raise UsageError("--out cannot be prepared (%s)" % (exc.strerror or type(exc).__name__)) from None
    return Settings(openshell, args.sandbox, args.timeout, env, out, args.force), cases, modes


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings, cases, modes = prepare(args)
    except UsageError as exc:
        print("%s: error: %s" % (PROG, exc), file=sys.stderr)
        return 2
    total = len(cases) * len(modes)
    names = [pair.split("=", 1)[0] for pair in settings.env]
    print("%s: %d case(s) x %s on sandbox %s, exec timeout %d s (host watchdog %d s)%s" % (
        PROG, len(cases), "+".join(modes), settings.sandbox, settings.timeout, settings.timeout + HOST_MARGIN_S,
        "; --env " + ", ".join(names) if names else ""), flush=True)
    records: List[Dict] = []
    started = time.monotonic()
    step = 0
    try:
        for case in cases:
            for mode in modes:
                step += 1
                print("[%d/%d] %s %s ..." % (step, total, mode, case["case_id"]), flush=True)
                record = run_one(settings, case, mode)
                append_record(settings.out, record)
                records.append(record)
                print("[%d/%d] %s %s: %s" % (step, total, mode, case["case_id"], outcome(record)), flush=True)
    except KeyboardInterrupt:
        print("%s: interrupted; the case and mode in progress has no record" % PROG, file=sys.stderr)
        print("\n".join(summary(records, modes, time.monotonic() - started)), flush=True)
        return 130
    except OSError as exc:  # runs.jsonl could not be appended; later records would be lost too
        print("%s: error: runs.jsonl could not be written (%s)" % (PROG, exc.strerror or type(exc).__name__),
              file=sys.stderr)
        print("\n".join(summary(records, modes, time.monotonic() - started)), flush=True)
        return 1
    print("\n".join(summary(records, modes, time.monotonic() - started)), flush=True)
    return 1 if any(is_failure(r) for r in records) else 0


def _exit_on_signal(signum, _frame):
    raise SystemExit(128 + signum)  # unwinds through run_command, which kills the openshell process group


if __name__ == "__main__":
    for _signal in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(_signal, _exit_on_signal)
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
