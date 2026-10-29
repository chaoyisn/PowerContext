"""B1 regression tests: Chinese recall over PowerContext memory.

The dataset (backend/tests/data/memory_queries_zh.json) was authored for benchmarking and is
independent of the assertions used while developing the matcher.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.memory import service as memory
from app.memory.models import ResearchProgress

from .conftest import requires_powercontext, requires_seekdb

pytestmark = [requires_seekdb, requires_powercontext]

DATA = Path(__file__).parent / "data" / "memory_queries_zh.json"
PAYLOAD = json.loads(DATA.read_text(encoding="utf-8"))
SEED = PAYLOAD["project_seed"]
QUERIES = PAYLOAD["queries"]
PROJECT_ID = f"t-zh-{SEED['project_id']}"


@pytest.fixture
async def seeded(store, gateway, settings):
    project, bound = await memory.create_project(
        store, gateway, project_id=PROJECT_ID, title=SEED["title"],
        objective=SEED["objective"], settings=settings,
    )
    assert bound
    await memory.save_progress(
        store,
        gateway,
        ResearchProgress(
            project_id=PROJECT_ID, title=SEED["title"], objective=SEED["objective"],
            completed_work=SEED["completed_work"], decisions=SEED["decisions"],
            open_questions=SEED["open_questions"], next_steps=SEED["next_steps"],
            confirmed_by="pytest-zh",
        ),
        settings,
    )
    entries = await memory._read_entries(gateway, project.scope_id)
    return project, entries


def _recalls(hits, fragments) -> bool:
    return any(fragment in hit["text"] for hit in hits for fragment in fragments)


@pytest.mark.parametrize("item", QUERIES, ids=[q["id"] for q in QUERIES])
def test_local_cjk_recall_matches_the_benchmark_expectation(seeded, item):
    _, entries = seeded
    hits = memory.local_memory_search(entries, item["query"], top_k=3)
    if item["expected_contains"]:
        assert _recalls(hits, item["expected_contains"]), (
            f"{item['id']}: expected one of {item['expected_contains']} in top 3, got "
            f"{[h['text'][:40] for h in hits]}"
        )
    else:
        assert hits == [], f"{item['id']}: unrelated query must not recall memory, got {hits}"


@pytest.mark.parametrize("item", [q for q in QUERIES if q["expected_contains"]],
                         ids=[q["id"] for q in QUERIES if q["expected_contains"]])
def test_kind_hint_points_at_the_right_memory_kind(seeded, item):
    _, entries = seeded
    hits = memory.local_memory_search(entries, item["query"], top_k=3)
    assert hits, item["id"]
    expected_kinds = set(item["expected_kinds"])
    assert hits[0]["kind"] in expected_kinds or any(h["kind"] in expected_kinds for h in hits), (
        f"{item['id']}: recalled kinds {[h['kind'] for h in hits]} vs expected {sorted(expected_kinds)}"
    )


async def test_restore_exposes_which_backend_answered(store, gateway, settings, seeded):
    restored = await memory.restore_progress(
        store, gateway, PROJECT_ID, query="上次定的下一步计划是什么", settings=settings
    )
    prepared = restored.prepared_context
    assert prepared["search_backend_used"] in {"powercontext", "researchflow-local-cjk", "none"}
    assert prepared["effective_hits"], "a meta question must still surface the next steps"
    assert all(hit["source"] == "memory" for hit in prepared["effective_hits"])
    kinds = {hit["kind"] for hit in prepared["effective_hits"]}
    assert "next_step" in kinds


async def test_powercontext_own_search_is_reported_not_hidden(store, gateway, settings, seeded):
    """The weakness of PowerContext's unicode61 FTS must stay visible in the payload."""
    restored = await memory.restore_progress(
        store, gateway, PROJECT_ID, query="还有哪些问题没有解决", settings=settings
    )
    prepared = restored.prepared_context
    assert "unicode61" in prepared["note"]
    assert prepared["local_hits"], "the CJK fallback must answer this meta question"
    assert prepared["search_backend_used"] in {"powercontext", "researchflow-local-cjk"}
