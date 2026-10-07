"""CLI `python -m loop` with injected fakes (no real wiring, no network)."""

import json
import re

import pytest

from loop.__main__ import main


@pytest.fixture
def cli(kit, tmp_path):
    def run(argv, *, router=None, nemotron=None, tools=None, repo="o/r"):
        tools = tools or kit.FakeTools()
        router = router or kit.ScriptedChat(['{"weight": "heavy", "why": "코스"}'])
        nemotron = nemotron or kit.ScriptedChat([kit.plan_json(kit.COURSE_TOOLS)])
        clock = kit.FakeClock()
        factories = {
            "ask": lambda ns: {"registry": tools.registry(), "deps_factory": lambda chat: kit.make_deps(chat=chat),
                               "router_chat": router, "nemotron_chat": nemotron, "index_fingerprint": "fp",
                               "publish_repo": repo},
            "publish": lambda ns: {"registry": tools.registry(), "deps": kit.make_deps(), "publish_repo": repo},
            "baseline": lambda ns: {"nemotron_chat": nemotron},
            "clock": clock, "sleep": clock.sleep, "now": kit.FakeNow(),
        }
        return main([*argv, "--output-dir", str(tmp_path)], factories=factories), tools

    return run


LAST_LINE = re.compile(r"^run_id: (\d{8}T\d{6}Z-[0-9a-z]{4}|-)$")


def _last_line(out: str) -> str:
    lines = out.rstrip("\n").split("\n")
    assert out.endswith("\n")
    assert LAST_LINE.match(lines[-1]), lines[-1]
    return lines[-1]


def _run_ids(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir() if p.is_dir())


def test_ask_course_prints_status_and_exits_0(cli, tmp_path, capsys):
    code, _ = cli(["ask", "별무리 코스 짜줘"])
    out = capsys.readouterr().out
    assert code == 0
    run_id = _run_ids(tmp_path)[0]
    assert f"run_id: {run_id}" in out and "상태: PUBLISHED" in out and "별무리공원" in out
    run = json.loads((tmp_path / run_id / "run.json").read_text(encoding="utf-8"))
    assert run["index"] == {"collection": "kb", "fingerprint": "fp"}


def test_ask_unavailable_exits_1(cli, kit, capsys):
    code, _ = cli(["ask", "안녕"], router=kit.ScriptedChat([TimeoutError(), TimeoutError()]))
    assert code == 1
    assert "상태: UNAVAILABLE" in capsys.readouterr().out


def test_publish_run_with_created_exits_1_before_any_setup(cli, kit, tmp_path, capsys):
    assert cli(["ask", "별무리 코스 짜줘"])[0] == 0
    run_id = _run_ids(tmp_path)[0]
    capsys.readouterr()

    def no_setup(ns):
        raise AssertionError("publish setup must not run for a CREATED run")

    code = main(["publish", "--run", run_id, "--output-dir", str(tmp_path)], factories={"publish": no_setup})
    assert code == 1
    cap = capsys.readouterr()
    assert "다시 보내지 않습니다" in cap.err
    assert _last_line(cap.out) == f"run_id: {run_id}"


def test_publish_created_exits_1_even_without_repo(cli, tmp_path):
    assert cli(["ask", "별무리 코스 짜줘"])[0] == 0
    code, tools = cli(["publish", "--run", _run_ids(tmp_path)[0]], repo="")
    assert code == 1 and tools.calls == []


def test_publish_without_repo_exits_2(cli, kit, tmp_path, capsys):
    tools = kit.FakeTools(publish_kinds=[])  # always blocked -> pending, no CREATED yet
    assert cli(["ask", "별무리 코스 짜줘"], tools=tools)[0] == 0
    run_id = _run_ids(tmp_path)[0]
    capsys.readouterr()
    code, tools = cli(["publish", "--run", run_id], repo="")
    assert code == 2 and tools.calls == []
    assert _last_line(capsys.readouterr().out) == f"run_id: {run_id}"


