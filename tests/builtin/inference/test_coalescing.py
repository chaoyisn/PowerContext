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
import math
from collections import Counter
from collections.abc import Callable

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel


class RecordingEmbedding:
    profile = EmbeddingProfile(profile_id="coalescing-test", model="offline", dimension=1)

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=tuple((float(len(text)),) for text in texts),
            usage=InferenceUsage(requests=1, input_tokens=len(texts) * 7, output_tokens=0),
        )


def test_deduplicates_batches_restores_order_and_charges_each_batch_once() -> None:
    async def scenario() -> None:
        base = RecordingEmbedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=2, coalesce_ms=0, cache_size=3)

        first, second = await asyncio.gather(
            model.embed(("alpha", "beta", "alpha")),
            model.embed(("beta", "gamma")),
        )

        assert first.vectors == ((5.0,), (4.0,), (5.0,))
        assert second.vectors == ((4.0,), (5.0,))
        assert Counter(text for call in base.calls for text in call) == Counter({"alpha": 1, "beta": 1, "gamma": 1})
        assert all(len(call) <= 2 for call in base.calls)
        assert first.usage == InferenceUsage(requests=1, input_tokens=14, output_tokens=0)
        assert second.usage == InferenceUsage(requests=2, input_tokens=21, output_tokens=0)

        cached = await model.embed(("alpha", "alpha"))
        assert cached.vectors == ((5.0,), (5.0,))
        assert cached.usage == InferenceUsage(requests=0, input_tokens=0, output_tokens=0)
        assert len(base.calls) == 2

    asyncio.run(scenario())


def test_batches_run_concurrently_and_cancelling_one_waiter_preserves_shared_work() -> None:
    class BarrierEmbedding(RecordingEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.both_started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.calls.append(texts)
            if len(self.calls) == 2:
                self.both_started.set()
            await self.release.wait()
            return EmbeddingResult(vectors=tuple((float(len(text)),) for text in texts))

    async def scenario() -> None:
        base = BarrierEmbedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        cancelled = asyncio.create_task(model.embed(("shared",)))
        survivor = asyncio.create_task(model.embed(("shared", "other")))

        await asyncio.wait_for(base.both_started.wait(), timeout=2)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        base.release.set()

        result = await asyncio.wait_for(survivor, timeout=2)
        assert result.vectors == ((6.0,), (5.0,))
        assert Counter(text for call in base.calls for text in call) == Counter({"shared": 1, "other": 1})

    asyncio.run(scenario())


def test_all_waiters_can_cancel_without_losing_the_completed_cache_entry() -> None:
    class BarrierEmbedding(RecordingEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.calls.append(texts)
            self.started.set()
            await self.release.wait()
            return EmbeddingResult(vectors=tuple((float(len(text)),) for text in texts))

    async def scenario() -> None:
        base = BarrierEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        waiters = [asyncio.create_task(model.embed(("shared",))) for _ in range(3)]
        await base.started.wait()
        for waiter in waiters:
            waiter.cancel()
        for waiter in waiters:
            with pytest.raises(asyncio.CancelledError):
                await waiter

        base.release.set()
        cached = await model.embed(("shared",))
        assert cached.vectors == ((6.0,),)
        assert len(base.calls) == 1

    asyncio.run(scenario())


def test_failures_and_invalid_vectors_are_not_cached_and_independent_batches_finish() -> None:
    class FlakyEmbedding(RecordingEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.attempts: Counter[str] = Counter()

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.calls.append(texts)
            text = texts[0]
            self.attempts[text] += 1
            if text == "failure" and self.attempts[text] == 1:
                raise ConnectionError("provider")
            if text == "bad-count" and self.attempts[text] == 1:
                return EmbeddingResult(vectors=())
            if text == "non-finite" and self.attempts[text] == 1:
                return EmbeddingResult(vectors=((math.nan,),))
            return EmbeddingResult(vectors=((float(len(text)),),))

    async def scenario() -> None:
        base = FlakyEmbedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0, cache_size=8)
        failure, independent = await asyncio.gather(
            model.embed(("failure",)),
            model.embed(("independent",)),
            return_exceptions=True,
        )
        assert isinstance(failure, ConnectionError)
        assert isinstance(independent, EmbeddingResult)
        assert independent.vectors == ((11.0,),)
        assert (await model.embed(("failure",))).vectors == ((7.0,),)

        for text in ("bad-count", "non-finite"):
            with pytest.raises(ValueError):
                await model.embed((text,))
            assert (await model.embed((text,))).vectors == ((float(len(text)),),)
            assert base.attempts[text] == 2

    asyncio.run(scenario())


def test_lru_is_bounded_and_zero_capacity_disables_only_completed_cache() -> None:
    async def scenario() -> None:
        base = RecordingEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=2)
        await model.embed(("one",))
        await model.embed(("two",))
        await model.embed(("one",))
        await model.embed(("three",))
        await model.embed(("two",))
        assert base.calls == [("one",), ("two",), ("three",), ("two",)]
        assert len(model._cache) == 2

        uncached_base = RecordingEmbedding()
        uncached = CoalescingEmbeddingModel(uncached_base, coalesce_ms=0, cache_size=0)
        await uncached.embed(("same",))
        await uncached.embed(("same",))
        assert uncached_base.calls == [("same",), ("same",)]

    asyncio.run(scenario())


def test_query_vectors_are_isolated_only_when_the_base_model_distinguishes_them() -> None:
    class AsymmetricEmbedding(RecordingEmbedding):
        async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.calls.append(texts)
            return EmbeddingResult(vectors=tuple((2.0,) for _ in texts))

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.calls.append(texts)
            return EmbeddingResult(vectors=tuple((1.0,) for _ in texts))

    async def scenario() -> None:
        base = AsymmetricEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        document, query = await asyncio.gather(model.embed(("same",)), model.embed_query(("same",)))
        cached_query = await model.embed_query(("same",))
        assert document.vectors == ((1.0,),)
        assert query.vectors == ((2.0,),)
        assert cached_query.vectors == ((2.0,),)
        assert len(base.calls) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "create_model",
    [
        lambda model: CoalescingEmbeddingModel(model, max_batch_size=0),
        lambda model: CoalescingEmbeddingModel(model, coalesce_ms=-1),
        lambda model: CoalescingEmbeddingModel(model, coalesce_ms=math.inf),
        lambda model: CoalescingEmbeddingModel(model, cache_size=-1),
    ],
)
def test_configuration_bounds_are_checked(
    create_model: Callable[[RecordingEmbedding], CoalescingEmbeddingModel],
) -> None:
    with pytest.raises(ValueError):
        create_model(RecordingEmbedding())
