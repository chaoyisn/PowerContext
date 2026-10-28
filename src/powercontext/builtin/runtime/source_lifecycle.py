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

"""Persisted, scope-local availability propagation for Source evidence graphs."""

# Domain errors include actionable context for callers and persisted audit events.
# ruff: noqa: TRY003

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import InvalidMemoryCitationError, MemoryEntryNotFoundError
from powercontext.builtin.persistence.errors import RepositoryNotFoundError
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources import validate_scope_id
from powercontext.builtin.statistics import ModelUsagePurpose
from powercontext.errors import ArtifactNotFoundError
from powercontext.limits import MAX_ARTIFACT_ID_LENGTH
from powercontext.sources import SourceRef

SourceLifecycleReference = SourceRef | MemoryCitation | ArtifactRef
SourceLifecycleNodeType = Literal["source", "memory", "topic"]
SourceLifecyclePolicy = Literal["all", "any"]
MemoryLifecycleState = Literal["active", "inactive"]


class SourceLifecycleError(ValueError):
    """A Source lifecycle registration or event violates its persisted contract."""


class SourceLifecycleEvent(BaseModel):
    """One ordered availability event for a registered Source node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: StrictInt = Field(gt=0)
    sequence: StrictInt = Field(gt=0)
    available: StrictBool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


@dataclass(frozen=True, slots=True)
class _Node:
    scope_id: str
    node_id: str
    node_type: SourceLifecycleNodeType
    reference: SourceLifecycleReference
    parents: tuple[str, ...]
    policy: SourceLifecyclePolicy
    revision: int | None
    sequence: int | None
    event_available: bool | None
    event_reason: str | None
    available: bool
    managed_revision: int | None
    pending_state: MemoryLifecycleState | None
    pending_from_revision: int | None


class SourceLifecycleRepository:
    """Relational storage for immutable bindings and their derived availability."""

    async def get(self, connection: AsyncConnection, scope_id: str, node_id: str) -> _Node | None:
        row = (
            (
                await connection.execute(
                    select(SOURCE_LIFECYCLE_NODES_TABLE).where(
                        SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
                        SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _decode_node(row)

    async def list_scope(self, connection: AsyncConnection, scope_id: str) -> tuple[_Node, ...]:
        rows = (
            await connection.execute(
                select(SOURCE_LIFECYCLE_NODES_TABLE)
                .where(SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id)
                .order_by(SOURCE_LIFECYCLE_NODES_TABLE.c.node_id)
            )
        ).mappings()
        return tuple(_decode_node(row) for row in rows)

    async def add(self, connection: AsyncConnection, values: dict[str, object]) -> None:
        await connection.execute(insert(SOURCE_LIFECYCLE_NODES_TABLE).values(**values))

    async def update(self, connection: AsyncConnection, scope_id: str, node_id: str, **values: object) -> None:
        await connection.execute(
            update(SOURCE_LIFECYCLE_NODES_TABLE)
            .where(
                SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
                SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
            )
            .values(**values)
        )

    async def topic_visibility(
        self,
        connection: AsyncConnection,
        scope_id: str,
    ) -> tuple[set[tuple[str, int]], set[tuple[str, int]]]:
        """Return managed and currently available exact Topic references."""

        nodes = await self.list_scope(connection, scope_id)
        managed: set[tuple[str, int]] = set()
        available: set[tuple[str, int]] = set()
        for node in nodes:
            if node.node_type != "topic":
                continue
            reference = node.reference
            if not isinstance(reference, ArtifactRef):
                raise SourceLifecycleError("Topic node does not contain an ArtifactRef")
            key = (reference.artifact_id, reference.revision)
            managed.add(key)
            if node.available:
                available.add(key)
        return managed, available


class SourceLifecycleApplication:
    """Select the persisted lifecycle service for a scope."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._repository = SourceLifecycleRepository()

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._runtime, self._repository, validate_scope_id(scope_id))


