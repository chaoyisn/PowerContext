"""Integration tests against the live PowerContext server: acceptance cases T4, T5, T7."""

from __future__ import annotations

import uuid

import pytest

from app.config import Settings
from app.memory import service as memory
from app.memory.client import PowerContextGateway
from app.memory.models import EvidencePointer, ResearchProgress
from app.retrieval import service as retrieval

from .conftest import PDF_NAME, requires_powercontext, requires_seekdb

pytestmark = [requires_seekdb, requires_powercontext]

PROJECT_ID = "t-memory-demo"
DECISIONS = [
    "D1: 文档主键使用文件内容 SHA-256，重复上传不产生新记录",
    "D2: 页号使用 PDF 物理页号，从 1 开始，空页保留身份行",
]
NEXT_STEPS = ["跑通 T1-T8 全部验收用例", "输出 Qoder Sites 部署可行性分析"]


def _progress(project_id: str = PROJECT_ID) -> ResearchProgress:
    return ResearchProgress(
        project_id=project_id,
        title="ResearchFlow 记忆闭环测试项目",
        objective="验证 PowerContext 真实写入与跨会话恢复",
        completed_work=["完成 seekdb 混合检索实测"],
        decisions=DECISIONS,
        key_evidence=[
            EvidencePointer(
                doc_id="d" * 64,
                filename=PDF_NAME,
                page_no=5,
                chunk_id=f"{'d' * 16}:p0005:c000",
                quote="A row placed first in both legs scores 1/61 + 1/61 = 0.0328.",
            )
        ],
        open_questions=["Q1: 是否需要切换到多语 embedding 模型"],
        next_steps=NEXT_STEPS,
        confirmed_by="pytest",
    )


@pytest.fixture
async def project(store, gateway, settings):
    created, bound = await memory.create_project(
        store,
        gateway,
        project_id=PROJECT_ID,
        title="ResearchFlow 记忆闭环测试项目",
        objective="验证 PowerContext 真实写入与跨会话恢复",
        settings=settings,
    )
    assert bound is True, "PowerContext scope binding must succeed for these tests"
    assert created.scope_id, "a real scope_id must be persisted"
    return created


# --------------------------------------------------------------------------- T4


async def test_t4_decision_and_next_steps_are_really_written_to_powercontext(
    store, gateway, settings, project
):
    saved = await memory.save_progress(store, gateway, _progress(), settings)
    assert saved.scope_id == project.scope_id
    assert saved.written >= 0
    assert saved.snapshot_artifact_id, "PowerContext must return a real artifact id"
    assert saved.snapshot_revision >= 1

    # Read back through PowerContext's own API, not through our service layer.
    from powercontext.http import ListMemoryEntriesRequest

    async with gateway.session() as client:
        page = await client.list_memory_entries(
            ListMemoryEntriesRequest(scope_id=project.scope_id, limit=100)
        )
    texts = [record.text for record in page.entries]
    kinds = {record.kind for record in page.entries}
    assert len(page.entries) >= 8, "one entry per bullet plus the snapshot"
    assert "rf_decision" in kinds and "rf_next_step" in kinds and "rf_progress_snapshot" in kinds

    for decision in DECISIONS:
        assert any(decision in text for text in texts), f"decision not persisted: {decision}"
    for step in NEXT_STEPS:
        assert any(step in text for text in texts), f"next_step not persisted: {step}"

    # Every stored memory record is a real PowerContext artifact reference.
    for record in page.entries:
        assert record.artifact.family == "atomic-memory"
        assert record.artifact.artifact_id.startswith("art_")
        assert record.artifact.revision >= 1


async def test_t4_repeated_save_does_not_duplicate(store, gateway, settings, project):
    first = await memory.save_progress(store, gateway, _progress(), settings)
    second = await memory.save_progress(store, gateway, _progress(), settings)
    assert second.written == 0, "identical bullets must not be written twice"
    assert second.skipped_duplicates >= len(DECISIONS) + len(NEXT_STEPS)
    assert second.snapshot_unchanged is True, "identical content must not create a new snapshot"
    assert second.snapshot_artifact_id == first.snapshot_artifact_id
    assert second.seq == first.seq, "a no-op save must not make the sequence look like it advanced"


async def test_changed_progress_creates_a_new_snapshot(store, gateway, settings, project):
    changed = _progress()
    # PowerContext memory outlives the test process, so the new bullet has to be unique
    # per run - otherwise dedupe would (correctly) skip it and the test would be vacuous.
    unique_step = f"补一条本次运行独有的下一步 {uuid.uuid4().hex[:8]}"
    changed.next_steps = [*NEXT_STEPS, unique_step]
    result = await memory.save_progress(store, gateway, changed, settings)
    assert result.written == 1, "only the genuinely new bullet should be written"
    assert result.written_kinds == ["next_step"]
    assert result.snapshot_unchanged is False
    assert result.snapshot_artifact_id

    restored = await memory.restore_progress(store, gateway, PROJECT_ID, settings=settings)
    assert restored.snapshot["next_steps"] == changed.next_steps
    assert unique_step in restored.resume_brief


async def test_project_registry_lives_in_seekdb(store, settings, project):
    rows = store.query(
        f"SELECT project_id, title, powercontext_scope_id FROM `{settings.projects_table}` "
        "WHERE project_id = %s",
        (PROJECT_ID,),
    )
    assert len(rows) == 1
    assert rows[0]["powercontext_scope_id"] == project.scope_id
    listed = {p.project_id for p in memory.list_projects(store, settings)}
    assert PROJECT_ID in listed


