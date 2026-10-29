"""B1 benchmark: Chinese recall over PowerContext task memory, before vs after.

Measures four recall paths for every query in backend/tests/data/memory_queries_zh.json:

* ``exact_snapshot``  - full read + latest snapshot (the V1 fallback, ground truth)
* ``pc_search``       - PowerContext's own search_memory (fts5 unicode61)
* ``pc_prepare``      - PowerContext's prepare_context
* ``local``           - ResearchFlow's CJK-aware matcher over entries read from PowerContext

Writes logs/bench-memory-zh-<ts>.json and prints a comparison table. Nothing is mocked:
every path talks to the live PowerContext server.

Usage: python scripts/bench_memory_zh.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.db.seekdb import SeekDBStore  # noqa: E402
from app.memory import service as memory  # noqa: E402
from app.memory.client import PowerContextGateway  # noqa: E402
from app.memory.models import ResearchProgress  # noqa: E402

DATA = BACKEND_DIR / "tests" / "data" / "memory_queries_zh.json"


def _hit(texts: list[str], expected: list[str]) -> bool:
    return any(fragment in candidate for candidate in texts for fragment in expected)


async def main() -> int:
    settings = get_settings()
    store = SeekDBStore(settings)
    store.ensure_schema(embedding_dimension=settings.embedding_dimension)
    gateway = PowerContextGateway(settings)
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    seed = payload["project_seed"]
    queries = payload["queries"]

    project, bound = await memory.create_project(
        store, gateway, project_id=seed["project_id"], title=seed["title"],
        objective=seed["objective"], settings=settings,
    )
    assert bound, "PowerContext must be reachable for this benchmark"
    progress = ResearchProgress(
        project_id=seed["project_id"], title=seed["title"], objective=seed["objective"],
        completed_work=seed["completed_work"], decisions=seed["decisions"],
        key_evidence=[], open_questions=seed["open_questions"], next_steps=seed["next_steps"],
        confirmed_by="bench",
    )
    saved = await memory.save_progress(store, gateway, progress, settings)
    print(f"seeded project {project.project_id} scope={project.scope_id} written={saved.written}")

    from powercontext.http import PrepareContextRequest, SearchMemoryRequest

    rows = []
    async with gateway.session() as client:
        entries = await memory._read_entries(gateway, project.scope_id)
        snapshot = memory._latest_snapshot(entries)
        for item in queries:
            query = item["query"]
            expected = item["expected_contains"]
            negative = not expected
            row = {"id": item["id"], "category": item["category"], "query": query, "paths": {}}

            snapshot_texts = [json.dumps(snapshot, ensure_ascii=False)] if snapshot else []
            row["paths"]["exact_snapshot"] = {"hit": _hit(snapshot_texts, expected) if not negative else None}

            started = time.perf_counter()
            searched = await client.search_memory(
                SearchMemoryRequest(scope_id=project.scope_id, query=query, limit=5)
            )
            pc_texts = [hit.memory.text for hit in searched.hits]
            row["paths"]["pc_search"] = {
                "hits": len(pc_texts),
                "hit@1": _hit(pc_texts[:1], expected) if not negative else (len(pc_texts) == 0),
                "hit@5": _hit(pc_texts, expected) if not negative else (len(pc_texts) == 0),
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }

            started = time.perf_counter()
            prepared = await client.prepare_context(
                PrepareContextRequest(scope_id=project.scope_id, query=query, max_bytes=6000)
            )
            pc_prepare_text = prepared.content or ""
            row["paths"]["pc_prepare"] = {
                "status": str(prepared.status),
                "bytes": prepared.content_bytes,
                "hit": (expected[0] in pc_prepare_text) if not negative else (prepared.content_bytes == 0),
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }

            started = time.perf_counter()
            local = memory.local_memory_search(entries, query, top_k=5)
            local_texts = [hit["text"] for hit in local]
            row["paths"]["local"] = {
                "hits": len(local_texts),
                "hit@1": _hit(local_texts[:1], expected) if not negative else (len(local_texts) == 0),
                "hit@3": _hit(local_texts[:3], expected) if not negative else (len(local_texts) == 0),
                "top_kind": local[0]["kind"] if local else None,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }

            restored = await memory.restore_progress(store, gateway, seed["project_id"], query=query, settings=settings)
            row["paths"]["restore_effective"] = {
                "backend": restored.prepared_context.get("search_backend_used"),
                "effective_hits": len(restored.prepared_context.get("effective_hits") or []),
            }
            rows.append(row)
            print(
                f"{item['id']:16s} pc_search@5={row['paths']['pc_search']['hit@5']!s:5} "
                f"pc_prepare={row['paths']['pc_prepare']['hit']!s:5} "
                f"local@3={row['paths']['local']['hit@3']!s:5} "
                f"effective={row['paths']['restore_effective']['backend']}"
            )

    def rate(path: str, key: str) -> str:
        relevant = [r for r in rows if r["paths"][path].get(key) is not None]
        if not relevant:
            return "n/a"
        ok = sum(1 for r in relevant if r["paths"][path][key])
        return f"{ok}/{len(relevant)}"

    summary = {
        "pc_search_hit@5": rate("pc_search", "hit@5"),
        "pc_prepare_hit": rate("pc_prepare", "hit"),
        "local_hit@1": rate("local", "hit@1"),
        "local_hit@3": rate("local", "hit@3"),
    }
    print("\nsummary:", json.dumps(summary, ensure_ascii=False))

    out = PROJECT_ROOT / "logs" / f"bench-memory-zh-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "project": seed["project_id"],
             "scope_id": project.scope_id, "summary": summary, "rows": rows},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print("wrote", out.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
