"""Embedders. Interface: encode(texts, kind="query"|"passage") -> float32 array, rows L2-normalized.

- HashEmbedder: deterministic character n-gram hashing, no dependencies (tests, offline smoke runs).
- LocalEmbedder: sentence-transformers model loaded from a local folder only (no downloads at runtime).
- NimEmbedder: OpenAI-compatible POST {base_url}/embeddings via urllib. The API key is read from an
  environment variable and only ever placed in the Authorization header (never logged or echoed).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

from retrieval.errors import InputError, RetrievalError

KINDS = ("query", "passage")
DEFAULT_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")


def l2_normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    if m.ndim == 1:
        m = m[None, :]
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class Embedder:
    type_name = "base"

    @property
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    def dim(self) -> int | None:
        """Vector size if known without a model call (None until first encode for remote models)."""
        raise NotImplementedError

    def identity(self) -> dict:
        return {"type": self.type_name, "model": self.model_name}

    def encode(self, texts: list[str], kind: str) -> np.ndarray:
        raise NotImplementedError


# ---------------------------------------------------------------- hash


class HashEmbedder(Embedder):
    """Signed feature hashing of character 2/3-grams and whitespace words, using blake2b (stable across processes)."""

    type_name = "hash"
    MODEL = "hash-char-ngram-v1"

    def __init__(self, dim: int = 256):
        if dim <= 0:
            raise InputError("hash 임베더 차원은 양수여야 합니다")
        self._dim = int(dim)

    @property
    def model_name(self) -> str:
        return self.MODEL

    @property
    def dim(self) -> int:
        return self._dim

    def _features(self, text: str) -> list[str]:
        t = re.sub(r"\s+", " ", text.lower()).strip()
        feats = [f"w:{w}" for w in t.split(" ") if w]
        compact = t.replace(" ", "")
        for n in (2, 3):
            feats.extend(f"c{n}:{compact[i:i + n]}" for i in range(len(compact) - n + 1))
        if not feats and compact:
            feats.append(f"c1:{compact}")
        return feats

    def encode(self, texts: list[str], kind: str) -> np.ndarray:
        _check_kind(kind)
        out = np.zeros((len(texts), self._dim), dtype=np.float32)
        for r, text in enumerate(texts):
            for f in self._features(text):
                h = hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest()
                v = int.from_bytes(h, "little")
                out[r, v % self._dim] += 1.0 if (v >> 63) & 1 else -1.0
        return l2_normalize(out)


# ---------------------------------------------------------------- local sentence-transformers


def _pick_device() -> str:
    forced = os.environ.get("RETRIEVAL_DEVICE")
    if forced:
        return forced
    try:
        import torch
    except ImportError:  # pragma: no cover - torch comes with sentence-transformers
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


class LocalEmbedder(Embedder):
    """sentence-transformers model from a local folder. Device: env RETRIEVAL_DEVICE, else cuda -> mps -> cpu."""

    type_name = "local"

    def __init__(self, model_path: str, batch_size: int = 16):
        if not model_path or not os.path.isdir(model_path):
            raise InputError(f"로컬 임베딩 모델 폴더가 없습니다(허브 ID가 아니라 내려받은 폴더 경로가 필요합니다): {model_path}")
        self.model_path = model_path
        self.batch_size = batch_size
        self._model = None
        self._dim: int | None = None

    @property
    def model_name(self) -> str:
        return os.path.basename(os.path.normpath(self.model_path))

    @property
    def dim(self) -> int | None:
        if self._dim is None and self._model is not None:
            self._dim = self._model_dim(self._model)
        return self._dim

    @staticmethod
    def _model_dim(model) -> int:
        getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        return int(getter())

    def _load(self):
        if self._model is None:
            # Block any hub download before the libraries are imported.
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise RetrievalError(
                    "sentence-transformers가 설치되어 있지 않습니다: `uv sync --extra local-embed`"
                ) from e
            device = _pick_device()
            self._model = SentenceTransformer(self.model_path, device=device, local_files_only=True)
            self._dim = self._model_dim(self._model)
        return self._model

    def encode(self, texts: list[str], kind: str) -> np.ndarray:
        _check_kind(kind)
        model = self._load()
        if not texts:
            return np.zeros((0, self.dim or 0), dtype=np.float32)
        vecs = model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return l2_normalize(vecs)


# ---------------------------------------------------------------- NIM (OpenAI-compatible)


class NimEmbedder(Embedder):
    type_name = "nim"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str = "NVIDIA_API_KEY",
        batch_size: int = 32,
        timeout: float = 60.0,
    ):
        if not model or not model.strip():
            raise InputError("NIM 임베딩 모델 ID가 필요합니다(nim:<모델ID>)")
        base_url = (base_url or "").rstrip("/")
        scheme = urllib.parse.urlparse(base_url).scheme
        if scheme not in ("http", "https"):
            raise InputError(f"NIM base_url은 http(s)여야 합니다: {base_url!r}")
        self.base_url = base_url
        self.model = model.strip()
        self.api_key_env = api_key_env
        self.batch_size = batch_size
        self.timeout = timeout
        self._dim: int | None = None

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def dim(self) -> int | None:
        return self._dim

    def _request(self, batch: list[str], kind: str) -> list[list[float]]:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RetrievalError(f"환경변수 {self.api_key_env}가 비어 있습니다")
        body = json.dumps(
            {"input": batch, "model": self.model, "input_type": kind, "encoding_format": "float"},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        # Not forwarded if the server redirects elsewhere.
        req.add_unredirected_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Response body is deliberately not included (could echo request headers).
            raise RetrievalError(f"NIM 임베딩 요청 실패: HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise RetrievalError(f"NIM 임베딩 서버에 연결하지 못했습니다: {type(e.reason).__name__}") from None
        except (ValueError, UnicodeDecodeError):
            raise RetrievalError("NIM 임베딩 응답을 JSON으로 읽지 못했습니다") from None
        try:
            data = sorted(payload["data"], key=lambda d: d.get("index", 0))
            vecs = [d["embedding"] for d in data]
        except (KeyError, TypeError):
            raise RetrievalError("NIM 임베딩 응답 형식이 예상과 다릅니다(data[].embedding 없음)") from None
        if len(vecs) != len(batch):
            raise RetrievalError(f"NIM 임베딩 응답 개수가 다릅니다: 요청 {len(batch)}, 응답 {len(vecs)}")
        return vecs

    def encode(self, texts: list[str], kind: str) -> np.ndarray:
        _check_kind(kind)
        rows: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            rows.extend(self._request(list(texts[i:i + self.batch_size]), kind))
        if not rows:
            return np.zeros((0, self._dim or 0), dtype=np.float32)
        m = l2_normalize(np.asarray(rows, dtype=np.float32))
        self._dim = int(m.shape[1])
        return m


# ---------------------------------------------------------------- factory


def make_embedder(spec: str) -> Embedder:
    """Spec: "hash" | "local:<folder>" | "nim:<model id>" (base URL from env NIM_BASE_URL)."""
    spec = (spec or "").strip()
    if spec == "hash":
        return HashEmbedder()
    kind, sep, rest = spec.partition(":")
    if sep and kind == "local" and rest:
        return LocalEmbedder(rest)
    if sep and kind == "nim" and rest:
        base = os.environ.get("NIM_BASE_URL") or DEFAULT_NIM_BASE_URL
        return NimEmbedder(base, rest)
    raise InputError(f"알 수 없는 임베더 지정입니다: {spec!r} (hash | local:<폴더> | nim:<모델ID>)")
