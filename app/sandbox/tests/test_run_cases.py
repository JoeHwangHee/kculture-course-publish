"""Tests for app/sandbox/run_cases.py, the host-side runner of the evaluation cases.

No keys, no network, no real OpenShell. Each test writes a fake `openshell` (a Python program behind a /bin/sh
wrapper) into its temporary folder and runs the runner with PATH limited to that folder and the system folders, so the
real CLI cannot be reached. The fake keeps a pretend sandbox under its state folder:
  sandbox exec ... -- <python> -m loop <mode> <request>   scripted stdout/stderr/exit; may create the run folder
  sandbox exec ... -- sh -c 'rm -rf ... && cp -R ...'      copies /hackathon/output/<run_id> to /sandbox/work/dl/
  sandbox download <sb> /sandbox/... <dest>                copies the folder out, files right under <dest> by default
                                                           (as measured); a path outside /sandbox fails with the
                                                           OpenShell 0.0.116 error, so a return to downloading
                                                           /hackathon/output directly breaks every collection test
  sandbox exec ... -- rm -rf /sandbox/work/dl/<run_id>     cleanup
Every call is logged with its argv and what the fake saw on stdin. The runner itself is started with an open pipe as
stdin that nobody writes to: a runner that handed its stdin on would leave the fake waiting ("open"), not "eof".
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2]
RUNNER = APP_DIR / "sandbox" / "run_cases.py"
SYSTEM_PYTHON = Path("/usr/bin/python3")
LOOP_PY = "/opt/kculture/.venv/bin/python"
MODE_DIRS = {"ask": "system", "baseline": "baseline"}
RECORD_KEYS = ["case_id", "split", "mode", "exit_code", "run_id", "seconds", "downloaded", "error", "started_at"]
EXPECT_MARKER = "EXPECT-MARKER-q7Zt"
REQUEST_MARKER = "REQUEST-MARKER-k3Vw"
VALUE_MARKER = "VALUE-MARKER-m2Xc"
DEST = "<dest>"
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")

FAKE_OPENSHELL = r'''"""Fake `openshell` for the run_cases tests (see the test module docstring)."""
import json
import os
import re
import select
import shutil
import sys
import time

RID = r"\d{8}T\d{6}Z-[0-9a-z]{4}"
COPY_RE = re.compile(
    r"rm -rf /sandbox/work/dl/(?P<a>%s) && mkdir -p /sandbox/work/dl && cp -R /hackathon/output/(?P<b>%s) /sandbox/work/dl/"
    % (RID, RID))
CLEANUP_RE = re.compile(r"/sandbox/work/dl/(?P<rid>%s)" % RID)
LOOP_PY = "/opt/kculture/.venv/bin/python"


def stdin_state():
    try:
        ready, _, _ = select.select([0], [], [], 1.5)
    except (OSError, ValueError):
        return "closed"
    if not ready:
        return "open"
    try:
        return "eof" if os.read(0, 64) == b"" else "data"
    except OSError:
        return "closed"


def local(scn, sandbox_path):
    return os.path.join(scn["state"], sandbox_path.lstrip("/"))


def write_out(beh):
    sys.stdout.buffer.write(beh.get("stdout", "").encode("utf-8"))
    sys.stdout.flush()
    sys.stderr.buffer.write(beh.get("stderr", "").encode("utf-8"))
    sys.stderr.flush()


def run_loop(scn, mode, request):
    beh = scn["exec"].get(mode + "|" + request, {"stdout": "fake: no scenario\n", "exit": 3})
    folder = beh.get("folder")
    if folder:
        path = local(scn, "/hackathon/output/" + folder)
        os.makedirs(path)
        with open(os.path.join(path, "run.json"), "w", encoding="utf-8") as fh:
            json.dump({"run_id": folder, "mode": mode}, fh)
        with open(os.path.join(path, "trace.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"seq": 1, "run_id": folder}) + "\n")
    write_out(beh)
    time.sleep(beh.get("sleep", 0))
    return beh.get("exit", 0)


def copy_to_workspace(scn, run_id):
    beh = scn["copy"].get(run_id, {})
    if beh.get("exit"):
        write_out(beh)
        return beh["exit"]
    dst = local(scn, "/sandbox/work/dl/" + run_id)
    if os.path.lexists(dst):
        shutil.rmtree(dst)
    os.makedirs(local(scn, "/sandbox/work/dl"), exist_ok=True)
    src = local(scn, "/hackathon/output/" + run_id)
    if not os.path.isdir(src):
        sys.stderr.write("cp: cannot stat '/hackathon/output/%s': No such file or directory\n" % run_id)
        return 1
    shutil.copytree(src, dst, symlinks=True)
    return 0


def cleanup(scn, run_id):
    beh = scn["cleanup"].get(run_id, {})
    if beh.get("exit"):
        write_out(beh)
        return beh["exit"]
    shutil.rmtree(local(scn, "/sandbox/work/dl/" + run_id), ignore_errors=True)
    return 0


def sandbox_exec(scn, argv):
    cmd = argv[argv.index("--") + 1:]
    if len(cmd) == 5 and cmd[:3] == [LOOP_PY, "-m", "loop"]:
        return run_loop(scn, cmd[3], cmd[4])
    if len(cmd) == 3 and cmd[:2] == ["sh", "-c"]:
        m = COPY_RE.fullmatch(cmd[2])
        if m and m.group("a") == m.group("b"):
            return copy_to_workspace(scn, m.group("a"))
    if len(cmd) == 3 and cmd[:2] == ["rm", "-rf"]:
        m = CLEANUP_RE.fullmatch(cmd[2])
        if m:
            return cleanup(scn, m.group("rid"))
    sys.stderr.write("fake: unexpected exec command\n")
    return 64


def sandbox_download(scn, argv):
    src, dest = argv[3], argv[4]
    if src != "/sandbox" and not src.startswith("/sandbox/"):
        sys.stderr.write("Error: sandbox source path '%s' is outside the sandbox workspace (/sandbox)\n" % src)
        return 1
    run_id = src.rsplit("/", 1)[-1]
    beh = scn["download"].get(run_id, {})
    if beh.get("exit"):
        write_out(beh)
        return beh["exit"]
    folder = local(scn, src)
    if not os.path.isdir(folder):
        sys.stderr.write("Error: no such path in the sandbox: %s\n" % src)
        return 1
    target = os.path.join(dest, run_id) if beh.get("form") == "nested" else dest
    os.makedirs(target, exist_ok=True)
    if beh.get("empty"):
        with open(os.path.join(target, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("no run files\n")
    else:
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isdir(path):
                shutil.copytree(path, os.path.join(target, name), symlinks=True)
            else:
                shutil.copy2(path, os.path.join(target, name), follow_symlinks=False)
    special = beh.get("special")
    if special == "file_link":
        os.symlink("run.json", os.path.join(target, "linked.json"))
    elif special == "dir_link":
        os.makedirs(os.path.join(target, "sub"))
        os.symlink("..", os.path.join(target, "sub", "up"))
    elif special == "fifo":
        os.mkfifo(os.path.join(target, "pipe"))
    write_out(beh)
    return 0


def main():
    with open(os.environ["FAKE_OPENSHELL_SCENARIO"], encoding="utf-8") as fh:
        scn = json.load(fh)
    argv = sys.argv[1:]
    with open(scn["calls"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": argv, "stdin": stdin_state()}) + "\n")
    if argv[:2] == ["sandbox", "exec"] and "--" in argv:
        return sandbox_exec(scn, argv)
    if argv[:2] == ["sandbox", "download"] and len(argv) == 5:
        return sandbox_download(scn, argv)
    sys.stderr.write("fake: unexpected arguments\n")
    return 64


sys.exit(main())
'''


def rid(n: int) -> str:
    return "20261007T%06dZ-%04x" % (n, n)


def req(case_id: str) -> str:
    return "request for " + case_id


def case(case_id: str, split: str = "dev", request: str | None = None, **extra) -> dict:
    data = {"case_id": case_id, "split": split, "request": req(case_id) if request is None else request}
    data.update(extra)
    return data


def loop_argv(mode, request, sandbox="kculture", timeout="420", env=()):
    argv = ["sandbox", "exec", "-n", sandbox, "--workdir", "/opt/kculture", "--no-tty", "--timeout", timeout]
    for item in env:
        argv += ["--env", item]
    return argv + ["--", LOOP_PY, "-m", "loop", mode, request]


def copy_argv(run_id, sandbox="kculture"):
    script = ("rm -rf /sandbox/work/dl/%s && mkdir -p /sandbox/work/dl && cp -R /hackathon/output/%s /sandbox/work/dl/"
              % (run_id, run_id))
    return ["sandbox", "exec", "-n", sandbox, "--no-tty", "--timeout", "60", "--", "sh", "-c", script]


def cleanup_argv(run_id, sandbox="kculture"):
    return ["sandbox", "exec", "-n", sandbox, "--no-tty", "--timeout", "60", "--", "rm", "-rf",
            "/sandbox/work/dl/" + run_id]


def fetch_argvs(run_id, sandbox="kculture"):
    """The three calls after a valid run_id line: copy into the workspace, download, cleanup."""
    return [copy_argv(run_id, sandbox), ["sandbox", "download", sandbox, "/sandbox/work/dl/" + run_id, DEST],
            cleanup_argv(run_id, sandbox)]


def without_dest(argv):
    return argv[:4] + [DEST] if argv[:2] == ["sandbox", "download"] else argv


class Harness:
    """A temporary folder with the fake openshell, its scenario, a cases file and the --out folder."""

    def __init__(self, root: Path):
        self.root = root
        self.bin = root / "bin"
        self.state = root / "fake-sandbox"
        self.calls_path = root / "calls.jsonl"
        self.scenario_path = root / "scenario.json"
        self.cases_path = root / "cases.jsonl"
        self.out = root / "out"
        self.scenario = {"exec": {}, "copy": {}, "download": {}, "cleanup": {}}
        self.bin.mkdir()
        self.state.mkdir()
        fake = root / "fake_openshell.py"
        fake.write_text(FAKE_OPENSHELL, encoding="utf-8")
        wrapper = self.bin / "openshell"
        wrapper.write_text("#!/bin/sh\nexec %s %s \"$@\"\n" % (shlex.quote(sys.executable), shlex.quote(str(fake))),
                           encoding="utf-8")
        wrapper.chmod(0o755)

    def write_cases(self, cases):
        self.cases_path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")

    def on_loop(self, mode, request, stdout="", stderr="", exit=0, folder=None, sleep=0):
        self.scenario["exec"][mode + "|" + request] = {"stdout": stdout, "stderr": stderr, "exit": exit,
                                                       "folder": folder, "sleep": sleep}

    def ok(self, mode, request, run_id, exit=0):
        """The loop prints an answer and ends with `run_id: <run_id>`; the run folder exists in the sandbox."""
        self.on_loop(mode, request, stdout="answer for %s\nrun_id: %s\n" % (mode, run_id), exit=exit, folder=run_id)

    def on_copy(self, run_id, **beh):
        self.scenario["copy"][run_id] = beh

    def on_download(self, run_id, **beh):
        self.scenario["download"][run_id] = beh

    def on_cleanup(self, run_id, **beh):
        self.scenario["cleanup"][run_id] = beh

    def write_scenario(self):
        data = dict(self.scenario, calls=str(self.calls_path), state=str(self.state))
        self.scenario_path.write_text(json.dumps(data), encoding="utf-8")

    def fake_path(self) -> str:
        return os.pathsep.join([str(self.bin), "/usr/bin", "/bin"])

    def child_env(self, path=None) -> dict:
        env = {k: v for k, v in os.environ.items() if not any(p in k.upper() for p in ("KEY", "TOKEN", "SECRET"))}
        env["PATH"] = self.fake_path() if path is None else path
        env["FAKE_OPENSHELL_SCENARIO"] = str(self.scenario_path)
        return env

    def run(self, *args, python=(sys.executable,), path=None, with_files=True):
        self.write_scenario()
        argv = [*python, str(RUNNER)]
        if with_files:
            argv += ["--cases", str(self.cases_path), "--out", str(self.out)]
        argv += list(args)
        read_end, write_end = os.pipe()  # held open and never written: an inherited stdin would never reach EOF
        try:
            return subprocess.run(argv, stdin=read_end, capture_output=True, env=self.child_env(path), timeout=180,
                                  encoding="utf-8", errors="replace")
        finally:
            os.close(read_end)
            os.close(write_end)

    def calls(self) -> list:
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def loop_calls(self) -> list:
        return [c for c in self.calls() if LOOP_PY in c["argv"]]

    def download_calls(self) -> list:
        return [c for c in self.calls() if c["argv"][:2] == ["sandbox", "download"]]

    def records(self) -> list:
        path = self.out / "runs.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def case_dir(self, mode, case_id) -> Path:
        return self.out / MODE_DIRS[mode] / case_id

    def log(self, mode, case_id) -> str:
        return (self.out / "logs" / ("%s-%s.txt" % (mode, case_id))).read_text(encoding="utf-8")

    def workspace_leftovers(self) -> list:
        dl = self.state / "sandbox" / "work" / "dl"
        return sorted(p.name for p in dl.iterdir()) if dl.exists() else []


@pytest.fixture
def h(tmp_path) -> Harness:
    return Harness(tmp_path)


@pytest.fixture(scope="module")
def runner_module():
    spec = importlib.util.spec_from_file_location("run_cases_under_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_usage_error(proc):
    """Exit 2 from the runner itself (python also exits 2 when the script is missing, so the message is checked)."""
    assert proc.returncode == 2, proc.stderr
    assert "run_cases.py: error: " in proc.stderr


def summary_line(mode, cases, received, skipped, failed, codes=""):
    tail = r" \[%s\]" % re.escape(codes) if codes else r"(?! \[)"
    return re.compile(r"^\s*%s\s+cases %d\s+received %d\s+skipped %d\s+failed %d%s"
                      % (mode, cases, received, skipped, failed, tail), re.M)


# --- the normal path ---------------------------------------------------------------------------------------------


def test_ask_and_baseline_run_folders_are_both_collected(h):
    plan = [("E01", "ask"), ("E01", "baseline"), ("E02", "ask"), ("E02", "baseline")]
    h.write_cases([case("E01"), case("E02", split="holdout")])
    for n, (cid, mode) in enumerate(plan, 1):
        h.ok(mode, req(cid), rid(n))
    proc = h.run()
    assert proc.returncode == 0, proc.stderr

    expected = []
    for n, (cid, mode) in enumerate(plan, 1):
        expected += [loop_argv(mode, req(cid))] + fetch_argvs(rid(n))
    assert [without_dest(c["argv"]) for c in h.calls()] == expected
    for call in h.download_calls():
        dest = Path(call["argv"][4])
        assert h.out in dest.parents
        assert not {"system", "baseline"} & set(dest.relative_to(h.out).parts)
    assert h.workspace_leftovers() == []

    for n, (cid, mode) in enumerate(plan, 1):
        folder = h.case_dir(mode, cid)
        assert [p.name for p in folder.iterdir()] == [rid(n)]
        assert json.loads((folder / rid(n) / "run.json").read_text(encoding="utf-8")) == {"run_id": rid(n), "mode": mode}
        assert (folder / rid(n) / "trace.jsonl").is_file()
        assert "answer for %s" % mode in h.log(mode, cid)

    records = h.records()
    assert [list(r) for r in records] == [RECORD_KEYS] * 4
    assert [(r["case_id"], r["split"], r["mode"]) for r in records] == [
        ("E01", "dev", "ask"), ("E01", "dev", "baseline"), ("E02", "holdout", "ask"), ("E02", "holdout", "baseline")]
    for n, r in enumerate(records, 1):
        assert (r["exit_code"], r["run_id"], r["downloaded"], r["error"]) == (0, rid(n), True, None)
        assert isinstance(r["seconds"], float) and r["seconds"] == round(r["seconds"], 1)
        assert ISO_UTC.match(r["started_at"])

    assert sorted(p.name for p in h.out.iterdir()) == ["baseline", "logs", "runs.jsonl", "system"]
    assert summary_line("ask", 2, 2, 0, 0).search(proc.stdout)
    assert summary_line("baseline", 2, 2, 0, 0).search(proc.stdout)


def test_every_openshell_call_gets_a_closed_stdin(h):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    h.ok("baseline", req("E01"), rid(2))
    proc = h.run()
    assert proc.returncode == 0, proc.stderr
    calls = h.calls()
    assert {tuple(c["argv"][:2]) for c in calls} == {("sandbox", "exec"), ("sandbox", "download")}
    assert len(calls) == 8
    assert [c["stdin"] for c in calls] == ["eof"] * 8


def test_fake_refuses_downloads_outside_the_sandbox_workspace(h):
    """Pins the measured OpenShell 0.0.116 refusal in the fake: going back to downloading /hackathon/output
    directly would make every collection test fail."""
    h.write_scenario()
    proc = subprocess.run([str(h.bin / "openshell"), "sandbox", "download", "kculture", "/hackathon/output/" + rid(1),
                           str(h.root / "dl")], stdin=subprocess.DEVNULL, capture_output=True, env=h.child_env(),
                          timeout=30, encoding="utf-8")
    assert proc.returncode == 1
    assert "is outside the sandbox workspace (/sandbox)" in proc.stderr


def test_env_sandbox_and_timeout_reach_the_commands(h):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    env = ["PUBLISH_REPO=owner/repo", "KCULTURE_APPROVAL_WAIT_S=0", "NIM_BASE_URL=http://nim.local:8000/v1?a=b"]
    args = ["--mode", "ask", "--sandbox", "kc-test", "--timeout", "30"]
    for item in env:
        args += ["--env", item]
    proc = h.run(*args)
    assert proc.returncode == 0, proc.stderr
    assert [without_dest(c["argv"]) for c in h.calls()] == (
        [loop_argv("ask", req("E01"), sandbox="kc-test", timeout="30", env=env)] + fetch_argvs(rid(1), "kc-test"))


def test_mode_baseline_runs_only_the_baseline(h):
    h.write_cases([case("E01")])
    h.ok("baseline", req("E01"), rid(1))
    proc = h.run("--mode", "baseline")
    assert proc.returncode == 0, proc.stderr
    assert [c["argv"] for c in h.loop_calls()] == [loop_argv("baseline", req("E01"))]
    assert not (h.out / "system").exists()
    assert (h.case_dir("baseline", "E01") / rid(1) / "run.json").is_file()


def test_loop_exit_code_does_not_matter_when_the_run_folder_arrives(h):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1), exit=1)
    proc = h.run("--mode", "ask")
    assert proc.returncode == 0, proc.stderr
    [r] = h.records()
    assert (r["exit_code"], r["run_id"], r["downloaded"], r["error"]) == (1, rid(1), True, None)


def test_run_id_line_may_be_followed_by_blank_lines_and_crlf(h):
    h.write_cases([case("E01")])
    h.on_loop("ask", req("E01"), stdout="answer\r\nrun_id: %s\r\n\r\n   \n" % rid(1), folder=rid(1))
    proc = h.run("--mode", "ask")
    assert proc.returncode == 0, proc.stderr
    assert h.records()[0]["run_id"] == rid(1)
    assert (h.case_dir("ask", "E01") / rid(1) / "run.json").is_file()


@pytest.mark.parametrize("form", ["flat", "nested"])
def test_both_download_layouts_land_as_one_run_folder(h, form):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    h.on_download(rid(1), form=form)
    proc = h.run("--mode", "ask")
    assert proc.returncode == 0, proc.stderr
    folder = h.case_dir("ask", "E01")
    assert [p.name for p in folder.iterdir()] == [rid(1)]
    assert sorted(p.name for p in (folder / rid(1)).iterdir()) == ["run.json", "trace.jsonl"]


# --- failures that are recorded and do not stop the run ---------------------------------------------------------


def test_run_id_dash_is_a_failure_without_fetching(h):
    h.write_cases([case("E01"), case("E02")])
    h.on_loop("ask", req("E01"), stdout="router failed\nrun_id: -\n", exit=1)
    h.ok("ask", req("E02"), rid(2))
    proc = h.run("--mode", "ask")
    assert proc.returncode == 1
    first, second = h.records()
    assert (first["exit_code"], first["run_id"], first["downloaded"]) == (1, None, False)
    assert first["error"]
    assert (second["run_id"], second["downloaded"]) == (rid(2), True)  # the next case still ran
    assert [without_dest(c["argv"]) for c in h.calls()] == (
        [loop_argv("ask", req("E01")), loop_argv("ask", req("E02"))] + fetch_argvs(rid(2)))
    assert not h.case_dir("ask", "E01").exists()
    assert "router failed" in h.log("ask", "E01")
    assert summary_line("ask", 2, 1, 0, 1, "exit 1: 1").search(proc.stdout)


NO_RUN_ID_STDOUT = {
    "empty": "",
    "blank_lines": "\n  \n\n",
    "answer_only": "an answer without the line\n",
    "line_not_last": "run_id: %s\nprinted after it\n" % rid(1),
    "upper_case": "run_id: 20261007T000001Z-ABCD\n",
    "short_suffix": "run_id: 20261007T000001Z-ab1\n",
    "leading_space": " run_id: %s\n" % rid(1),
    "path": "run_id: ../../etc\n",
    "non_ascii_digits": "run_id: ２０２６１００７T０００００１Z-ab12\n",
}


@pytest.mark.parametrize("stdout", list(NO_RUN_ID_STDOUT.values()), ids=list(NO_RUN_ID_STDOUT))
def test_without_a_run_id_line_at_the_end_nothing_is_fetched(h, stdout):
    h.write_cases([case("E01")])
    h.on_loop("ask", req("E01"), stdout=stdout, folder=rid(1))
    proc = h.run("--mode", "ask")
    assert proc.returncode == 1
    [r] = h.records()
    assert (r["exit_code"], r["run_id"], r["downloaded"]) == (0, None, False)
    assert r["error"]
    assert [c["argv"] for c in h.calls()] == [loop_argv("ask", req("E01"))]
    assert not h.case_dir("ask", "E01").exists()


def test_copy_into_the_workspace_failing_is_a_failure(h):
    h.write_cases([case("E01")])
    h.on_loop("ask", req("E01"), stdout="run_id: %s\n" % rid(1))  # no run folder in the sandbox: cp fails
    proc = h.run("--mode", "ask")
    assert proc.returncode == 1
    [r] = h.records()
    assert (r["run_id"], r["downloaded"]) == (rid(1), False)
    assert "copy" in r["error"]
    assert [c["argv"] for c in h.calls()] == [loop_argv("ask", req("E01")), copy_argv(rid(1)), cleanup_argv(rid(1))]
    assert "No such file or directory" in h.log("ask", "E01")


@pytest.mark.parametrize("beh, words", [({"exit": 1, "stderr": "boom\n"}, "download failed"),
                                        ({"empty": True}, "no run.json or trace.jsonl")], ids=["exit_1", "empty"])
def test_failed_or_empty_download_is_a_failure(h, beh, words):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    h.on_download(rid(1), **beh)
    proc = h.run("--mode", "ask")
    assert proc.returncode == 1
    [r] = h.records()
    assert (r["run_id"], r["downloaded"]) == (rid(1), False)
    assert words in r["error"]
    assert not h.case_dir("ask", "E01").exists()
    assert h.workspace_leftovers() == []  # cleanup ran after the failed download


@pytest.mark.parametrize("special", ["file_link", "dir_link", "fifo"])
def test_links_and_special_files_in_the_download_are_refused(h, special):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    h.on_download(rid(1), special=special)
    proc = h.run("--mode", "ask")
    assert proc.returncode == 1
    [r] = h.records()
    assert (r["run_id"], r["downloaded"]) == (rid(1), False)
    assert "link or special file" in r["error"]
    assert not h.case_dir("ask", "E01").exists()
    assert sorted(p.name for p in h.out.iterdir()) == ["logs", "runs.jsonl", "system"]  # no staging folder left
    assert list((h.out / "system").iterdir()) == []
    assert h.workspace_leftovers() == []


def test_cleanup_failure_is_logged_and_the_run_folder_still_counts(h):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    h.on_cleanup(rid(1), exit=1, stderr="rm: busy\n")
    proc = h.run("--mode", "ask")
    assert proc.returncode == 0, proc.stderr
    [r] = h.records()
    assert (r["downloaded"], r["error"]) == (True, None)
    assert "cleanup" in proc.stderr
    assert "rm: busy" in h.log("ask", "E01")


# --- existing case folders and --force --------------------------------------------------------------------------


def test_existing_case_folder_is_skipped_and_force_runs_it_again(h):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    assert h.run("--mode", "ask").returncode == 0

    h.ok("ask", req("E01"), rid(2))
    proc = h.run("--mode", "ask")
    assert proc.returncode == 0, proc.stderr
    assert len(h.loop_calls()) == 1
    skipped = h.records()[-1]
    assert (skipped["exit_code"], skipped["run_id"], skipped["downloaded"], skipped["error"]) == (
        None, rid(1), False, "skipped_existing")
    assert [p.name for p in h.case_dir("ask", "E01").iterdir()] == [rid(1)]
    assert summary_line("ask", 1, 0, 1, 0).search(proc.stdout)

    proc = h.run("--mode", "ask", "--force")
    assert proc.returncode == 0, proc.stderr
    assert len(h.loop_calls()) == 2
    assert [p.name for p in h.case_dir("ask", "E01").iterdir()] == [rid(2)]
    rerun = h.records()[-1]
    assert (rerun["run_id"], rerun["downloaded"], rerun["error"]) == (rid(2), True, None)
    assert len(h.records()) == 3


def test_skipping_is_per_mode(h):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    assert h.run("--mode", "ask").returncode == 0
    h.ok("baseline", req("E01"), rid(2))
    proc = h.run()
    assert proc.returncode == 0, proc.stderr
    assert [(r["mode"], r["error"]) for r in h.records()[1:]] == [("ask", "skipped_existing"), ("baseline", None)]
    assert [c["argv"] for c in h.loop_calls()] == [loop_argv("ask", req("E01")), loop_argv("baseline", req("E01"))]


def test_force_removes_the_old_case_folder_before_running_again(h):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    assert h.run("--mode", "ask").returncode == 0
    h.on_loop("ask", req("E01"), stdout="run_id: -\n", exit=1)
    proc = h.run("--mode", "ask", "--force")
    assert proc.returncode == 1
    assert not h.case_dir("ask", "E01").exists()  # the result reflects this run, not the earlier one


def test_existing_case_folder_without_exactly_one_run_folder_is_a_failure(h):
    h.write_cases([case("E01")])
    for name in (rid(1), rid(2)):
        (h.case_dir("ask", "E01") / name).mkdir(parents=True)
    proc = h.run("--mode", "ask")
    assert proc.returncode == 1
    [r] = h.records()
    assert r["error"].startswith("skipped_existing") and r["error"] != "skipped_existing"
    assert (r["run_id"], r["downloaded"]) == (None, False)
    assert h.calls() == []


# --- arguments and input ----------------------------------------------------------------------------------------

REFUSED_ENV = {
    "nvidia_key_name": "NVIDIA_API_KEY=" + VALUE_MARKER,
    "anthropic_key_name": "ANTHROPIC_API_KEY=" + VALUE_MARKER,
    "github_token_name": "GITHUB_TOKEN=" + VALUE_MARKER,
    "secret_name": "CLIENT_SECRET=" + VALUE_MARKER,
    "lower_case_name": "publish_repo=" + VALUE_MARKER,
    "leading_digit": "1PUBLISH_REPO=" + VALUE_MARKER,
    "no_equals": VALUE_MARKER,
    "newline_value": "PUBLISH_REPO=owner/" + VALUE_MARKER + "\nX=1",
    "carriage_return_value": "PUBLISH_REPO=owner/" + VALUE_MARKER + "\r",
    "key_shaped_value": "NIM_BASE_URL=" + "nv" + "api-" + VALUE_MARKER + "x" * 20,
    "given_twice": "KCULTURE_APPROVAL_WAIT_S=" + VALUE_MARKER,
}


@pytest.mark.parametrize("item", list(REFUSED_ENV.values()), ids=list(REFUSED_ENV))
def test_env_items_that_could_carry_keys_are_refused(h, item):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    proc = h.run("--env", "KCULTURE_APPROVAL_WAIT_S=0", "--env", item)
    assert_usage_error(proc)
    assert h.calls() == []
    assert VALUE_MARKER not in proc.stdout + proc.stderr
    assert not (h.out / "runs.jsonl").exists()


@pytest.mark.parametrize("args", [["--timeout", "0"], ["--timeout", "-5"], ["--timeout", "x"],
                                  ["--sandbox", "bad name"], ["--sandbox=-x"], ["--mode", "all"],
                                  ["--split", "train"]])
def test_bad_options_exit_2(h, args):
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    proc = h.run(*args)
    assert_usage_error(proc)
    assert h.calls() == []


@pytest.mark.parametrize("args, expected", [
    ([], ["E01", "E02", "E03"]),
    (["--split", "dev"], ["E01", "E03"]),
    (["--split", "holdout"], ["E02"]),
    (["--split", "all"], ["E01", "E02", "E03"]),
    (["--only", "E02"], ["E02"]),
    (["--only", "E03, E01"], ["E01", "E03"]),
    (["--split", "dev", "--only", "E01,E02"], ["E01"]),
])
def test_split_and_only_select_cases_in_file_order(h, args, expected):
    h.write_cases([case("E01"), case("E02", split="holdout"), case("E03")])
    for n, cid in enumerate(["E01", "E02", "E03"], 1):
        h.ok("ask", req(cid), rid(n))
    proc = h.run("--mode", "ask", *args)
    assert proc.returncode == 0, proc.stderr
    assert [c["argv"][-1] for c in h.loop_calls()] == [req(cid) for cid in expected]
    assert [r["case_id"] for r in h.records()] == expected


@pytest.mark.parametrize("args", [["--only", "E09"], ["--only", " , "], ["--split", "holdout", "--only", "E01"]],
                         ids=["unknown_id", "empty_list", "nothing_left"])
def test_selection_that_runs_nothing_exits_2(h, args):
    h.write_cases([case("E01"), case("E02", split="holdout")])
    proc = h.run(*args)
    assert_usage_error(proc)
    assert h.calls() == []


BAD_CASE_FILES = {
    "broken_json": '{"case_id": "E01", "split": "dev", "request": "r", "expect": {"x": "%s"}\n' % EXPECT_MARKER,
    "not_an_object": '["E01", "dev", "%s"]\n' % EXPECT_MARKER,
    "missing_case_id": '{"split": "dev", "request": "%s"}\n' % EXPECT_MARKER,
    "blank_request": '{"case_id": "E01", "split": "dev", "request": "  ", "expect": "%s"}\n' % EXPECT_MARKER,
    "request_not_text": '{"case_id": "E01", "split": "dev", "request": ["%s"]}\n' % EXPECT_MARKER,
    "unknown_split": '{"case_id": "E01", "split": "train", "request": "%s"}\n' % EXPECT_MARKER,
    "path_like_case_id": '{"case_id": "../E01", "split": "dev", "request": "%s"}\n' % EXPECT_MARKER,
    "duplicate_case_id": ('{"case_id": "E01", "split": "dev", "request": "a"}\n'
                          '{"case_id": "e01", "split": "dev", "request": "%s"}\n' % EXPECT_MARKER),
    "no_cases": "\n\n",
}


@pytest.mark.parametrize("text", list(BAD_CASE_FILES.values()), ids=list(BAD_CASE_FILES))
def test_bad_case_files_exit_2_without_echoing_content(h, text):
    h.cases_path.write_text(text, encoding="utf-8")
    proc = h.run()
    assert_usage_error(proc)
    assert h.calls() == []
    assert EXPECT_MARKER not in proc.stdout + proc.stderr
    assert not (h.out / "runs.jsonl").exists()


def test_missing_cases_file_exits_2(h):
    proc = h.run()  # cases.jsonl was never written
    assert_usage_error(proc)
    assert h.calls() == []


def test_missing_openshell_cli_exits_2(h, tmp_path):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    h.write_cases([case("E01")])
    proc = h.run(path=str(empty))
    assert_usage_error(proc)
    assert "openshell" in proc.stderr


# --- what must never leave the runner ---------------------------------------------------------------------------


def test_expect_and_request_stay_out_of_console_and_records(h):
    expect = {"route": "heavy", "status_in": [EXPECT_MARKER], "must_include_place_ids": [EXPECT_MARKER + "-place"],
              "max_total_min": 180, "publish_requested": True}
    one, two = REQUEST_MARKER + " one", REQUEST_MARKER + " two"
    h.write_cases([case("E01", request=one, expect=expect),
                   case("E02", split="holdout", request=two, expect=expect, note=EXPECT_MARKER)])
    h.ok("ask", one, rid(1))
    h.ok("baseline", one, rid(2))
    h.on_loop("ask", two, stdout="no run\nrun_id: -\n", exit=1)
    h.ok("baseline", two, rid(3))
    proc = h.run()
    assert proc.returncode == 1

    console = proc.stdout + proc.stderr
    assert EXPECT_MARKER not in console
    assert REQUEST_MARKER not in console
    files = [p for p in h.out.rglob("*") if p.is_file()]
    assert len(files) >= 8  # runs.jsonl, 4 logs, run.json and trace.jsonl of the three runs
    for path in files:
        assert EXPECT_MARKER not in path.read_bytes().decode("utf-8", "replace"), path.name
    assert REQUEST_MARKER not in (h.out / "runs.jsonl").read_text(encoding="utf-8")
    for log in (h.out / "logs").iterdir():
        assert REQUEST_MARKER not in log.read_text(encoding="utf-8"), log.name
    assert EXPECT_MARKER not in h.calls_path.read_text(encoding="utf-8")  # openshell never sees the expectations


def test_logs_mask_key_shaped_strings(h):
    keys = ["nv" + "api-" + "Q" * 40, "sk-" + "ant-" + "api03-" + "w" * 30, "gh" + "p_" + "E" * 36,
            "github_" + "pat_" + "11" + "R" * 40]
    short = "gh" + "p_" + "abc"
    h.write_cases([case("E01")])
    h.on_loop("ask", req("E01"), stdout="uses %s\n%s and %s\nrun_id: %s\n" % (keys[0], keys[1], short, rid(1)),
              stderr="header %s; %s\n" % (keys[2], keys[3]), folder=rid(1))
    h.on_cleanup(rid(1), exit=1, stderr="cleanup saw %s\n" % keys[0])
    proc = h.run("--mode", "ask")
    assert proc.returncode == 0, proc.stderr
    log = h.log("ask", "E01")
    for key in keys:
        assert key not in log
        assert key not in proc.stdout + proc.stderr
    assert log.count("***") >= 5
    assert short in log  # short chunks are not key-shaped
    assert (h.out / "runs.jsonl").read_text(encoding="utf-8").count("***") == 0


# --- host watchdog ----------------------------------------------------------------------------------------------

GRANDCHILD_PARENT = (
    "import os, subprocess, sys, time\n"
    "pid_file = sys.argv[1]\n"
    "subprocess.Popen([sys.executable, '-c', 'import os, sys, time\\n"
    "open(sys.argv[1], \"w\").write(str(os.getpid()))\\ntime.sleep(60)', pid_file])\n"
    "deadline = time.time() + 10\n"
    "while not os.path.exists(pid_file) and time.time() < deadline:\n"
    "    time.sleep(0.05)\n"
    "print('started', flush=True)\n"
    "time.sleep(60)\n"
)


def _wait_gone(pid, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def test_watchdog_kills_the_whole_process_group(runner_module, tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    started = time.monotonic()
    result = runner_module.run_command([sys.executable, "-c", GRANDCHILD_PARENT, str(pid_file)], 5.0)
    assert time.monotonic() - started < 25
    assert result.timed_out is True
    assert result.returncode is None
    assert b"started" in result.stdout
    grandchild = int(pid_file.read_text(encoding="utf-8"))
    assert _wait_gone(grandchild), "the grandchild holding stdout survived the watchdog"


def test_run_command_returns_exit_code_and_output(runner_module):
    code = "import sys\nprint('out')\nprint('err', file=sys.stderr)\nprint(repr(sys.stdin.read()))\nsys.exit(3)\n"
    result = runner_module.run_command([sys.executable, "-c", code], 30)
    assert result.timed_out is False
    assert result.returncode == 3
    assert result.stdout.decode().split() == ["out", "''"]
    assert result.stderr.decode().strip() == "err"


def test_watchdog_timeout_is_a_failure_without_fetching(h, runner_module, monkeypatch):
    h.write_cases([case("E01")])
    h.on_loop("ask", req("E01"), stdout="answer\nrun_id: %s\n" % rid(1), folder=rid(1), sleep=30)
    h.write_scenario()
    monkeypatch.setattr(runner_module, "HOST_MARGIN_S", 0)
    monkeypatch.setenv("PATH", h.fake_path())
    monkeypatch.setenv("FAKE_OPENSHELL_SCENARIO", str(h.scenario_path))
    started = time.monotonic()
    rc = runner_module.main(["--cases", str(h.cases_path), "--out", str(h.out), "--mode", "ask", "--timeout", "3"])
    assert time.monotonic() - started < 25
    assert rc == 1
    [r] = h.records()
    assert (r["exit_code"], r["run_id"], r["downloaded"]) == (None, None, False)
    assert "watchdog" in r["error"]
    assert [c["argv"] for c in h.calls()] == [loop_argv("ask", req("E01"), timeout="3")]
    log = h.log("ask", "E01")
    assert "answer" in log and "watchdog" in log


# --- Python 3.9 (macOS system python3) --------------------------------------------------------------------------


@pytest.mark.skipif(not SYSTEM_PYTHON.exists(), reason="no system python3 at /usr/bin/python3")
def test_runner_works_with_the_system_python(h):
    version = subprocess.run([str(SYSTEM_PYTHON), "-I", "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                             capture_output=True, encoding="utf-8", timeout=60)
    assert version.returncode == 0
    h.write_cases([case("E01")])
    h.ok("ask", req("E01"), rid(1))
    h.ok("baseline", req("E01"), rid(2))
    h.on_download(rid(2), form="nested")
    proc = h.run(python=(str(SYSTEM_PYTHON), "-I"))
    assert proc.returncode == 0, "python %s: %s" % (version.stdout.strip(), proc.stderr)
    assert [(r["run_id"], r["downloaded"]) for r in h.records()] == [(rid(1), True), (rid(2), True)]
