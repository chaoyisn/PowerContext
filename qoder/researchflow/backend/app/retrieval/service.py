"""Retrieval over seekdb: vector, full-text and hybrid (RRF) modes.

Every hit carries a real ``doc_id`` / ``page_no`` / ``chunk_id`` so the UI can open the
stored original page. Nothing here can invent a page number: metadata comes straight
back from the seekdb row.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence

import numpy as np

from ..config import Settings, get_settings
from ..db.seekdb import SeekDBStore
from ..errors import RequestValidationError, ResearchFlowError
from ..logging_setup import get_logger
from .embeddings import EmbeddingBackend
from .relevance import combined_relevance, lexical_coverage, normalize_score, passes_gate

logger = get_logger(__name__)

RetrievalMode = Literal["vector", "fulltext", "hybrid"]
_VALID_MODES: tuple[str, ...] = ("vector", "fulltext", "hybrid")


class RetrievalError(ResearchFlowError):
    status_code = 502
    error_code = "retrieval_error"


@dataclass
class RetrievalHit:
    chunk_id: str
    doc_id: str
    filename: str
    content_type: str
    title: str
    page_no: int
    page_id: str
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    score: float
    score_kind: str
    matched_by: str = ""
    coverage: float = 0.0
    normalized_score: float = 0.0
    semantic_similarity: float = 0.0
    relevance: float = 0.0
    gate_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    query: str
    mode: str
    hits: list[RetrievalHit] = field(default_factory=list)
    elapsed_ms: float = 0.0
    backend: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)
    dropped_by_gate: int = 0
    error: str | None = None

    @property
    def relevant_hits(self) -> list[RetrievalHit]:
        return [hit for hit in self.hits if hit.gate_passed]

    @property
    def citations(self) -> list[dict[str, Any]]:
        """Only gate-passing hits become citations. Raw hits stay visible in ``hits``."""
        return [
            {
                "citation_id": f"c{index + 1}",
                "chunk_id": hit.chunk_id,
                "doc_id": hit.doc_id,
                "filename": hit.filename,
                "content_type": hit.content_type,
                "page_no": hit.page_no,
                "page_id": hit.page_id,
                "char_start": hit.char_start,
                "char_end": hit.char_end,
                "quote": hit.text,
                "score": hit.score,
                "score_kind": hit.score_kind,
                "relevance": hit.relevance,
                "coverage": hit.coverage,
                "source": "document",
            }
            for index, hit in enumerate(self.relevant_hits)
        ]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["citations"] = self.citations
        payload["relevant_count"] = len(self.relevant_hits)
        return payload


_DOC_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_VALID_CONTENT_TYPES = {"pdf", "markdown", "text"}


def build_where(filters: dict[str, Any] | None) -> dict[str, Any] | None:
    """Translate API filters into a pyseekdb metadata ``where`` clause.

    Filter values are validated fail-closed. Measured on seekdb v1.4.0.0 / pyseekdb
    1.4.0.post1: the vector leg parameterises metadata values correctly, but the full-text
    leg of ``hybrid_search`` silently DROPS a ``where`` clause whose value contains SQL
    metacharacters (a hostile value behaved exactly like no filter at all). Since filters are
    a scoping boundary, an invalid value must reject the request rather than widen it.
    """
    if not filters:
        return None
    where: dict[str, Any] = {}
    if filters.get("doc_id"):
        value = str(filters["doc_id"])
        if not _DOC_ID_RE.match(value):
            raise RequestValidationError(
                "doc_id filter must be a 64-character hex sha256",
                detail={"received_length": len(value)},
            )
        where["doc_id"] = {"$eq": value}
    if filters.get("content_type"):
        value = str(filters["content_type"])
        if value not in _VALID_CONTENT_TYPES:
            raise RequestValidationError(
                f"content_type filter must be one of {sorted(_VALID_CONTENT_TYPES)}",
                detail={"received": value},
            )
        where["content_type"] = {"$eq": value}
    page_conditions: list[dict[str, Any]] = []
    if filters.get("page_from") is not None:
        page_conditions.append({"page_no": {"$gte": int(filters["page_from"])}})
    if filters.get("page_to") is not None:
        page_conditions.append({"page_no": {"$lte": int(filters["page_to"])}})
    if len(page_conditions) == 1:
        where.update(page_conditions[0])
    elif len(page_conditions) == 2:
        where.setdefault("$and", []).extend(page_conditions)
    return where or None


def _cosine_similarity(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return round(float(np.dot(a, b) / (na * nb)), 6)


def _rows_to_hits(
    query: str,
    mode: str,
    ids: Sequence[str],
    documents: Sequence[str] | None,
    metadatas: Sequence[dict[str, Any]] | None,
    distances: Sequence[float] | None,
    embeddings: Sequence[Sequence[float]] | None,
    query_vector: Sequence[float] | None,
    *,
    score_kind: str,
    matched_by: str,
    invert_distance: bool,
    min_coverage: float,
    vector_confidence: float,
) -> list[RetrievalHit]:
    hits: list[RetrievalHit] = []
    for index, chunk_id in enumerate(ids):
        metadata = (metadatas[index] if metadatas else {}) or {}
        text = documents[index] if documents else ""
        text = text or ""
        raw = float(distances[index]) if distances and index < len(distances) else 0.0
        score = (1.0 - raw) if invert_distance else raw
        stored_vector = embeddings[index] if embeddings and index < len(embeddings) else None
        similarity = _cosine_similarity(query_vector, stored_vector)
        coverage = lexical_coverage(query, text)
        normalized = normalize_score(score, score_kind)
        hits.append(
            RetrievalHit(
                chunk_id=str(chunk_id),
                doc_id=str(metadata.get("doc_id", "")),
                filename=str(metadata.get("filename", "")),
                content_type=str(metadata.get("content_type", "")),
                title=str(metadata.get("title", "")),
                page_no=int(metadata.get("page_no", 0)),
                page_id=str(metadata.get("page_id", "")),
                chunk_index=int(metadata.get("chunk_index", 0)),
                char_start=int(metadata.get("char_start", 0)),
                char_end=int(metadata.get("char_end", 0)),
                text=text,
                score=round(score, 6),
                score_kind=score_kind,
                matched_by=matched_by,
                coverage=coverage,
                normalized_score=normalized,
                semantic_similarity=similarity,
                relevance=combined_relevance(normalized, coverage),
                gate_passed=passes_gate(
                    coverage=coverage,
                    semantic_similarity=similarity,
                    min_coverage=min_coverage,
                    vector_confidence=vector_confidence,
                ),
            )
        )
    return hits


def search(
    store: SeekDBStore,
    backend: EmbeddingBackend,
    query: str,
    *,
    mode: RetrievalMode = "hybrid",
    top_k: int | None = None,
    filters: dict[str, Any] | None = None,
    apply_gate: bool = False,
    settings: Settings | None = None,
) -> RetrievalResult:
    """Run one retrieval mode against seekdb.

    ``apply_gate=False`` keeps every raw hit (knowledge-base browsing, mode comparison);
    ``apply_gate=True`` drops hits that fail the evidence gate, which is what the QA path
    uses so an unanswerable question cannot produce a citation.
    """
    settings = settings or get_settings()
    if mode not in _VALID_MODES:
        raise RetrievalError(
            f"unknown retrieval mode '{mode}'", detail={"valid": list(_VALID_MODES)}
        )
    text = (query or "").strip()
    if not text:
        raise RetrievalError("query must not be empty")

    limit = int(top_k or settings.retrieval_top_k)
    limit = max(1, min(limit, 50))
    where = build_where(filters)
    # Embeddings are fetched so the semantic half of the evidence gate can be evaluated in
    # every mode, not only in pure vector search.
    include = ["documents", "metadatas", "embeddings"]
    started = time.perf_counter()
    query_vector = backend.embed([text])[0]

    backend_info = {
        "endpoint": f"{settings.seekdb_host}:{settings.seekdb_port}",
        "database": settings.seekdb_database,
        "collection": settings.chunks_collection,
        "fts_analyzer": settings.seekdb_fts_analyzer,
        "vector_distance": settings.seekdb_vector_distance,
        "embedding_provider": backend.provider,
        "embedding_dimension": backend.dimension,
    }
    # Vectors written by a different provider are not comparable to the query vector.
    # Surface it instead of silently returning garbage ranks.
    stored_provider = store.get_meta("embedding_provider")
    if stored_provider and stored_provider != backend.provider:
        backend_info["stored_embedding_provider"] = stored_provider
        backend_info["warning"] = (
            f"chunks were embedded with '{stored_provider}' but queries are being embedded "
            f"with '{backend.provider}'; re-ingest the corpus for comparable vectors"
        )
    gate_info = {
        "applied": apply_gate,
        "min_coverage": settings.retrieval_min_coverage,
        "vector_confidence": settings.retrieval_vector_confidence,
    }

    collection = store.chunks()
    result = RetrievalResult(
        query=text,
        mode=mode,
        backend=backend_info,
        filters=filters or {},
        gate=gate_info,
    )
    scoring = {
        "min_coverage": settings.retrieval_min_coverage,
        "vector_confidence": settings.retrieval_vector_confidence,
    }

    def _first(payload: dict[str, Any], key: str) -> Sequence[Any] | None:
        value = payload.get(key)
        return value[0] if value else None

    try:
        if mode == "vector":
            raw = collection.query(
                query_embeddings=[query_vector],
                n_results=limit,
                where=where,
                include=include,
            )
            result.hits = _rows_to_hits(
                text,
                mode,
                raw["ids"][0],
                _first(raw, "documents"),
                _first(raw, "metadatas"),
                _first(raw, "distances"),
                _first(raw, "embeddings"),
                query_vector,
                score_kind=(
                    "cosine_similarity" if settings.seekdb_vector_distance == "cosine" else "distance"
                ),
                matched_by="vector",
                invert_distance=True,
                **scoring,
            )
        elif mode == "fulltext":
            raw = collection.hybrid_search(
                query={"where_document": {"$contains": text}, "where": where, "n_results": limit},
                knn=None,
                rank=None,
                n_results=limit,
                include=include,
            )
            result.hits = _rows_to_hits(
                text,
                mode,
                raw["ids"][0],
                _first(raw, "documents"),
                _first(raw, "metadatas"),
                _first(raw, "distances"),
                _first(raw, "embeddings"),
                query_vector,
                score_kind="fts_relevance",
                matched_by="fulltext",
                invert_distance=False,
                **scoring,
            )
        else:
            raw = collection.hybrid_search(
                query={"where_document": {"$contains": text}, "where": where, "n_results": limit},
                knn={"query_embeddings": [query_vector], "where": where, "n_results": limit},
                rank={"rrf": {}},
                n_results=limit,
                include=include,
            )
            result.hits = _rows_to_hits(
                text,
                mode,
                raw["ids"][0],
                _first(raw, "documents"),
                _first(raw, "metadatas"),
                _first(raw, "distances"),
                _first(raw, "embeddings"),
                query_vector,
                score_kind="rrf",
                matched_by="hybrid",
                invert_distance=False,
                **scoring,
            )
    except ResearchFlowError:
        raise
    except Exception as exc:
        logger.error(
            "retrieval failed",
            fields={"mode": mode, "query": text[:80], "error": f"{type(exc).__name__}: {exc}"},
        )
        raise RetrievalError(
            f"seekdb {mode} search failed: {type(exc).__name__}: {exc}",
            detail={"mode": mode},
        ) from exc

    if settings.retrieval_min_score > 0:
        result.hits = [h for h in result.hits if h.score >= settings.retrieval_min_score]
    if apply_gate:
        kept = [h for h in result.hits if h.gate_passed]
        result.dropped_by_gate = len(result.hits) - len(kept)
        result.hits = kept

    result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "retrieval done",
        fields={
            "mode": mode,
            "hits": len(result.hits),
            "relevant": len(result.relevant_hits),
            "dropped": result.dropped_by_gate,
            "ms": result.elapsed_ms,
            "query": text[:60],
        },
    )
    return result


def compare_modes(
    store: SeekDBStore,
    backend: EmbeddingBackend,
    query: str,
    *,
    top_k: int | None = None,
    filters: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run all three modes so the UI can show what each retrieval strategy actually returns."""
    settings = settings or get_settings()
    results = {
        mode: search(
            store, backend, query, mode=mode, top_k=top_k, filters=filters, settings=settings
        ).to_dict()
        for mode in _VALID_MODES
    }
    overlap: dict[str, list[str]] = {}
    ids = {mode: [h["chunk_id"] for h in results[mode]["hits"]] for mode in _VALID_MODES}
    overlap["vector_and_fulltext"] = sorted(set(ids["vector"]) & set(ids["fulltext"]))
    overlap["hybrid_only"] = sorted(set(ids["hybrid"]) - set(ids["vector"]) - set(ids["fulltext"]))
    return {
        "query": query,
        "results": results,
        "ids": ids,
        "overlap": overlap,
        "backend": results["hybrid"]["backend"],
    }


