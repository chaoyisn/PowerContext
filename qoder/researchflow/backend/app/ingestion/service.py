"""Document ingestion: parse -> page records -> chunks -> vectors -> seekdb.

Idempotent by construction: ``doc_id`` is the SHA-256 of the file bytes, and every
page/chunk id is derived from it, so re-uploading the same file rewrites the same rows
instead of accumulating duplicates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from ..config import Settings, get_settings
from ..db.seekdb import SeekDBStore
from ..errors import DocumentParseError, NotFoundError
from ..logging_setup import get_logger
from ..retrieval.embeddings import EmbeddingBackend
from .chunking import Chunk, chunk_page_text, doc_prefix, page_id_for
from .hashing import safe_filename, sha256_bytes, validate_upload
from .parsers import ParsedDocument, parse_document

logger = get_logger(__name__)

_EMBED_BATCH = 32
_UPSERT_BATCH = 64


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def parse_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.isoformat()
    return str(value)


@dataclass
class IngestedDocument:
    doc_id: str
    filename: str
    content_type: str
    size_bytes: int
    page_count: int
    chunk_count: int
    title: str
    status: str
    deduplicated: bool = False
    empty_pages: list[int] = field(default_factory=list)
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    embedding_provider: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageRecord:
    page_id: str
    doc_id: str
    page_no: int
    char_count: int
    is_empty: bool
    content: str
    filename: str = ""
    content_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_to_document(row: dict[str, Any]) -> IngestedDocument:
    return IngestedDocument(
        doc_id=row["doc_id"],
        filename=row["filename"],
        content_type=row["content_type"],
        size_bytes=int(row["size_bytes"]),
        page_count=int(row["page_count"]),
        chunk_count=int(row["chunk_count"]),
        title=row["title"] or "",
        status=row["status"],
        error_message=row.get("error_message"),
        created_at=parse_timestamp(row.get("created_at")),
        updated_at=parse_timestamp(row.get("updated_at")),
    )


def _batched(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _embed_all(backend: EmbeddingBackend, texts: Sequence[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for batch in _batched(texts, _EMBED_BATCH):
        vectors.extend(backend.embed(list(batch)))
    if len(vectors) != len(texts):
        raise DocumentParseError(
            f"embedding provider returned {len(vectors)} vectors for {len(texts)} chunks"
        )
    for vector in vectors:
        if len(vector) != backend.dimension:
            raise DocumentParseError(
                f"embedding dimension mismatch: got {len(vector)}, expected {backend.dimension}"
            )
    return vectors


def ingest_bytes(
    store: SeekDBStore,
    backend: EmbeddingBackend,
    data: bytes,
    filename: str,
    *,
    settings: Settings | None = None,
    force: bool = False,
) -> IngestedDocument:
    """Validate, parse and persist one upload. Raises on any real failure."""
    settings = settings or get_settings()
    clean_name = safe_filename(filename)
    content_type = validate_upload(clean_name, data, settings)
    doc_id = sha256_bytes(data)
    now = _utcnow()

    if not force:
        existing = store.query(
            f"SELECT * FROM `{settings.documents_table}` WHERE doc_id = %s", (doc_id,)
        )
        if existing and existing[0]["status"] == "ready":
            document = _row_to_document(existing[0])
            document.deduplicated = True
            document.empty_pages = _empty_pages(store, settings, doc_id)
            document.embedding_provider = backend.provider
            logger.info(
                "duplicate upload skipped", fields={"doc_id": doc_id, "filename": clean_name}
            )
            return document

    parsed: ParsedDocument = parse_document(data, clean_name, content_type)
    prefix = doc_prefix(doc_id)

    page_rows: list[tuple[Any, ...]] = []
    chunks: list[Chunk] = []
    for page in parsed.pages:
        page_rows.append(
            (
                page_id_for(doc_id, page.page_no),
                doc_id,
                page.page_no,
                len(page.text),
                1 if page.is_empty else 0,
                page.text,
                now,
            )
        )
        chunks.extend(
            chunk_page_text(page.text, page.page_no) if not page.is_empty else []
        )

    vectors = _embed_all(backend, [chunk.text for chunk in chunks]) if chunks else []

    try:
        collection = store.chunks()
        if force:
            collection.delete(where={"doc_id": {"$eq": doc_id}})

        with store.transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""INSERT INTO `{settings.documents_table}`
  (doc_id, filename, content_type, size_bytes, page_count, chunk_count, title,
   status, error_message, created_at, updated_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,'ready',NULL,%s,%s)
ON DUPLICATE KEY UPDATE
  filename=VALUES(filename), content_type=VALUES(content_type), size_bytes=VALUES(size_bytes),
  page_count=VALUES(page_count), chunk_count=VALUES(chunk_count), title=VALUES(title),
  status='ready', error_message=NULL, updated_at=VALUES(updated_at)""",
                    (
                        doc_id,
                        clean_name,
                        content_type,
                        len(data),
                        parsed.page_count,
                        len(chunks),
                        parsed.title,
                        now,
                        now,
                    ),
                )
                cursor.execute(
                    f"DELETE FROM `{settings.pages_table}` WHERE doc_id = %s", (doc_id,)
                )
                if page_rows:
                    cursor.executemany(
                        f"""INSERT INTO `{settings.pages_table}`
  (page_id, doc_id, page_no, char_count, is_empty, content, created_at)
VALUES (%s,%s,%s,%s,%s,%s,%s)
ON DUPLICATE KEY UPDATE
  char_count=VALUES(char_count), is_empty=VALUES(is_empty),
  content=VALUES(content), created_at=VALUES(created_at)""",
                        page_rows,
                    )

        for start in range(0, len(chunks), _UPSERT_BATCH):
            batch = chunks[start : start + _UPSERT_BATCH]
            collection.upsert(
                ids=[chunk.chunk_id(prefix) for chunk in batch],
                embeddings=vectors[start : start + len(batch)],
                documents=[chunk.text for chunk in batch],
                metadatas=[
                    {
                        "doc_id": doc_id,
                        "filename": clean_name,
                        "content_type": content_type,
                        "title": parsed.title,
                        "page_no": chunk.page_no,
                        "page_id": chunk.page_id(prefix),
                        "chunk_index": chunk.chunk_index,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "sha256": doc_id,
                    }
                    for chunk in batch
                ],
            )

        if chunks:
            # Without this, freshly written vectors are not reliably visible to ANN search
            # (observed: a 13-chunk corpus returning only 3 hits right after ingest).
            try:
                collection.refresh_index()
            except Exception as exc:
                logger.warning(
                    "vector index refresh failed; ANN recall may lag until seekdb catches up",
                    fields={"doc_id": doc_id, "error": f"{type(exc).__name__}: {exc}"},
                )
    except Exception as exc:
        _mark_failed(store, settings, doc_id, clean_name, content_type, data, parsed, now, exc)
        logger.error(
            "ingestion failed",
            fields={"doc_id": doc_id, "filename": clean_name, "error": f"{type(exc).__name__}: {exc}"},
        )
        raise

    result = IngestedDocument(
        doc_id=doc_id,
        filename=clean_name,
        content_type=content_type,
        size_bytes=len(data),
        page_count=parsed.page_count,
        chunk_count=len(chunks),
        title=parsed.title,
        status="ready",
        deduplicated=False,
        empty_pages=parsed.empty_pages,
        created_at=now,
        updated_at=now,
        embedding_provider=backend.provider,
    )
    store.set_meta("embedding_provider", backend.provider)
    store.set_meta("embedding_dimension", str(backend.dimension))
    store.set_meta("embedding_updated_at", now)
    logger.info(
        "document ingested",
        fields={
            "doc_id": doc_id,
            "filename": clean_name,
            "pages": result.page_count,
            "chunks": result.chunk_count,
            "empty_pages": len(result.empty_pages),
        },
    )
    return result


