"""HTTP-level integration tests for the public API contract."""

from __future__ import annotations

import pytest

from .conftest import MD_NAME, PDF_NAME, TXT_NAME, DEMO_DIR, requires_powercontext, requires_seekdb

pytestmark = requires_seekdb


def _upload(client, name: str):
    with (DEMO_DIR / name).open("rb") as handle:
        return client.post(
            "/api/documents/upload",
            files={"file": (name, handle.read(), "application/octet-stream")},
        )


# --------------------------------------------------------------------- health


def test_health_reports_real_backend_state(api_client):
    response = api_client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    seekdb = body["components"]["seekdb"]
    assert seekdb["available"] is True
    assert "seekdb" in seekdb["server_version"], "the real server version must be reported"
    assert seekdb["endpoint"].endswith(":2881")
    assert body["components"]["embedding"]["provider"] in {"hashing", "minilm", "openai"}
    assert body["capabilities"]["retrieval"] is True
    assert response.headers.get("x-request-id"), "every response must be correlatable"


def test_meta_exposes_only_non_secret_configuration(api_client):
    body = api_client.get("/api/meta").json()
    assert body["seekdb"]["prefix"] == "rft_"
    assert body["seekdb"]["collection"] == "rft_chunks"
    assert body["seekdb"]["tables"]["pages"] == "rft_pages"
    assert body["retrieval"]["modes"] == ["vector", "fulltext", "hybrid"]
    assert ".pdf" in body["upload"]["allowed_extensions"]
    assert set(body["llm"]) == {"base_url", "model", "enabled"}, "no key material in /api/meta"
    assert "password" not in body["seekdb"]


def test_openapi_document_is_served(api_client):
    response = api_client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for expected in (
        "/api/health",
        "/api/documents/upload",
        "/api/retrieval/search",
        "/api/retrieval/compare",
        "/api/qa/ask",
        "/api/projects",
        "/api/memory/status",
    ):
        assert expected in paths, f"{expected} missing from the OpenAPI document"


# --------------------------------------------------------------------- upload


def test_upload_pdf_reports_every_physical_page(api_client):
    response = _upload(api_client, PDF_NAME)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content_type"] == "pdf"
    assert body["page_count"] == 5
    assert body["empty_pages"] == [4]
    assert body["status"] == "ready"
    assert len(body["doc_id"]) == 64
    assert [page["page_no"] for page in body["pages"]] == [1, 2, 3, 4, 5]

    again = _upload(api_client, PDF_NAME)
    assert again.json()["deduplicated"] is True
    assert again.json()["doc_id"] == body["doc_id"]


def test_upload_markdown_and_text(api_client):
    for name, content_type in ((MD_NAME, "markdown"), (TXT_NAME, "text")):
        response = _upload(api_client, name)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["content_type"] == content_type
        assert body["page_count"] == 1
        assert body["chunk_count"] > 0


