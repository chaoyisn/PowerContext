"""Smoke test the PowerContext memory loop: save -> new session -> restore.

Usage: python scripts/smoke_memory.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db.seekdb import SeekDBStore  # noqa: E402
from app.memory import service as memory  # noqa: E402
from app.memory.client import PowerContextGateway  # noqa: E402
from app.memory.models import EvidencePointer, ResearchProgress  # noqa: E402

PROJECT_ID = "smoke-memory-demo"


async def main() -> int:
    settings = get_settings()
    store = SeekDBStore(settings)
    store.ensure_schema(embedding_dimension=settings.embedding_dimension)
    gateway = PowerContextGateway(settings)

    print("PowerContext health:", json.dumps(await gateway.health(), ensure_ascii=False))

    project, bound = await memory.create_project(
        store, gateway, project_id=PROJECT_ID,
        title="ResearchFlow 记忆闭环冒烟", objective="验证跨会话任务记忆恢复",
    )
    print(f"project: {project.project_id} scope_id={project.scope_id} memory_bound={bound}")

    progress = ResearchProgress(
        project_id=PROJECT_ID,
        title=project.title,
        objective="验证跨会话任务记忆恢复",
        completed_work=["完成 seekdb 混合检索实测", "完成 PowerContext scope 幂等创建实测"],
        decisions=["D1: 文档主键使用文件内容 SHA-256", "D2: 页号使用 PDF 物理页号，空页保留身份行"],
        key_evidence=[
            EvidencePointer(
                doc_id="d52ced86d6516a03", filename="seekdb_hybrid_retrieval_notes.pdf",
                page_no=5, chunk_id="d52ced86d6516a03:p0005:c000",
                quote="A row placed first in both legs scores 1/61 + 1/61 = 0.0328.",
            )
        ],
        open_questions=["Q1: 是否需要切换到多语 embedding 模型"],
        next_steps=["跑通 T1-T8 全部验收用例", "输出 Qoder Sites 部署可行性分析"],
        confirmed_by="user",
    )
    saved = await memory.save_progress(store, gateway, progress, settings)
    print("save #1:", json.dumps(saved.to_dict(), ensure_ascii=False))

    saved_again = await memory.save_progress(store, gateway, progress, settings)
    print(
        f"save #2 (identical payload): written={saved_again.written} "
        f"skipped_duplicates={saved_again.skipped_duplicates} seq={saved_again.seq} "
        f"snapshot_unchanged={saved_again.snapshot_unchanged}"
    )
    assert saved_again.written == 0, "duplicate save wrote new bullets; dedupe is broken"
    assert saved_again.snapshot_unchanged, "identical save created a second snapshot"

    # --- brand new session: fresh gateway, fresh client, same project_id ---
    fresh_gateway = PowerContextGateway(settings)
    restored = await memory.restore_progress(store, fresh_gateway, PROJECT_ID, settings=settings)
    print("\n--- restored in a new session ---")
    print("memory_available:", restored.memory_available, "entries:", len(restored.entries))
    print("snapshot seq:", (restored.snapshot or {}).get("seq"),
          "updated_at:", (restored.snapshot or {}).get("updated_at"))
    print("grouped counts:", {k: len(v) for k, v in restored.grouped.items() if v})
    print("prepared_context:", restored.prepared_context["status"],
          restored.prepared_context["content_bytes"], "bytes;",
          "search_mode:", restored.prepared_context["search_mode"],
          "hits:", len(restored.prepared_context["search_hits"]))
    print("\nresume brief:\n" + restored.resume_brief)

    snap = restored.snapshot or {}
    checks = {
        "objective": snap.get("objective") == "验证跨会话任务记忆恢复",
        "decisions": snap.get("decisions") == progress.decisions,
        "next_steps": snap.get("next_steps") == progress.next_steps,
        "open_questions": snap.get("open_questions") == progress.open_questions,
        "evidence_page": (snap.get("key_evidence") or [{}])[0].get("page_no") == 5,
    }
    print("\nfield-level restore checks:", json.dumps(checks, ensure_ascii=False))
    if not all(checks.values()):
        print("RESTORE MISMATCH")
        return 1

    history = await memory.list_history(store, fresh_gateway, PROJECT_ID, settings)
    print("history:", history["entry_count"], "entries,", history["snapshot_count"], "snapshots")
    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
