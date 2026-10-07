"""Index build and load (JSON index, format 3, spec 4.3).

Index folder layout:
- manifest.json    format version, creation time, embedder identity and dim, tokenizer setting, BM25 parameters,
                   chunker setting, input root name (basename only), source_fingerprint (see
                   retrieval.source_meta.source_fingerprint), doc/chunk counts, skipped files, and the piece lists
                   `chunk_files` and `vector_files` (always lists, read in order and concatenated on load)
- chunks.json      JSON array of chunk dicts, one chunk per line: base keys + source keys (+ operating keys)
                   + text + tokens (tokens are not re-analyzed on load; they never leave the Retriever)
- vectors.json     JSON array of vectors in chunk order, one vector per line, values rounded to 6 decimals,
                   rows L2-normalized before rounding
- chunks-0001.json, chunks-0002.json, ... / vectors-0001.json, ...
                   used instead of the single file when it would exceed MAX_FILE_BYTES (build_index
                   `max_file_bytes`); one item larger than the limit is a piece by itself
- theme_packs/     byte copies of the input root's `theme_packs/*.json` (not indexed; read by `theme_packs()`)
                   Each pack must be a JSON object or indexing fails (InputError); packs skipped for safety
                   (symlink, outside root, too large) are listed in `skipped`.

Rebuilding into a folder removes earlier outputs (pieces, format 2 files, theme_packs/*.json) only when the folder
already has a manifest.json that is a JSON object with `format_version`; otherwise nothing is deleted.

Format 2 indexes (chunks.jsonl + embeddings.npy) are rejected with a format version error.
The input root is only ever an argument, so a development folder and the final input folder are
indexed by the same code.
"""

from __future__ import annotations

import copy
import json
import os
import re
import stat
from datetime import datetime, timezone

import numpy as np

from retrieval.bm25 import DEFAULT_B, DEFAULT_EPSILON, DEFAULT_K1, BM25Index
from retrieval.chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP_CHARS, chunk_document
from retrieval.dense import dense_rank
from retrieval.embedder import Embedder
from retrieval.errors import (
    EmbedderMismatchError,
    IndexLocationError,
    InputError,
    RetrievalError,
    TokenizerMismatchError,
)
from retrieval.fusion import DEFAULT_RRF_K, rrf_fuse
from retrieval.loader import DEFAULT_MAX_BYTES, load_documents
from retrieval.source_meta import THEME_PACK_DIR, resolve_source_meta, source_fingerprint
from retrieval.tokenize import tokenize, tokenizer_config

FORMAT_VERSION = 3  # 2: BM25 tokens drop particles, endings, suffixes and copulas; 3: JSON files + source keys
MODES = ("hybrid", "bm25", "dense")
CHUNKS_STEM = "chunks"
VECTORS_STEM = "vectors"
MANIFEST_FILE = "manifest.json"
MAX_FILE_BYTES = 50 * 1024 * 1024  # 조정값: one index file larger than this is split into numbered pieces
VECTOR_DECIMALS = 6  # 조정값
# Earlier outputs removed before writing (format 3 pieces and the format 2 files); nothing else is touched.
_OLD_OUTPUT = re.compile(r"^(?:(?:chunks|vectors)(?:-\d{4,})?\.json|chunks\.jsonl|embeddings\.npy)$")


def _is_within(parent: str, child: str) -> bool:
    try:
        return os.path.commonpath([parent, child]) == parent
    except ValueError:
        return False


