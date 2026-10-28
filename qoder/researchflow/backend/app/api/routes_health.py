"""Health and configuration endpoints. These report real backend state, never a hardcoded OK."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..config import Settings
from .deps import get_app_state, get_settings_dep

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(state=Depends(get_app_state)) -> dict[str, Any]:
    seekdb = state.store.health()
    powercontext = await state.gateway.health()
    available = bool(seekdb.get("available"))
    return {
        "status": "ok" if available else "degraded",
        "components": {
            "seekdb": seekdb,
            "powercontext": powercontext,
            "llm": state.llm.info(),
            "embedding": {
                "provider": state.embeddings.provider,
                "dimension": state.embeddings.dimension,
                "note": state.embeddings.note,
                "configured": state.settings.embedding_provider,
            },
        },
        "capabilities": {
            "upload": available,
            "retrieval": available,
            "qa": available,
            "qa_generates_answers": available and state.llm.enabled,
            "memory": bool(powercontext.get("available")),
        },
    }


@router.get("/meta")
def meta(settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    """Non-secret runtime configuration, so the UI can show what it is actually talking to."""
    return {
        "app": "ResearchFlow",
        "version": "0.1.0",
        "seekdb": {
            "mode": settings.seekdb_mode,
            "endpoint": f"{settings.seekdb_host}:{settings.seekdb_port}",
            "database": settings.seekdb_database,
            "prefix": settings.seekdb_prefix,
            "fts_analyzer": settings.seekdb_fts_analyzer,
            "vector_distance": settings.seekdb_vector_distance,
            "collection": settings.chunks_collection,
            "tables": {
                "documents": settings.documents_table,
                "pages": settings.pages_table,
                "projects": settings.projects_table,
                "meta": settings.meta_table,
            },
        },
        "powercontext": {
            "url": settings.powercontext_url,
            "integration": settings.powercontext_integration,
            "max_context_bytes": settings.powercontext_max_context_bytes,
        },
        "llm": {"base_url": settings.llm_base_url, "model": settings.llm_model, "enabled": settings.llm_enabled},
        "embedding": {"configured": settings.embedding_provider, "dimension": settings.embedding_dimension},
        "retrieval": {
            "default_top_k": settings.retrieval_top_k,
            "modes": ["vector", "fulltext", "hybrid"],
            "min_coverage": settings.retrieval_min_coverage,
            "vector_confidence": settings.retrieval_vector_confidence,
        },
        "upload": {
            "max_bytes": settings.upload_max_bytes,
            "allowed_extensions": sorted(settings.allowed_extensions),
        },
    }