def _mark_failed(
    store: SeekDBStore,
    settings: Settings,
    doc_id: str,
    filename: str,
    content_type: str,
    data: bytes,
    parsed: ParsedDocument | None,
    now: str,
    exc: Exception,
) -> None:
    """Persist the failure reason instead of swallowing it."""
    try:
        store.execute(
            f"""INSERT INTO `{settings.documents_table}`
  (doc_id, filename, content_type, size_bytes, page_count, chunk_count, title,
   status, error_message, created_at, updated_at)
VALUES (%s,%s,%s,%s,%s,0,%s,'failed',%s,%s,%s)
ON DUPLICATE KEY UPDATE status='failed', error_message=VALUES(error_message), updated_at=VALUES(updated_at)""",
            (
                doc_id,
                filename,
                content_type,
                len(data),
                parsed.page_count if parsed else 0,
                (parsed.title if parsed else filename) or filename,
                f"{type(exc).__name__}: {exc}"[:2000],
                now,
                now,
            ),
        )
    except Exception:  # pragma: no cover - the original error is the one that matters
        logger.exception("could not record failed document row")


def _empty_pages(store: SeekDBStore, settings: Settings, doc_id: str) -> list[int]:
    rows = store.query(
        f"SELECT page_no FROM `{settings.pages_table}` WHERE doc_id = %s AND is_empty = 1 ORDER BY page_no",
        (doc_id,),
    )
    return [int(r["page_no"]) for r in rows]


