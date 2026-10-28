from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput, MemoryService
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    RememberMemoryRequest,
    RetireMemoryEntryRequest,
    SourceLifecycleError,
    SourceLifecycleEvent,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft


async def _scope(runtime, key: str) -> str:
    scope = await runtime.scopes.create(
        ScopeDraft(title="Lifecycle", summary="Source lifecycle test", idempotency_key=key)
    )
    return scope.scope_id


async def _bound_memory(runtime, scope_id: str, source_id: str, node_id: str):
    captured = await runtime.sources.for_scope(scope_id).capture(
        CaptureSource(source_id=source_id, content=f"Evidence {source_id}", metadata={})
    )
    created = await runtime.memory.for_scope(scope_id).remember(
        RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"{node_id} fact"),))
    )
    lifecycle = runtime.lifecycle.for_scope(scope_id)
    await lifecycle.register_source(node_id + "-source", captured.source_ref, revision=1)
    await lifecycle.register_memory(
        node_id,
        created.entry.citation,
        parents=(node_id + "-source",),
        policy="all",
    )
    return lifecycle, created.entry.citation


def test_failed_memory_transition_completes_on_same_event_retry():
    async def run():
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            scope_id = await _scope(runtime, "retry")
            lifecycle, citation = await _bound_memory(runtime, scope_id, "source", "memory")
            original = MemoryService.forget
            calls = 0

            async def fail_once(self, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError from None
                return await original(self, *args, **kwargs)

            event = SourceLifecycleEvent(
                node_id="memory-source",
                revision=1,
                sequence=1,
                available=False,
                reason="source withdrawn",
            )
            with patch.object(MemoryService, "forget", fail_once):
                with pytest.raises(RuntimeError):
                    await lifecycle.apply(event)
                await lifecycle.apply(event)
            entries = await runtime.memory.for_scope(scope_id).list(include_inactive=True)
            assert (
                next(item for item in entries.entries if item.citation.entry_id == citation.entry_id).state
                == "inactive"
            )

    asyncio.run(run())


def test_manual_memory_deactivation_survives_source_recovery():
    async def run():
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            scope_id = await _scope(runtime, "manual")
            lifecycle, _ = await _bound_memory(runtime, scope_id, "source", "memory")
            await lifecycle.apply(
                SourceLifecycleEvent(
                    node_id="memory-source",
                    revision=1,
                    sequence=1,
                    available=False,
                    reason="source withdrawn",
                )
            )
            current_entry = (await runtime.memory.for_scope(scope_id).list(include_inactive=True)).entries[0]
            await runtime.memory.for_scope(scope_id).retire(
                RetireMemoryEntryRequest(citation=current_entry.citation, reason="user requested forgetting")
            )
            await lifecycle.apply(
                SourceLifecycleEvent(
                    node_id="memory-source",
                    revision=1,
                    sequence=2,
                    available=True,
                    reason="source restored",
                )
            )
            with pytest.raises(SourceLifecycleError):
                await lifecycle.resolve("memory", purpose="generation")
            entries = await runtime.memory.for_scope(scope_id).list(include_inactive=True)
            assert entries.entries[0].state == "inactive"

    asyncio.run(run())


def test_same_node_ids_are_isolated_by_scope():
    async def run():
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            first = await _scope(runtime, "scope-a")
            second = await _scope(runtime, "scope-b")
            lifecycle_a, _ = await _bound_memory(runtime, first, "shared-source", "shared-memory")
            lifecycle_b, citation_b = await _bound_memory(runtime, second, "shared-source", "shared-memory")
            await lifecycle_a.apply(
                SourceLifecycleEvent(
                    node_id="shared-memory-source",
                    revision=1,
                    sequence=1,
                    available=False,
                    reason="scope-local withdrawal",
                )
            )
            assert await lifecycle_b.resolve("shared-memory", purpose="generation") == citation_b

    asyncio.run(run())
