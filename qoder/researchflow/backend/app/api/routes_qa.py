"""Evidence-grounded QA endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..agent import service as agent
from .deps import get_app_state
from .schemas import AskRequest

router = APIRouter(prefix="/api/qa", tags=["qa"])


@router.post("/ask")
async def ask(request: AskRequest, state=Depends(get_app_state)) -> dict[str, Any]:
    result = await agent.answer_question(
        state.store,
        state.embeddings,
        state.llm,
        request.question,
        mode=request.mode,
        top_k=request.top_k,
        project_id=request.project_id,
        filters=request.filters(),
        gateway=state.gateway,
        settings=state.settings,
    )
    payload = result.to_dict()
    payload["unused_evidence"] = [c for c in agent.unused_evidence(result)]
    return payload
