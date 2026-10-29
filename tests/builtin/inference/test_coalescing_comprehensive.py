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

from __future__ import annotations

import asyncio

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel


class ControllableMockProvider:
    profile = EmbeddingProfile(profile_id="mock-profile", model="test-embed", dimension=3)

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.called_event = asyncio.Event()
        self.started_events: list[asyncio.Event] = []
        self.release_event = asyncio.Event()
        self.release_event.set()
        self.fail_once = False
        self.fail_count = 0

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        self.calls.append(texts)
        self.called_event.set()
        evt = asyncio.Event()
        self.started_events.append(evt)
        evt.set()
        await self.release_event.wait()
        if self.fail_once and self.fail_count == 0:
            self.fail_count += 1
            raise RuntimeError("provider-fail-simulated")
        vectors = tuple((float(len(t)), 1.0, 2.0) for t in texts)
        return EmbeddingResult(
            vectors=vectors,
            usage=InferenceUsage(requests=1, input_tokens=len(texts) * 10, output_tokens=0),
        )


def test_concurrent_same_text_merged() -> None:
    async def scenario():
        provider = ControllableMockProvider()
        provider.release_event.clear()
        model = CoalescingEmbeddingModel(provider, max_batch_size=10, coalesce_ms=0, cache_size=100)

        t1 = asyncio.create_task(model.embed(("shared_query",)))
        t2 = asyncio.create_task(model.embed(("shared_query",)))

        await provider.called_event.wait()
        provider.release_event.set()
        r1, r2 = await asyncio.gather(t1, t2)

        assert r1.vectors == r2.vectors
        assert len(provider.calls) == 1
        assert provider.calls[0] == ("shared_query",)
        assert r1.usage.requests == 1
        assert r2.usage.requests == 1

    asyncio.run(scenario())


def test_partial_overlap_preserves_order() -> None:
    async def scenario():
        provider = ControllableMockProvider()
        model = CoalescingEmbeddingModel(provider, max_batch_size=4, coalesce_ms=0, cache_size=100)

        # Call with partial overlap
        f1, f2 = await asyncio.gather(
            model.embed(("A", "B", "A")),
            model.embed(("B", "C", "D")),
        )
        assert f1.vectors == ((1.0, 1.0, 2.0), (1.0, 1.0, 2.0), (1.0, 1.0, 2.0))
        assert f2.vectors == ((1.0, 1.0, 2.0), (1.0, 1.0, 2.0), (1.0, 1.0, 2.0))
        all_requested = [text for call in provider.calls for text in call]
        assert sorted(all_requested) == ["A", "B", "C", "D"]
        assert all_requested.count("B") == 1

    asyncio.run(scenario())


def test_independent_batches_not_globally_serialized() -> None:
    async def scenario():
        provider = ControllableMockProvider()
        provider.release_event.clear()
        model = CoalescingEmbeddingModel(provider, max_batch_size=1, coalesce_ms=0, cache_size=100)

        # 3 distinct texts with max_batch_size=1 -> 3 separate batches
        t1 = asyncio.create_task(model.embed(("X",)))
        t2 = asyncio.create_task(model.embed(("Y",)))
        t3 = asyncio.create_task(model.embed(("Z",)))

        # All 3 should start concurrently without waiting for previous to finish
        for _ in range(100):
            if len(provider.started_events) == 3:
                break
            await asyncio.sleep(0.005)

        assert len(provider.started_events) == 3, "Batches must run concurrently without serialization"
        provider.release_event.set()
        await asyncio.gather(t1, t2, t3)
        assert len(provider.calls) == 3

    asyncio.run(scenario())


def test_cancellation_isolation_and_all_cancelled_cleanup() -> None:
    async def scenario():
        provider = ControllableMockProvider()
        provider.release_event.clear()
        model = CoalescingEmbeddingModel(provider, max_batch_size=10, coalesce_ms=0, cache_size=100)

        w1 = asyncio.create_task(model.embed(("cancel_test",)))
        w2 = asyncio.create_task(model.embed(("cancel_test",)))

        await provider.called_event.wait()

        w1.cancel()
        with pytest.raises(asyncio.CancelledError):
            await w1

        provider.release_event.set()
        r2 = await w2
        assert r2.vectors == ((11.0, 1.0, 2.0),)
        assert len(provider.calls) == 1

        # Now test all cancelled
        provider2 = ControllableMockProvider()
        provider2.release_event.clear()
        model2 = CoalescingEmbeddingModel(provider2, max_batch_size=10, coalesce_ms=0, cache_size=10)

        w3 = asyncio.create_task(model2.embed(("all_cancel",)))
        await provider2.called_event.wait()

        w3.cancel()
        with pytest.raises(asyncio.CancelledError):
            await w3

        provider2.release_event.set()
        # Wait a moment for background task to finish and populate cache
        await asyncio.sleep(0.05)

        # Later caller gets cached result with 0 additional provider requests
        cached_res = await model2.embed(("all_cancel",))
        assert cached_res.vectors == ((10.0, 1.0, 2.0),)
        assert len(provider2.calls) == 1
        assert cached_res.usage.requests == 0

    asyncio.run(scenario())