def list_documents(store: SeekDBStore, settings: Settings | None = None) -> list[IngestedDocument]:
    settings = settings or get_settings()
    rows = store.query(f"SELECT * FROM `{settings.documents_table}` ORDER BY created_at DESC, doc_id")
    documents = [_row_to_document(row) for row in rows]
    for document in documents:
        document.empty_pages = _empty_pages(store, settings, document.doc_id)
    return documents


def get_document(
    store: SeekDBStore, doc_id: str, settings: Settings | None = None
) -> IngestedDocument:
    settings = settings or get_settings()
    rows = store.query(
        f"SELECT * FROM `{settings.documents_table}` WHERE doc_id = %s", (doc_id,)
    )
    if not rows:
        raise NotFoundError(f"document '{doc_id}' not found", detail={"doc_id": doc_id})
    document = _row_to_document(rows[0])
    document.empty_pages = _empty_pages(store, settings, doc_id)
    return document


def list_pages(
    store: SeekDBStore, doc_id: str, settings: Settings | None = None
) -> list[dict[str, Any]]:
    """Page identity rows without the full text (for the page navigator)."""
    settings = settings or get_settings()
    rows = store.query(
        f"""SELECT page_id, doc_id, page_no, char_count, is_empty
FROM `{settings.pages_table}` WHERE doc_id = %s ORDER BY page_no""",
        (doc_id,),
    )
    return [
        {
            "page_id": r["page_id"],
            "doc_id": r["doc_id"],
            "page_no": int(r["page_no"]),
            "char_count": int(r["char_count"]),
            "is_empty": bool(r["is_empty"]),
        }
        for r in rows
    ]


def get_page(
    store: SeekDBStore, doc_id: str, page_no: int, settings: Settings | None = None
) -> PageRecord:
    """Return the stored original text of one physical page. 404 if the page does not exist."""
    settings = settings or get_settings()
    doc_rows = store.query(
        f"SELECT filename, content_type FROM `{settings.documents_table}` WHERE doc_id = %s",
        (doc_id,),
    )
    if not doc_rows:
        raise NotFoundError(f"document '{doc_id}' not found", detail={"doc_id": doc_id})
    rows = store.query(
        f"""SELECT * FROM `{settings.pages_table}` WHERE doc_id = %s AND page_no = %s""",
        (doc_id, page_no),
    )
    if not rows:
        page_count = get_document(store, doc_id, settings).page_count
        raise NotFoundError(
            f"page {page_no} does not exist in document '{doc_id}' (it has {page_count} pages)",
            detail={"doc_id": doc_id, "requested_page": page_no, "page_count": page_count},
        )
    row = rows[0]
    return PageRecord(
        page_id=row["page_id"],
        doc_id=row["doc_id"],
        page_no=int(row["page_no"]),
        char_count=int(row["char_count"]),
        is_empty=bool(row["is_empty"]),
        content=row["content"] or "",
        filename=doc_rows[0]["filename"],
        content_type=doc_rows[0]["content_type"],
    )


def delete_document(store: SeekDBStore, doc_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    get_document(store, doc_id, settings)
    collection = store.chunks()
    collection.delete(where={"doc_id": {"$eq": doc_id}})
    with store.transaction() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"DELETE FROM `{settings.pages_table}` WHERE doc_id = %s", (doc_id,))
            pages = cursor.rowcount
            cursor.execute(f"DELETE FROM `{settings.documents_table}` WHERE doc_id = %s", (doc_id,))
    logger.info("document deleted", fields={"doc_id": doc_id, "pages_removed": pages})
    return {"doc_id": doc_id, "deleted": True, "pages_removed": pages}
