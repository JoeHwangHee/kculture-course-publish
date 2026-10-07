"""Local web server for the kculture agent (W2).

Runs one agent request at a time inside the OpenShell sandbox and reads the run folder back.
Standard library only. Binds to 127.0.0.1 only.

    python3 app/web/server.py [--port 8787] [--sandbox kculture]

Routes
    GET  /               index.html next to this file (404 when missing)
    POST /api/ask        {"question": "<text>"} -> {"job": "<id>"}; 409 while a job runs; 400 on bad input;
                         415 unless Content-Type is application/json (blocks cross-site form posts)
    GET  /api/jobs/<id>  {"state": "running|done|failed", "elapsed_s": n, "result": {...}|null, "error": "..."|null}

Every request whose Host header is not 127.0.0.1:<port> or localhost:<port> gets 403 (DNS rebinding guard).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import unicodedata
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_SANDBOX = "kculture"

INDEX_PATH = Path(__file__).parent / "index.html"

WORKDIR = "/opt/kculture"
AGENT_PYTHON = "/opt/kculture/.venv/bin/python"
OUTPUT_ROOT = "/hackathon/output"
ASK_TIMEOUT_S = 600  # openshell --timeout for the agent run
WATCHDOG_S = 660  # outer watchdog for the ask call (read at call time so tests can shrink it)
CAT_TIMEOUT_S = 30  # openshell --timeout for reading one result file
CAT_WATCHDOG_S = 60  # outer watchdog for one cat call

# Host environment variables forwarded into the sandbox, in this order, only when set and non-empty.
ENV_NAMES = ("PUBLISH_REPO", "NIM_BASE_URL", "NIM_MODEL", "NIM_API_KEY_ENV", "KCULTURE_APPROVAL_WAIT_S")
RESULT_FILES = (("run", "run.json"), ("course", "course.json"), ("answer", "answer.json"), ("publish", "publish.json"))

QUESTION_MAX = 500
MAX_BODY = 64 * 1024
RUN_ID_RE = re.compile(r"run_id: (\d{8}T\d{6}Z-[0-9a-z]{4})")
JOB_PATH_RE = re.compile(r"/api/jobs/([0-9a-f]{32})")
BAD_ENV_CHARS = re.compile(r"[\s'\"`\x00-\x1f\x7f]")

# Key-shaped strings are masked as *** (patterns built from pieces so the secret scan does not flag this file).
_MASK_PATTERNS = (
    re.compile(re.escape("nv" + "api-") + r"[A-Za-z0-9_\-]{8,}", re.I),
    re.compile(re.escape("sk" + "-ant-") + r"[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?<![A-Za-z0-9])" + "gh" + r"[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(re.escape("github" + "_pat_") + r"[A-Za-z0-9_]{16,}"),
    re.compile(r"(?i)(?<=bearer )[A-Za-z0-9._~+/\-]{20,}=*"),
)


def mask(value):
    """Mask key-shaped substrings in strings, dict keys and list items (recursive)."""
    if isinstance(value, str):
        for pat in _MASK_PATTERNS:
            value = pat.sub("***", value)
        return value
    if isinstance(value, dict):
        return {mask(k): mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


def clean_question(raw) -> str | None:
    """Drop control characters (Unicode Cc), strip, then 1..500 characters and not starting with '-'."""
    if not isinstance(raw, str):
        return None
    q = "".join(ch for ch in raw if unicodedata.category(ch) != "Cc").strip()
    if not 1 <= len(q) <= QUESTION_MAX or q.startswith("-"):
        return None
    return q


def env_args() -> list[str]:
    """`--env NAME=value` pairs from the host environment (whitelist only). Raises ValueError naming a bad variable."""
    out: list[str] = []
    for name in ENV_NAMES:
        val = os.environ.get(name)
        if not val:
            continue
        if BAD_ENV_CHARS.search(val):
            raise ValueError(f"환경변수 {name} 값에 공백·따옴표·제어 문자가 있어 거부함")
        if any(pat.search(val) for pat in _MASK_PATTERNS):
            raise ValueError(f"환경변수 {name} 값이 키 모양이라 거부함")
        out += ["--env", f"{name}={val}"]
    return out


def _openshell() -> str | None:
    return shutil.which("openshell")


def _run(argv: list[str], watchdog_s: float) -> tuple[int | None, str]:
    """Run argv with stdin closed in its own process group. Returns (exit code or None on watchdog, stdout)."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=watchdog_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.communicate()
        return None, ""
    return proc.returncode, out.decode("utf-8", "replace")


def _last_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


class JobFailed(Exception):
    pass