class ScopedSourceLifecycle:
    """Register a fixed evidence DAG and apply ordered Source availability events."""

    def __init__(self, runtime: Any, repository: SourceLifecycleRepository, scope_id: str) -> None:
        self._runtime = runtime
        self._repository = repository
        self.scope_id = scope_id

    @property
    def _database(self) -> Any:
        return self._runtime._provider.database

    @property
    def _repositories(self) -> Any:
        return self._runtime._provider.repositories

    async def register_source(self, node_id: str, source_ref: SourceRef, /, *, revision: int) -> None:
        _validate_node_id(node_id)
        if not isinstance(source_ref, SourceRef) or type(revision) is not int or revision < 1:
            raise SourceLifecycleError("source registration requires a SourceRef and positive revision")
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            async with self._database.transaction() as connection:
                try:
                    await self._repositories.sources.get(connection, self.scope_id, source_ref)
                except RepositoryNotFoundError:
                    raise SourceLifecycleError("source reference does not exist in this scope") from None
            await self._register(
                node_id,
                "source",
                source_ref,
                parents=(),
                policy="all",
                revision=revision,
            )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: Sequence[str],
        policy: SourceLifecyclePolicy,
    ) -> None:
        _validate_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("memory registration requires a MemoryCitation")
        if citation.memory_ref.family != "memory":
            raise SourceLifecycleError("memory registration requires a Memory citation")
        _validate_dependencies(node_id, parents, policy)
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            try:
                await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
            except (ArtifactNotFoundError, InvalidMemoryCitationError, MemoryEntryNotFoundError):
                raise SourceLifecycleError("memory citation is not readable in this scope") from None
            await self._register(node_id, "memory", citation, parents=tuple(parents), policy=policy)
            await self._reconcile_memories()

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        /,
        *,
        parents: Sequence[str],
        policy: SourceLifecyclePolicy,
    ) -> None:
        _validate_node_id(node_id)
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("topic registration requires a Topic Memory ArtifactRef")
        _validate_dependencies(node_id, parents, policy)
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            try:
                await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                    artifact_ref.family,
                    artifact_ref.artifact_id,
                    artifact_ref.revision,
                )
            except ArtifactNotFoundError:
                raise SourceLifecycleError("Topic Memory reference is not readable in this scope") from None
            await self._register(node_id, "topic", artifact_ref, parents=tuple(parents), policy=policy)

    async def _register(
        self,
        node_id: str,
        node_type: SourceLifecycleNodeType,
        reference: SourceLifecycleReference,
        *,
        parents: tuple[str, ...],
        policy: SourceLifecyclePolicy,
        revision: int | None = None,
    ) -> None:
        async with self._database.transaction() as connection:
            existing = await self._repository.get(connection, self.scope_id, node_id)
            if existing is not None:
                if not _same_registration(existing, node_type, reference, parents, policy, revision):
                    raise SourceLifecycleError("node id is already bound to different evidence")
                return
            nodes = {node.node_id: node for node in await self._repository.list_scope(connection, self.scope_id)}
            missing = tuple(parent for parent in parents if parent not in nodes)
            if missing:
                raise SourceLifecycleError(f"parent node is not registered: {missing[0]}")
            if node_type == "source":
                available = True
            else:
                parent_states = [nodes[parent].available for parent in parents]
                available = all(parent_states) if policy == "all" else any(parent_states)
            await self._repository.add(
                connection,
                {
                    "scope_id": self.scope_id,
                    "node_id": node_id,
                    "node_type": node_type,
                    "reference": _encode(reference),
                    "parents": _encode(list(parents)),
                    "policy": policy,
                    "revision": revision,
                    "sequence": 0 if node_type == "source" else None,
                    "event_available": None,
                    "event_reason": None,
                    "available": available,
                    "managed_revision": None,
                    "pending_state": None,
                    "pending_from_revision": None,
                },
            )

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event must be a SourceLifecycleEvent")
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            async with self._database.transaction() as connection:
                nodes = await self._repository.list_scope(connection, self.scope_id)
                source = next(
                    (node for node in nodes if node.node_id == event.node_id and node.node_type == "source"),
                    None,
                )
                if source is None:
                    raise SourceLifecycleError("event source is not registered")
                if event.revision != source.revision:
                    raise SourceLifecycleError("event revision does not match the registered Source")
                if event.sequence < (source.sequence or 0):
                    raise SourceLifecycleError("event sequence is stale")
                if event.sequence == source.sequence:
                    if event.available != source.event_available or event.reason != source.event_reason:
                        raise SourceLifecycleError("event sequence was already used for different content")
                else:
                    await self._repository.update(
                        connection,
                        self.scope_id,
                        source.node_id,
                        sequence=event.sequence,
                        event_available=event.available,
                        event_reason=event.reason,
                        available=event.available,
                    )
                await self._recompute(connection)
            await self._reconcile_memories()
            async with self._database.transaction() as connection:
                nodes = await self._repository.list_scope(connection, self.scope_id)
            return sorted(node.node_id for node in nodes if node.available)

    async def _recompute(self, connection: AsyncConnection) -> None:
        nodes = await self._repository.list_scope(connection, self.scope_id)
        states = {node.node_id: node.available for node in nodes if node.node_type == "source"}
        pending = [node for node in nodes if node.node_type != "source"]
        while pending:
            remaining: list[_Node] = []
            progressed = False
            for node in pending:
                if not all(parent in states for parent in node.parents):
                    remaining.append(node)
                    continue
                parent_states = [states[parent] for parent in node.parents]
                available = all(parent_states) if node.policy == "all" else any(parent_states)
                if available != node.available:
                    await self._repository.update(
                        connection,
                        self.scope_id,
                        node.node_id,
                        available=available,
                    )
                states[node.node_id] = available
                progressed = True
            if not progressed:
                raise SourceLifecycleError("registered dependency graph is incomplete or cyclic")
            pending = remaining

    async def _reconcile_memories(self) -> None:
        async with self._database.transaction() as connection:
            nodes = await self._repository.list_scope(connection, self.scope_id)
        for node in nodes:
            if node.node_type == "memory":
                await self._reconcile_memory(node.node_id)

    async def _reconcile_memory(self, node_id: str) -> None:
        async with self._runtime._context(
            self.scope_id,
            embedding_purpose=ModelUsagePurpose.MEMORY_INDEXING,
        ) as context:
            service = context.artifacts.memory
            for _ in range(4):
                if await self._reconcile_memory_state(service, node_id):
                    return
            raise SourceLifecycleError("Memory state did not settle after propagation")

    async def _reconcile_memory_state(self, service: Any, node_id: str) -> bool:
        async with self._database.transaction() as connection:
            node = await self._repository.get(connection, self.scope_id, node_id)
        if node is None or node.node_type != "memory":
            raise SourceLifecycleError("registered Memory node is missing")
        citation = node.reference
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("registered Memory node does not contain a MemoryCitation")
        try:
            current = await service.head(citation.memory_ref.artifact_id)
        except ArtifactNotFoundError:
            raise SourceLifecycleError("registered Memory has no current head") from None
        entries = await service.entries(current)
        entry = next(
            (
                item
                for item in entries
                if item.entry_id == citation.entry_id and item.entry_version_id == citation.entry_version_id
            ),
            None,
        )
        manifest_entry = next(
            (item for item in current.content.manifest.entries if item.entry_id == citation.entry_id),
            None,
        )
        if entry is None or manifest_entry is None:
            raise SourceLifecycleError("registered Memory entry changed while bound")
        state: MemoryLifecycleState = manifest_entry.state
        desired: MemoryLifecycleState = "active" if node.available else "inactive"

        if await self._reconcile_pending_memory(service, node, current, entry, state, desired):
            return False
        if desired == "inactive" and state == "active":
            await self._perform_memory_transition(service, node, current, entry, desired)
            return False
        if desired == "active" and state == "inactive" and node.managed_revision is not None:
            await self._perform_memory_transition(service, node, current, entry, desired)
            return False
        return True

    async def _reconcile_pending_memory(
        self,
        service: Any,
        node: _Node,
        current: Any,
        entry: Any,
        state: MemoryLifecycleState,
        desired: MemoryLifecycleState,
    ) -> bool:
        if node.pending_state is None:
            return False
        if node.pending_from_revision is None:
            raise SourceLifecycleError("incomplete Memory state transition")
        if state == node.pending_state:
            await self._finish_memory_transition(node.node_id, current.revision)
        elif node.pending_state == desired:
            await self._perform_memory_transition(service, node, current, entry, desired)
        else:
            await self._clear_memory_transition(node.node_id)
        return True

    async def _perform_memory_transition(
        self,
        service: Any,
        node: _Node,
        current: Any,
        entry: Any,
        target: MemoryLifecycleState,
    ) -> None:
        async with self._database.transaction() as connection:
            await self._repository.update(
                connection,
                self.scope_id,
                node.node_id,
                pending_state=target,
                pending_from_revision=current.revision,
            )
        if target == "inactive":
            updated = await service.forget(current, entries=(entry,), reason="Source evidence withdrawn")
        else:
            updated = await service.reactivate(current, entries=(entry,), reason="Source evidence restored")
        await self._finish_memory_transition(node.node_id, updated.revision)

    async def _finish_memory_transition(self, node_id: str, revision: int) -> None:
        async with self._database.transaction() as connection:
            await self._repository.update(
                connection,
                self.scope_id,
                node_id,
                managed_revision=revision,
                pending_state=None,
                pending_from_revision=None,
            )

    async def _clear_memory_transition(self, node_id: str) -> None:
        values = {"pending_state": None, "pending_from_revision": None}
        async with self._database.transaction() as connection:
            await self._repository.update(connection, self.scope_id, node_id, **values)

    async def mark_manual_inactive(self, citation: MemoryCitation, /) -> None:
        """Keep a deliberate user deactivation from being undone by later Source recovery."""

        async with self._database.transaction() as connection:
            nodes = await self._repository.list_scope(connection, self.scope_id)
            for node in nodes:
                reference = node.reference
                if node.node_type == "memory" and isinstance(reference, MemoryCitation):
                    same_entry = (
                        reference.memory_ref.artifact_id == citation.memory_ref.artifact_id
                        and reference.entry_id == citation.entry_id
                        and reference.entry_version_id == citation.entry_version_id
                    )
                    if same_entry:
                        await self._repository.update(
                            connection,
                            self.scope_id,
                            node.node_id,
                            managed_revision=None,
                            pending_state=None,
                            pending_from_revision=None,
                        )

    async def resolve(self, node_id: str, /, *, purpose: Literal["generation", "audit"]) -> SourceLifecycleReference:
        _validate_node_id(node_id)
        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("unknown reference purpose")
        async with self._runtime._scope_operation(self.scope_id):
            async with self._database.transaction() as connection:
                node = await self._repository.get(connection, self.scope_id, node_id)
            if node is None:
                raise SourceLifecycleError("node is not registered")
            if purpose == "generation" and not node.available:
                raise SourceLifecycleError("node has no currently available evidence")
            if purpose == "generation" and node.node_type == "memory":
                citation = node.reference
                if not isinstance(citation, MemoryCitation):
                    raise SourceLifecycleError("registered Memory node does not contain a MemoryCitation")
                page = await self._runtime.memory.for_scope(self.scope_id).list(include_inactive=True)
                current = next(
                    (
                        entry
                        for entry in page.entries
                        if entry.entry.entry_id == citation.entry_id
                        and entry.entry.entry_version_id == citation.entry_version_id
                    ),
                    None,
                )
                if current is None or current.state != "active":
                    raise SourceLifecycleError("Memory is explicitly inactive")
            return node.reference


