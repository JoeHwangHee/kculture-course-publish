import io
import json
import os
import urllib.error

import numpy as np
import pytest

from retrieval import embedder as emb_mod
from retrieval.embedder import HashEmbedder, LocalEmbedder, NimEmbedder, make_embedder
from retrieval.errors import InputError, RetrievalError

FAKE_KEY = "test-placeholder"


def test_hash_embedder_shape_norm_determinism():
    e = HashEmbedder(dim=64)
    v = e.encode(["경복궁 관람 시간", "훈민정음 반포"], kind="passage")
    assert v.shape == (2, 64)
    assert v.dtype == np.float32
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)
    v2 = HashEmbedder(dim=64).encode(["경복궁 관람 시간", "훈민정음 반포"], kind="query")
    assert np.array_equal(v, v2)


def test_hash_embedder_similarity_is_meaningful():
    e = HashEmbedder()
    q, a, b = e.encode(["경복궁 관람 시간", "경복궁 관람 시간 안내", "주간 회의록 프린터"], kind="passage")
    assert float(q @ a) > float(q @ b)


def test_hash_embedder_empty_text_is_zero_vector():
    v = HashEmbedder(dim=16).encode([""], kind="query")
    assert v.shape == (1, 16)
    assert not np.isnan(v).any()


def test_encode_rejects_bad_kind():
    with pytest.raises(ValueError):
        HashEmbedder().encode(["x"], kind="document")


def test_make_embedder_specs(monkeypatch, tmp_path):
    assert isinstance(make_embedder("hash"), HashEmbedder)

    monkeypatch.delenv("NIM_BASE_URL", raising=False)
    n = make_embedder("nim:org/model-x:v2")
    assert isinstance(n, NimEmbedder)
    assert n.model == "org/model-x:v2"  # split only on first colon
    assert n.base_url == "https://integrate.api.nvidia.com/v1"

    monkeypatch.setenv("NIM_BASE_URL", "http://localhost:8000/v1/")
    assert make_embedder("nim:m").base_url == "http://localhost:8000/v1"

    model_dir = tmp_path / "bge-m3"
    model_dir.mkdir()
    loc = make_embedder(f"local:{model_dir}")
    assert isinstance(loc, LocalEmbedder)
    assert loc.identity() == {"type": "local", "model": "bge-m3"}

    for bad in ["", "nim:", "local:", "bogus", "hash:abc"]:
        with pytest.raises(InputError):
            make_embedder(bad)


def test_local_embedder_requires_existing_folder(tmp_path):
    with pytest.raises(InputError):
        LocalEmbedder("BAAI/bge-m3")  # hub id, not a local folder
    with pytest.raises(InputError):
        LocalEmbedder(str(tmp_path / "missing"))


@pytest.mark.skipif(not os.environ.get("RETRIEVAL_MODEL_PATH"), reason="RETRIEVAL_MODEL_PATH not set")
def test_local_embedder_integration():
    e = LocalEmbedder(os.environ["RETRIEVAL_MODEL_PATH"])
    v = e.encode(["훈민정음은 1446년에 반포되었다.", "회사 회의록"], kind="passage")
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"
    assert v.dtype == np.float32 and v.shape[0] == 2
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-4)
    q = e.encode(["훈민정음 반포 연도"], kind="query")[0]
    assert float(v[0] @ q) > float(v[1] @ q)


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_nim_request_format(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        body = json.loads(req.data.decode("utf-8"))
        # return out of order to check index sorting
        data = [
            {"index": i, "embedding": [float(i + 1), 0.0, 0.0]} for i in range(len(body["input"]))
        ][::-1]
        return _FakeResp(json.dumps({"data": data}).encode("utf-8"))

    monkeypatch.setattr(emb_mod.urllib.request, "urlopen", fake_urlopen)
    e = NimEmbedder("https://example.invalid/v1", "some/embed-model")
    v = e.encode(["가", "나"], kind="query")

    req = captured["req"]
    assert req.get_method() == "POST"
    assert req.full_url == "https://example.invalid/v1/embeddings"
    body = json.loads(req.data.decode("utf-8"))
    assert body == {
        "input": ["가", "나"],
        "model": "some/embed-model",
        "input_type": "query",
        "encoding_format": "float",
    }
    assert req.get_header("Content-type") == "application/json"
    # auth header must not be forwarded on redirects
    assert req.unredirected_hdrs.get("Authorization") == f"Bearer {FAKE_KEY}"
    assert "Authorization" not in req.headers
    assert captured["timeout"] and captured["timeout"] > 0

    assert v.dtype == np.float32 and v.shape == (2, 3)
    assert np.allclose(v[:, 0], 1.0)
    assert e.dim == 3

    e.encode(["다"], kind="passage")
    assert json.loads(captured["req"].data.decode("utf-8"))["input_type"] == "passage"


def test_nim_missing_key_errors_without_network(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    def boom(*a, **k):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(emb_mod.urllib.request, "urlopen", boom)
    with pytest.raises(RetrievalError) as ei:
        NimEmbedder("https://example.invalid/v1", "m").encode(["x"], kind="query")
    assert "NVIDIA_API_KEY" in str(ei.value)


def test_nim_http_error_does_not_leak_key(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_KEY)

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, io.BytesIO(f"bad key {FAKE_KEY}".encode())
        )

    monkeypatch.setattr(emb_mod.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RetrievalError) as ei:
        NimEmbedder("https://example.invalid/v1", "m").encode(["x"], kind="query")
    assert "401" in str(ei.value)
    assert FAKE_KEY not in str(ei.value)
    assert FAKE_KEY not in repr(ei.value)


def test_nim_requires_model_and_http_url():
    with pytest.raises(InputError):
        NimEmbedder("https://example.invalid/v1", "")
    with pytest.raises(InputError):
        NimEmbedder("file:///etc", "m")