def build_index(
    input_root,
    index_dir,
    embedder: Embedder,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
    epsilon: float = DEFAULT_EPSILON,
    batch_size: int = 64,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_theme_pack_bytes: int = DEFAULT_MAX_BYTES,
) -> dict:
    input_root = os.fspath(input_root)
    index_dir = os.fspath(index_dir)
    if not os.path.isdir(input_root):
        raise InputError(f"입력 폴더가 없거나 폴더가 아닙니다: {input_root}")
    real_in = os.path.realpath(input_root)
    # realpath also resolves a not-yet-existing path through its existing ancestors.
    real_idx = os.path.realpath(os.path.abspath(index_dir))
    if _is_within(real_in, real_idx):
        raise IndexLocationError("인덱스 폴더는 입력 폴더 안에 둘 수 없습니다(입력 폴더 밖 경로를 지정하세요)")

    fingerprint = source_fingerprint(input_root)
    docs, skipped = load_documents(input_root)
    theme_packs = _collect_theme_packs(input_root, real_in, max_theme_pack_bytes, skipped)
    cleanup = _is_index_folder(index_dir)
    _check_theme_pack_target(index_dir, theme_packs, cleanup)
    records = []
    for d in docs:
        meta = d.meta or resolve_source_meta({}, {})
        for c in chunk_document(d, max_chars=max_chars, overlap_chars=overlap_chars):
            rec = c.to_dict()
            rec.update(copy.deepcopy(meta))
            rec["tokens"] = tokenize(c.text)
            records.append(rec)
    texts = [r["text"] for r in records]

    parts = [embedder.encode(texts[i:i + batch_size], kind="passage") for i in range(0, len(texts), batch_size)]
    if parts:
        emb = np.vstack(parts).astype(np.float32)
    else:
        emb = np.zeros((0, embedder.dim or 0), dtype=np.float32)
    dim = int(emb.shape[1]) if emb.shape[0] else embedder.dim

    os.makedirs(index_dir, exist_ok=True)
    if cleanup:
        _remove_old_outputs(index_dir)
    chunk_files = _write_pieces(index_dir, CHUNKS_STEM, records, max_file_bytes)
    vectors = [[round(float(x), VECTOR_DECIMALS) for x in row] for row in emb]
    vector_files = _write_pieces(index_dir, VECTORS_STEM, vectors, max_file_bytes)
    _write_theme_packs(index_dir, theme_packs)

    manifest = {
        "format_version": FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "embedder": {**embedder.identity(), "dim": dim},
        "tokenizer": tokenizer_config(),
        "bm25": {"k1": k1, "b": b, "epsilon": epsilon},
        "chunker": {"max_chars": max_chars, "overlap_chars": overlap_chars},
        "input_name": os.path.basename(os.path.normpath(real_in)),
        "source_fingerprint": fingerprint,
        "doc_count": len(docs),
        "chunk_count": len(records),
        "chunk_files": chunk_files,
        "vector_files": vector_files,
        "skipped": skipped,
    }
    with open(os.path.join(index_dir, MANIFEST_FILE), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return manifest


def _is_index_folder(index_dir: str) -> bool:
    """True only if the folder holds a manifest.json that is a JSON object with a `format_version` key."""
    try:
        with open(os.path.join(index_dir, MANIFEST_FILE), encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError, RecursionError):
        return False
    return isinstance(manifest, dict) and "format_version" in manifest


def _remove_old_outputs(index_dir: str) -> None:
    """Delete earlier index outputs (format 3 pieces, format 2 files, theme_packs/*.json) and nothing else."""
    for name in os.listdir(index_dir):
        path = os.path.join(index_dir, name)
        if _OLD_OUTPUT.match(name) and not os.path.isdir(path):
            os.unlink(path)
    tp = os.path.join(index_dir, THEME_PACK_DIR)
    if os.path.islink(tp):
        os.unlink(tp)  # never delete through a symlinked folder
    elif os.path.isdir(tp):
        for name in os.listdir(tp):
            path = os.path.join(tp, name)
            if name.endswith(".json") and not os.path.isdir(path):
                os.unlink(path)
        if not os.listdir(tp):
            os.rmdir(tp)


def _write_pieces(index_dir: str, stem: str, items: list, max_file_bytes: int) -> list[str]:
    """Write items as `[\n` + one JSON item per line joined by `,\n` + `\n]\n`; split by byte size.

    One file `<stem>.json` when it fits in max_file_bytes, else `<stem>-0001.json`, ... filled greedily in order
    (an item larger than the limit is a piece by itself). Returns the file names in order.
    """
    lines = [json.dumps(item, ensure_ascii=False) for item in items]
    sizes = [len(line.encode("utf-8")) for line in lines]
    pieces: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    for line, size in zip(lines, sizes):
        # bytes of the file holding current + line: "[\n" + items + ",\n" between + "\n]\n"
        grown = 5 + current_size + size + 2 * len(current)
        if current and grown > max_file_bytes:
            pieces.append(current)
            current, current_size = [], 0
        current.append(line)
        current_size += size
    if current or not pieces:
        pieces.append(current)
    if len(pieces) == 1:
        names = [f"{stem}.json"]
    else:
        names = [f"{stem}-{i:04d}.json" for i in range(1, len(pieces) + 1)]
    for name, piece in zip(names, pieces):
        body = "[\n" + ",\n".join(piece) + "\n]\n" if piece else "[]\n"
        with open(os.path.join(index_dir, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    return names


def _collect_theme_packs(
    input_root: str, real_in: str, max_bytes: int, skipped: list[dict]
) -> list[tuple[str, bytes]]:
    """(name, bytes) of `<input>/theme_packs/*.json`, checked before anything is written.

    Loader safety rules: symlinks, non-regular files, files whose real path is outside the input root and files
    over max_bytes are not copied and are recorded in `skipped` as "theme pack not copied: <reason>".
    A pack that is not a JSON object (broken JSON included) fails indexing with InputError naming the file.
    """
    src_dir = os.path.join(input_root, THEME_PACK_DIR)
    try:
        st = os.lstat(src_dir)
    except OSError:
        return []
    # A symlinked or outside theme_packs folder is already recorded by the loader walk.
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or not _is_within(real_in, os.path.realpath(src_dir)):
        return []
    try:
        names = sorted(os.listdir(src_dir))
    except OSError:
        return []
    packs = []
    for name in names:
        if not name.endswith(".json"):
            continue
        rel = f"{THEME_PACK_DIR}/{name}"
        full = os.path.join(src_dir, name)

        def not_copied(reason: str) -> None:
            skipped.append({"path": rel, "reason": f"theme pack not copied: {reason}"})

        try:
            fst = os.lstat(full)
        except PermissionError:
            not_copied("permission denied")
            continue
        except OSError:
            not_copied("unreadable")
            continue
        if stat.S_ISLNK(fst.st_mode):
            not_copied("symlink")
            continue
        if not stat.S_ISREG(fst.st_mode):
            not_copied("not a regular file")
            continue
        if not _is_within(real_in, os.path.realpath(full)):
            not_copied("outside root")
            continue
        if fst.st_size > max_bytes:
            not_copied("too large")
            continue
        try:
            fd = os.open(full, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as fh:
                data = fh.read(max_bytes + 1)
        except PermissionError:
            not_copied("permission denied")
            continue
        except OSError:
            not_copied("unreadable")
            continue
        if len(data) > max_bytes:
            not_copied("too large")
            continue
        try:
            obj = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            obj = None
        if not isinstance(obj, dict):
            raise InputError(f"테마 팩이 JSON 객체가 아닙니다(깨진 JSON 포함): {rel}")
        packs.append((name, data))
    return packs


def _check_theme_pack_target(index_dir: str, packs: list[tuple[str, bytes]], cleanup: bool) -> None:
    """Fail before anything is written if packs would go into a `theme_packs` that is not a plain folder.

    In a folder that will be cleaned (it has an index manifest) a symlinked `theme_packs` is removed by the
    cleanup, so only a non-folder file is an error there.
    """
    if not packs:
        return
    dst_dir = os.path.join(index_dir, THEME_PACK_DIR)
    if os.path.islink(dst_dir):
        if not cleanup:
            raise InputError(f"색인 폴더의 {THEME_PACK_DIR}가 심볼릭 링크입니다: {index_dir}")
    elif os.path.exists(dst_dir) and not os.path.isdir(dst_dir):
        raise InputError(f"색인 폴더의 {THEME_PACK_DIR}가 폴더가 아닙니다: {index_dir}")


def _write_theme_packs(index_dir: str, packs: list[tuple[str, bytes]]) -> None:
    """Byte copies into `<index>/theme_packs/`; a same-named file is overwritten."""
    if not packs:
        return
    dst_dir = os.path.join(index_dir, THEME_PACK_DIR)
    if os.path.islink(dst_dir) or (os.path.exists(dst_dir) and not os.path.isdir(dst_dir)):
        raise InputError(f"색인 폴더의 {THEME_PACK_DIR}가 일반 폴더가 아닙니다(심볼릭 링크 등): {index_dir}")
    os.makedirs(dst_dir, exist_ok=True)
    for name, data in packs:
        with open(os.path.join(dst_dir, name), "wb") as out:
            out.write(data)


def _piece_names(manifest: dict, key: str) -> list[str]:
    names = manifest.get(key)
    if not isinstance(names, list) or not names:
        raise InputError(f"manifest의 {key}가 없거나 목록이 아닙니다. 다시 색인하세요")
    for name in names:
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or "\\" in name
            or ".." in name
            or name in (".",)
            or "\0" in name
        ):
            raise InputError(f"manifest의 {key}에 쓸 수 없는 파일 이름이 있습니다: {name!r}")
    return names


def _read_pieces(index_dir: str, names: list[str]) -> list:
    items: list = []
    for name in names:
        path = os.path.join(index_dir, name)
        if not os.path.isfile(path):
            raise InputError(f"인덱스가 불완전합니다({name} 없음): {index_dir}")
        try:
            with open(path, encoding="utf-8") as fh:
                part = json.load(fh)
        except ValueError:
            raise RetrievalError(f"인덱스가 손상되었습니다({name}를 읽지 못함): {index_dir}") from None
        if not isinstance(part, list):
            raise RetrievalError(f"인덱스가 손상되었습니다({name}가 배열이 아님): {index_dir}")
        items.extend(part)
    return items


def _public(chunk: dict) -> dict:
    """Deep copy of a chunk without the internal BM25 tokens."""
    return copy.deepcopy({key: v for key, v in chunk.items() if key != "tokens"})


def _check_tokenizer(saved: dict | None) -> None:
    current = tokenizer_config()
    saved = saved or {}
    diffs = [
        f"{key}: 인덱스 {saved.get(key)!r}, 현재 {current[key]!r}"
        for key in current
        if saved.get(key) != current[key]
    ]
    if diffs:
        raise TokenizerMismatchError(
            "인덱스의 토크나이저 설정이 현재 코드와 다릅니다. 다시 색인하세요 (" + "; ".join(diffs) + ")"
        )


def _bm25_params(saved: dict | None) -> dict:
    saved = saved or {}
    out = {}
    for key in ("k1", "b"):
        v = saved.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise InputError(f"manifest의 BM25 매개변수 {key}가 없거나 숫자가 아닙니다. 다시 색인하세요")
        out[key] = float(v)
    eps = saved.get("epsilon", DEFAULT_EPSILON)
    out["epsilon"] = float(eps) if isinstance(eps, (int, float)) and not isinstance(eps, bool) else DEFAULT_EPSILON
    return out


def _check_embedder(saved: dict | None, embedder: Embedder) -> None:
    saved = saved or {}
    want = embedder.identity()
    if saved.get("type") != want["type"] or saved.get("model") != want["model"]:
        raise EmbedderMismatchError(
            f"임베더가 인덱스와 다릅니다: 인덱스 {saved.get('type')}:{saved.get('model')}, "
            f"지정 {want['type']}:{want['model']}"
        )
    if embedder.dim is not None and saved.get("dim") is not None and embedder.dim != saved["dim"]:
        raise EmbedderMismatchError(f"임베더 차원이 인덱스와 다릅니다: 인덱스 {saved['dim']}, 지정 {embedder.dim}")


class Retriever:
    def __init__(
        self,
        manifest: dict,
        chunks: list[dict],
        embeddings: np.ndarray,
        embedder: Embedder,
        index_dir: str | os.PathLike | None = None,
    ):
        self.manifest = manifest
        self.chunks = chunks
        self.embeddings = embeddings
        self.embedder = embedder
        self.index_dir = os.fspath(index_dir) if index_dir is not None else None
        self.bm25 = BM25Index([c.get("tokens", []) for c in chunks], **_bm25_params(manifest.get("bm25")))
        self._by_id = {}
        for i, c in enumerate(chunks):
            self._by_id.setdefault(c.get("chunk_id"), i)

    @classmethod
    def load(cls, index_dir, embedder: Embedder) -> "Retriever":
        index_dir = os.fspath(index_dir)
        mpath = os.path.join(index_dir, MANIFEST_FILE)
        if not os.path.isfile(mpath):
            raise InputError(f"인덱스가 없습니다(manifest.json 없음): {index_dir}")
        try:
            with open(mpath, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except ValueError:
            raise InputError(f"manifest.json을 읽지 못했습니다: {index_dir}") from None
        if manifest.get("format_version") != FORMAT_VERSION:
            raise InputError(
                f"인덱스 형식 버전이 다릅니다: {manifest.get('format_version')} (지원: {FORMAT_VERSION}). 다시 색인하세요"
            )
        _check_tokenizer(manifest.get("tokenizer"))
        _bm25_params(manifest.get("bm25"))
        _check_embedder(manifest.get("embedder"), embedder)

        chunk_names = _piece_names(manifest, "chunk_files")
        vector_names = _piece_names(manifest, "vector_files")
        chunks = _read_pieces(index_dir, chunk_names)
        if not all(isinstance(c, dict) for c in chunks):
            raise RetrievalError(f"인덱스가 손상되었습니다(청크가 객체가 아님): {index_dir}")
        rows = _read_pieces(index_dir, vector_names)
        if len(rows) != len(chunks) or len(chunks) != manifest.get("chunk_count"):
            raise RetrievalError(
                f"인덱스가 손상되었습니다: manifest 청크 {manifest.get('chunk_count')}개, "
                f"실제 청크 {len(chunks)}개, 벡터 {len(rows)}개"
            )
        saved_dim = (manifest.get("embedder") or {}).get("dim")
        if rows:
            dims = {len(r) if isinstance(r, list) else -1 for r in rows}
            if len(dims) != 1 or -1 in dims or (isinstance(saved_dim, int) and dims != {saved_dim}):
                raise RetrievalError(
                    f"인덱스가 손상되었습니다: 벡터 차원이 행마다 다르거나 manifest 차원({saved_dim})과 다릅니다"
                )
            try:
                emb = np.asarray(rows, dtype=np.float32)
            except (TypeError, ValueError):
                raise RetrievalError(f"인덱스가 손상되었습니다(벡터 값이 숫자가 아님): {index_dir}") from None
        else:
            emb = np.zeros((0, saved_dim if isinstance(saved_dim, int) else 0), dtype=np.float32)
        return cls(manifest, chunks, emb, embedder, index_dir=index_dir)

    def get_chunk(self, chunk_id: str) -> dict | None:
        """Copy of the chunk with this ID (no tokens), or None."""
        i = self._by_id.get(chunk_id)
        return _public(self.chunks[i]) if i is not None else None

    def chunks_where(self, kind: str, place_id: str) -> list[dict]:
        """Copies of every chunk of this kind whose place_ids holds place_id, in index order (no tokens)."""
        return [
            _public(c)
            for c in self.chunks
            if c.get("kind") == kind and isinstance(c.get("place_ids"), list) and place_id in c["place_ids"]
        ]

    def theme_packs(self) -> list[dict]:
        """Theme pack dicts from the index folder's theme_packs/*.json, by file name; [] without the folder.

        A file that is not valid JSON or not an object raises RetrievalError (a broken pack is not hidden).
        """
        if self.index_dir is None:
            return []
        tp = os.path.join(self.index_dir, THEME_PACK_DIR)
        if not os.path.isdir(tp):
            return []
        packs = []
        for name in sorted(os.listdir(tp)):
            path = os.path.join(tp, name)
            if not name.endswith(".json") or not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    obj = json.load(fh)
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise RetrievalError(f"테마 팩을 읽지 못했습니다: {THEME_PACK_DIR}/{name}") from None
            if not isinstance(obj, dict):
                raise RetrievalError(f"테마 팩이 JSON 객체가 아닙니다: {THEME_PACK_DIR}/{name}")
            packs.append(obj)
        return packs

    def query(self, q: str, k: int = 5, mode: str = "hybrid", candidates: int | None = None) -> list[dict]:
        """Top-k chunks: text, metadata, "score" (RRF), "rank" (1-based), per-method rank and score."""
        if mode not in MODES:
            raise InputError(f"검색 방식은 {'|'.join(MODES)} 중 하나여야 합니다: {mode!r}")
        if not q or not q.strip():
            raise InputError("질문이 비어 있습니다")
        if k <= 0:
            raise InputError("k는 1 이상이어야 합니다")
        if not self.chunks:
            return []
        depth = candidates or max(50, k * 10)

        rankings: dict[str, list[int]] = {}
        bm25_score: dict[int, float] = {}
        dense_score: dict[int, float] = {}
        if mode in ("hybrid", "bm25"):
            hits = self.bm25.rank(tokenize(q), top_k=depth)
            rankings["bm25"] = [i for i, _ in hits]
            bm25_score = dict(hits)
        if mode in ("hybrid", "dense"):
            qv = self.embedder.encode([q], kind="query")[0]
            saved_dim = self.embeddings.shape[1]
            if qv.shape[0] != saved_dim:
                raise EmbedderMismatchError(f"질문 벡터 차원({qv.shape[0]})이 인덱스 차원({saved_dim})과 다릅니다")
            hits = dense_rank(self.embeddings, qv, top_k=depth)
            rankings["dense"] = [i for i, _ in hits]
            dense_score = dict(hits)

        out = []
        for rank, f in enumerate(rrf_fuse(rankings, k=DEFAULT_RRF_K)[:k], start=1):
            hit = _public(self.chunks[f["idx"]])
            hit.update(
                score=f["rrf"],
                rank=rank,
                bm25_rank=f["bm25_rank"],
                dense_rank=f["dense_rank"],
                bm25_score=bm25_score.get(f["idx"]),
                dense_score=dense_score.get(f["idx"]),
            )
            out.append(hit)
        return out
