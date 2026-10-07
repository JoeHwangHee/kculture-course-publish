"""Tests for tools.publish (request_publish, spec 2.4 / 4.2)."""

from __future__ import annotations

import pytest

from common.schema import (
    KIND_BLOCKED_BY_POLICY,
    KIND_CREATED,
    KIND_HTTP_ERROR,
    KIND_NETWORK_ERROR,
    KIND_TOOL_ERROR,
)
from common.tooling import ToolRegistry
from tools import publish
from tools.tests.fakes import FakeHttp, make_ctx, make_deps

LEAK = "zz-response-body-marker-zz"


def _course() -> dict:
    return {
        "run_id": "20261007T033105Z-0a1f",
        "request": "별수단 배경지 코스",
        "goal": {"work": "별무리 수호단", "time_budget_min": 180, "start": "새벽솔", "constraints": [],
                 "publish_requested": True},
        "places": [],
        "total_min": None,
        "excluded": [],
        "unknowns": [],
        "warnings": [],
        "publish": {"status": "", "url": None},
    }


def _run(response: dict, **ctx_kwargs):
    http = FakeHttp(response)
    ctx_kwargs.setdefault("course", _course())
    ctx_kwargs.setdefault("publish_repo", "o/r")
    ctx = make_ctx(**ctx_kwargs)
    result = publish.run_request_publish({"title": ""}, ctx, make_deps(http=http))
    return result, http


def _assert_no_leak(result):
    assert set(result.data) == {"http_status", "issue_url"}
    assert LEAK not in str(result.data)
    assert LEAK not in result.error
    assert "\n" not in result.error


def test_tunnel_403_is_blocked_by_policy():
    result, http = _run({"status": None, "body": "", "error": "TUNNEL_403"})
    assert result.ok is False
    assert result.kind == KIND_BLOCKED_BY_POLICY
    assert result.data == {"http_status": None, "issue_url": None}
    assert not result.needs_replan
    assert len(http.calls) == 1


def test_403_policy_denied_body_is_blocked_by_policy():
    result, _ = _run({"status": 403, "body": '{"error": "policy_denied", "x": "' + LEAK + '"}', "error": None})
    assert result.ok is False
    assert result.kind == KIND_BLOCKED_BY_POLICY
    assert result.data == {"http_status": 403, "issue_url": None}
    _assert_no_leak(result)


def test_201_is_created_with_issue_url():
    result, _ = _run({"status": 201, "body": '{"html_url": "https://github.com/o/r/issues/1", "id": 7}',
                      "error": None})
    assert result.ok is True
    assert result.kind == KIND_CREATED
    assert result.data == {"http_status": 201, "issue_url": "https://github.com/o/r/issues/1"}
    assert result.error == ""


def test_cut_201_body_is_still_created_without_url():
    result, _ = _run({"status": 201, "body": '{"html_url": "https://github.com/o/r/iss', "error": None})
    assert result.ok is True
    assert result.kind == KIND_CREATED
    assert result.data == {"http_status": 201, "issue_url": None}


def test_201_with_non_string_html_url_has_no_url():
    result, _ = _run({"status": 201, "body": '{"html_url": 5}', "error": None})
    assert result.kind == KIND_CREATED
    assert result.data["issue_url"] is None


@pytest.mark.parametrize("status", [401, 404, 422, 500, 502, 200, 202])
def test_other_statuses_are_http_error_without_body(status):
    result, _ = _run({"status": status, "body": '{"message": "' + LEAK + '"}', "error": None})
    assert result.ok is False
    assert result.kind == KIND_HTTP_ERROR
    assert result.data == {"http_status": status, "issue_url": None}
    assert result.error == f"HTTP {status}"
    _assert_no_leak(result)


def test_403_without_policy_denied_is_http_error():
    result, _ = _run({"status": 403, "body": '{"message": "Resource not accessible ' + LEAK + '"}', "error": None})
    assert result.kind == KIND_HTTP_ERROR
    assert result.data == {"http_status": 403, "issue_url": None}
    _assert_no_leak(result)


def test_network_error():
    result, _ = _run({"status": None, "body": "", "error": "NETWORK"})
    assert result.ok is False
    assert result.kind == KIND_NETWORK_ERROR
    assert result.data == {"http_status": None, "issue_url": None}


def test_status_none_without_error_is_network_error():
    result, _ = _run({"status": None, "body": "", "error": None})
    assert result.kind == KIND_NETWORK_ERROR


def test_one_call_to_contract_url_without_auth_header():
    _, http = _run({"status": 201, "body": "{}", "error": None})
    assert len(http.calls) == 1
    url, headers, body = http.calls[0]
    assert url == "https://api.github.com/repos/o/r/issues"
    assert headers == {"Accept": "application/vnd.github+json"}
    assert "authorization" not in {k.lower() for k in headers}
    assert body["title"] == "K-콘텐츠 배경지 코스: 별무리 수호단"
    assert isinstance(body["body"], str) and "별무리 수호단" in body["body"]


def test_title_argument_is_used():
    http = FakeHttp({"status": 201, "body": "{}", "error": None})
    ctx = make_ctx(course=_course(), publish_repo="o/r")
    publish.run_request_publish({"title": "내 코스"}, ctx, make_deps(http=http))
    assert http.calls[0][2]["title"] == "내 코스"


def test_missing_course_is_tool_error_without_call():
    result, http = _run({"status": 201, "body": "{}", "error": None}, course=None)
    assert result.kind == KIND_TOOL_ERROR
    assert http.calls == []


@pytest.mark.parametrize("repo", ["", "o", "o/r/x", "o/../r", "o/r?x=1", "https://x/o/r"])
def test_bad_repo_is_tool_error_without_call(repo):
    result, http = _run({"status": 201, "body": "{}", "error": None}, publish_repo=repo)
    assert result.kind == KIND_TOOL_ERROR
    assert http.calls == []


def test_spec_registers_with_contract_args():
    registry = ToolRegistry()
    for spec in publish.SPECS:
        registry.register(spec)
    assert registry.names() == ["request_publish"]


def test_cut_201_body_with_issue_url_first_keeps_url():
    body = ('{"url": "https://api.github.com/repos/o/r/issues/1", "html_url": "https://github.com/o/r/issues/1", '
            '"user": {"login": "o", "html_url": "https://github.com/o", "bio": "' + "x" * 4000)
    body = body[:4096]
    result, _ = _run({"status": 201, "body": body, "error": None})
    assert result.ok is True
    assert result.kind == KIND_CREATED
    assert result.data == {"http_status": 201, "issue_url": "https://github.com/o/r/issues/1"}
    assert result.error == ""


def test_cut_201_body_with_only_user_html_url_has_no_url():
    body = ('{"user": {"login": "o", "html_url": "https://github.com/o", "bio": "' + "x" * 4000)[:4096]
    result, _ = _run({"status": 201, "body": body, "error": None})
    assert result.kind == KIND_CREATED
    assert result.data == {"http_status": 201, "issue_url": None}
