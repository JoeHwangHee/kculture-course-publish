import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

import pytest

from agent.__main__ import main
from conftest import APP_DIR

FAKE_KEY = "test-placeholder-key-0123456789"
FIXED_NOW = datetime(2026, 10, 7, 12, 34, 56, tzinfo=timezone.utc)

GOOD = {
    "answer": "훈민정음은 1446년에 반포되었다 [1].",
    "citations": [1, 4],
    "conflicts": [{"topic": "반포 연도", "sources": [1, 2], "chosen": 1, "reason": "더 공식적인 출처 | 최신"}],
    "stale": [{"source": 2, "reason": "2019년 자료"}],
    "unknown": False,
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access in tests")

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _blocked)
    monkeypatch.setenv("NIM_BASE_URL", "http://nim.test/v1")
    monkeypatch.delenv("NIM_MODEL", raising=False)


class FakeTransport:
    def __init__(self, contents):
        self.contents = list(contents)
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append(req)
        body = {"model": "nvidia/test-model",
                "choices": [{"message": {"content": self.contents.pop(0)}, "finish_reason": "stop"}]}
        return 200, {}, json.dumps(body, ensure_ascii=False).encode("utf-8")


def run_agent_cli(args, env_extra=None):
    env = dict(os.environ)
    env.pop("NVIDIA_API_KEY", None)
    env["HF_HUB_OFFLINE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["NIM_BASE_URL"] = "http://nim.test/v1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, "-m", "agent", *args], cwd=str(APP_DIR), env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=300)


@pytest.fixture()
def empty_index(tmp_path):
    from retrieval.embedder import HashEmbedder
    from retrieval.index import build_index

    inp = tmp_path / "empty_in"
    inp.mkdir()
    idx = tmp_path / "empty_idx"
    build_index(inp, idx, HashEmbedder())
    return idx


def test_missing_key_exit_2_subprocess(built_index):
    res = run_agent_cli(["ask", "--index", str(built_index), "--embedder", "hash", "훈민정음"])
    assert res.returncode == 2
    assert "NVIDIA_API_KEY" in res.stderr


def test_missing_key_exit_2_in_process(built_index, monkeypatch, capsys):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    t = FakeTransport([])
    code = main(["ask", "--index", str(built_index), "--embedder", "hash", "q"], transport=t)
    assert code == 2
    assert t.requests == []
    assert "NVIDIA_API_KEY" in capsys.readouterr().err


def test_usage_errors_exit_2(built_index, monkeypatch, tmp_path):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    t = FakeTransport([])
    assert main([], transport=t) == 2
    assert main(["ask", "--index", str(built_index), "--embedder", "hash"], transport=t) == 2
    assert main(["ask", "--index", str(tmp_path / "missing"), "--embedder", "hash", "q"], transport=t) == 2
    assert main(["ask", "--index", str(built_index), "--embedder", "bogus", "q"], transport=t) == 2
    assert main(["ask", "--index", str(built_index), "--embedder", "hash", "   "], transport=t) == 2
    assert main(["ask", "--index", str(built_index), "--embedder", "hash", "-k", "0", "q"], transport=t) == 2
    assert t.requests == []


def test_no_results_exit_1_without_model_call(empty_index, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    t = FakeTransport([])
    out_dir = tmp_path / "out"
    code = main(["ask", "--index", str(empty_index), "--embedder", "hash", "--out", str(out_dir), "q"], transport=t)
    assert code == 1
    assert t.requests == []
    assert "검색 결과" in capsys.readouterr().err
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_no_results_exit_1_subprocess(empty_index):
    res = run_agent_cli(["ask", "--index", str(empty_index), "--embedder", "hash", "q"],
                        env_extra={"NVIDIA_API_KEY": FAKE_KEY})
    assert res.returncode == 1, res.stderr
    assert FAKE_KEY not in res.stdout + res.stderr


def test_model_failure_exit_3(built_index, monkeypatch, capsys):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)

    def transport(req, timeout):
        return 401, {}, b"unauthorized " + FAKE_KEY.encode()

    code = main(["ask", "--index", str(built_index), "--embedder", "hash", "경복궁 관람 시간"], transport=transport)
    assert code == 3
    err = capsys.readouterr().err
    assert "401" in err
    assert FAKE_KEY not in err and "unauthorized" not in err


def test_success_writes_md_and_json_without_overwrite(built_index, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    out_dir = tmp_path / "output"
    content = json.dumps(GOOD, ensure_ascii=False)
    args = ["ask", "--index", str(built_index), "--embedder", "hash", "-k", "3", "--out", str(out_dir),
            "훈민정음은 언제 반포되었나"]

    t = FakeTransport([content])
    assert main(args, transport=t, now=lambda: FIXED_NOW) == 0
    md = out_dir / "answer-20261007T123456Z.md"
    js = out_dir / "answer-20261007T123456Z.json"
    assert md.is_file() and js.is_file()
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["question"] == "훈민정음은 언제 반포되었나"
    assert data["citations"] == [1]  # 4 is not among the 3 chunks
    assert any("4" in w for w in data["warnings"])
    assert data["chunks"][0]["source"] == "hunminjeongeum.md"
    assert data["model"] == "nvidia/test-model"
    text = md.read_text(encoding="utf-8")
    assert "훈민정음은 1446년에 반포되었다 [1]." in text
    assert "hunminjeongeum.md" in text
    assert "반포 연도" in text and "2019년 자료" in text
    assert "더 공식적인 출처 \\| 최신" in text  # table cell pipes are escaped
    printed = capsys.readouterr().out
    assert "훈민정음은 1446년에 반포되었다" in printed

    # same timestamp again: the first pair stays, a new pair is written next to it
    before_md, before_js = md.read_bytes(), js.read_bytes()
    t2 = FakeTransport([json.dumps({"answer": "두 번째", "citations": []}, ensure_ascii=False)])
    assert main(args, transport=t2, now=lambda: FIXED_NOW) == 0
    assert md.read_bytes() == before_md and js.read_bytes() == before_js
    md2 = out_dir / "answer-20261007T123456Z-1.md"
    js2 = out_dir / "answer-20261007T123456Z-1.json"
    assert md2.is_file() and js2.is_file()
    assert json.loads(js2.read_text(encoding="utf-8"))["answer"] == "두 번째"

    # a stray file with only the .json name also blocks that stem
    (out_dir / "answer-20261007T123456Z-2.json").write_text("keep", encoding="utf-8")
    t3 = FakeTransport([json.dumps({"answer": "세 번째", "citations": []}, ensure_ascii=False)])
    assert main(args, transport=t3, now=lambda: FIXED_NOW) == 0
    assert (out_dir / "answer-20261007T123456Z-2.json").read_text(encoding="utf-8") == "keep"
    assert not (out_dir / "answer-20261007T123456Z-2.md").exists()
    assert (out_dir / "answer-20261007T123456Z-3.md").is_file()


def test_parse_error_still_exit_0_and_saved(built_index, monkeypatch, tmp_path):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    out_dir = tmp_path / "o"
    t = FakeTransport(["JSON 아님", "여전히 JSON 아님"])
    code = main(["ask", "--index", str(built_index), "--embedder", "hash", "--out", str(out_dir), "경복궁 관람 시간"],
                transport=t, now=lambda: FIXED_NOW)
    assert code == 0
    data = json.loads((out_dir / "answer-20261007T123456Z.json").read_text(encoding="utf-8"))
    assert data["parse_error"] is True and data["answer"] == "여전히 JSON 아님"
    assert "JSON" in (out_dir / "answer-20261007T123456Z.md").read_text(encoding="utf-8")


def test_json_stdout_has_no_key(built_index, monkeypatch, capsys):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    t = FakeTransport([json.dumps(GOOD, ensure_ascii=False)])
    code = main(["ask", "--index", str(built_index), "--embedder", "hash", "--json", "경복궁 관람 시간"], transport=t)
    assert code == 0
    cap = capsys.readouterr()
    data = json.loads(cap.out)
    assert data["question"] == "경복궁 관람 시간"
    assert FAKE_KEY not in cap.out + cap.err
