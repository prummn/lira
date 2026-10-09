"""All API tests use isolated temporary databases and file stores."""

from __future__ import annotations
import os
import sys
from pathlib import Path
from collections.abc import Iterator
import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def isolate_model_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests never use keys or endpoints inherited from the developer's shell.
    for name in (
        "PAPER_READER_MODEL_BASE_URL", "PAPER_READER_MODEL_API_KEY",
        "PAPER_READER_MODEL_NAME", "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app(
        database_url=f"sqlite:///{(tmp_path / 'workspace.db').as_posix()}",
        storage_dir=tmp_path / "storage",
        model_config_path=tmp_path / "model.env",
        seed_demo=False,
    )
    with TestClient(app) as api:
        yield api
    for name in (
        "PAPER_READER_MODEL_BASE_URL", "PAPER_READER_MODEL_API_KEY",
        "PAPER_READER_MODEL_NAME", "PAPER_READER_MODEL_WIRE_API",
        "PAPER_READER_MODEL_REASONING_EFFORT", "PAPER_READER_MODEL_TIMEOUT",
    ):
        os.environ.pop(name, None)


@pytest.fixture
def demo_client(tmp_path: Path) -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app(
        database_url=f"sqlite:///{(tmp_path / 'demo.db').as_posix()}",
        storage_dir=tmp_path / "demo-pdfs",
        model_config_path=tmp_path / "model.env",
        seed_demo=True,
    )
    with TestClient(app) as api:
        yield api
