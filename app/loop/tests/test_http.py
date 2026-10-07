"""http_post_json, make_github_post, read_path with fakes (no network)."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import timezone

import pytest

from common import limits
from loop.http import OutOfScopePath, http_post_json, make_github_post, read_path, utc_now

FAKE_TOKEN = "placeholder-not-a-key"


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = io.BytesIO(body)

    def read(self, n=-1):
        return self._body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append((req, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def http_error(code, body):
    return urllib.error.HTTPError("https://x.example/", code, "msg", {}, io.BytesIO(body))


def test_201_created():
    opener = FakeOpener(FakeResponse(201, b'{"html_url": "https://github.com/o/r/issues/1"}'))
    out = http_post_json("https://x.example/p", {"X-Test": "1"}, {"title": "코스"}, opener=opener)
    assert out == {"status": 201, "body": '{"html_url": "https://github.com/o/r/issues/1"}', "error": None}
    req, timeout = opener.requests[0]
    assert req.get_method() == "POST"
    assert req.get_header("Content-type") == "application/json"
    assert req.get_header("X-test") == "1"
    assert json.loads(req.data.decode("utf-8")) == {"title": "코스"}
    assert "코스".encode("utf-8") in req.data
    assert timeout == 30


def test_403_policy_denied_body():
    opener = FakeOpener(http_error(403, b'{"error": "policy_denied"}'))
    out = http_post_json("https://x.example/p", {}, {}, opener=opener)
    assert out["status"] == 403 and "policy_denied" in out["body"] and out["error"] is None


def test_tunnel_403():
    opener = FakeOpener(urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden")))
    out = http_post_json("https://api.github.com/x", {}, {}, opener=opener)
    assert out == {"status": None, "body": "", "error": "TUNNEL_403"}


def test_tunnel_403_plain_oserror():
    opener = FakeOpener(OSError("Tunnel connection failed: 403 Forbidden"))
    assert http_post_json("https://x.example/", {}, {}, opener=opener)["error"] == "TUNNEL_403"


@pytest.mark.parametrize("exc", [urllib.error.URLError(ConnectionRefusedError("refused")), TimeoutError("t"),
                                 ValueError("odd")])
def test_other_errors_are_network(exc):
    out = http_post_json("https://x.example/", {}, {}, opener=FakeOpener(exc))
    assert out == {"status": None, "body": "", "error": "NETWORK"}


def test_body_cut_at_4kb():
    big = b"a" * (limits.HTTP_BODY_MAX_BYTES + 500)
    out = http_post_json("https://x.example/", {}, {}, opener=FakeOpener(FakeResponse(200, big)))
    assert len(out["body"]) == limits.HTTP_BODY_MAX_BYTES
    out = http_post_json("https://x.example/", {}, {}, opener=FakeOpener(http_error(500, big)))
    assert out["status"] == 500 and len(out["body"]) == limits.HTTP_BODY_MAX_BYTES


def test_redirect_status_returned_not_followed():
    out = http_post_json("https://x.example/", {}, {}, opener=FakeOpener(http_error(302, b"")))
    assert out == {"status": 302, "body": "", "error": None}


def test_default_opener_refuses_redirects():
    from loop import http as http_mod

    handler = http_mod._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/") is None


class RecordingPost:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, body):
        self.calls.append((url, dict(headers), body))
        return {"status": 201, "body": "", "error": None}


def test_github_headers_added_for_api_github():
    post = RecordingPost()
    fn = make_github_post(post=post, environ={"GITHUB_TOKEN": FAKE_TOKEN})
    assert fn("https://api.github.com/repos/o/r/issues", {"X-Extra": "1"}, {"title": "t"})["status"] == 201
    url, headers, body = post.calls[0]
    assert headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert headers["X-Extra"] == "1"
    assert body == {"title": "t"}


def test_github_headers_not_added_elsewhere():
    post = RecordingPost()
    fn = make_github_post(post=post, environ={"GITHUB_TOKEN": FAKE_TOKEN})
    fn("https://ntfy.example/topic", {}, {})
    fn("https://api.github.com.evil.example/x", {}, {})
    for _, headers, _ in post.calls:
        assert "Authorization" not in headers and "X-GitHub-Api-Version" not in headers


def test_github_without_token():
    post = RecordingPost()
    fn = make_github_post(post=post, environ={})
    fn("https://api.github.com/repos/o/r/issues", {}, {})
    headers = post.calls[0][1]
    assert "Authorization" not in headers
    assert headers["Accept"] == "application/vnd.github+json"


def test_github_token_read_at_call_time():
    env = {}
    post = RecordingPost()
    fn = make_github_post(post=post, environ=env)
    env["GITHUB_TOKEN"] = FAKE_TOKEN
    fn("https://api.github.com/repos/o/r/issues", {}, {})
    assert post.calls[0][1]["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_read_path_folder_and_file(tmp_path):
    (tmp_path / "b.txt").write_bytes(b"0123456789")
    (tmp_path / "a").mkdir()
    entries = read_path(str(tmp_path), 100, root=str(tmp_path))
    assert [e["name"] for e in entries] == ["a", "b.txt"]
    assert entries[0]["is_dir"] is True and entries[1]["is_dir"] is False
    assert entries[1]["size"] == 10
    assert set(entries[0]) == {"name", "is_dir", "size"}
    assert read_path(str(tmp_path / "b.txt"), 4, root=str(tmp_path)) == b"0123"
    assert read_path(str(tmp_path / "b.txt"), 100, root=str(tmp_path)) == b"0123456789"


def test_read_path_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_path(str(tmp_path / "nope"), 10, root=str(tmp_path))


def test_utc_now_is_aware():
    assert utc_now().tzinfo == timezone.utc


def test_github_auth_header_unredirected_through_real_post():
    opener = FakeOpener(FakeResponse(201, b"{}"))
    fn = make_github_post(post=lambda u, h, b: http_post_json(u, h, b, opener=opener),
                          environ={"GITHUB_TOKEN": FAKE_TOKEN})
    assert fn("https://api.github.com/repos/o/r/issues", {}, {"title": "t"})["status"] == 201
    req, _ = opener.requests[0]
    assert "Authorization" in req.unredirected_hdrs
    assert req.unredirected_hdrs["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert "Authorization" not in req.headers
    assert req.headers.get("Accept") == "application/vnd.github+json"
    assert req.headers.get("X-github-api-version") == "2022-11-28"


@pytest.fixture
def fake_root(tmp_path):
    """tmp_path/hackathon stands in for /hackathon; tmp_path/outside.txt is outside it."""
    root = tmp_path / "hackathon"
    (root / "input").mkdir(parents=True)
    (root / "input" / "a.txt").write_bytes(b"inside")
    (tmp_path / "outside.txt").write_bytes(b"outside")
    return root


def test_read_path_symlink_out_of_root_refused(fake_root, tmp_path):
    link = fake_root / "input" / "link"
    link.symlink_to(tmp_path / "outside.txt")
    with pytest.raises(OutOfScopePath) as ei:
        read_path(str(link), 100, root=str(fake_root))
    assert ei.value.kind == "OUT_OF_SCOPE"
    assert isinstance(ei.value, ValueError)
    assert str(tmp_path) not in str(ei.value) and "link" not in str(ei.value)


def test_read_path_symlink_inside_root_reads(fake_root):
    link = fake_root / "input" / "link"
    link.symlink_to(fake_root / "input" / "a.txt")
    assert read_path(str(link), 100, root=str(fake_root)) == b"inside"


def test_read_path_root_itself_lists(fake_root):
    entries = read_path(str(fake_root), 100, root=str(fake_root))
    assert entries == [{"name": "input", "is_dir": True, "size": 0}]


def test_read_path_sibling_with_same_prefix_refused(fake_root):
    sibling = fake_root.parent / (fake_root.name + "X")
    sibling.mkdir()
    (sibling / "a").write_bytes(b"x")
    with pytest.raises(OutOfScopePath):
        read_path(str(sibling / "a"), 100, root=str(fake_root))


def test_read_path_dotdot_escape_refused(fake_root):
    with pytest.raises(OutOfScopePath):
        read_path(str(fake_root / "input" / ".." / ".." / "outside.txt"), 100, root=str(fake_root))


def test_read_path_missing_inside_root(fake_root):
    with pytest.raises(FileNotFoundError):
        read_path(str(fake_root / "input" / "nope.txt"), 100, root=str(fake_root))


def test_read_path_default_root_is_hackathon(tmp_path):
    (tmp_path / "f.txt").write_bytes(b"x")
    with pytest.raises(OutOfScopePath):
        read_path(str(tmp_path / "f.txt"), 10)
