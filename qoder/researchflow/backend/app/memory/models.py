"""Domain models for research task memory.

PowerContext's ``AtomicMemoryRecord`` carries no timestamp and its list order is not
insertion order (both measured, see QODER_LOG.md 2026-10-29). ResearchFlow therefore
embeds its own monotonic ``seq`` and ISO ``updated_at`` in the memory text, and
de-duplicates writes itself because ``remember_memory`` creates a new artifact even for
byte-identical text.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from ..errors import RequestValidationError

MemoryKind = Literal[
    "goal", "completed_work", "decision", "evidence", "open_question", "next_step"
]

KIND_PREFIX = "rf_"
SNAPSHOT_KIND = "rf_progress_snapshot"
KINDS: tuple[MemoryKind, ...] = (
    "goal",
    "completed_work",
    "decision",
    "evidence",
    "open_question",
    "next_step",
)
KIND_LABELS: dict[str, str] = {
    "goal": "研究目标",
    "completed_work": "已完成工作",
    "decision": "已确认决策",
    "evidence": "关键证据",
    "open_question": "未解决问题",
    "next_step": "下一步",
    "progress_snapshot": "进度快照",
}

# PowerContext caps RememberMemoryRequest.text at 8192 UTF-8 bytes.
MAX_TEXT_BYTES = 8192
_SAFE_TEXT_BYTES = 7800

_ITEM_RE = re.compile(r"^\[(\d+)\|([^\]]+)\]\s*(.*)$", re.DOTALL)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class EvidencePointer:
    """A pointer into seekdb. The quote is a short excerpt, never the whole page."""

    doc_id: str
    filename: str
    page_no: int
    chunk_id: str
    quote: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidencePointer":
        return cls(
            doc_id=str(data.get("doc_id", "")),
            filename=str(data.get("filename", "")),
            page_no=int(data.get("page_no", 0)),
            chunk_id=str(data.get("chunk_id", "")),
            quote=str(data.get("quote", ""))[:600],
        )


@dataclass
class ResearchProgress:
    project_id: str
    title: str = ""
    objective: str = ""
    completed_work: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    key_evidence: list[EvidencePointer] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    note: str = ""
    confirmed_by: str = "user"
    updated_at: str = field(default_factory=utc_now_iso)
    seq: int = 0

    def validate(self) -> None:
        if not self.project_id.strip():
            raise RequestValidationError("project_id must not be empty")
        if not any(
            [
                self.objective.strip(),
                self.completed_work,
                self.decisions,
                self.key_evidence,
                self.open_questions,
                self.next_steps,
            ]
        ):
            raise RequestValidationError(
                "nothing to save: provide at least one of objective / completed_work / "
                "decisions / key_evidence / open_questions / next_steps"
            )

    def items(self) -> list[tuple[str, str]]:
        """Flatten into (kind, text) pairs, one per user-visible bullet."""
        pairs: list[tuple[str, str]] = []
        if self.objective.strip():
            pairs.append(("goal", self.objective.strip()))
        pairs += [("completed_work", t.strip()) for t in self.completed_work if t.strip()]
        pairs += [("decision", t.strip()) for t in self.decisions if t.strip()]
        pairs += [
            (
                "evidence",
                f"{e.filename} 第 {e.page_no} 页 — {e.quote}".strip(),
            )
            for e in self.key_evidence
        ]
        pairs += [("open_question", t.strip()) for t in self.open_questions if t.strip()]
        pairs += [("next_step", t.strip()) for t in self.next_steps if t.strip()]
        return pairs

    def _core_payload(self) -> dict[str, Any]:
        return {
            "v": 1,
            "project_id": self.project_id,
            "title": self.title,
            "objective": self.objective,
            "completed_work": self.completed_work,
            "decisions": self.decisions,
            "key_evidence": [e.to_dict() for e in self.key_evidence],
            "open_questions": self.open_questions,
            "next_steps": self.next_steps,
            "note": self.note,
            "confirmed_by": self.confirmed_by,
        }

    def content_fingerprint(self) -> str:
        """Stable hash of the substantive content, ignoring seq/updated_at bookkeeping."""
        canonical = json.dumps(
            self._core_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def snapshot_payload(self) -> dict[str, Any]:
        return {
            **self._core_payload(),
            "seq": self.seq,
            "updated_at": self.updated_at,
            "fingerprint": self.content_fingerprint(),
        }

    def snapshot_json(self) -> str:
        payload = self.snapshot_payload()
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > _SAFE_TEXT_BYTES:
            # Evidence quotes are the bulkiest part and are recoverable from seekdb.
            payload["key_evidence"] = [
                {**e.to_dict(), "quote": e.quote[:80] + "…"} for e in self.key_evidence
            ]
            payload["truncated"] = True
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise RequestValidationError(
                "progress snapshot exceeds PowerContext's 8192-byte memory limit even after "
                "trimming evidence quotes",
                detail={"bytes": len(text.encode("utf-8")), "limit": MAX_TEXT_BYTES},
            )
        return text


@dataclass
class MemoryEntry:
    """One decoded PowerContext atomic memory."""

    kind: str
    text: str
    seq: int
    updated_at: str
    artifact_id: str
    revision: int
    state: str
    source: str = "memory"

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind.removeprefix(KIND_PREFIX), self.kind)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind_label"] = self.kind_label
        return data


def encode_item_text(seq: int, updated_at: str, content: str) -> str:
    return f"[{seq}|{updated_at}] {content}"


def decode_entry(kind: str, text: str, artifact_id: str, revision: int, state: str) -> MemoryEntry:
    if kind == SNAPSHOT_KIND:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {}
        return MemoryEntry(
            kind="progress_snapshot",
            text=text,
            seq=int(payload.get("seq", 0)),
            updated_at=str(payload.get("updated_at", "")),
            artifact_id=artifact_id,
            revision=revision,
            state=state,
        )
    match = _ITEM_RE.match(text or "")
    if match:
        seq, updated_at, content = int(match.group(1)), match.group(2), match.group(3)
    else:
        seq, updated_at, content = 0, "", text or ""
    return MemoryEntry(
        kind=kind.removeprefix(KIND_PREFIX),
        text=content,
        seq=seq,
        updated_at=updated_at,
        artifact_id=artifact_id,
        revision=revision,
        state=state,
    )