def _same_registration(
    existing: _Node,
    node_type: SourceLifecycleNodeType,
    reference: SourceLifecycleReference,
    parents: tuple[str, ...],
    policy: SourceLifecyclePolicy,
    revision: int | None,
) -> bool:
    return (
        existing.node_type == node_type
        and existing.reference == reference
        and existing.parents == parents
        and existing.policy == policy
        and existing.revision == revision
    )


def _validate_node_id(node_id: str) -> None:
    if not isinstance(node_id, str) or not node_id.strip() or len(node_id) > MAX_ARTIFACT_ID_LENGTH:
        raise SourceLifecycleError("node id must be nonblank and no longer than 128 characters")


def _validate_dependencies(node_id: str, parents: Sequence[str], policy: SourceLifecyclePolicy) -> None:
    if isinstance(parents, (str, bytes)):
        raise SourceLifecycleError("parents must be a sequence of node ids")
    if policy not in {"all", "any"}:
        raise SourceLifecycleError("policy must be 'all' or 'any'")
    if not parents or len(set(parents)) != len(parents):
        raise SourceLifecycleError("derived nodes require distinct registered parents")
    for parent in parents:
        _validate_node_id(parent)
        if parent == node_id:
            raise SourceLifecycleError("a node cannot depend on itself")


