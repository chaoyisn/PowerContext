"""C2 held-out acceptance tests.

The corpus and queries here were authored AFTER the implementation was frozen and are used
only by this file: a seven-page PDF with two blank pages and an appendix, a second document
for cross-source localisation, concurrency, reconnect-after-outage and LLM retry behaviour.
Nothing in this file tuned any threshold or gate parameter.
"""

from __future__ import annotations

import io
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from openai import APIConnectionError

from app.agent import service as agent
from app.agent.llm import LLMGateway
from app.errors import LLMUnavailableError, NotFoundError, SeekDBUnavailableError
from app.ingestion import service as ingestion
from app.retrieval import service as retrieval

from .conftest import requires_seekdb

pytestmark = requires_seekdb

DOC_A_FACTS = {
    1: "The held-out corpus begins on page one with the identifier ALPHA-771.",
    2: "Page two records that the cooling loop pressure was 3.7 bar during run H-12.",
    4: "Page four states the sampler kept 4096 candidates per epoch.",
    5: "Page five tabulates latency: p50 12ms, p99 87ms for the hybrid path.",
    7: "Page seven concludes that the appendix reproduces the ALPHA-771 identifier.",
}
DOC_B_FACTS = {
    1: "备忘录 BETA-204 指出组会时间改为每周四下午三点。",
}


def _build_pdf() -> bytes:
    import fitz

    document = fitz.open()
    for page_no in range(1, 8):
        page = document.new_page(width=595, height=842)
        text = DOC_A_FACTS.get(page_no)
        if text:
            page.insert_textbox(fitz.Rect(56, 56, 539, 786), text, fontname="helv", fontsize=11)
        # pages 3 and 6 stay blank on purpose; page 5 also carries a long unbroken line
        if page_no == 5:
            page.insert_textbox(
                fitz.Rect(56, 400, 539, 780),
                "unbroken-" + "x" * 900,
                fontname="helv",
                fontsize=8,
            )
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _cleanup_heldout(store, settings) -> None:
    rows = store.query(
        f"SELECT doc_id FROM `{settings.documents_table}` WHERE filename LIKE %s", ("heldout%",)
    )
    for row in rows:
        ingestion.delete_document(store, row["doc_id"], settings)


@pytest.fixture(scope="module")
def heldout(store, settings, embeddings, ingested):
    """Held-out documents on top of the shared three-document session corpus."""
    _cleanup_heldout(store, settings)
    pdf_bytes = _build_pdf()
    pdf = ingestion.ingest_bytes(store, embeddings, pdf_bytes, "heldout_alpha.pdf", settings=settings)
    memo = ingestion.ingest_bytes(
        store, embeddings, DOC_B_FACTS[1].encode("utf-8"), "heldout_beta.txt", settings=settings
    )
    yield {"pdf": pdf, "memo": memo, "pdf_bytes": pdf_bytes}
    _cleanup_heldout(store, settings)


def _key_for(filename: str) -> str:
    return "memo" if filename.endswith(".txt") else "pdf"


# --------------------------------------------------------------------- physical pages


def test_every_physical_page_including_both_blanks_has_a_record(store, settings, heldout):
    detail = ingestion.get_document(store, heldout["pdf"].doc_id, settings)
    assert detail.page_count == 7
    pages = ingestion.list_pages(store, heldout["pdf"].doc_id, settings)
    assert [p["page_no"] for p in pages] == [1, 2, 3, 4, 5, 6, 7]
    blanks = [p["page_no"] for p in pages if p["is_empty"]]
    assert blanks == [3, 6], f"expected blank pages 3 and 6, got {blanks}"
    for page_no in blanks:
        page = ingestion.get_page(store, heldout["pdf"].doc_id, page_no, settings)
        assert page.content.strip() == ""
        assert page.page_id.endswith(f":p{page_no:04d}")
    # the long unbroken line on page 5 must not break chunking or offsets
    page5 = ingestion.get_page(store, heldout["pdf"].doc_id, 5, settings)
    assert "unbroken-" in page5.content


def test_chunks_never_reference_a_blank_page(store, embeddings, settings, heldout):
    doc_id = heldout["pdf"].doc_id
    for mode in ("vector", "fulltext", "hybrid"):
        result = retrieval.search(
            store, embeddings, "pressure cooling loop bar", mode=mode, top_k=10, settings=settings
        )
        own = [hit for hit in result.hits if hit.doc_id == doc_id]
        assert own, f"{mode} returned no hit from the held-out document"
        assert all(hit.page_no not in (3, 6) for hit in own), (
            f"{mode} surfaced a blank page: {[(h.page_no, h.chunk_id) for h in own]}"
        )


# --------------------------------------------------------------------- cross-source localisation


@pytest.mark.parametrize(
    ("query", "filename", "page_no"),
    [
        ("what was the cooling loop pressure during run H-12", "heldout_alpha.pdf", 2),
        ("ALPHA-771 identifier appears on which pages", "heldout_alpha.pdf", 1),
        ("p99 latency of the hybrid path", "heldout_alpha.pdf", 5),
        ("组会时间改到什么时候", "heldout_beta.txt", 1),
    ],
)
def test_cross_document_source_localisation(store, embeddings, settings, heldout, query, filename, page_no):
    result = retrieval.search(
        store, embeddings, query, mode="hybrid", top_k=5, apply_gate=True, settings=settings
    )
    assert result.citations, f"no gated evidence for {query!r}"
    located = [h for h in result.hits if h.filename == filename and h.page_no == page_no]
    assert located, f"{query!r} -> {[(h.filename, h.page_no) for h in result.hits]}"
    assert located[0].chunk_id.startswith(heldout[_key_for(filename)].doc_id[:16])