def test_failure_retry_and_no_inflight_leak() -> None:
    async def scenario():
        provider = ControllableMockProvider()
        provider.fail_once = True
        model = CoalescingEmbeddingModel(provider, max_batch_size=10, coalesce_ms=0, cache_size=10)

        with pytest.raises(RuntimeError, match="provider-fail-simulated"):
            await model.embed(("retry_key",))

        assert len(model._inflight) == 0, "Failed keys must not linger in _inflight"
        assert len(model._cache) == 0, "Failed keys must not enter cache"

        # Retry must succeed
        success = await model.embed(("retry_key",))
        assert success.vectors == ((9.0, 1.0, 2.0),)
        assert len(provider.calls) == 2

    asyncio.run(scenario())


def test_lru_eviction_and_zero_capacity() -> None:
    async def scenario():
        provider = ControllableMockProvider()
        model = CoalescingEmbeddingModel(provider, max_batch_size=1, coalesce_ms=0, cache_size=2)

        await model.embed(("k1",))
        await model.embed(("k2",))
        # k1 hit refreshes recency
        await model.embed(("k1",))
        assert len(provider.calls) == 2

        # k3 evicts k2
        await model.embed(("k3",))
        assert len(provider.calls) == 3

        # k1 still cached
        await model.embed(("k1",))
        assert len(provider.calls) == 3

        # k2 must re-fetch
        await model.embed(("k2",))
        assert len(provider.calls) == 4

        # Zero cache test
        zero_model = CoalescingEmbeddingModel(provider, max_batch_size=1, coalesce_ms=0, cache_size=0)
        await zero_model.embed(("z1",))
        await zero_model.embed(("z1",))
        assert len(zero_model._cache) == 0

    asyncio.run(scenario())


def test_invalid_dimension_nan_and_count_rejected() -> None:
    class BadProvider(ControllableMockProvider):
        def __init__(self, mode: str):
            super().__init__()
            self.mode = mode

        async def embed(self, texts):
            self.calls.append(texts)
            if self.mode == "count":
                return EmbeddingResult(vectors=())
            if self.mode == "dim":
                return EmbeddingResult(vectors=((1.0, 2.0),))  # profile dimension is 3
            if self.mode == "nan":
                return EmbeddingResult(vectors=((1.0, float("nan"), 2.0),))
            if self.mode == "inf":
                return EmbeddingResult(vectors=((1.0, float("inf"), 2.0),))
            return EmbeddingResult(vectors=((1.0, 2.0, 3.0),))

    async def scenario():
        for bad_mode in ("count", "dim", "nan", "inf"):
            p = BadProvider(bad_mode)
            m = CoalescingEmbeddingModel(p, coalesce_ms=0, cache_size=5)
            with pytest.raises(ValueError):
                await m.embed(("bad",))
            assert len(m._cache) == 0
            assert len(m._inflight) == 0

    asyncio.run(scenario())


def test_usage_accounting_fidelity() -> None:
    async def scenario():
        provider = ControllableMockProvider()
        model = CoalescingEmbeddingModel(provider, max_batch_size=2, coalesce_ms=0, cache_size=10)

        # 3 texts with batch size 2 -> 2 provider batches (2 + 1)
        res = await model.embed(("u1", "u2", "u3"))
        assert res.usage.requests == 2
        assert res.usage.input_tokens == 30

        # Full cache hit -> requests=0
        hit = await model.embed(("u1", "u2"))
        assert hit.usage.requests == 0
        assert hit.usage.input_tokens in (None, 0)

        # Partial cache hit -> 1 cached, 1 new -> 1 request
        mixed = await model.embed(("u1", "u4"))
        assert mixed.usage.requests == 1
        assert mixed.usage.input_tokens == 10

    asyncio.run(scenario())