def lookup_chunks(
    store: SeekDBStore, chunk_ids: Sequence[str], settings: Settings | None = None
) -> dict[str, RetrievalHit]:
    """Re-read chunks by id straight from seekdb, used to validate LLM citations."""
    settings = settings or get_settings()
    if not chunk_ids:
        return {}
    collection = store.chunks()
    raw = collection.get(ids=list(chunk_ids), include=["documents", "metadatas"])
    hits: dict[str, RetrievalHit] = {}
    for index, chunk_id in enumerate(raw.get("ids", [])):
        metadata = (raw.get("metadatas") or [{}])[index] or {}
        text = (raw.get("documents") or [""])[index] or ""
        hits[str(chunk_id)] = RetrievalHit(
            chunk_id=str(chunk_id),
            doc_id=str(metadata.get("doc_id", "")),
            filename=str(metadata.get("filename", "")),
            content_type=str(metadata.get("content_type", "")),
            title=str(metadata.get("title", "")),
            page_no=int(metadata.get("page_no", 0)),
            page_id=str(metadata.get("page_id", "")),
            chunk_index=int(metadata.get("chunk_index", 0)),
            char_start=int(metadata.get("char_start", 0)),
            char_end=int(metadata.get("char_end", 0)),
            text=text,
            score=1.0,
            score_kind="lookup",
            matched_by="citation_check",
        )
    return hits
