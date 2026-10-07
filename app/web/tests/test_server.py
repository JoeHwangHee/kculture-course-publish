"""Tests for app/web/server.py with a fake `openshell` on PATH (no network, no real sandbox)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SERVER_PATH = Path(__file__).resolve().parent.parent / "server.py"
RUN_ID = "20261007T071500Z-ab12"

FAKE_OPENSHELL = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys, time
    from pathlib import Path

    here = Path(__file__).resolve().parent
    cfg = json.loads((here / "fake.json").read_text(encoding="utf-8"))
    argv = sys.argv[1:]
    try:
        st, dn = os.fstat(0), os.stat(os.devnull)
        stdin_null = (st.st_dev, st.st_ino) == (dn.st_dev, dn.st_ino)
    except OSError:
        stdin_null = "closed"
    with open(here / "calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv, "stdin_null": stdin_null}, ensure_ascii=False) + "\\n")
    tail = argv[argv.index("--") + 1:]
    if tail[:1] == ["cat"]:
        name = tail[-1].rsplit("/", 1)[-1]
        files = cfg.get("files", {})
        if name not in files:
            sys.stderr.write("no such file\\n")
            sys.exit(1)
        val = files[name]
        sys.stdout.write(val if isinstance(val, str) else json.dumps(val, ensure_ascii=False))
        sys.exit(0)
    if cfg.get("wait_release"):
        (here / "started").write_text("1")
        deadline = time.monotonic() + 20
        while not (here / "release").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
    sys.stdout.write(cfg.get("ask_stdout", ""))
    sys.stdout.flush()
    sys.exit(cfg.get("ask_code", 0))
''')


def _load_server():
    spec = importlib.util.spec_from_file_location("kculture_web_server", SERVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def srv_mod():
    return _load_server()


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """Fake openshell in tmp_path/bin, first on PATH. Returns a helper to configure it and read its calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "openshell"
    exe.write_text(FAKE_OPENSHELL, encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    for name in ("PUBLISH_REPO", "NIM_BASE_URL", "NIM_MODEL", "NIM_API_KEY_ENV", "KCULTURE_APPROVAL_WAIT_S"):
        monkeypatch.delenv(name, raising=False)

    class Fake:
        dir = bin_dir

        def configure(self, **cfg):
            (bin_dir / "fake.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

        def calls(self):
            p = bin_dir / "calls.jsonl"
            if not p.exists():
                return []
            return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

        def release(self):
            (bin_dir / "release").write_text("1")

    f = Fake()
    f.configure()
    return f


@pytest.fixture
def server(srv_mod):
    srv = srv_mod.make_server(0, "kculture")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    t.join(timeout=5)


def _url(srv, path):
    return f"http://127.0.0.1:{srv.server_address[1]}{path}"


def _req(srv, method, path, body=None, raw=None, headers=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(_url(srv, path), data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def _ask(srv, question):
    code, _, body = _req(srv, "POST", "/api/ask", {"question": question})
    return code, json.loads(body)


def _wait(srv, job, limit=15.0):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        code, _, body = _req(srv, "GET", f"/api/jobs/{job}")
        assert code == 200
        view = json.loads(body)
        if view["state"] != "running":
            return view
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


def _ask_calls(calls):
    return [c for c in calls if c["argv"][c["argv"].index("--") + 1:][:1] != ["cat"]]


def _cat_calls(calls):
    return [c for c in calls if c["argv"][c["argv"].index("--") + 1:][:1] == ["cat"]]


# --- happy paths -------------------------------------------------------------------------------------------


def test_course_and_publish(fake, server):
    run = {"run_id": RUN_ID, "route": "heavy", "status": "PUBLISHED"}
    course = {"run_id": RUN_ID, "stops": [{"name": "혜화문"}]}
    publish = {"status": "PUBLISHED", "target": "github-issue", "issue_url": "https://example.invalid/1"}
    fake.configure(ask_stdout=f"log line\nrun_id: {RUN_ID}\n\n", ask_code=0,
                   files={"run.json": run, "course.json": course, "publish.json": publish})
    code, body = _ask(server, "드라마 배경지 코스 짜줘")
    assert code == 200 and set(body) == {"job"}
    view = _wait(server, body["job"])
    assert view["state"] == "done" and view["error"] is None
    assert isinstance(view["elapsed_s"], (int, float))
    res = view["result"]
    assert res == {"run_id": RUN_ID, "status": "PUBLISHED", "route": "heavy", "run": run, "course": course,
                   "publish": publish}
    calls = fake.calls()
    ask = _ask_calls(calls)
    assert len(ask) == 1
    argv = ask[0]["argv"]
    assert argv == ["sandbox", "exec", "-n", "kculture", "--workdir", "/opt/kculture", "--no-tty", "--timeout", "600",
                    "--", "/opt/kculture/.venv/bin/python", "-m", "loop", "ask", "드라마 배경지 코스 짜줘"]
    cats = _cat_calls(calls)
    assert [c["argv"][-1] for c in cats] == [f"/hackathon/output/{RUN_ID}/{n}"
                                            for n in ("run.json", "course.json", "answer.json", "publish.json")]
    for c in cats:
        assert c["argv"][:8] == ["sandbox", "exec", "-n", "kculture", "--no-tty", "--timeout", "30", "--"]


def test_light_answer(fake, server):
    run = {"run_id": RUN_ID, "route": "light", "status": "ANSWERED_LIGHT"}
    answer = {"answer": "안녕하세요", "evidence_label": "자료 근거 없음(일반 안내)"}
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n", files={"run.json": run, "answer.json": answer})
    _, body = _ask(server, "안녕")
    view = _wait(server, body["job"])
    assert view["state"] == "done"
    res = view["result"]
    assert res["route"] == "light" and res["status"] == "ANSWERED_LIGHT"
    assert res["answer"]["evidence_label"] == "자료 근거 없음(일반 안내)"
    assert "course" not in res and "publish" not in res


def test_unavailable_nonzero_exit_still_done(fake, server):
    run = {"run_id": RUN_ID, "route": "none", "status": "UNAVAILABLE"}
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n", ask_code=3, files={"run.json": run, "answer.json": "not json"})
    _, body = _ask(server, "코스 짜줘")
    view = _wait(server, body["job"])
    assert view["state"] == "done"
    assert view["result"]["status"] == "UNAVAILABLE"
    assert "answer" not in view["result"]  # invalid JSON is skipped quietly


@pytest.mark.parametrize("stdout", ["run_id: -\n", "", "no run id here\n", f"run_id: {RUN_ID}\nextra\n",
                                    "run_id: 2026-10-07-bad\n"])
def test_missing_run_id_fails(fake, server, stdout):
    fake.configure(ask_stdout=stdout, ask_code=2)
    _, body = _ask(server, "코스 짜줘")
    view = _wait(server, body["job"])
    assert view["state"] == "failed" and view["result"] is None
    assert view["error"] and len(view["error"]) < 80
    assert _cat_calls(fake.calls()) == []


# --- concurrency -------------------------------------------------------------------------------------------


def test_busy_returns_409(fake, server):
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n", wait_release=True, files={"run.json": {"status": "PUBLISHED"}})
    try:
        code, body = _ask(server, "첫 질문")
        assert code == 200
        job = body["job"]
        code2, body2 = _ask(server, "둘째 질문")  # lock taken synchronously in the POST handler
        assert code2 == 409 and "job" not in body2
        code3, _, b3 = _req(server, "GET", f"/api/jobs/{job}")
        assert code3 == 200 and json.loads(b3)["state"] == "running"
    finally:
        fake.release()
    assert _wait(server, job)["state"] == "done"
    code4, body4 = _ask(server, "셋째 질문")
    assert code4 == 200
    _wait(server, body4["job"])


# --- input validation --------------------------------------------------------------------------------------


@pytest.mark.parametrize("question", ["", "   ", "\x00\x07\n\t", "가" * 501, "-h", "--output-dir=x", 123, None])
def test_bad_question_400(fake, server, question):
    code, body = _ask(server, question)
    assert code == 400 and "job" not in body
    assert fake.calls() == []


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b"\xff\xfe"])
def test_bad_body_400(fake, server, raw):
    code, _, _ = _req(server, "POST", "/api/ask", raw=raw)
    assert code == 400


def test_500_chars_ok_and_control_chars_removed(fake, server, srv_mod):
    assert srv_mod.clean_question("가" * 500) == "가" * 500
    assert srv_mod.clean_question("가" * 501) is None
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n")
    _, body = _ask(server, "  혜화\x00문\x1b 유래\n알려줘\x7f  ")
    _wait(server, body["job"])
    assert _ask_calls(fake.calls())[0]["argv"][-1] == "혜화문 유래알려줘"


def test_unknown_job_404(server):
    code, _, _ = _req(server, "GET", "/api/jobs/" + "0" * 32)
    assert code == 404
    code, _, _ = _req(server, "GET", "/api/jobs/nope")
    assert code == 404


# --- CSRF and DNS rebinding guards ------------------------------------------------------------------------


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x",
                                   ""])
