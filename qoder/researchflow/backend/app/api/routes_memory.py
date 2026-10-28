"""Project registry (seekdb) and research task memory (PowerContext)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..memory import service as memory
from ..memory.models import ResearchProgress, utc_now_iso
from .deps import get_app_state
from .schemas import ProjectCreateRequest, SaveProgressRequest

router = APIRouter(prefix="/api", tags=["memory"])


@router.post("/projects")
async def create_project(request: ProjectCreateRequest, state=Depends(get_app_state)) -> dict[str, Any]:
    project, memory_bound = await memory.create_project(
        state.store,
        state.gateway,
        project_id=request.project_id,
        title=request.title,
        objective=request.objective,
        settings=state.settings,
    )
    return {**project.to_dict(), "memory_bound": memory_bound}


@router.get("/projects")
def list_projects(state=Depends(get_app_state)) -> dict[str, Any]:
    projects = memory.list_projects(state.store, state.settings)
    return {"count": len(projects), "projects": [p.to_dict() for p in projects]}


@router.get("/projects/{project_id}")
async def get_project(project_id: str, state=Depends(get_app_state)) -> dict[str, Any]:
    project = memory.get_project(state.store, project_id, state.settings)
    restored = await memory.restore_progress(
        state.store, state.gateway, project_id, settings=state.settings
    )
    return {
        **project.to_dict(),
        "memory_available": restored.memory_available,
        "snapshot": restored.snapshot,
        "resume_brief": restored.resume_brief,
        "entry_count": len(restored.entries),
        "memory_error": restored.error,
    }


@router.post("/projects/{project_id}/memory/save")
async def save_progress(
    project_id: str, request: SaveProgressRequest, state=Depends(get_app_state)
) -> dict[str, Any]:
    """Explicit user-triggered save. Model output is never written here automatically."""
    project = memory.get_project(store=state.store, project_id=project_id, settings=state.settings)
    progress = ResearchProgress(
        project_id=project.project_id,
        title=request.title or project.title,
        objective=request.objective or project.objective,
        completed_work=request.completed_work,
        decisions=request.decisions,
        key_evidence=[item.to_domain() for item in request.key_evidence],
        open_questions=request.open_questions,
        next_steps=request.next_steps,
        note=request.note,
        confirmed_by=request.confirmed_by,
        updated_at=utc_now_iso(),
    )
    result = await memory.save_progress(state.store, state.gateway, progress, state.settings)
    return result.to_dict()


@router.get("/projects/{project_id}/memory/restore")
async def restore_progress(project_id: str, query: str = "", state=Depends(get_app_state)) -> dict[str, Any]:
    restored = await memory.restore_progress(
        state.store, state.gateway, project_id, query=query, settings=state.settings
    )
    return restored.to_dict()


@router.get("/projects/{project_id}/memory/history")
async def memory_history(project_id: str, state=Depends(get_app_state)) -> dict[str, Any]:
    return await memory.list_history(state.store, state.gateway, project_id, state.settings)


@router.get("/memory/status")
async def memory_status(state=Depends(get_app_state)) -> dict[str, Any]:
    """Used by acceptance test T7 to show PowerContext's real contribution."""
    health = await state.gateway.health()
    return {
        "backend": "PowerContext",
        "role": "long-term research task memory",
        "url": state.gateway.url,
        **health,
        "note": (
            "文献证据来自 seekdb，任务记忆来自 PowerContext，两者在 UI 中分别标记，"
            "历史记忆永远不会被当作原文证据。"
        ),
    }
