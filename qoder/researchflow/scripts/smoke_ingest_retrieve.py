"""End-to-end smoke test of the ingestion + retrieval closed loop against live seekdb.

Usage: python scripts/smoke_ingest_retrieve.py [--provider hashing|minilm]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db.seekdb import SeekDBStore  # noqa: E402
from app.ingestion import service as ingestion  # noqa: E402
from app.ingestion.parsers import parse_pdf  # noqa: E402
from app.retrieval import service as retrieval  # noqa: E402
from app.retrieval.embeddings import build_embedding_backend  # noqa: E402

DEMO = PROJECT_ROOT / "demo"
UPLOADS = [
    "seekdb_hybrid_retrieval_notes.pdf",
    "research_plan.md",
    "experiment_log.txt",
]
QUERIES = [
    "RRF rank constant 60 的融合分数是多少",
    "which full text analyzer segments Chinese correctly",
    "HNSW cosine distance measured for the hybrid retrieval query",
    "空白页在第几页",
    "这篇文档里有没有关于量子纠缠实验的结果",
]


def main() -> int:
    settings = get_settings()
    store = SeekDBStore(settings)
    backend = build_embedding_backend(settings)
    print(f"embedding provider: {backend.provider} dim={backend.dimension} note={backend.note}")
    print("schema:", store.ensure_schema(embedding_dimension=backend.dimension))

    pdf_bytes = (DEMO / UPLOADS[0]).read_bytes()
    parsed = parse_pdf(pdf_bytes, UPLOADS[0])
    print(f"\nPDF physical pages: {parsed.page_count}, empty pages: {parsed.empty_pages}")
    for page in parsed.pages:
        first = next((ln for ln in page.text.splitlines() if ln.strip()), "<blank>")
        print(f"  page {page.page_no}: chars={len(page.text):5d} first_line={first[:60]!r}")

    print("\n--- ingest ---")
    for name in UPLOADS:
        data = (DEMO / name).read_bytes()
        result = ingestion.ingest_bytes(store, backend, data, name, settings=settings)
        print(
            f"  {name}: doc_id={result.doc_id[:12]}… pages={result.page_count} "
            f"chunks={result.chunk_count} empty_pages={result.empty_pages} dedup={result.deduplicated}"
        )
        again = ingestion.ingest_bytes(store, backend, data, name, settings=settings)
        assert again.deduplicated, f"re-upload of {name} was not deduplicated"
        assert again.doc_id == result.doc_id
    print("  re-upload deduplication: OK")

    print("\n--- seekdb row counts (read back from the database) ---")
    print("  health:", json.dumps(store.health(), ensure_ascii=False))

    pdf_doc = next(
        d for d in ingestion.list_documents(store, settings) if d.content_type == "pdf"
    )
    pdf_pages = ingestion.list_pages(store, pdf_doc.doc_id, settings)
    print(f"  pdf {pdf_doc.filename}: page rows={len(pdf_pages)} page_nos={[p['page_no'] for p in pdf_pages]}")
    print(f"  page 4 is_empty={[p['is_empty'] for p in pdf_pages if p['page_no'] == 4]}")

    print("\n--- retrieval ---")
    for query in QUERIES:
        for mode in ("vector", "fulltext", "hybrid"):
            res = retrieval.search(store, backend, query, mode=mode, top_k=3, settings=settings)
            top = res.hits[0] if res.hits else None
            desc = (
                f"{top.filename} p{top.page_no} score={top.score} cov={top.coverage} "
                f"rel={top.relevance} gate={top.gate_passed} :: {top.text[:40]!r}"
                if top
                else "NO HITS"
            )
            print(f"  [{mode:8s}] {query[:30]!r} -> {desc}")
            gated = retrieval.search(
                store, backend, query, mode=mode, top_k=3, apply_gate=True, settings=settings
            )
            print(
                f"           apply_gate=True -> kept={len(gated.hits)} "
                f"dropped={gated.dropped_by_gate} citations={len(gated.citations)}"
            )
        print()

    print("--- mode comparison (single call) ---")
    cmp = retrieval.compare_modes(store, backend, QUERIES[1], top_k=3, settings=settings)
    print("  ids:", json.dumps(cmp["ids"], ensure_ascii=False))
    print("  overlap:", json.dumps(cmp["overlap"], ensure_ascii=False))

    print("\n--- evidence lookup ---")
    page = ingestion.get_page(store, pdf_doc.doc_id, 5, settings)
    print(f"  page 5 chars={page.char_count} head={page.content[:70]!r}")
    try:
        ingestion.get_page(store, pdf_doc.doc_id, 99, settings)
        print("  ERROR: page 99 should not exist")
        return 1
    except Exception as exc:
        print(f"  page 99 correctly rejected: {type(exc).__name__}: {exc}")

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
