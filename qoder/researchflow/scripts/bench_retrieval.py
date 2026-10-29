"""B2 benchmark: bilingual retrieval quality per embedding provider and mode.

For every provider the script re-ingests the demo corpus under its own seekdb prefix, then
measures Recall@K, MRR, top-1 page accuracy, mean latency and the false-positive rate on
unanswerable queries, for each of vector / fulltext / hybrid. All numbers come from live
seekdb queries; nothing is simulated.

Usage:
    python scripts/bench_retrieval.py
    python scripts/bench_retrieval.py --providers hashing,minilm,multilingual --top-k 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DEMO_DIR = PROJECT_ROOT / "demo"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings, get_settings  # noqa: E402
from app.db.seekdb import SeekDBStore  # noqa: E402
from app.ingestion import service as ingestion  # noqa: E402
from app.retrieval import service as retrieval  # noqa: E402
from app.retrieval.embeddings import build_embedding_backend  # noqa: E402

DATA = BACKEND_DIR / "tests" / "data" / "bilingual_queries.json"
UPLOADS = ["seekdb_hybrid_retrieval_notes.pdf", "research_plan.md", "experiment_log.txt"]
MODES = ("vector", "fulltext", "hybrid")


def _reset(store: SeekDBStore, settings: Settings) -> None:
    client = store.pyseekdb_client()
    if client.has_collection(settings.chunks_collection):
        client.delete_collection(settings.chunks_collection)
    for table in (
        settings.documents_table,
        settings.pages_table,
        settings.projects_table,
        settings.meta_table,
    ):
        store.execute(f"DROP TABLE IF EXISTS `{table}`")
    store._schema_ready = False


def _metrics(hits, expected, top_k) -> dict:
    pairs = [(h.filename, h.page_no) for h in hits]
    want = [tuple(e) for e in expected]
    ranks = [pairs.index(w) + 1 for w in want if w in pairs]
    first = min(ranks) if ranks else 0
    return {
        "recall@1": float(any(r <= 1 for r in ranks)) if want else None,
        "recall@3": float(any(r <= 3 for r in ranks)) if want else None,
        "recall@5": float(any(r <= 5 for r in ranks)) if want else None,
        "mrr": (1.0 / first) if first else 0.0,
        "page_acc@1": bool(want and pairs and pairs[0] in want),
        "top1": pairs[0] if pairs else None,
    }


def run_provider(provider: str, queries, top_k: int) -> dict:
    settings = Settings(
        **{
            **get_settings().model_dump(),
            "seekdb_prefix": f"rfb_{provider}_",
            "embedding_provider": provider,
        }
    )
    store = SeekDBStore(settings)
    backend = build_embedding_backend(settings)
    print(f"\n=== provider={provider} (actual={backend.provider}, note={backend.note}) ===")
    _reset(store, settings)
    store.ensure_schema(embedding_dimension=backend.dimension)
    for name in UPLOADS:
        ingestion.ingest_bytes(store, backend, (DEMO_DIR / name).read_bytes(), name, settings=settings)

    results: dict[str, dict] = {}
    for mode in MODES:
        per_query = []
        latencies = []
        false_positives = 0
        negatives = 0
        for item in queries:
            expected = [list(e) for e in item["expected"]]
            started = time.perf_counter()
            res = retrieval.search(
                store,
                backend,
                item["query"],
                mode=mode,
                top_k=top_k,
                filters=item.get("filters"),
                apply_gate=True,
                settings=settings,
            )
            latencies.append((time.perf_counter() - started) * 1000)
            if not expected:
                negatives += 1
                if res.citations:
                    false_positives += 1
                per_query.append({"id": item["id"], "negative": True, "citations": len(res.citations)})
                continue
            m = _metrics(res.hits, expected, top_k)
            per_query.append({"id": item["id"], "negative": False, **m})
        positives = [q for q in per_query if not q["negative"]]
        results[mode] = {
            "recall@1": round(sum(q["recall@1"] for q in positives) / len(positives), 3),
            "recall@3": round(sum(q["recall@3"] for q in positives) / len(positives), 3),
            "recall@5": round(sum(q["recall@5"] for q in positives) / len(positives), 3),
            "mrr": round(sum(q["mrr"] for q in positives) / len(positives), 3),
            "page_acc@1": round(sum(q["page_acc@1"] for q in positives) / len(positives), 3),
            "latency_ms_mean": round(sum(latencies) / len(latencies), 1),
            "negative_false_positives": f"{false_positives}/{negatives}",
            "per_query": per_query,
        }
        r = results[mode]
        print(
            f"  {mode:8s} R@1={r['recall@1']:.2f} R@3={r['recall@3']:.2f} R@5={r['recall@5']:.2f} "
            f"MRR={r['mrr']:.2f} pageAcc@1={r['page_acc@1']:.2f} "
            f"lat={r['latency_ms_mean']:.0f}ms fp={r['negative_false_positives']}"
        )
    _reset(store, settings)
    store.close_thread_resources()
    return {"provider": provider, "actual_provider": backend.provider, "note": backend.note, "modes": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", default="hashing,minilm,multilingual")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    queries = json.loads(DATA.read_text(encoding="utf-8"))["queries"]
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dataset": str(DATA.relative_to(PROJECT_ROOT)),
        "top_k": args.top_k,
        "providers": {},
    }
    for provider in [p.strip() for p in args.providers.split(",") if p.strip()]:
        report["providers"][provider] = run_provider(provider, queries, args.top_k)

    out = PROJECT_ROOT / "logs" / f"bench-retrieval-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out.relative_to(PROJECT_ROOT)}")

    print("\n| provider | mode | R@1 | R@3 | R@5 | MRR | pageAcc@1 | latency ms | 负例误报 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for provider, body in report["providers"].items():
        for mode, r in body["modes"].items():
            print(
                f"| {provider} | {mode} | {r['recall@1']:.2f} | {r['recall@3']:.2f} | {r['recall@5']:.2f} "
                f"| {r['mrr']:.2f} | {r['page_acc@1']:.2f} | {r['latency_ms_mean']:.0f} | {r['negative_false_positives']} |"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
