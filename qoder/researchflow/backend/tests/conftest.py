"""Shared pytest fixtures.

Tests run against the **live** seekdb server and the **live** PowerContext server, but
under their own ``rft_`` prefix and their own project ids, so nothing belonging to another
competition entry or to the demo run is touched.

Embeddings default to the deterministic ``hashing`` provider here: it needs no model
download, so the suite is reproducible offline. The acceptance runner uses ``minilm``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("RF_SEEKDB_PREFIX", "rft_")
os.environ.setdefault("RF_EMBEDDING_PROVIDER", "hashing")
os.environ.setdefault("RF_POWERCONTEXT_URL", "http://127.0.0.1:17429")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
DEMO_DIR = PROJECT_ROOT / "demo"

from app.config import get_settings  # noqa: E402
from app.db.seekdb import SeekDBStore  # noqa: E402
from app.memory.client import PowerContextGateway  # noqa: E402
from app.retrieval.embeddings import build_embedding_backend  # noqa: E402

PDF_NAME = "seekdb_hybrid_retrieval_notes.pdf"
MD_NAME = "research_plan.md"
TXT_NAME = "experiment_log.txt"


def _service_available(url: str, path: str, timeout: float = 5.0) -> bool:
    import httpx

    try:
        response = httpx.get(url.rstrip("/") + path, timeout=timeout)
        return response.status_code < 500
    except Exception:
        return False


def seekdb_available() -> bool:
    settings = get_settings()
    import pymysql

    try:
        conn = pymysql.connect(
            host=settings.seekdb_host,
            port=settings.seekdb_port,
            user=f"{settings.seekdb_user}@{settings.seekdb_tenant}",
            password=settings.seekdb_password,
            database=settings.seekdb_database,
            charset="utf8mb4",
            connect_timeout=5,
        )
        conn.close()
        return True
    except Exception:
        return False


requires_seekdb = pytest.mark.skipif(not seekdb_available(), reason="seekdb server not reachable")
requires_powercontext = pytest.mark.skipif(
    not _service_available("http://127.0.0.1:17429", "/health/live"),
    reason="PowerContext server not reachable",
)


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def embeddings(settings):
    return build_embedding_backend(settings)


@pytest.fixture(scope="session")
def store(settings, embeddings):
    """A store whose schema is guaranteed to exist, so tests never depend on fixture order."""
    seekdb_store = SeekDBStore(settings)
    seekdb_store.ensure_schema(embedding_dimension=embeddings.dimension)
    return seekdb_store


@pytest.fixture(scope="session")
def gateway(settings):
    return PowerContextGateway(settings)


@pytest.fixture(scope="session")
def schema(store, embeddings):
    return store.ensure_schema(embedding_dimension=embeddings.dimension)


@pytest.fixture(scope="session")
def demo_files():
    return {name: (DEMO_DIR / name).read_bytes() for name in (PDF_NAME, MD_NAME, TXT_NAME)}


@pytest.fixture(scope="session")
def ingested(store, embeddings, settings, demo_files):
    """Ingest the demo corpus once for the whole session under the test-only prefix."""
    from app.ingestion import service as ingestion

    reset_test_store(store, settings)
    store.ensure_schema(embedding_dimension=embeddings.dimension)
    records = {
        name: ingestion.ingest_bytes(store, embeddings, data, name, settings=settings)
        for name, data in demo_files.items()
    }
    yield records
    reset_test_store(store, settings)
    store.close_thread_resources()


@pytest.fixture(scope="session")
def api_client(settings):
    """Real app through its real lifespan, so the startup path is tested too."""
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


def reset_test_store(store: SeekDBStore, settings) -> None:
    """Drop and recreate only the ``rft_``-prefixed objects."""
    client = store.pyseekdb_client()
    for name in (settings.chunks_collection,):
        if client.has_collection(name):
            client.delete_collection(name)
    for name in (
        settings.documents_table,
        settings.pages_table,
        settings.projects_table,
        settings.meta_table,
    ):
        store.execute(f"DROP TABLE IF EXISTS `{name}`")
    store._schema_ready = False
