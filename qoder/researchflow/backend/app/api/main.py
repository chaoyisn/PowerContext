"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..config import PROJECT_ROOT, get_settings
from ..errors import ResearchFlowError
from ..logging_setup import get_logger, request_id_var, setup_logging
from .deps import build_state
from .routes_documents import router as documents_router
from .routes_health import router as health_router
from .routes_memory import router as memory_router
from .routes_qa import router as qa_router
from .routes_retrieval import router as retrieval_router

logger = get_logger(__name__)

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def _error_payload(request: Request, code: str, message: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "detail": detail,
            "path": request.url.path,
            "request_id": request_id_var.get(),
        }
    }


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state = build_state(settings)
        app.state.rf = state
        logger.info(
            "ResearchFlow backend started",
            fields={
                "seekdb": f"{settings.seekdb_host}:{settings.seekdb_port}/{settings.seekdb_database}",
                "collection": settings.chunks_collection,
                "embedding": state.embeddings.provider,
                "powercontext": settings.powercontext_url,
                "llm_enabled": state.llm.enabled,
                "schema_created": state.schema_result.get("created"),
            },
        )
        yield
        logger.info("ResearchFlow backend stopping")

    app = FastAPI(
        title="ResearchFlow API",
        version="0.1.0",
        description=(
            "科研知识与任务连续性助手后端。文献证据存于 seekdb（向量 + 全文 + 混合检索），"
            "科研任务记忆存于 PowerContext。两个后端职责分离，可独立断开验证。"
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            if response is not None:
                response.headers["x-request-id"] = request_id
                if request.url.path.startswith("/api"):
                    logger.info(
                        "request",
                        fields={
                            "method": request.method,
                            "path": request.url.path,
                            "status": response.status_code,
                            "ms": elapsed,
                        },
                    )
            request_id_var.reset(token)

    @app.exception_handler(ResearchFlowError)
    async def researchflow_error_handler(request: Request, exc: ResearchFlowError) -> JSONResponse:
        logger.warning(
            "request failed",
            fields={
                "path": request.url.path,
                "code": exc.error_code,
                "status": exc.status_code,
                "error": exc.message,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, exc.error_code, exc.message, exc.detail),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", fields={"path": request.url.path})
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                request, "internal_error", f"{type(exc).__name__}: {exc}", {}
            ),
        )

    for router in (health_router, documents_router, retrieval_router, qa_router, memory_router):
        app.include_router(router)

    @app.get("/api", include_in_schema=False)
    def api_index() -> dict[str, Any]:
        return {
            "name": "ResearchFlow API",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "endpoints": [
                "GET  /api/health",
                "GET  /api/meta",
                "POST /api/documents/upload",
                "GET  /api/documents",
                "GET  /api/documents/{doc_id}",
                "GET  /api/documents/{doc_id}/pages/{page_no}",
                "DELETE /api/documents/{doc_id}",
                "POST /api/retrieval/search",
                "POST /api/retrieval/compare",
                "POST /api/qa/ask",
                "POST /api/projects",
                "GET  /api/projects",
                "GET  /api/projects/{project_id}",
                "POST /api/projects/{project_id}/memory/save",
                "GET  /api/projects/{project_id}/memory/restore",
                "GET  /api/projects/{project_id}/memory/history",
                "GET  /api/memory/status",
            ],
        }

    if FRONTEND_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
        logger.info("serving built frontend", fields={"path": str(FRONTEND_DIST)})

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_config=None)


if __name__ == "__main__":
    main()
