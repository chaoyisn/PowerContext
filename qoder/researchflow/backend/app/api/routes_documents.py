"""Document upload, listing and page-level evidence lookup."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from starlette.concurrency import run_in_threadpool

from ..ingestion import service as ingestion
from .deps import get_app_state

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), force: bool = False, state=Depends(get_app_state)) -> dict[str, Any]:
    data = await file.read()
    result = await run_in_threadpool(
        ingestion.ingest_bytes,
        state.store,
        state.embeddings,
        data,
        file.filename or "upload",
        settings=state.settings,
        force=force,
    )
    payload = result.to_dict()
    payload["pages"] = await run_in_threadpool(
        ingestion.list_pages, state.store, result.doc_id, state.settings
    )
    return payload


@router.get("")
def list_documents(state=Depends(get_app_state)) -> dict[str, Any]:
    documents = ingestion.list_documents(state.store, state.settings)
    return {
        "count": len(documents),
        "documents": [document.to_dict() for document in documents],
        "embedding_provider": state.embeddings.provider,
    }


@router.get("/{doc_id}")
def get_document(doc_id: str, state=Depends(get_app_state)) -> dict[str, Any]:
    document = ingestion.get_document(state.store, doc_id, state.settings)
    return {
        **document.to_dict(),
        "pages": ingestion.list_pages(state.store, doc_id, state.settings),
    }


@router.get("/{doc_id}/pages/{page_no}")
def get_page(doc_id: str, page_no: int, state=Depends(get_app_state)) -> dict[str, Any]:
    """Original text of one physical page. 404 if that page does not exist - never synthesised."""
    page = ingestion.get_page(state.store, doc_id, page_no, state.settings)
    return page.to_dict()


@router.delete("/{doc_id}")
def delete_document(doc_id: str, state=Depends(get_app_state)) -> dict[str, Any]:
    return ingestion.delete_document(state.store, doc_id, state.settings)