def test_upload_rejects_disallowed_extension(api_client):
    response = api_client.post(
        "/api/documents/upload",
        files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "unsupported_file_type"
    assert ".pdf" in error["detail"]["allowed"]


def test_upload_rejects_traversal_filename_but_keeps_the_safe_part(api_client):
    response = api_client.post(
        "/api/documents/upload",
        files={"file": ("../../etc/notes.txt", b"plain text body", "text/plain")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "notes.txt"


def test_upload_rejects_oversize_file(api_client, settings):
    payload = b"%PDF-" + b"0" * (settings.upload_max_bytes + 10)
    response = api_client.post(
        "/api/documents/upload", files={"file": ("big.pdf", payload, "application/pdf")}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


# --------------------------------------------------------------------- documents


def test_document_listing_and_page_evidence(api_client):
    uploaded = _upload(api_client, PDF_NAME).json()
    doc_id = uploaded["doc_id"]

    listing = api_client.get("/api/documents").json()
    assert listing["count"] >= 3
    assert any(item["doc_id"] == doc_id for item in listing["documents"])

    detail = api_client.get(f"/api/documents/{doc_id}").json()
    assert detail["page_count"] == 5
    assert len(detail["pages"]) == 5

    page5 = api_client.get(f"/api/documents/{doc_id}/pages/5")
    assert page5.status_code == 200
    assert "Reciprocal Rank Fusion" in page5.json()["content"]
    assert page5.json()["page_no"] == 5

    page4 = api_client.get(f"/api/documents/{doc_id}/pages/4").json()
    assert page4["is_empty"] is True and page4["content"].strip() == ""


def test_missing_page_returns_404_with_a_real_reason(api_client):
    doc_id = _upload(api_client, PDF_NAME).json()["doc_id"]
    response = api_client.get(f"/api/documents/{doc_id}/pages/99")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["detail"]["page_count"] == 5
    assert "does not exist" in error["message"]

    assert api_client.get(f"/api/documents/{'0' * 64}").status_code == 404


# --------------------------------------------------------------------- retrieval


def test_search_endpoint_returns_citations_with_real_pages(api_client):
    response = api_client.post(
        "/api/retrieval/search",
        json={
            "query": "which full text analyzer segments Chinese correctly",
            "mode": "hybrid",
            "top_k": 3,
            "apply_gate": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "hybrid"
    assert body["citations"], "an answerable question must produce citations"
    pages = [citation["page_no"] for citation in body["citations"]]
    assert 3 in pages[:2], f"the analyzer page must be in the top two citations, got {pages}"
    top = body["citations"][0]
    assert top["source"] == "document"
    assert top["chunk_id"].startswith(top["doc_id"][:16])
    assert f":p{top['page_no']:04d}:c" in top["chunk_id"], "chunk id must encode the real page"
    assert body["backend"]["collection"] == "rft_chunks"


@pytest.mark.parametrize("mode", ["vector", "fulltext", "hybrid"])
def test_search_accepts_every_mode(api_client, mode):
    response = api_client.post(
        "/api/retrieval/search",
        json={"query": "HNSW cosine distance", "mode": mode, "top_k": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == mode


def test_search_rejects_unknown_mode_and_empty_query(api_client):
    response = api_client.post(
        "/api/retrieval/search", json={"query": "x", "mode": "magic", "top_k": 3}
    )
    assert response.status_code == 422
    empty = api_client.post("/api/retrieval/search", json={"query": "", "mode": "hybrid"})
    assert empty.status_code == 422


def test_search_filters_by_document(api_client):
    doc_id = _upload(api_client, PDF_NAME).json()["doc_id"]
    response = api_client.post(
        "/api/retrieval/search",
        json={"query": "analyzer", "mode": "fulltext", "top_k": 5, "doc_id": doc_id},
    )
    assert response.status_code == 200
    assert all(hit["doc_id"] == doc_id for hit in response.json()["hits"])


def test_search_rejects_malformed_filter_values(api_client):
    """The seekdb full-text leg silently drops where clauses with SQL metacharacters, so the
    API must reject such values instead of widening the result set."""
    for hostile in ["' OR '1'='1", "not-a-sha", "4d5da56c0b76197b"]:
        response = api_client.post(
            "/api/retrieval/search",
            json={"query": "analyzer", "mode": "fulltext", "top_k": 5, "doc_id": hostile},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"


def test_compare_endpoint_returns_all_three_modes(api_client):
    response = api_client.post(
        "/api/retrieval/compare",
        json={"query": "RRF rank constant 60", "top_k": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body["results"]) == {"vector", "fulltext", "hybrid"}
    assert set(body["ids"]) == {"vector", "fulltext", "hybrid"}
    assert "vector_and_fulltext" in body["overlap"]


# --------------------------------------------------------------------- qa


def test_ask_endpoint_labels_retrieval_only_when_no_llm_is_configured(api_client):
    response = api_client.post(
        "/api/qa/ask",
        json={"question": "which full text analyzer segments Chinese correctly", "top_k": 3},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "retrieval_only"
    assert body["answer"].startswith("【仅检索模式】")
    assert body["citations"]
    assert body["label_summary"]["supported"] >= 1


def test_ask_endpoint_refuses_to_answer_without_evidence(api_client):
    response = api_client.post(
        "/api/qa/ask",
        json={"question": "这篇文档里有没有关于量子纠缠实验的测量结果", "top_k": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answerable"] is False
    assert body["citations"] == []
    assert body["used_citations"] == []
    assert body["label_summary"]["no_evidence"] == 1
    assert "没有" in body["answer"]


# --------------------------------------------------------------------- memory


@requires_powercontext
def test_memory_status_endpoint(api_client):
    response = api_client.get("/api/memory/status")
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "PowerContext"
    assert body["role"] == "long-term research task memory"
    assert body["available"] is True
    assert body["package_version"] == "1.4.1"


@requires_powercontext
def test_project_and_memory_roundtrip_over_http(api_client):
    created = api_client.post(
        "/api/projects",
        json={"project_id": "t-api-project", "title": "API 记忆回路测试", "objective": "验证 HTTP 层"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["project_id"] == "t-api-project"
    assert body["scope_id"], "the PowerContext scope must be bound"

    listing = api_client.get("/api/projects").json()
    assert any(p["project_id"] == "t-api-project" for p in listing["projects"])

    saved = api_client.post(
        "/api/projects/t-api-project/memory/save",
        json={
            "decisions": ["D-API-1: 通过 HTTP 保存的决策"],
            "next_steps": ["N-API-1: 通过 HTTP 恢复"],
            "completed_work": ["完成 API 层联调"],
            "confirmed_by": "pytest",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["snapshot_artifact_id"]

    restored = api_client.get("/api/projects/t-api-project/memory/restore").json()
    assert restored["memory_available"] is True
    assert restored["source"] == "memory"
    assert "D-API-1: 通过 HTTP 保存的决策" in restored["resume_brief"]
    assert "N-API-1: 通过 HTTP 恢复" in restored["resume_brief"]
    assert restored["snapshot"]["decisions"] == ["D-API-1: 通过 HTTP 保存的决策"]

    history = api_client.get("/api/projects/t-api-project/memory/history").json()
    assert history["entry_count"] >= 4
    assert history["source"] == "memory"

    overview = api_client.get("/api/projects/t-api-project").json()
    assert overview["memory_available"] is True
    assert overview["entry_count"] >= 4


@requires_powercontext
def test_memory_save_requires_something_to_save(api_client):
    api_client.post("/api/projects", json={"project_id": "t-api-empty", "title": "空项目"})
    response = api_client.post("/api/projects/t-api-empty/memory/save", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_project_returns_404(api_client):
    assert api_client.get("/api/projects/no-such-project").status_code == 404
    restore = api_client.get("/api/projects/no-such-project/memory/restore")
    assert restore.status_code == 404
    assert restore.json()["error"]["code"] == "not_found"
