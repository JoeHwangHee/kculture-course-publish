"""Publish attempts, approval wait and `publish --run` (spec 2.4)."""

import json

from common import limits
from common.schema import TRACE_JSONL

import pytest

from loop.publish import mask_local_paths, publish_run


def _pending_run(run_heavy_case, kit):
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], kit.FakeTools(publish_kinds=[]))
    assert r.out["status"] == "PUBLISH_PENDING_APPROVAL"
    return r


def _publish(tmp_path, kit, run_id, tools, clock=None, repo="o/r"):
    clock = clock or kit.FakeClock()
    return publish_run(run_id, output_root=tmp_path, registry=tools.registry(), deps=kit.make_deps(),
                       sleep=clock.sleep, clock=clock, now=kit.FakeNow(), publish_repo=repo)


def test_publish_run_after_pending_sends_and_continues_trace(run_heavy_case, kit, tmp_path):
    r = _pending_run(run_heavy_case, kit)
    n_before = len(r.publish.attempts)
    tools = kit.FakeTools(publish_kinds=["BLOCKED_BY_POLICY", "CREATED"])
    code, status = _publish(tmp_path, kit, r.out["run_id"], tools)
    assert (code, status) == (0, "PUBLISHED")
    after = kit.check_run(r.out["run_dir"], tmp_path)
    assert [a.result for a in after["publish"].attempts][n_before:] == ["BLOCKED_BY_POLICY", "CREATED"]
    assert after["publish"].status == "PUBLISHED"
    assert after["course"]["publish"]["status"] == "PUBLISHED"
    assert after["run"].status == "PUBLISHED"
    assert after["model_calls"] == r.model_calls and after["tokens"] == r.tokens  # kept as written by the run
    assert len(after["trace"]) > len(r.trace)
    assert [t["event"] for t in after["trace"]].count("final") == 2


def test_publish_run_with_created_sends_nothing_and_exits_1(run_heavy_case, kit, tmp_path):
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)])
    assert r.out["status"] == "PUBLISHED"
    before = (tmp_path / r.out["run_id"] / TRACE_JSONL).read_text(encoding="utf-8")
    tools = kit.FakeTools(publish_kinds=["CREATED"])
    code, _ = _publish(tmp_path, kit, r.out["run_id"], tools)
    assert code == 1
    assert tools.calls == []
    assert (tmp_path / r.out["run_id"] / TRACE_JSONL).read_text(encoding="utf-8") == before


def test_publish_run_timeout_exits_3(run_heavy_case, kit, tmp_path):
    r = _pending_run(run_heavy_case, kit)
    clock = kit.FakeClock()
    code, status = _publish(tmp_path, kit, r.out["run_id"], kit.FakeTools(publish_kinds=[]), clock=clock)
    assert (code, status) == (3, "PUBLISH_PENDING_APPROVAL")
    assert sum(clock.sleeps) == limits.APPROVAL_WAIT_SECONDS
    kit.check_run(r.out["run_dir"], tmp_path)


def test_publish_run_missing_or_bad_run_is_usage(kit, tmp_path):
    tools = kit.FakeTools()
    assert _publish(tmp_path, kit, "20261007T033105Z-0a1f", tools)[0] == 2
    assert _publish(tmp_path, kit, "../etc", tools)[0] == 2
    assert tools.calls == []


def test_publish_run_without_course_is_usage(run_heavy_case, kit, tmp_path):
    plan = kit.plan_json(["read_file"], publish=False, work="", args={0: {"path": "/hackathon/secrets"}})
    r = run_heavy_case([plan])
    assert _publish(tmp_path, kit, r.out["run_id"], kit.FakeTools())[0] == 2


def test_publish_json_has_no_body_or_headers(run_heavy_case, kit, tmp_path):
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS)], kit.FakeTools(publish_kinds=["HTTP_ERROR"]))
    data = json.loads((tmp_path / r.out["run_id"] / "publish.json").read_text(encoding="utf-8"))
    assert set(data) == {"status", "target", "repo", "attempts", "issue_url"}
    assert set(data["attempts"][0]) == {"ts", "result", "http_status"}
    summaries = [t["result"]["summary"] for t in r.trace if t["event"] == "publish_attempt"]
    assert summaries == ["HTTP 422"]


