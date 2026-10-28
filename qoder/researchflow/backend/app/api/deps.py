"""Shared application state and FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from ..agent.llm import LLMGateway
from ..config import Settings, get_settings
from ..db.seekdb import SeekDBStore
from ..memory.client import PowerContextGateway
from ..retrieval.embeddings import EmbeddingBackend, build_embedding_backend


@dataclass
class AppState:
    settings: Settings
    store: SeekDBStore
    embeddings: EmbeddingBackend
    gateway: PowerContextGateway
    llm: LLMGateway
    schema_result: dict[str, Any]


def build_state(settings: Settings | None = None) -> AppState:
    settings = settings or get_settings()
    store = SeekDBStore(settings)
    embeddings = build_embedding_backend(settings)
    schema_result = store.ensure_schema(embedding_dimension=embeddings.dimension)
    return AppState(
        settings=settings,
        store=store,
        embeddings=embeddings,
        gateway=PowerContextGateway(settings),
        llm=LLMGateway(settings),
        schema_result=schema_result,
    )


def get_app_state(request: Request) -> AppState:
    return request.app.state.rf


def get_store(request: Request) -> SeekDBStore:
    return get_app_state(request).store


def get_embeddings(request: Request) -> EmbeddingBackend:
    return get_app_state(request).embeddings


def get_gateway(request: Request) -> PowerContextGateway:
    return get_app_state(request).gateway


def get_llm(request: Request) -> LLMGateway:
    return get_app_state(request).llm


def get_settings_dep(request: Request) -> Settings:
    return get_app_state(request).settings