# --------------------------------------------------------------------------- T5


async def test_t5_a_brand_new_session_restores_decisions_and_next_steps(store, settings):
    """A fresh gateway means a fresh HTTP client and a fresh connection pool."""
    fresh = PowerContextGateway(settings)
    restored = await memory.restore_progress(store, fresh, PROJECT_ID, settings=settings)

    assert restored.memory_available is True
    assert restored.scope_id, "the scope must be resolvable from project_id alone"
    snapshot = restored.snapshot
    assert snapshot is not None, "the latest snapshot must be recoverable in a new session"
    assert snapshot["decisions"] == DECISIONS
    assert set(NEXT_STEPS) <= set(snapshot["next_steps"])
    assert snapshot["objective"] == "验证 PowerContext 真实写入与跨会话恢复"
    assert snapshot["key_evidence"][0]["page_no"] == 5
    assert snapshot["confirmed_by"] == "pytest"
    assert snapshot["updated_at"]

    brief = restored.resume_brief
    for decision in DECISIONS:
        assert decision in brief
    for step in NEXT_STEPS:
        assert step in brief
    assert "上次做到了哪里" in brief and "接下来该做什么" in brief
    assert "不是文献原文证据" in brief, "memory must be labelled as memory"

    grouped = restored.grouped
    assert grouped["decision"], "decisions must be grouped for the UI"
    assert grouped["next_step"]
    for entries in grouped.values():
        for entry in entries:
            assert entry["source"] == "memory", "memory entries must never look like document evidence"


async def test_t5_restore_survives_a_second_new_session_and_reports_history(store, settings):
    another = PowerContextGateway(settings)
    restored = await memory.restore_progress(store, another, PROJECT_ID, settings=settings)
    history = await memory.list_history(store, another, PROJECT_ID, settings)

    assert history["entry_count"] == len(restored.entries)
    assert history["snapshot_count"] >= 2, "two different snapshots were saved above"
    assert history["source"] == "memory"
    assert restored.prepared_context["source"] == "memory"
    assert "recall_query" in restored.prepared_context


async def test_memory_search_is_labelled_and_reports_the_cjk_limitation(store, settings):
    gateway = PowerContextGateway(settings)
    restored = await memory.restore_progress(
        store, gateway, PROJECT_ID, query="seekdb 混合检索实测", settings=settings
    )
    prepared = restored.prepared_context
    assert prepared["search_mode"] in {"text", "fts", "vector", "hybrid"}
    assert prepared["recall_query"], "the actual query sent to PowerContext must be reported"
    assert "unicode61" in prepared["note"], "the CJK FTS limitation must be disclosed, not hidden"


# --------------------------------------------------------------------------- T7


def _dead_gateway(settings) -> PowerContextGateway:
    broken = Settings(
        **{
            **settings.model_dump(),
            "powercontext_url": "http://127.0.0.1:17999",
            "powercontext_timeout": 3.0,
        }
    )
    return PowerContextGateway(broken)


async def test_t7_with_powercontext_down_memory_reports_a_real_failure(settings, store):
    dead = _dead_gateway(settings)
    health = await dead.health()
    assert health["available"] is False
    assert health["error"], "the outage reason must be reported"

    restored = await memory.restore_progress(store, dead, PROJECT_ID, settings=settings)
    assert restored.memory_available is False
    assert restored.error
    assert restored.snapshot is None
    assert restored.entries == []
    assert "PowerContext 当前不可用" in restored.resume_brief
    assert "seekdb" in restored.resume_brief, "the brief must state that retrieval still works"


async def test_t7_retrieval_and_qa_still_work_while_powercontext_is_down(
    store, embeddings, settings, ingested, project
):
    """This is the comparison that proves PowerContext has an independent role."""
    dead = _dead_gateway(settings)
    assert (await dead.health())["available"] is False

    result = retrieval.search(
        store,
        embeddings,
        "which full text analyzer segments Chinese correctly",
        mode="hybrid",
        top_k=3,
        apply_gate=True,
        settings=settings,
    )
    assert result.citations, "document evidence must not depend on PowerContext"
    assert result.citations[0]["source"] == "document"
    assert result.citations[0]["page_no"] == 3

    alive = PowerContextGateway(settings)
    assert (await alive.health())["available"] is True
    restored = await memory.restore_progress(store, alive, PROJECT_ID, settings=settings)
    assert restored.memory_available is True and restored.snapshot is not None


async def test_t7_project_creation_degrades_without_powercontext(store, settings):
    dead = _dead_gateway(settings)
    project, bound = await memory.create_project(
        store, dead, project_id="t-memory-offline", title="离线创建的项目", settings=settings
    )
    assert bound is False
    assert project.scope_id is None
    # The registry row still exists in seekdb, so the project is not lost.
    assert project.project_id in {p.project_id for p in memory.list_projects(store, settings)}
    store.execute(f"DELETE FROM `{settings.projects_table}` WHERE project_id = %s", ("t-memory-offline",))


async def test_scope_binding_is_idempotent_across_calls(store, gateway, settings, project):
    first = await memory.ensure_scope(store, gateway, project, settings)
    second = await memory.ensure_scope(
        store, gateway, memory.get_project(store, PROJECT_ID, settings), settings
    )
    assert first == second == project.scope_id