def test_publish_pending_then_published_prints_run_id_last(cli, kit, tmp_path, capsys):
    assert cli(["ask", "별무리 코스 짜줘"], tools=kit.FakeTools(publish_kinds=[]))[0] == 0
    run_id = _run_ids(tmp_path)[0]
    capsys.readouterr()
    code, _ = cli(["publish", "--run", run_id], tools=kit.FakeTools(publish_kinds=["CREATED"]))
    assert code == 0
    out = capsys.readouterr().out
    assert "상태: PUBLISHED" in out
    assert _last_line(out) == f"run_id: {run_id}"


def test_publish_unknown_run_exits_2(cli):
    assert cli(["publish", "--run", "20261007T033105Z-0a1f"])[0] == 2


def test_baseline_exits_0(cli, kit, tmp_path, capsys):
    code, _ = cli(["baseline", "별무리 코스 짜줘"], nemotron=kit.ScriptedChat(['{"places": []}']))
    assert code == 0
    assert "상태: BASELINE_DONE" in capsys.readouterr().out
    assert (tmp_path / _run_ids(tmp_path)[0] / "baseline.json").is_file()


def test_usage_errors_exit_2(cli):
    assert cli([])[0] == 2
    assert cli(["ask", "  "])[0] == 2
    assert cli(["publish"])[0] == 2


def test_setup_error_exits_2(kit, tmp_path, capsys):
    def broken(ns):
        raise RuntimeError("설정 없음")

    assert main(["ask", "요청", "--output-dir", str(tmp_path)], factories={"ask": broken}) == 2
    assert "설정 오류" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_last_line_is_run_id_for_every_command(cli, kit, tmp_path, capsys):
    assert cli(["ask", "별무리 코스 짜줘"])[0] == 0
    ask_id = _run_ids(tmp_path)[0]
    assert _last_line(capsys.readouterr().out) == f"run_id: {ask_id}"
    assert cli(["baseline", "별무리 코스 짜줘"], nemotron=kit.ScriptedChat(['{"places": []}']))[0] == 0
    base_id = [x for x in _run_ids(tmp_path) if x != ask_id][0]
    assert _last_line(capsys.readouterr().out) == f"run_id: {base_id}"
    assert cli(["publish", "--run", ask_id])[0] == 1  # already CREATED
    assert _last_line(capsys.readouterr().out) == f"run_id: {ask_id}"


def test_last_line_on_unavailable_and_failed(cli, kit, tmp_path, capsys):
    assert cli(["ask", "안녕"], router=kit.ScriptedChat([TimeoutError(), TimeoutError()]))[0] == 1
    out = capsys.readouterr().out
    assert "상태: UNAVAILABLE" in out
    line = _last_line(out)
    assert line != "run_id: -" and line.split(": ")[1] in _run_ids(tmp_path)
    assert cli(["baseline", "코스"], nemotron=kit.ScriptedChat([TimeoutError()]))[0] == 1
    assert _last_line(capsys.readouterr().out) != "run_id: -"


@pytest.mark.parametrize("argv", [[], ["ask", "  "], ["publish"], ["publish", "--run", "../x"],
                                  ["publish", "--run", "20261007T033105Z-0a1f"]])
def test_last_line_is_dash_before_a_run_folder(cli, capsys, argv):
    assert cli(argv)[0] == 2
    assert _last_line(capsys.readouterr().out) == "run_id: -"


def test_setup_error_hides_message_and_prints_dash(kit, tmp_path, capsys):
    def broken(ns):
        raise RuntimeError("/somewhere/local/index 없음")

    assert main(["baseline", "요청", "--output-dir", str(tmp_path)], factories={"baseline": broken}) == 2
    cap = capsys.readouterr()
    assert "RuntimeError" in cap.err and "/somewhere" not in cap.err
    assert _last_line(cap.out) == "run_id: -"


