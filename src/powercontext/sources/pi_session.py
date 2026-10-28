# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pi session branch parsing, durable text evidence, and incremental checkpoint connector."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
)
from powercontext.sources.definitions import SourceDefinition, SourceProjection
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TextEvidence


class PiSessionInput(BaseModel):
    """Input payload containing raw session JSONL content and optional branch leaf ID."""

    content: bytes
    leaf_id: str | None = None

    def __init__(self, content: bytes = b"", leaf_id: str | None = None, **data: Any) -> None:
        if "content" not in data and content:
            data["content"] = content
        if "leaf_id" not in data and leaf_id is not None:
            data["leaf_id"] = leaf_id
        super().__init__(**data)


class PiEventInput(BaseModel):
    """Normalized Pi event carrying identity, hierarchy, and complete input record."""

    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


class PiEventSource(Source):
    """Captured Pi event Source retaining exact identity and metadata."""

    source_id: str
    name: str = ""
    definition_version: str = "1"
    materialization: SourceMaterialization = SourceMaterialization.CAPTURED
    description: str | None = None
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _ensure_identity_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "source_id" in data and not data.get("name"):
                data["name"] = data["source_id"]
            elif "name" in data and not data.get("source_id"):
                data["source_id"] = data["name"]
        return data

    @model_validator(mode="after")
    def _validate_identity(self) -> PiEventSource:
        if not self.name:
            self.name = self.source_id
        if self.name != self.source_id:
            raise ValueError("PiEventSource name and source_id must be identical")
        return self


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Generate a stable Source identity from session ID and event ID."""
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be a non-empty string")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id must be a non-empty string")
    identity = f"pi:{session_id}:{event_id}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id length {len(identity)} exceeds limit of {MAX_SOURCE_ID_LENGTH}")
    return identity


def _record_digest(record: dict[str, Any]) -> str:
    """Compute a canonical SHA-256 digest of one raw JSON record."""
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _extract_text_or_blocks(raw_content: Any) -> str | None:
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, list):
        parts: list[str] = []
        for block in raw_content:
            if isinstance(block, str):
                if block:
                    parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    t = block.get("text", "")
                    if t:
                        parts.append(t)
        return "\n".join(parts) if parts else None
    return None


def _extract_message_blocks(raw_content: Any) -> str | None:
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, list):
        parts: list[str] = []
        for block in raw_content:
            if isinstance(block, str):
                if block:
                    parts.append(block)
            elif isinstance(block, dict):
                b_type = block.get("type")
                if b_type == "text":
                    t = block.get("text", "")
                    if t:
                        parts.append(t)
                elif b_type == "toolCall":
                    name = block.get("name", "")
                    call_id = block.get("id", "")
                    args = block.get("arguments", {})
                    compact_args = json.dumps(
                        args,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    parts.append(f"[tool_call {name} {call_id}] {compact_args}")
                elif b_type in ("thinking", "image"):
                    continue
        return "\n".join(parts) if parts else None
    return None


def _extract_event_info(record: dict[str, Any]) -> tuple[str, str, str] | None:
    rec_type = record.get("type", "")

    if rec_type in ("compaction", "branch_summary"):
        summary = record.get("summary", "")
        if isinstance(summary, str) and summary.strip():
            role = rec_type
            content = f"{role}: {summary}"
            return (rec_type, role, content)
        return None

    if rec_type == "custom_message":
        raw_content = record.get("content")
        body = _extract_text_or_blocks(raw_content)
        if body is not None and body.strip():
            role = "custom"
            content = f"{role}: {body}"
            return (rec_type, role, content)
        return None

    if rec_type == "message":
        msg = record.get("message")
        if not isinstance(msg, dict):
            return None
        role = msg.get("role")
        if not isinstance(role, str) or not role:
            return None

        if role == "toolResult":
            tool_name = msg.get("toolName", "")
            tool_call_id = msg.get("toolCallId", "")
            raw_content = msg.get("content")
            text = _extract_text_or_blocks(raw_content) or ""
            prefix = f"[tool_result {tool_name} {tool_call_id}]"
            body = f"{prefix} {text}" if text else prefix
            content = f"{role}: {body}"
            return (rec_type, role, content)

        if role == "bashExecution":
            command = msg.get("command", "")
            output = msg.get("output", "")
            body = f"$ {command}\n{output}"
            content = f"{role}: {body}"
            return (rec_type, role, content)

        raw_content = msg.get("content")
        body = _extract_message_blocks(raw_content)
        if body is not None and body.strip():
            content = f"{role}: {body}"
            return (rec_type, role, content)
        return None

    return None


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse a Pi session JSONL into the ancestor chain of visible events for the selected leaf."""
    if not isinstance(value.content, (bytes, bytearray)):
        raise ValueError("content must be bytes")

    raw = bytes(value.content)
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ValueError("Session content is not valid UTF-8") from err

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Session content is empty")

    try:
        header = json.loads(lines[0])
    except Exception as err:
        raise ValueError(f"Invalid JSON in session header: {err}") from err

    if not isinstance(header, dict):
        raise ValueError("Session header must be a JSON object")

    if header.get("type") != "session":
        raise ValueError("First record must have type='session'")
    if header.get("version") != 3:
        raise ValueError("First record must have version=3")
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("First record must have a non-empty string 'id'")

    records: list[dict[str, Any]] = []
    records_by_id: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()

    for idx, line in enumerate(lines[1:], start=2):
        try:
            record = json.loads(line)
        except Exception as err:
            raise ValueError(f"Invalid JSON on line {idx}: {err}") from err

        if not isinstance(record, dict):
            raise ValueError(f"Record on line {idx} must be a JSON object")

        rec_id = record.get("id")
        if not isinstance(rec_id, str) or not rec_id:
            raise ValueError(f"Record on line {idx} must have a non-empty string 'id'")

        if rec_id in seen_ids:
            raise ValueError(f"Duplicate record id {rec_id!r} on line {idx}")

        parent_id = record.get("parentId")
        if parent_id is not None and parent_id != "":
            if not isinstance(parent_id, str):
                raise ValueError(f"Invalid parentId on line {idx}")
            if parent_id not in seen_ids:
                raise ValueError(f"Record {rec_id!r} points to non-existent or forward parent {parent_id!r}")

        seen_ids.add(rec_id)
        records_by_id[rec_id] = record
        records.append(record)

    if not records:
        raise ValueError("No records found in session")

    if value.leaf_id is not None:
        if value.leaf_id not in records_by_id:
            raise ValueError(f"Leaf id {value.leaf_id!r} not found in session")
        leaf_id = value.leaf_id
    else:
        leaf_id = records[-1]["id"]

    chain: list[dict[str, Any]] = []
    curr: str | None = leaf_id
    visited: set[str] = set()

    while curr is not None and curr != "":
        if curr in visited:
            raise ValueError(f"Cycle detected at node {curr!r}")
        visited.add(curr)
        node = records_by_id.get(curr)
        if node is None:
            raise ValueError(f"Missing ancestor node {curr!r}")
        chain.append(node)
        curr = node.get("parentId")

    chain.reverse()

    events: list[PiEventInput] = []
    for node in chain:
        extracted = _extract_event_info(node)
        if extracted is not None:
            event_type, role, content = extracted
            events.append(
                PiEventInput(
                    session_id=session_id,
                    event_id=node["id"],
                    parent_id=node.get("parentId"),
                    event_type=event_type,
                    role=role,
                    content=content,
                    record=node,
                )
            )

    return tuple(events)


