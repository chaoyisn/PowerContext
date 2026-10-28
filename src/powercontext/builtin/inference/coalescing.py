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

"""Coalesce concurrent embedding work and retain successful vectors in an LRU."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel, QueryEmbeddingModel

_EmbeddingKind = Literal["document", "query"]
_EmbeddingKey = tuple[_EmbeddingKind, str]


@dataclass(frozen=True, slots=True, eq=False)
class _BatchUsage:
    usage: InferenceUsage


@dataclass(frozen=True, slots=True)
class _CompletedEmbedding:
    vector: EmbeddingVector
    batch: _BatchUsage | None


class CoalescingEmbeddingModel:
    """Share overlapping text embeddings, batch new work, and cache successes.

    State is owned by one event loop. A wrapper belongs to one base model/profile, so its
    bounded cache cannot mix vectors from different deployments. Query embeddings use a
    separate key when the base model distinguishes query and document inputs.
    """

    def __init__(
        self,
        model: EmbeddingModel | None = None,
        *,
        base_model: EmbeddingModel | None = None,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        target_model = model if model is not None else base_model
        if target_model is None:
            raise TypeError("model is required")
        if isinstance(max_batch_size, bool) or not isinstance(max_batch_size, int) or max_batch_size < 1:
            raise ValueError("max_batch_size")
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce_ms")
        if isinstance(cache_size, bool) or not isinstance(cache_size, int) or cache_size < 0:
            raise ValueError("cache_size")

        self.model = target_model
        self.base_model = target_model
        self._base_model = target_model
        self.profile = target_model.profile
        self._query_model: QueryEmbeddingModel | None = None
        if isinstance(target_model, QueryEmbeddingModel):
            self._query_model = target_model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[_EmbeddingKey, EmbeddingVector] = OrderedDict()
        self._inflight: dict[_EmbeddingKey, asyncio.Future[_CompletedEmbedding]] = {}
        self._pending: dict[_EmbeddingKey, asyncio.Future[_CompletedEmbedding]] = {}
        self._flush_task: asyncio.Task[None] | None = None
        self._batch_tasks: set[asyncio.Task[None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def embed(
        self,
        texts: Sequence[str] | tuple[str, ...] | None = None,
        *args: object,
        **kwargs: object,
    ) -> EmbeddingResult:
        """Embed documents and preserve input order, including duplicate positions."""
        if texts is None and "texts" in kwargs:
            texts = kwargs["texts"]  # type: ignore[assignment]
        elif texts is None and args:
            texts = args[0]  # type: ignore[assignment]
        if texts is None:
            texts = ()
        return await self._embed(tuple(texts), kind="document")

    async def embed_query(
        self,
        texts: Sequence[str] | tuple[str, ...] | None = None,
        *args: object,
        **kwargs: object,
    ) -> EmbeddingResult:
        """Embed queries, sharing document results only for symmetric models."""
        if texts is None and "texts" in kwargs:
            texts = kwargs["texts"]  # type: ignore[assignment]
        elif texts is None and args:
            texts = args[0]  # type: ignore[assignment]
        if texts is None:
            texts = ()
        kind: _EmbeddingKind = "query" if self._query_model is not None else "document"
        return await self._embed(tuple(texts), kind=kind)

    async def _embed(self, texts: tuple[str, ...], *, kind: _EmbeddingKind) -> EmbeddingResult:
        ordered_texts = tuple(texts)
        if not ordered_texts:
            return EmbeddingResult(
                vectors=(),
                usage=InferenceUsage(requests=0, input_tokens=0, output_tokens=0),
            )

        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop and (self._inflight or self._batch_tasks):
            raise RuntimeError("event-loop")
        self._loop = loop

        completed, waiting, added_work = self._resolve_inputs(ordered_texts, kind=kind, loop=loop)
        if added_work:
            self._schedule_flush(loop)
        if waiting:
            keys = tuple(waiting)
            values = await asyncio.gather(*(asyncio.shield(waiting[key]) for key in keys))
            completed.update(zip(keys, values, strict=True))

        usages: dict[_BatchUsage, InferenceUsage] = {}
        for value in completed.values():
            if value.batch is not None:
                usages.setdefault(value.batch, value.batch.usage)

        vectors = tuple(completed[(kind, text)].vector for text in ordered_texts)
        return EmbeddingResult(vectors=vectors, usage=_sum_usage(tuple(usages.values())))

    def _resolve_inputs(
        self,
        texts: tuple[str, ...],
        *,
        kind: _EmbeddingKind,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[
        dict[_EmbeddingKey, _CompletedEmbedding],
        dict[_EmbeddingKey, asyncio.Future[_CompletedEmbedding]],
        bool,
    ]:
        completed: dict[_EmbeddingKey, _CompletedEmbedding] = {}
        waiting: dict[_EmbeddingKey, asyncio.Future[_CompletedEmbedding]] = {}
        added_work = False
        for text in texts:
            key = (kind, text)
            if key in completed or key in waiting:
                continue
            cached = self._cache_hit(key)
            if cached is not None:
                completed[key] = _CompletedEmbedding(cached, None)
                continue
            future = self._inflight.get(key)
            if future is None:
                future = self._create_flight(loop, key)
                added_work = True
            waiting[key] = future
        return completed, waiting, added_work

    def _cache_hit(self, key: _EmbeddingKey) -> EmbeddingVector | None:
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
        return cached

    def _create_flight(
        self,
        loop: asyncio.AbstractEventLoop,
        key: _EmbeddingKey,
    ) -> asyncio.Future[_CompletedEmbedding]:
        future = loop.create_future()
        future.add_done_callback(_consume_future_exception)
        self._inflight[key] = future
        self._pending[key] = future
        return future

    def _schedule_flush(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = loop.create_task(self._flush())
            self._flush_task.add_done_callback(self._flush_done)

    async def _flush(self) -> None:
        try:
            while self._pending:
                await asyncio.sleep(self._coalesce_seconds)
                pending = tuple(self._pending.items())
                self._pending.clear()
                by_kind: dict[_EmbeddingKind, list[tuple[_EmbeddingKey, asyncio.Future[_CompletedEmbedding]]]] = {}
                for item in pending:
                    by_kind.setdefault(item[0][0], []).append(item)
                for items in by_kind.values():
                    for start in range(0, len(items), self._max_batch_size):
                        self._start_batch(items[start : start + self._max_batch_size])
        except asyncio.CancelledError:
            for key, future in tuple(self._pending.items()):
                self._pending.pop(key, None)
                if self._inflight.get(key) is future:
                    self._inflight.pop(key, None)
                future.cancel()
            raise
        finally:
            self._flush_task = None

    def _flush_done(self, task: asyncio.Task[None]) -> None:
        if self._flush_task is task:
            self._flush_task = None
            if task.cancelled():
                for key, future in tuple(self._pending.items()):
                    self._pending.pop(key, None)
                    if self._inflight.get(key) is future:
                        self._inflight.pop(key, None)
                    future.cancel()
        _consume_task_exception(task)

    def _start_batch(self, items: Sequence[tuple[_EmbeddingKey, asyncio.Future[_CompletedEmbedding]]]) -> None:
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._run_batch(tuple(items)))
        self._batch_tasks.add(task)
        task.add_done_callback(self._batch_tasks.discard)
        task.add_done_callback(_consume_task_exception)

    async def _run_batch(
        self,
        items: tuple[tuple[_EmbeddingKey, asyncio.Future[_CompletedEmbedding]], ...],
    ) -> None:
        keys = tuple(key for key, _future in items)
        futures = tuple(future for _key, future in items)
        texts = tuple(key[1] for key in keys)
        try:
            result = await self._call_base(keys[0][0], texts)
            vectors = _validate_vectors(result.vectors, expected_count=len(texts), dimension=self.profile.dimension)
            self._complete_batch(keys, futures, vectors, getattr(result, "usage", None))
        except asyncio.CancelledError:
            self._cancel_batch(futures)
            raise
        except Exception as error:
            self._fail_batch(futures, error)
        finally:
            self._remove_batch(keys, futures)

    def _complete_batch(
        self,
        keys: tuple[_EmbeddingKey, ...],
        futures: tuple[asyncio.Future[_CompletedEmbedding], ...],
        vectors: tuple[EmbeddingVector, ...],
        usage: InferenceUsage | None,
    ) -> None:
        actual_usage = usage if isinstance(usage, InferenceUsage) else InferenceUsage(requests=1)
        batch = _BatchUsage(actual_usage.model_copy(deep=True))
        for key, future, vector in zip(keys, futures, vectors, strict=True):
            if self._cache_size:
                self._cache[key] = vector
                self._cache.move_to_end(key)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            if not future.done():
                future.set_result(_CompletedEmbedding(vector, batch))

    @staticmethod
    def _cancel_batch(futures: tuple[asyncio.Future[_CompletedEmbedding], ...]) -> None:
        for future in futures:
            if not future.done():
                future.cancel()

    @staticmethod
    def _fail_batch(futures: tuple[asyncio.Future[_CompletedEmbedding], ...], error: Exception) -> None:
        for future in futures:
            if not future.done():
                future.set_exception(error)

    def _remove_batch(
        self,
        keys: tuple[_EmbeddingKey, ...],
        futures: tuple[asyncio.Future[_CompletedEmbedding], ...],
    ) -> None:
        for key, future in zip(keys, futures, strict=True):
            if self._inflight.get(key) is future:
                self._inflight.pop(key, None)

    async def _call_base(self, kind: _EmbeddingKind, texts: tuple[str, ...]) -> EmbeddingResult:
        if kind == "query" and self._query_model is not None:
            return await self._query_model.embed_query(texts)
        return await self._base_model.embed(texts)


def _validate_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
    dimension: int,
) -> tuple[EmbeddingVector, ...]:
    if len(vectors) != expected_count:
        raise ValueError("vector-count")
    validated: list[EmbeddingVector] = []
    for vector in vectors:
        value = tuple(float(component) for component in vector)
        if len(value) != dimension:
            raise ValueError("vector-dimension")
        if not all(math.isfinite(component) for component in value):
            raise ValueError("vector-finite")
        validated.append(value)
    return tuple(validated)


def _sum_usage(usages: tuple[InferenceUsage, ...]) -> InferenceUsage:
    if not usages:
        return InferenceUsage(requests=0, input_tokens=0, output_tokens=0)

    def total(field: Literal["input_tokens", "output_tokens"]) -> int | None:
        values = tuple(getattr(usage, field) for usage in usages if usage is not None)
        non_none = [v for v in values if v is not None]
        if not non_none:
            return None
        return sum(non_none)

    return InferenceUsage(
        requests=sum(usage.requests for usage in usages if usage is not None),
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
    )


def _consume_future_exception(future: asyncio.Future[object]) -> None:
    if not future.cancelled():
        future.exception()


def _consume_task_exception(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = ["CoalescingEmbeddingModel"]