def test_publish_with_broken_attempts_does_not_exit_1(cli, kit, tmp_path, capsys):
    assert cli(["ask", "별무리 코스 짜줘"], tools=kit.FakeTools(publish_kinds=[]))[0] == 0
    run_id = _run_ids(tmp_path)[0]
    (tmp_path / run_id / "publish.json").write_text('{"attempts": 5}', encoding="utf-8")
    capsys.readouterr()
    code, tools = cli(["publish", "--run", run_id], tools=kit.FakeTools(publish_kinds=["CREATED"]))
    assert code != 1
    assert _last_line(capsys.readouterr().out) == f"run_id: {run_id}"


def test_publish_exception_through_main_exits_3(cli, kit, tmp_path, capsys):
    assert cli(["ask", "별무리 코스 짜줘"], tools=kit.FakeTools(publish_kinds=[]))[0] == 0
    run_id = _run_ids(tmp_path)[0]
    capsys.readouterr()
    code, _ = cli(["publish", "--run", run_id], tools=kit.FakeTools(publish_kinds=["BLOCKED_BY_POLICY", "BOOM"]))
    assert code == 3
    assert _last_line(capsys.readouterr().out) == f"run_id: {run_id}"


def test_unexpected_exception_in_main_exits_3(kit, tmp_path, capsys):
    tools = kit.FakeTools(publish_kinds=[])
    clock = kit.FakeClock()
    factories = {
        "ask": lambda ns: {"registry": tools.registry(), "deps_factory": lambda chat: kit.make_deps(chat=chat),
                           "router_chat": kit.ScriptedChat(['{"weight": "heavy"}']),
                           "nemotron_chat": kit.ScriptedChat([kit.plan_json(kit.COURSE_TOOLS)]),
                           "publish_repo": "o/r"},
        "clock": clock, "sleep": clock.sleep, "now": kit.FakeNow(),
    }
    assert main(["ask", "코스", "--output-dir", str(tmp_path)], factories=factories) == 0
    run_id = _run_ids(tmp_path)[0]
    capsys.readouterr()

    def broken_clock():
        raise RuntimeError("시계 고장")

    factories = {"publish": lambda ns: {"registry": tools.registry(), "deps": kit.make_deps(), "publish_repo": "o/r"},
                 "clock": broken_clock, "sleep": clock.sleep, "now": kit.FakeNow()}
    assert main(["publish", "--run", run_id, "--output-dir", str(tmp_path)], factories=factories) == 3
    cap = capsys.readouterr()
    assert "RuntimeError" in cap.err and "시계 고장" not in cap.err
    assert _last_line(cap.out) == f"run_id: {run_id}"


@pytest.mark.parametrize("bad", ["abc", "-1", "181", "1.5"])
@pytest.mark.parametrize("command", [["ask", "별무리 코스 짜줘"], ["publish", "--run", "20261007T033105Z-0a1f"]])
def test_bad_approval_wait_env_exits_2_before_a_run(cli, tmp_path, capsys, monkeypatch, bad, command):
    monkeypatch.setenv("KCULTURE_APPROVAL_WAIT_S", bad)
    code, tools = cli(command)
    cap = capsys.readouterr()
    assert code == 2
    assert "KCULTURE_APPROVAL_WAIT_S" in cap.err
    assert _last_line(cap.out) == "run_id: -"
    assert list(tmp_path.iterdir()) == [] and tools.calls == []


def test_approval_wait_env_reaches_the_run(cli, kit, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("KCULTURE_APPROVAL_WAIT_S", "0")
    code, tools = cli(["ask", "별무리 코스 짜줘"], tools=kit.FakeTools(publish_kinds=[]))
    assert code == 0
    assert "상태: PUBLISH_PENDING_APPROVAL" in capsys.readouterr().out
    assert tools.calls.count("request_publish") == 1