@dataclass(frozen=True, slots=True)
class PiEventTextEvidenceProjection:
    """Project one PiEventSource into standard text-evidence representation."""

    name: str = "powercontext.text-evidence"
    version: str = "1"
    source_class: type[PiEventSource] = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pi-event",
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


@dataclass(frozen=True, slots=True)
class PiEventSourceDefinition:
    """Source Definition for Pi event ingestion and exact evidence citation."""

    name: str = "pi-event"
    version: str = "1"
    input_class: type[PiEventInput] = PiEventInput
    source_class: type[PiEventSource] = PiEventSource
    projections: tuple[SourceProjection[PiEventSource], ...] = (PiEventTextEvidenceProjection(),)

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            definition_version="1",
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = PiEventSourceDefinition()


class PiSessionConnector:
    """Connector for incrementally ingesting Pi session branches with checkpointing."""

    name: str = "pi-session-history"
    version: str = "1"
    source_definitions: frozenset[str] = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession) -> ConnectorRunCompletion:
        if not self.path.exists() or not self.path.is_file():
            raise ValueError(f"File not found: {self.path}")

        try:
            content = self.path.read_bytes()
        except Exception as err:
            raise ValueError(f"Failed to read file {self.path}: {err}") from err

        raw = content
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as err:
            raise ValueError(f"Invalid UTF-8 in {self.path}") from err

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise ValueError(f"Empty session file: {self.path}")

        try:
            header = json.loads(lines[0])
        except Exception as err:
            raise ValueError(f"Invalid JSON in session header: {err}") from err

        if not isinstance(header, dict) or header.get("type") != "session" or header.get("version") != 3:
            raise ValueError("Invalid session header")
        session_id = header.get("id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("Invalid session id")

        all_records_by_id: dict[str, dict[str, Any]] = {}
        seen_ids: set[str] = set()
        for idx, line in enumerate(lines[1:], start=2):
            try:
                rec = json.loads(line)
            except Exception as err:
                raise ValueError(f"Invalid JSON on line {idx}: {err}") from err
            if not isinstance(rec, dict):
                raise ValueError(f"Invalid JSON object on line {idx}")
            rec_id = rec.get("id")
            if not isinstance(rec_id, str) or not rec_id:
                raise ValueError(f"Missing id on line {idx}")
            if rec_id in seen_ids:
                raise ValueError(f"Duplicate id {rec_id!r} on line {idx}")
            pid = rec.get("parentId")
            if pid is not None and pid != "":
                if pid not in seen_ids:
                    raise ValueError(f"Record {rec_id!r} references missing parent {pid!r}")
            seen_ids.add(rec_id)
            all_records_by_id[rec_id] = rec

        checkpoint = session.checkpoint
        known_events: dict[str, str] = {}
        if isinstance(checkpoint, dict):
            known_events = dict(checkpoint.get("events", {}))

        for rec_id, rec in all_records_by_id.items():
            if rec_id in known_events:
                expected_digest = known_events[rec_id]
                actual_digest = _record_digest(rec)
                if actual_digest != expected_digest:
                    raise ValueError(f"Historical record {rec_id!r} was mutated")

        events = parse_pi_session(PiSessionInput(content=content, leaf_id=self.leaf_id))

        for event in events:
            if event.event_id not in known_events:
                await session.submit(event.event_id, "pi-event", event)
                known_events[event.event_id] = _record_digest(event.record)

        new_checkpoint = {
            "version": 1,
            "events": known_events,
        }

        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint=new_checkpoint,
        )


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