def test_post_without_json_content_type_415(fake, server, ctype):
    code, _, _ = _req(server, "POST", "/api/ask", {"question": "코스 짜줘"}, headers={"Content-Type": ctype})
    assert code == 415
    assert fake.calls() == []


def test_post_json_content_type_with_charset_ok(fake, server):
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n")
    code, _, body = _req(server, "POST", "/api/ask", {"question": "코스 짜줘"},
                         headers={"Content-Type": "Application/JSON; charset=utf-8"})
    assert code == 200
    _wait(server, json.loads(body)["job"])


@pytest.mark.parametrize("host", ["evil.example:{port}", "evil.example", "127.0.0.1", "127.0.0.1:1",
                                  "localhost.evil.example:{port}", "0.0.0.0:{port}"])
def test_foreign_host_403(fake, server, srv_mod, host, monkeypatch, tmp_path):
    page = tmp_path / "index.html"
    page.write_text("<!doctype html><title>k</title>", encoding="utf-8")
    monkeypatch.setattr(srv_mod, "INDEX_PATH", page)
    h = host.format(port=server.server_address[1])
    for method, path, body in (("GET", "/", None), ("GET", "/api/jobs/" + "0" * 32, None),
                               ("POST", "/api/ask", {"question": "코스 짜줘"})):
        code, _, _ = _req(server, method, path, body, headers={"Host": h})
        assert code == 403, (method, path, h)
    assert fake.calls() == []


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost"])
def test_loopback_hosts_allowed(fake, server, srv_mod, name, monkeypatch, tmp_path):
    page = tmp_path / "index.html"
    page.write_text("<!doctype html><title>k</title>", encoding="utf-8")
    monkeypatch.setattr(srv_mod, "INDEX_PATH", page)
    h = f"{name}:{server.server_address[1]}"
    code, _, _ = _req(server, "GET", "/", headers={"Host": h})
    assert code == 200
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n")
    code, _, body = _req(server, "POST", "/api/ask", {"question": "코스 짜줘"}, headers={"Host": h})
    assert code == 200
    job = json.loads(body)["job"]
    code, _, _ = _req(server, "GET", f"/api/jobs/{job}", headers={"Host": h})
    assert code == 200
    _wait(server, job)


