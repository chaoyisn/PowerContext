"""Retrieval endpoints: single mode search and three-mode comparison."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from ..retrieval import service as retrieval
from .deps import get_app_state
from .schemas import CompareRequest, SearchRequest

router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])


@router.post("/search")
async def search(request: SearchRequest, state=Depends(get_app_state)) -> dict[str, Any]:
    result = await run_in_threadpool(
        retrieval.search,
        state.store,
        state.embeddings,
        request.query,
        mode=request.mode,
        top_k=request.top_k,
        filters=request.filters(),
        apply_gate=request.apply_gate,
        settings=state.settings,
    )
    return result.to_dict()


@router.post("/compare")
async def compare(request: CompareRequest, state=Depends(get_app_state)) -> dict[str, Any]:
    """Run vector / fulltext / hybrid on the same query so the difference is visible."""
    return await run_in_threadpool(
        retrieval.compare_modes,
        state.store,
        state.embeddings,
        request.query,
        top_k=request.top_k,
        filters=request.filters(),
        settings=state.settings,
    )
