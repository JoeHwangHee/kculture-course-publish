"""Shared pytest fixtures for every package's tests (`<package>/tests/`), run from `app/`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent
# Retrieval-layer test corpus (loader/index/CLI tests).
FIXTURE_INPUT = APP_DIR / "retrieval" / "tests" / "fixtures" / "input"
# Spec 4.7-format fake input (fictional theme pack + sources) shared by the tools/loop/retrieval tracks.
COMMON_FIXTURES = APP_DIR / "common" / "fixtures"


@pytest.fixture(scope="session")
def app_dir() -> Path:
    return APP_DIR


@pytest.fixture(scope="session")
def fixture_input() -> Path:
    return FIXTURE_INPUT


@pytest.fixture(scope="session")
def common_fixtures() -> Path:
    return COMMON_FIXTURES


@pytest.fixture(scope="session")
def built_index(tmp_path_factory) -> Path:
    from retrieval.embedder import HashEmbedder
    from retrieval.index import build_index

    index_dir = tmp_path_factory.mktemp("index")
    build_index(FIXTURE_INPUT, index_dir, HashEmbedder())
    return index_dir


def run_cli(args: list[str], cwd: Path = APP_DIR, env_extra: dict | None = None):
    """Run `python -m retrieval ...` in a child process (also checks hashing is stable across processes)."""
    import subprocess

    env = dict(os.environ)
    env.pop("NVIDIA_API_KEY", None)
    env["HF_HUB_OFFLINE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "retrieval", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


@pytest.fixture(autouse=True)
def _no_model_endpoint_env(monkeypatch):
    """Tests never inherit a demo shell's model endpoint settings (NIM_API_KEY_ENV etc.)."""
    for name in ("NIM_API_KEY_ENV", "NIM_BASE_URL", "NIM_MODEL"):
        monkeypatch.delenv(name, raising=False)
