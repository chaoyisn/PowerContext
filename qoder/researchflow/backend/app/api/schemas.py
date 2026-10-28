"""Request/response schemas for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..memory.models import EvidencePointer


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["vector", "fulltext", "hybrid"] = "hybrid"
    top_k: int = Field(default=8, ge=1, le=50)
    apply_gate: bool = False
    doc_id: str | None = None
    content_type: Literal["pdf", "markdown", "text"] | None = None
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)

    def filters(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in (
                ("doc_id", self.doc_id),
                ("content_type", self.content_type),
                ("page_from", self.page_from),
                ("page_to", self.page_to),
            )
            if value is not None
        }


class CompareRequest(SearchRequest):
    mode: Literal["vector", "fulltext", "hybrid"] = "hybrid"  # ignored; all three run


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    mode: Literal["vector", "fulltext", "hybrid"] = "hybrid"
    top_k: int = Field(default=8, ge=1, le=50)
    project_id: str | None = None
    doc_id: str | None = None
    content_type: Literal["pdf", "markdown", "text"] | None = None
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)

    def filters(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in (
                ("doc_id", self.doc_id),
                ("content_type", self.content_type),
                ("page_from", self.page_from),
                ("page_to", self.page_to),
            )
            if value is not None
        }


class ProjectCreateRequest(BaseModel):
    project_id: str = Field(default="", max_length=64)
    title: str = Field(min_length=1, max_length=256)
    objective: str = Field(default="", max_length=2000)


class EvidencePointerModel(BaseModel):
    doc_id: str = ""
    filename: str = ""
    page_no: int = Field(default=0, ge=0)
    chunk_id: str = ""
    quote: str = Field(default="", max_length=600)

    def to_domain(self) -> EvidencePointer:
        return EvidencePointer(
            doc_id=self.doc_id,
            filename=self.filename,
            page_no=self.page_no,
            chunk_id=self.chunk_id,
            quote=self.quote,
        )


class SaveProgressRequest(BaseModel):
    objective: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=256)
    completed_work: list[str] = Field(default_factory=list, max_length=50)
    decisions: list[str] = Field(default_factory=list, max_length=50)
    key_evidence: list[EvidencePointerModel] = Field(default_factory=list, max_length=30)
    open_questions: list[str] = Field(default_factory=list, max_length=50)
    next_steps: list[str] = Field(default_factory=list, max_length=50)
    note: str = Field(default="", max_length=1000)
    confirmed_by: str = Field(default="user", max_length=64)