def test_publish_run_exception_keeps_attempts_final_and_exits_3(run_heavy_case, kit, tmp_path):
    r = _pending_run(run_heavy_case, kit)
    n_before = len(r.publish.attempts)
    tools = kit.FakeTools(publish_kinds=["BLOCKED_BY_POLICY", "BOOM"])
    code, status = _publish(tmp_path, kit, r.out["run_id"], tools)
    assert code == 3
    assert status == "PUBLISH_PENDING_APPROVAL"
    after = kit.check_run(r.out["run_dir"], tmp_path)  # trace chain intact and ends with final
    assert len(after["publish"].attempts) == n_before + 1
    assert after["publish"].attempts[-1].result == "BLOCKED_BY_POLICY"
    assert after["run"].status == "PUBLISH_PENDING_APPROVAL"
    assert "RuntimeError" in after["trace"][-1]["result"]["summary"]


def test_publish_run_unreadable_trace_is_usage(run_heavy_case, kit, tmp_path):
    r = _pending_run(run_heavy_case, kit)
    (tmp_path / r.out["run_id"] / TRACE_JSONL).write_text("깨진 줄\n", encoding="utf-8")
    tools = kit.FakeTools(publish_kinds=["CREATED"])
    assert _publish(tmp_path, kit, r.out["run_id"], tools)[0] == 2
    assert tools.calls == []


@pytest.mark.parametrize("text, expected", [
    ("[Errno 13] Permission denied: '/var/data/x.json'", "[Errno 13] Permission denied: '<경로>'"),
    ("열지 못함 /opt/kculture/index/kb/chunks.json 끝", "열지 못함 <경로> 끝"),
    ("거부 /hackathon/secrets/key.txt", "거부 /hackathon/secrets/key.txt"),
    ("폴더 /hackathon", "폴더 /hackathon"),
    ("POST https://api.github.com/repos/o/r/issues 실패", "POST https://api.github.com/repos/o/r/issues 실패"),
    ("a/b 상대 경로와 ./x", "a/b 상대 경로와 ./x"),
    ("/hackathonx/y", "<경로>"),
])
def test_mask_local_paths(text, expected):
    assert mask_local_paths(text) == expected


def test_tool_error_paths_are_masked_in_trace(run_heavy_case, kit, tmp_path):
    def leaky(args, ctx, deps):
        from common.tooling import ToolResult
        return ToolResult.tool_error(f"색인 없음: {tmp_path}/index/kb")

    tools = kit.FakeTools()
    tools.noop = leaky  # lookup_station etc. fail with a local path in the error
    r = run_heavy_case([kit.plan_json(kit.COURSE_TOOLS), kit.plan_json(["save_course"], start=9)], tools)
    text = (tmp_path / r.out["run_id"] / TRACE_JSONL).read_text(encoding="utf-8")
    assert "<경로>" in text


def test_created_url_survives_a_later_exception(run_heavy_case, kit, tmp_path):
    from common.tooling import RunContext
    from loop.budget import Budget
    from loop.publish import PublishOutcome, attempt_with_wait

    class FailingTrace:
        def append(self, event, **kw):
            raise RuntimeError("trace 고장")

    tools = kit.FakeTools(publish_kinds=["CREATED"])
    ctx = RunContext(run_id="20261007T033105Z-0a1f", course={"publish": {}}, publish_repo="o/r")
    outcome = PublishOutcome(status=None)
    clock = kit.FakeClock()
    with pytest.raises(RuntimeError):
        attempt_with_wait({"title": ""}, ctx, kit.make_deps(), registry=tools.registry(), trace=FailingTrace(),
                          budget=Budget(clock=clock), sleep=clock.sleep, clock=clock, now=kit.FakeNow(),
                          outcome=outcome)
    assert [a.result for a in outcome.attempts] == ["CREATED"]
    assert outcome.issue_url == "https://github.com/o/r/issues/1"


def test_publish_run_wait_limit_zero(run_heavy_case, kit, tmp_path):
    r = _pending_run(run_heavy_case, kit)
    clock = kit.FakeClock()
    tools = kit.FakeTools(publish_kinds=[])
    code, status = publish_run(r.out["run_id"], output_root=tmp_path, registry=tools.registry(),
                               deps=kit.make_deps(), sleep=clock.sleep, clock=clock, now=kit.FakeNow(),
                               publish_repo="o/r", approval_wait_s=0)
    assert (code, status) == (3, "PUBLISH_PENDING_APPROVAL")
    assert tools.calls == ["request_publish"] and clock.sleeps == []