def _encode(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode(value: object) -> Any:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(str(value))


def _decode_node(row: Any) -> _Node:
    node_type_value = str(row["node_type"])
    if node_type_value not in {"source", "memory", "topic"}:
        raise SourceLifecycleError("unknown registered node type")
    node_type = cast(SourceLifecycleNodeType, node_type_value)
    value = _decode(row["reference"])
    reference: SourceLifecycleReference
    if node_type == "source":
        reference = SourceRef.model_validate(value)
    elif node_type == "memory":
        reference = MemoryCitation.model_validate(value)
    else:
        reference = ArtifactRef.model_validate(value)
    sequence = row["sequence"]
    revision = row["revision"]
    event_available = row["event_available"]
    return _Node(
        scope_id=str(row["scope_id"]),
        node_id=str(row["node_id"]),
        node_type=node_type,
        reference=reference,
        parents=tuple(str(parent) for parent in _decode(row["parents"])),
        policy=cast(SourceLifecyclePolicy, str(row["policy"])),
        revision=None if revision is None else int(revision),
        sequence=None if sequence is None else int(sequence),
        event_available=None if event_available is None else bool(event_available),
        event_reason=None if row["event_reason"] is None else str(row["event_reason"]),
        available=bool(row["available"]),
        managed_revision=None if row["managed_revision"] is None else int(row["managed_revision"]),
        pending_state=row["pending_state"],  # type: ignore[arg-type]
        pending_from_revision=(None if row["pending_from_revision"] is None else int(row["pending_from_revision"])),
    )


__all__ = [
    "ScopedSourceLifecycle",
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
    "SourceLifecycleNodeType",
    "SourceLifecyclePolicy",
    "SourceLifecycleReference",
    "SourceLifecycleRepository",
]