# --- environment whitelist ---------------------------------------------------------------------------------


def test_env_whitelist_and_key_names_never_passed(fake, server, monkeypatch):
    nv = "nv" + "api-" + "x" * 40
    gh = "gh" + "p_" + "y" * 40
    monkeypatch.setenv("NVIDIA_API_KEY", nv)
    monkeypatch.setenv("GITHUB_TOKEN", gh)
    monkeypatch.setenv("SOME_SECRET", "s3cr3t-value")
    monkeypatch.setenv("PUBLISH_REPO", "owner/repo")
    monkeypatch.setenv("NIM_MODEL", "nvidia/nemotron-test")
    monkeypatch.setenv("NIM_API_KEY_ENV", "NIM_KEY_VAR_FOR_TEST")
    monkeypatch.setenv("KCULTURE_APPROVAL_WAIT_S", "")  # empty counts as absent
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n")
    _, body = _ask(server, "코스 짜줘")
    assert _wait(server, body["job"])["state"] == "done"
    calls = fake.calls()
    argv = _ask_calls(calls)[0]["argv"]
    head = argv[:argv.index("--")]
    assert head[9:] == ["--env", "PUBLISH_REPO=owner/repo", "--env", "NIM_MODEL=nvidia/nemotron-test",
                        "--env", "NIM_API_KEY_ENV=NIM_KEY_VAR_FOR_TEST"]
    blob = json.dumps([c["argv"] for c in calls])
    for bad in (nv, gh, "s3cr3t-value", "GITHUB_TOKEN", "SOME_SECRET", "NVIDIA_API_KEY"):
        assert bad not in blob
    for i, tok in enumerate(argv):
        if tok == "--env":
            assert argv[i + 1].split("=", 1)[0] in {"PUBLISH_REPO", "NIM_BASE_URL", "NIM_MODEL", "NIM_API_KEY_ENV",
                                                    "KCULTURE_APPROVAL_WAIT_S"}


@pytest.mark.parametrize("value", ["owner/repo extra", "a'b", 'a"b', "a\tb", "a`b"])
def test_env_value_with_space_or_quote_rejected(fake, server, monkeypatch, value):
    monkeypatch.setenv("PUBLISH_REPO", value)
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n")
    _, body = _ask(server, "코스 짜줘")
    view = _wait(server, body["job"])
    assert view["state"] == "failed" and "PUBLISH_REPO" in view["error"]
    assert value not in view["error"]
    assert fake.calls() == []


