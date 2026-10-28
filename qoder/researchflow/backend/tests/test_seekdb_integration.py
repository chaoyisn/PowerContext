"""Integration tests against the live seekdb server: acceptance cases T1, T2, T3, T8.

Runs under the ``rft_`` prefix so nothing belonging to the demo run or to another
competition entry is touched.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.db.seekdb import SeekDBStore
from app.errors import SeekDBUnavailableError
from app.ingestion import service as ingestion
from app.retrieval import service as retrieval

from .conftest import MD_NAME, PDF_NAME, TXT_NAME, requires_seekdb

pytestmark = requires_seekdb


# --------------------------------------------------------------------------- T1


def test_t1_pdf_has_a_stable_record_for_every_physical_page(store, settings, ingested):
    pdf = ingested[PDF_NAME]
    assert pdf.content_type == "pdf"
    assert pdf.page_count == 5, "demo PDF must have 5 physical pages"
    assert pdf.status == "ready"
    assert pdf.error_message is None
    assert len(pdf.doc_id) == 64

    rows = store.query(
        f"SELECT page_id, page_no, char_count, is_empty FROM `{settings.pages_table}` "
        "WHERE doc_id = %s ORDER BY page_no",
        (pdf.doc_id,),
    )
    assert len(rows) == 5, "every physical page must have its own row in seekdb"
    assert [int(r["page_no"]) for r in rows] == [1, 2, 3, 4, 5], "page numbers start at 1"

    blank = next(r for r in rows if int(r["page_no"]) == 4)
    assert bool(blank["is_empty"]) is True, "page 4 of the demo PDF is intentionally blank"
    assert int(blank["char_count"]) == 0
    assert blank["page_id"] == f"{pdf.doc_id[:16]}:p0004", "page id must be recomputable"

    for row in rows[:3] + rows[4:]:
        assert bool(row["is_empty"]) is False
        assert int(row["char_count"]) > 0

    # The blank page keeps its identity row but contributes no chunks.
    assert pdf.chunk_count == 4, "4 non-blank pages -> 4 chunks"


def test_t1_chunks_are_persisted_in_seekdb_not_in_memory(store, settings, embeddings, ingested):
    collection = store.chunks()
    total = collection.count()
    expected = sum(record.chunk_count for record in ingested.values())
    assert total == expected, "chunk rows in seekdb must match the ingested chunk count"

    pdf = ingested[PDF_NAME]
    fetched = collection.get(
        where={"doc_id": {"$eq": pdf.doc_id}}, include=["documents", "metadatas"]
    )
    assert len(fetched["ids"]) == pdf.chunk_count
    for metadata in fetched["metadatas"]:
        assert metadata["doc_id"] == pdf.doc_id
        assert 1 <= int(metadata["page_no"]) <= 5, "no page number outside the real page range"
        assert int(metadata["page_no"]) != 4, "the blank page must not produce a chunk"

    counts = store.health()["counts"]
    assert counts["documents"] == 3
    assert counts["pages"] == 7, "5 PDF pages + 1 markdown page + 1 text page"
    assert counts["chunks"] == expected


def test_t1_reupload_is_idempotent(store, settings, embeddings, ingested, demo_files):
    before = store.health()["counts"]
    again = ingestion.ingest_bytes(
        store, embeddings, demo_files[PDF_NAME], PDF_NAME, settings=settings
    )
    assert again.deduplicated is True
    assert again.doc_id == ingested[PDF_NAME].doc_id
    after = store.health()["counts"]
    assert after == before, "re-uploading the same file must not create duplicate rows"

    forced = ingestion.ingest_bytes(
        store, embeddings, demo_files[PDF_NAME], PDF_NAME, settings=settings, force=True
    )
    assert forced.deduplicated is False
    assert forced.doc_id == ingested[PDF_NAME].doc_id
    assert store.health()["counts"] == before, "forced re-ingest must rewrite, not append"


def test_page_lookup_returns_stored_original_text(store, settings, ingested):
    pdf = ingested[PDF_NAME]
    page5 = ingestion.get_page(store, pdf.doc_id, 5, settings)
    assert page5.page_no == 5
    assert "Reciprocal Rank Fusion" in page5.content
    assert "0.0328" in page5.content

    page4 = ingestion.get_page(store, pdf.doc_id, 4, settings)
    assert page4.is_empty is True and page4.content.strip() == ""


def test_nonexistent_page_is_rejected_not_synthesised(store, ingested):
    from app.errors import NotFoundError

    pdf = ingested[PDF_NAME]
    with pytest.raises(NotFoundError) as info:
        ingestion.get_page(store, pdf.doc_id, 6, settings=None)
    assert "does not exist" in str(info.value)
    with pytest.raises(NotFoundError):
        ingestion.get_page(store, pdf.doc_id, 0, settings=None)
    with pytest.raises(NotFoundError):
        ingestion.get_page(store, "f" * 64, 1, settings=None)


# --------------------------------------------------------------------------- T2


KNOWN_QUESTIONS = [
    ("which full text analyzer segments Chinese correctly", PDF_NAME, 3),
    ("RRF rank constant 60 fusion score for a row first in both legs", PDF_NAME, 5),
    ("HNSW cosine distance measured for the hybrid retrieval query", PDF_NAME, 2),
    ("server VERSION() reported by the seekdb baseline environment", PDF_NAME, 1),
]


@pytest.mark.parametrize(("question", "filename", "page_no"), KNOWN_QUESTIONS)
def test_t2_retrieval_returns_the_right_document_and_real_page(
    store, embeddings, settings, ingested, question, filename, page_no
):
    """Full-text and hybrid must rank the right page first.

    Pure vector mode is only required to surface it inside the top 3: ANN is approximate
    and, with the offline ``hashing`` provider, several chunks land at nearly the same
    distance, so top-1 is not a stable property of the system. With ``minilm`` it is
    (measured: 0.72 for the right page vs <=0.31 for the rest) - see logs/smoke-minilm.log.
    """
    for mode in ("vector", "fulltext", "hybrid"):
        result = retrieval.search(
            store, embeddings, question, mode=mode, top_k=5, apply_gate=True, settings=settings
        )
        assert result.hits, f"{mode} returned nothing for an answerable question"
        located = [
            (index, hit)
            for index, hit in enumerate(result.hits)
            if hit.filename == filename and hit.page_no == page_no
        ]
        assert located, (
            f"{mode} did not surface {filename} page {page_no} at all; "
            f"got {[(h.filename, h.page_no) for h in result.hits]}"
        )
        rank = located[0][0]
        if mode in ("fulltext", "hybrid"):
            assert rank == 0, f"{mode} ranked {[(h.filename, h.page_no) for h in result.hits]} "
        else:
            assert rank < 3, f"vector mode pushed the right page to rank {rank}"

        top = located[0][1]
        assert top.doc_id == ingested[filename].doc_id
        assert top.chunk_id == f"{top.doc_id[:16]}:p{page_no:04d}:c{top.chunk_index:03d}"

        # Every citation must point at a page that really exists in seekdb.
        for citation in result.citations:
            page = ingestion.get_page(store, citation["doc_id"], citation["page_no"], settings)
            assert page.page_no == citation["page_no"]
            assert citation["quote"], "citation must carry the actual text fragment"


def test_t2_structured_filters_narrow_the_result_set(store, embeddings, settings, ingested):
    unfiltered = retrieval.search(
        store, embeddings, "analyzer", mode="fulltext", top_k=10, settings=settings
    )
    filtered = retrieval.search(
        store,
        embeddings,
        "analyzer",
        mode="fulltext",
        top_k=10,
        filters={"doc_id": ingested[PDF_NAME].doc_id},
        settings=settings,
    )
    assert filtered.hits, "doc_id filter must still return the matching PDF chunks"
    assert all(hit.doc_id == ingested[PDF_NAME].doc_id for hit in filtered.hits)
    assert len(filtered.hits) <= len(unfiltered.hits)

    paged = retrieval.search(
        store,
        embeddings,
        "seekdb",
        mode="fulltext",
        top_k=10,
        filters={"page_from": 5, "page_to": 5},
        settings=settings,
    )
    assert all(hit.page_no == 5 for hit in paged.hits)


def test_mode_comparison_runs_all_three_strategies(store, embeddings, settings, ingested):
    comparison = retrieval.compare_modes(
        store,
        embeddings,
        "which full text analyzer segments Chinese correctly",
        top_k=3,
        settings=settings,
    )
    assert set(comparison["results"]) == {"vector", "fulltext", "hybrid"}
    pdf = ingested[PDF_NAME]
    for mode, payload in comparison["results"].items():
        assert payload["mode"] == mode
        assert payload["hits"], f"{mode} leg returned nothing"
        assert payload["backend"]["collection"] == settings.chunks_collection
        assert any(
            hit["doc_id"] == pdf.doc_id and hit["page_no"] == 3 for hit in payload["hits"]
        ), f"{mode} leg did not surface the analyzer page"
    assert comparison["results"]["hybrid"]["hits"][0]["page_no"] == 3
    assert comparison["results"]["fulltext"]["hits"][0]["page_no"] == 3
    assert comparison["overlap"]["vector_and_fulltext"], "the modes must overlap on a clear question"


# --------------------------------------------------------------------------- T3


UNANSWERABLE = [
    "这篇文档里有没有关于量子纠缠实验的测量结果",
    "what is the half life of the isotope used in the fusion reactor experiment",
    "作者在哪一年获得了图灵奖",
]


@pytest.mark.parametrize("question", UNANSWERABLE)
def test_t3_unanswerable_question_produces_no_citation(
    store, embeddings, settings, ingested, question
):
    for mode in ("vector", "fulltext", "hybrid"):
        raw = retrieval.search(
            store, embeddings, question, mode=mode, top_k=5, apply_gate=False, settings=settings
        )
        gated = retrieval.search(
            store, embeddings, question, mode=mode, top_k=5, apply_gate=True, settings=settings
        )
        assert gated.citations == [], (
            f"{mode} offered a citation for a question the corpus cannot answer"
        )
        assert gated.dropped_by_gate >= 0
        # The raw hits stay visible so the UI can explain *why* nothing was offered.
        assert raw.gate["min_coverage"] == settings.retrieval_min_coverage


# --------------------------------------------------------------------------- T8


def test_t8_seekdb_outage_reports_a_real_error(settings, embeddings):
    broken_settings = Settings(
        **{
            **settings.model_dump(),
            "seekdb_port": 2899,  # nothing listens here
            "seekdb_connect_timeout": 2,
        }
    )
    broken = SeekDBStore(broken_settings)

    health = broken.health()
    assert health["available"] is False
    assert "error" in health and health["error"], "health must carry the real failure reason"

    with pytest.raises(SeekDBUnavailableError) as info:
        broken.query("SELECT 1")
    assert "cannot connect" in str(info.value) or "seekdb" in str(info.value).lower()
    assert info.value.status_code == 503
    assert info.value.detail.get("reason"), "the underlying driver error must be preserved"

    with pytest.raises(Exception) as search_error:
        retrieval.search(broken, embeddings, "anything", mode="hybrid", top_k=3)
    assert "预置" not in str(search_error.value)
    broken.close_thread_resources()


def test_t8_ingestion_fails_loudly_when_seekdb_is_down(settings, embeddings, demo_files):
    broken_settings = Settings(
        **{**settings.model_dump(), "seekdb_port": 2899, "seekdb_connect_timeout": 2}
    )
    broken = SeekDBStore(broken_settings)
    with pytest.raises(SeekDBUnavailableError):
        ingestion.ingest_bytes(
            broken, embeddings, demo_files[MD_NAME], MD_NAME, settings=broken_settings
        )
    broken.close_thread_resources()


def test_all_three_demo_documents_are_ingestible(ingested):
    assert set(ingested) == {PDF_NAME, MD_NAME, TXT_NAME}
    assert ingested[MD_NAME].content_type == "markdown"
    assert ingested[TXT_NAME].content_type == "text"
    assert all(record.status == "ready" for record in ingested.values())
    assert all(record.chunk_count > 0 for record in ingested.values())