def run_job(sandbox: str, question: str) -> dict:
    """Run one agent request in the sandbox and return the result dict (raises JobFailed with a short message)."""
    try:
        envs = env_args()
    except ValueError as exc:
        raise JobFailed(str(exc)) from None
    exe = _openshell()
    if exe is None:
        raise JobFailed("openshell을 찾지 못함")
    argv = [exe, "sandbox", "exec", "-n", sandbox, "--workdir", WORKDIR, "--no-tty", "--timeout", str(ASK_TIMEOUT_S),
            *envs, "--", AGENT_PYTHON, "-m", "loop", "ask", question]
    code, out = _run(argv, WATCHDOG_S)
    if code is None:
        raise JobFailed(f"시간 초과({WATCHDOG_S}초)")
    m = RUN_ID_RE.fullmatch(_last_line(out))
    if not m:
        raise JobFailed(f"run_id 없음(종료 {code})")
    run_id = m.group(1)
    result: dict = {"run_id": run_id, "status": None, "route": None}
    for key, fname in RESULT_FILES:
        exe = _openshell()
        if exe is None:
            break
        cat = [exe, "sandbox", "exec", "-n", sandbox, "--no-tty", "--timeout", str(CAT_TIMEOUT_S), "--",
               "cat", f"{OUTPUT_ROOT}/{run_id}/{fname}"]
        rc, text = _run(cat, CAT_WATCHDOG_S)
        if rc != 0:
            continue
        try:
            result[key] = json.loads(text)
        except ValueError:
            continue
    run = result.get("run")
    if isinstance(run, dict):
        result["status"] = run.get("status")
        result["route"] = run.get("route")
    return mask(result)


class App:
    """Per-server state: jobs table and the one-at-a-time lock."""

    def __init__(self, sandbox: str):
        self.sandbox = sandbox
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()  # held while a job runs
        self.table_lock = threading.Lock()

    def start(self, question: str) -> str | None:
        if not self.lock.acquire(blocking=False):
            return None
        job_id = uuid.uuid4().hex
        with self.table_lock:
            self.jobs[job_id] = {"state": "running", "started": time.monotonic(), "ended": None,
                                 "result": None, "error": None}
        threading.Thread(target=self._work, args=(job_id, question), daemon=True).start()
        return job_id

    def _work(self, job_id: str, question: str) -> None:
        state, result, error = "failed", None, "예상하지 못한 오류"
        try:
            result = run_job(self.sandbox, question)
            state, error = "done", None
        except JobFailed as exc:
            error = mask(str(exc))
        except Exception as exc:  # keep the server alive; short message only
            error = f"예상하지 못한 오류: {type(exc).__name__}"
        finally:
            with self.table_lock:
                job = self.jobs[job_id]
                job.update(state=state, result=result, error=error, ended=time.monotonic())
            self.lock.release()

    def view(self, job_id: str) -> dict | None:
        with self.table_lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            end = job["ended"] if job["ended"] is not None else time.monotonic()
            return {"state": job["state"], "elapsed_s": round(end - job["started"], 1),
                    "result": job["result"], "error": job["error"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "kculture-web"

    def log_message(self, fmt, *args):  # no request logging (questions could hold personal text)
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        """DNS rebinding guard: the Host header must name the loopback address and the bound port."""
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").strip().lower()
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "Host 머리글이 허용되지 않음"})
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            index = INDEX_PATH
            if not index.is_file():
                return self._json(404, {"error": "index.html 없음"})
            return self._send(200, index.read_bytes(), "text/html; charset=utf-8")
        m = JOB_PATH_RE.fullmatch(path)
        if m:
            view = self.server.app.view(m.group(1))
            if view is None:
                return self._json(404, {"error": "작업 없음"})
            return self._json(200, view)
        return self._json(404, {"error": "없음"})

    def do_POST(self):
        if not self._host_ok():
            return self._json(403, {"error": "Host 머리글이 허용되지 않음"})
        path = self.path.split("?", 1)[0]
        if path != "/api/ask":
            return self._json(404, {"error": "없음"})
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            return self._json(415, {"error": "Content-Type은 application/json이어야 함"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json(400, {"error": "본문 길이 오류"})
        if length <= 0 or length > MAX_BODY:
            return self._json(400, {"error": "본문 길이 오류"})
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return self._json(400, {"error": "JSON이 아님"})
        if not isinstance(body, dict):
            return self._json(400, {"error": "JSON 객체가 아님"})
        question = clean_question(body.get("question"))
        if question is None:
            return self._json(400, {"error": f"질문은 1~{QUESTION_MAX}자(제어 문자 제외, '-'로 시작하지 않음)"})
        job_id = self.server.app.start(question)
        if job_id is None:
            return self._json(409, {"error": "이미 실행 중인 작업이 있음"})
        return self._json(200, {"job": job_id})


def make_server(port: int = DEFAULT_PORT, sandbox: str = DEFAULT_SANDBOX) -> ThreadingHTTPServer:
    """HTTP server bound to 127.0.0.1 (port 0 picks a free port). Call serve_forever() on it."""
    srv = ThreadingHTTPServer((HOST, port), Handler)
    srv.daemon_threads = True
    srv.app = App(sandbox)
    return srv


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="kculture 로컬 웹 서버(127.0.0.1 전용)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--sandbox", default=DEFAULT_SANDBOX)
    ns = p.parse_args(argv)
    srv = make_server(ns.port, ns.sandbox)
    print(f"http://{HOST}:{srv.server_address[1]}/ (샌드박스 {ns.sandbox})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