def test_env_value_key_shaped_rejected(fake, server, monkeypatch):
    nv = "nv" + "api-" + "k" * 40
    monkeypatch.setenv("NIM_MODEL", nv)
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n")
    _, body = _ask(server, "코스 짜줘")
    view = _wait(server, body["job"])
    assert view["state"] == "failed" and "NIM_MODEL" in view["error"]
    assert nv not in json.dumps(view, ensure_ascii=False)
    assert fake.calls() == []


# --- masking -----------------------------------------------------------------------------------------------


def test_key_shaped_strings_masked(fake, server, srv_mod):
    nv = "nv" + "api-" + "A1b2" * 10
    gh = "gh" + "p_" + "Z9" * 20
    pat = "github" + "_pat_" + "Q" * 30
    ant = "sk" + "-ant-" + "k" * 30
    bearer = "Bearer " + "t" * 40
    run = {"status": "PUBLISHED", "route": "heavy", "note": f"key {nv} here",
           "nested": [{"x": gh}, {pat: "v"}], "auth": bearer, "a": ant}
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n", files={"run.json": run})
    _, body = _ask(server, "코스 짜줘")
    view = _wait(server, body["job"])
    blob = json.dumps(view, ensure_ascii=False)
    for secret in (nv, gh, pat, ant, "t" * 40):
        assert secret not in blob
    assert view["result"]["run"]["note"] == "key *** here"
    assert view["result"]["run"]["nested"][0]["x"] == "***"
    assert srv_mod.mask(f"err {nv}") == "err ***"


def test_error_message_masked(srv_mod, monkeypatch):
    nv = "nv" + "api-" + "q" * 30

    def boom(sandbox, question):
        raise srv_mod.JobFailed(f"bad {nv}")

    monkeypatch.setattr(srv_mod, "run_job", boom)
    app = srv_mod.App("kculture")
    job = app.start("질문")
    deadline = time.monotonic() + 5
    while app.view(job)["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app.view(job)["error"] == "bad ***"


# --- stdin closed, binding, watchdog -----------------------------------------------------------------------


def test_stdin_is_devnull_for_every_call(fake, server, srv_mod, monkeypatch):
    seen = []
    real = subprocess.Popen

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(srv_mod.subprocess, "Popen", spy)
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n",
                   files={"run.json": {"status": "PUBLISHED"}, "course.json": {}, "publish.json": {}})
    _, body = _ask(server, "코스 짜줘")
    assert _wait(server, body["job"])["state"] == "done"
    calls = fake.calls()
    assert len(_ask_calls(calls)) == 1 and len(_cat_calls(calls)) == 4
    assert len(seen) == 5
    for kw in seen:
        assert kw.get("stdin") is subprocess.DEVNULL
        assert kw.get("start_new_session") is True
        assert kw.get("shell") in (None, False)
    for c in calls:  # layer 2: the child really saw /dev/null on fd 0
        assert c["stdin_null"] is True


def test_binds_loopback_only(srv_mod):
    srv = srv_mod.make_server(0, "kculture")
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()
    assert srv_mod.HOST == "127.0.0.1"


def test_watchdog_constant_and_timeout(fake, server, srv_mod, monkeypatch):
    assert srv_mod.WATCHDOG_S == 660
    monkeypatch.setattr(srv_mod, "WATCHDOG_S", 0.5)
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n", wait_release=True)
    try:
        _, body = _ask(server, "코스 짜줘")
        view = _wait(server, body["job"], limit=10)
    finally:
        fake.release()
    assert view["state"] == "failed" and "시간 초과" in view["error"]
    assert _cat_calls(fake.calls()) == []
    # the lock is released after a timeout
    fake.configure(ask_stdout=f"run_id: {RUN_ID}\n")
    code, body = _ask(server, "다시")
    assert code == 200
    _wait(server, body["job"])


def test_openshell_missing(fake, server, monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    _, body = _ask(server, "코스 짜줘")
    view = _wait(server, body["job"])
    assert view["state"] == "failed" and "openshell" in view["error"]


# --- index page --------------------------------------------------------------------------------------------


def test_index_404_then_200(server, srv_mod, tmp_path, monkeypatch):
    page = tmp_path / "index.html"
    monkeypatch.setattr(srv_mod, "INDEX_PATH", page)
    code, _, _ = _req(server, "GET", "/")
    assert code == 404
    page.write_text("<!doctype html><title>k</title>", encoding="utf-8")
    code, ctype, body = _req(server, "GET", "/")
    assert code == 200 and ctype == "text/html; charset=utf-8"
    assert body.startswith(b"<!doctype html>")


def test_no_init_py_in_web():
    web = SERVER_PATH.parent
    assert not list(web.rglob("__init__.py"))
    assert sys.version_info >= (3, 10)
