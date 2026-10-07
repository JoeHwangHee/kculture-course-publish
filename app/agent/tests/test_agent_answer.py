import json
import urllib.request

import pytest

from agent.answer import answer, parse_model_json
from agent.errors import ModelCallError
from agent.nim_client import NimClient
from agent.prompt import begin_marker

FAKE_KEY = "test-placeholder-key-0123456789"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access in tests")

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _blocked)


def chat_body(content, model="nvidia/test-model"):
    return json.dumps({"model": model, "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode()


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append(json.loads(req.data.decode("utf-8")))
        return self.responses.pop(0)


def client_with(contents_or_responses):
    responses = [r if isinstance(r, tuple) else (200, {}, chat_body(r)) for r in contents_or_responses]
    t = FakeTransport(responses)
    return NimClient("http://nim.test/v1", "nvidia/test-model", FAKE_KEY, transport=t, sleep=lambda s: None), t


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def query(self, q, k=5):
        self.calls.append((q, k))
        return self.hits[:k]


def hit(n, text="본문", source=None):
    return {"chunk_id": f"doc{n}#0", "source": source or f"doc{n}.md", "title": f"제목{n}", "mtime": "2026-01-01",
            "dates_in_text": [], "text": text, "rank": n, "score": 0.5 / n}


GOOD = {
    "answer": "경복궁은 09:00에 연다 [1]. 예전 자료는 10:00이었다 [2].",
    "citations": [1, 2],
    "conflicts": [{"topic": "개장 시각", "sources": [1, 2], "chosen": 1, "reason": "더 최근 날짜"}],
    "stale": [{"source": 2, "reason": "2019년 자료"}],
    "unknown": False,
}


def test_answer_happy_path_metadata():
    r = FakeRetriever([hit(1), hit(2), hit(3)])
    c, t = client_with([json.dumps(GOOD, ensure_ascii=False)])
    out = answer("경복궁은 몇 시에 여나?", r, c, k=3)
    assert r.calls == [("경복궁은 몇 시에 여나?", 3)]
    assert out["question"] == "경복궁은 몇 시에 여나?"
    assert out["answer"] == GOOD["answer"]
    assert out["citations"] == [1, 2]
    assert out["conflicts"] == GOOD["conflicts"]
    assert out["stale"] == GOOD["stale"]
    assert out["unknown"] is False
    assert out["parse_error"] is False
    assert out["warnings"] == []
    assert out["model"] == "nvidia/test-model"
    assert out["requests"] == {"model_calls": 1, "http_attempts": 1}
    assert isinstance(out["elapsed_s"], float) and out["elapsed_s"] >= 0
    assert out["chunks"][0] == {"n": 1, "source": "doc1.md", "chunk_id": "doc1#0", "title": "제목1",
                                "rank": 1, "score": 0.5}
    assert len(out["chunks"]) == 3
    # the prompt actually carried the evidence and asked for JSON
    sent = t.requests[0]
    assert sent["response_format"] == {"type": "json_object"}
    assert begin_marker(3) in sent["messages"][1]["content"]


def test_code_fenced_json_is_parsed():
    fenced = "```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```"
    assert parse_model_json(fenced)["citations"] == [1, 2]


@pytest.mark.parametrize("text", ["", "그냥 문장", "[1, 2]", '{"citations": [1]}', '{"answer": 3}'])
def test_parse_model_json_rejects(text):
    assert parse_model_json(text) is None


def test_parse_failure_retries_once_then_succeeds():
    r = FakeRetriever([hit(1)])
    c, t = client_with(["이건 JSON이 아니다", json.dumps({"answer": "답 [1]", "citations": [1]})])
    out = answer("q", r, c)
    assert out["parse_error"] is False
    assert out["answer"] == "답 [1]"
    assert out["requests"]["model_calls"] == 2
    assert len(t.requests) == 2
    # missing optional fields are filled with defaults
    assert out["conflicts"] == [] and out["stale"] == [] and out["unknown"] is False


def test_parse_failure_twice_keeps_raw_text():
    r = FakeRetriever([hit(1)])
    c, t = client_with(["첫 번째 원문", "두 번째 원문"])
    out = answer("q", r, c)
    assert out["parse_error"] is True
    assert out["answer"] == "두 번째 원문"
    assert out["citations"] == []
    assert out["requests"] == {"model_calls": 2, "http_attempts": 2}
    assert len(t.requests) == 2
    assert any("JSON" in w for w in out["warnings"])


def test_empty_content_counts_as_parse_failure():
    r = FakeRetriever([hit(1)])
    c, _ = client_with(["", ""])
    out = answer("q", r, c)
    assert out["parse_error"] is True
    assert out["answer"] == ""


def test_unknown_citation_numbers_are_dropped_with_warning():
    r = FakeRetriever([hit(1), hit(2)])
    bad = {
        "answer": "답",
        "citations": [1, 5, 0, True, "2", 2, 2],
        "conflicts": [{"topic": "t", "sources": [1, 9], "chosen": 9, "reason": "r"}],
        "stale": [{"source": 7, "reason": "old"}, {"source": 2, "reason": "old"}],
        "unknown": False,
    }
    c, _ = client_with([json.dumps(bad)])
    out = answer("q", r, c, k=2)
    assert out["citations"] == [1, 2]
    assert out["conflicts"] == [{"topic": "t", "sources": [1], "chosen": None, "reason": "r"}]
    assert out["stale"] == [{"source": 2, "reason": "old"}]
    joined = " ".join(out["warnings"])
    for n in ("5", "0", "9", "7"):
        assert n in joined


def test_retry_counts_include_http_retries():
    r = FakeRetriever([hit(1)])
    c, _ = client_with([(503, {}, b""), json.dumps({"answer": "a", "citations": [1]})])
    out = answer("q", r, c)
    assert out["requests"] == {"model_calls": 1, "http_attempts": 2}


def test_no_hits_does_not_call_model():
    r = FakeRetriever([])
    c, t = client_with([])
    out = answer("q", r, c)
    assert out["no_results"] is True
    assert out["chunks"] == []
    assert out["requests"] == {"model_calls": 0, "http_attempts": 0}
    assert t.requests == []


def test_model_failure_propagates():
    r = FakeRetriever([hit(1)])
    c, _ = client_with([(401, {}, b"")])
    with pytest.raises(ModelCallError):
        answer("q", r, c)


def test_answer_with_real_index(built_index):
    from retrieval.embedder import HashEmbedder
    from retrieval.index import Retriever

    retr = Retriever.load(built_index, HashEmbedder())
    c, t = client_with([json.dumps({"answer": "1446년 반포 [1]", "citations": [1]}, ensure_ascii=False)])
    out = answer("훈민정음은 언제 반포되었나", retr, c, k=3)
    assert out["chunks"][0]["source"] == "hunminjeongeum.md"
    assert len(out["chunks"]) == 3
    user = t.requests[0]["messages"][1]["content"]
    assert "출처: hunminjeongeum.md" in user
