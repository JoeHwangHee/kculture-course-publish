import json
import shutil

import pytest

from conftest import FIXTURE_INPUT, run_cli


@pytest.fixture(scope="module")
def cli_index(tmp_path_factory):
    idx = tmp_path_factory.mktemp("cli_index")
    res = run_cli(["index", "--input", str(FIXTURE_INPUT), "--index", str(idx), "--embedder", "hash"])
    assert res.returncode == 0, res.stderr
    assert "misc/brochure.pdf" in res.stdout
    return idx


def test_index_exit_0(cli_index):
    assert (cli_index / "manifest.json").is_file()
    assert (cli_index / "chunks.json").is_file()
    assert (cli_index / "vectors.json").is_file()


def test_query_json_exit_0_in_separate_process(cli_index):
    # index and query run in different processes: hash embedder must be stable across processes
    res = run_cli(["query", "--index", str(cli_index), "--embedder", "hash", "--json", "훈민정음은 언제 반포되었나"])
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["query"] == "훈민정음은 언제 반포되었나"
    assert out["mode"] == "hybrid" and out["k"] == 5
    top = out["hits"][0]
    assert top["source"] == "hunminjeongeum.md"
    assert top["rank"] == 1 and top["dense_rank"] is not None
    assert "tokens" not in top


def test_dense_mode_stable_across_processes(cli_index):
    res = run_cli(["query", "--index", str(cli_index), "--embedder", "hash", "--mode", "dense", "--json", "-k", "1",
                   "훈민정음 창제와 반포 세종 1443년"])
    assert res.returncode == 0, res.stderr
    hits = json.loads(res.stdout)["hits"]
    assert len(hits) == 1 and hits[0]["source"] == "hunminjeongeum.md"


def test_query_text_output(cli_index):
    res = run_cli(["query", "--index", str(cli_index), "--embedder", "hash", "경회루"])
    assert res.returncode == 0, res.stderr
    assert "palace/gyeongbokgung.md" in res.stdout
    assert "출처: - | 종류: other | 출처 종류: informal" in res.stdout


def test_no_results_exit_1(cli_index):
    res = run_cli(["query", "--index", str(cli_index), "--embedder", "hash", "--mode", "bm25", "zzzqqqxyz"])
    assert res.returncode == 1
    assert "결과" in res.stderr


def test_usage_and_input_errors_exit_2(cli_index, tmp_path):
    res = run_cli(["index", "--input", str(tmp_path / "missing"), "--index", str(tmp_path / "i"), "--embedder", "hash"])
    assert res.returncode == 2
    assert res.stderr.strip()

    res = run_cli(["query", "--index", str(tmp_path / "missing"), "--embedder", "hash", "q"])
    assert res.returncode == 2

    # embedder mismatch is detected before any network call
    res = run_cli(["query", "--index", str(cli_index), "--embedder", "nim:some/model", "q"])
    assert res.returncode == 2
    assert "임베더" in res.stderr

    res = run_cli(["query", "--index", str(cli_index), "--embedder", "bogus", "q"])
    assert res.returncode == 2

    res = run_cli(["query", "--index", str(cli_index), "--embedder", "hash", "--mode", "nope", "q"])
    assert res.returncode == 2

    res = run_cli(["query", "--index", str(cli_index), "--embedder", "hash", "   "])
    assert res.returncode == 2

    res = run_cli(["query"])
    assert res.returncode == 2

    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "a.md").write_text("# 제목\n\n본문", encoding="utf-8")
    res = run_cli(["index", "--input", str(inp), "--index", str(inp / "idx"), "--embedder", "hash"])
    assert res.returncode == 2


def test_tokenizer_mismatch_exit_2(cli_index, tmp_path):
    idx = tmp_path / "idx"
    shutil.copytree(cli_index, idx)
    m = json.loads((idx / "manifest.json").read_text(encoding="utf-8"))
    m["tokenizer"]["kiwipiepy"] = "0.0.1"
    (idx / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    res = run_cli(["query", "--index", str(idx), "--embedder", "hash", "세종"])
    assert res.returncode == 2
    assert "토크나이저" in res.stderr