def test_unanswerable_heldout_question_is_refused(store, embeddings, settings, heldout):
    result = retrieval.search(
        store, embeddings, "ALPHA-771 的固件版本号是多少", mode="hybrid", top_k=5,
        apply_gate=True, settings=settings,
    )
    assert result.citations == []


# --------------------------------------------------------------------- duplicates & concurrency


def test_concurrent_uploads_of_the_same_file_stay_deduplicated(store, embeddings, settings, heldout):
    # Reuse the fixture bytes: fitz stamps a fresh /ID and creation date on every build, so
    # rebuilding here would upload a genuinely different document.
    data = heldout["pdf_bytes"]
    errors = []

    def worker(_) -> None:
        try:
            ingestion.ingest_bytes(store, embeddings, data, "heldout_alpha.pdf", settings=settings)
        except Exception as exc:  # noqa: BLE001 - any failure here is a concurrency bug
            errors.append(f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(worker, range(6)))
    assert errors == [], errors

    counts = store.health()["counts"]
    # three session documents plus the two held-out ones; six concurrent identical uploads
    # must not add anything.
    assert counts["documents"] == 5, f"concurrent identical uploads created duplicates: {counts}"
    pages = ingestion.list_pages(store, heldout["pdf"].doc_id, settings)
    assert len(pages) == 7


def test_concurrent_searches_do_not_corrupt_connections(store, embeddings, settings, heldout):
    errors = []

    def worker(index: int) -> list:
        try:
            result = retrieval.search(
                store, embeddings, "latency p99 hybrid", mode=("vector", "fulltext", "hybrid")[index % 3],
                top_k=4, settings=settings,
            )
            return [hit.page_no for hit in result.hits]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(worker, range(16)))
    assert errors == [], errors
    assert all(outcomes), "every concurrent search must return hits"


# --------------------------------------------------------------------- outage & reconnect


def test_store_recovers_after_an_outage_without_a_restart(settings, embeddings):
    from app.config import Settings
    from app.db.seekdb import SeekDBStore

    broken = SeekDBStore(
        Settings(**{**settings.model_dump(), "seekdb_port": 2899, "seekdb_connect_timeout": 2})
    )
    with pytest.raises(SeekDBUnavailableError):
        broken.query("SELECT 1")
    # Pointing the same instance back at the live server must recover on the next call.
    broken.settings = settings
    broken.close_thread_resources()
    rows = broken.query("SELECT 1 AS one")
    assert rows[0]["one"] == 1
    broken.close_thread_resources()


def test_missing_page_stays_missing_after_reingest(store, embeddings, settings, heldout):
    with pytest.raises(NotFoundError):
        ingestion.get_page(store, heldout["pdf"].doc_id, 8, settings)
    again = ingestion.ingest_bytes(
        store, embeddings, heldout["pdf_bytes"], "heldout_alpha.pdf", settings=settings, force=True
    )
    assert again.page_count == 7
    assert again.doc_id == heldout["pdf"].doc_id
    with pytest.raises(NotFoundError):
        ingestion.get_page(store, again.doc_id, 8, settings)


# --------------------------------------------------------------------- LLM retry & degradation


class _FlakyCompletions:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise APIConnectionError(request=None)

        class _Message:
            content = '{"answer":"ok","answerable":true,"claims":[],"missing":""}'

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]
            model = "flaky"
            usage = None

        return _Response()


class _FlakyClient:
    def __init__(self, failures: int) -> None:
        self.chat = type("chat", (), {"completions": _FlakyCompletions(failures)})()


def test_llm_transient_errors_are_retried_then_succeed(settings, monkeypatch):
    gateway = LLMGateway(settings.model_copy(update={"llm_api_key": "test-key"}))
    flaky = _FlakyClient(failures=2)
    monkeypatch.setattr(gateway, "_ensure_client", lambda: flaky)
    monkeypatch.setattr("app.agent.llm.time.sleep", lambda *_: None)
    response = gateway.chat([{"role": "user", "content": "hi"}])
    assert response.content.startswith("{\"answer\"")
    assert flaky.chat.completions.calls == 3


def test_llm_persistent_outage_raises_not_silence(settings, monkeypatch):
    gateway = LLMGateway(settings.model_copy(update={"llm_api_key": "test-key"}))
    flaky = _FlakyClient(failures=99)
    monkeypatch.setattr(gateway, "_ensure_client", lambda: flaky)
    monkeypatch.setattr("app.agent.llm.time.sleep", lambda *_: None)
    with pytest.raises(LLMUnavailableError) as info:
        gateway.chat([{"role": "user", "content": "hi"}])
    assert info.value.status_code == 503
    assert info.value.detail["attempts"] == 3


async def test_qa_degrades_to_retrieval_only_without_a_key(store, embeddings, settings, heldout):
    gateway = LLMGateway(settings.model_copy(update={"llm_api_key": ""}))
    assert gateway.enabled is False
    result = await agent.answer_question(
        store, embeddings, gateway, "what was the cooling loop pressure during run H-12",
        mode="hybrid", top_k=4, settings=settings,
    )
    assert result.mode == "retrieval_only"
    assert result.citations, "retrieval-only mode must still return the real evidence"
    assert result.citations[0]["page_no"] == 2


def test_thread_safety_of_embedding_backend(store, embeddings, settings):
    errors = []

    def worker(_) -> None:
        try:
            embeddings.embed(["并发向量化测试 concurrency probe"] * 4)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(16)))
    assert errors == [], errors
