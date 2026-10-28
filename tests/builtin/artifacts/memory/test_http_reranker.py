"""Boundary and regression tests for the batched HTTP Memory reranker."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.http_reranker import (
    HTTPMemoryReranker,
    HTTPRerankResponseError,
)
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import (
    LLMMemoryReranker,
    MemoryRerankInput,
    MemoryRerankOutput,
)
from powercontext.builtin.inference import GenerationResult, InferenceUsage
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts

ENDPOINT = "https://reranker.invalid/score"


def _hit(rank: int, text: str | None = None) -> MemoryHit:
    return MemoryHit(
        memory_ref=ArtifactRef(family="memory", artifact_id="m", revision=1),
        entry_id=f"e{rank}",
        entry_version_id=f"v{rank}",
        text=text if text is not None else f"candidate {rank}",
        score=1.0 / rank,
        matched_by=("fts",),
    )


def _pool(count: int) -> tuple[MemoryHit, ...]:
    return tuple(_hit(rank) for rank in range(1, count + 1))


class ScoringService:
    """Stateful offline scorer: deterministic score function, optional per-call faults."""

    def __init__(
        self,
        score_of: Callable[[int, str], float],
        *,
        reverse: bool = False,
        fault: Callable[[int], httpx.Response | None] | None = None,
    ) -> None:
        self.score_of = score_of
        self.reverse = reverse
        self.fault = fault
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.fault is not None:
            response = self.fault(len(self.bodies))
            if response is not None:
                return response
        scores = [
            {"rank": item["rank"], "score": self.score_of(item["rank"], item["text"])} for item in body["candidates"]
        ]
        if self.reverse:
            scores.reverse()
        return httpx.Response(200, json={"scores": scores})

    @property
    def sent_ranks(self) -> list[int]:
        return [item["rank"] for body in self.bodies for item in body["candidates"]]


def _run(
    service: Callable[[httpx.Request], httpx.Response],
    candidates: tuple[MemoryHit, ...],
    limit: int,
    *,
    batch_size: int,
    query: str = "q",
):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            return await HTTPMemoryReranker(ENDPOINT, client=client, batch_size=batch_size).rerank(
                query, candidates, limit
            )

    return asyncio.run(scenario())


def _expected(scores: dict[int, float], limit: int) -> tuple[int, ...]:
    return tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit])


# --- batching -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "batch_size"),
    [(1, 4), (3, 4), (4, 4), (5, 4), (9, 4), (11, 4), (1, 1), (7, 1), (173, 7), (100, 32)],
)
def test_batch_boundaries_cover_every_rank_once(count: int, batch_size: int) -> None:
    service = ScoringService(lambda rank, _text: math.sin(rank * 7.3))
    decision = _run(service, _pool(count), count, batch_size=batch_size)
    assert decision.usage.requests == math.ceil(count / batch_size) == len(service.bodies)
    assert sorted(service.sent_ranks) == list(range(1, count + 1))
    assert all(1 <= len(body["candidates"]) <= batch_size for body in service.bodies)
    for body in service.bodies:
        assert body["query"] == "q"
        assert set(body) == {"query", "candidates"}
        for item in body["candidates"]:
            assert set(item) == {"rank", "text"}
            assert item["text"] == f"candidate {item['rank']}"
    scores = {rank: math.sin(rank * 7.3) for rank in range(1, count + 1)}
    assert decision.selected_ranks == _expected(scores, count)
    assert decision.used_fallback is False
    assert decision.discarded_rank_count == 0


def test_last_batch_best_candidate_wins_globally() -> None:
    service = ScoringService(lambda rank, _text: 10.0 if rank == 9 else 1.0 / rank)
    decision = _run(service, _pool(9), 3, batch_size=4)
    assert decision.selected_ranks == (9, 1, 2)
    assert decision.usage.requests == 3


def test_instruction_example_cross_batch_tie_uses_original_rank() -> None:
    table = {1: 0.10, 2: 0.90, 3: 0.95, 4: 0.90}
    service = ScoringService(lambda rank, _text: table[rank])
    decision = _run(service, _pool(4), 2, batch_size=2)
    assert decision.selected_ranks == (3, 2)
    assert decision.usage.requests == 2


def test_all_equal_scores_keep_original_order_and_limit() -> None:
    service = ScoringService(lambda _rank, _text: 0.5, reverse=True)
    decision = _run(service, _pool(10), 6, batch_size=3)
    assert decision.selected_ranks == (1, 2, 3, 4, 5, 6)


def test_negative_zero_and_integer_scores_are_valid() -> None:
    table = {1: -2.5, 2: 0, 3: -0.0, 4: 3, 5: -1e-9}
    service = ScoringService(lambda rank, _text: table[rank])
    decision = _run(service, _pool(5), 5, batch_size=2)
    assert decision.selected_ranks == (4, 2, 3, 5, 1)


def test_scoring_depends_on_text_not_position() -> None:
    texts = ("alpha", "beta", "gamma", "delta", "epsilon")
    candidates = tuple(_hit(rank, text) for rank, text in enumerate(texts, start=1))
    service = ScoringService(lambda _rank, text: float(len(text)), reverse=True)
    decision = _run(service, candidates, 3, batch_size=2)
    assert decision.selected_ranks == (5, 1, 3)  # len 7, then len-5 ties by original rank


def test_repeated_runs_are_deterministic() -> None:
    service = ScoringService(lambda rank, _text: float(rank % 3))
    results = {_run(service, _pool(20), 10, batch_size=6).selected_ranks for _ in range(5)}
    assert len(results) == 1
    assert len(service.bodies) == 5 * 4


def test_unicode_query_and_text_are_sent_verbatim() -> None:
    candidates = (_hit(1, "数据库连接超时 🚀"), _hit(2, 'quote " comma , newline\n'))
    service = ScoringService(lambda rank, _text: float(rank))
    decision = _run(service, candidates, 1, batch_size=8, query="连接超时怎么排查")
    assert decision.selected_ranks == (2,)
    assert service.bodies[0]["query"] == "连接超时怎么排查"
    assert [item["text"] for item in service.bodies[0]["candidates"]] == [c.text for c in candidates]


def test_candidates_are_not_mutated() -> None:
    candidates = _pool(5)
    snapshot = tuple(hit.model_dump() for hit in candidates)
    _run(ScoringService(lambda rank, _text: float(rank)), candidates, 2, batch_size=2)
    assert tuple(hit.model_dump() for hit in candidates) == snapshot


# --- argument validation --------------------------------------------------------------------


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5])
def test_rejects_invalid_batch_size(batch_size) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(500))) as client:
            with pytest.raises(ValueError):
                HTTPMemoryReranker(ENDPOINT, client=client, batch_size=batch_size)

    asyncio.run(scenario())


def test_defaults_match_contract() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient() as client:
            reranker = HTTPMemoryReranker(ENDPOINT, client=client)
            assert reranker.batch_size == 32
            assert reranker.policy_id == "http-cross-encoder-v1"
            assert HTTPMemoryReranker(ENDPOINT, client=client, policy_id="custom").policy_id == "custom"
            with pytest.raises(ValueError):
                HTTPMemoryReranker(ENDPOINT, client=client, policy_id=" ")

    asyncio.run(scenario())


@pytest.mark.parametrize(("count", "limit"), [(0, 1), (2, 0), (2, 3), (2, -1)])
def test_invalid_bounds_raise_without_requests(count: int, limit: int) -> None:
    service = ScoringService(lambda rank, _text: float(rank))
    with pytest.raises(ValueError):
        _run(service, _pool(count), limit, batch_size=2)
    assert service.bodies == []


# --- response validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not json",
        b'{"scores": [], "scores": []}',
        b'{"scores": [{"rank": 1, "rank": 1, "score": 0.1}]}',
        b"\xff\xfe",
        b"[]",
        b"null",
        b'{"scores": {}}',
        b'{"score": []}',
        b'{"scores": [], "extra": 1}',
        b'{"scores": []}',
        b'{"scores": [{"rank": 1, "score": 0.1}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2, "score": 0.2}, {"rank": 3, "score": 0.3}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 1, "score": 0.2}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 0, "score": 0.2}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": "2", "score": 0.2}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2.0, "score": 0.2}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": true, "score": 0.2}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2, "score": "0.2"}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2, "score": null}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2, "score": false}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2, "score": NaN}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2, "score": -Infinity}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2, "score": 1e999}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2, "score": 1' + b"0" * 400 + b"}]}",
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, {"rank": 2, "score": 0.2, "id": "x"}]}',
        b'{"scores": [{"rank": 1, "score": 0.1}, [2, 0.2]]}',
    ],
)
def test_invalid_response_bodies_raise_value_error(content: bytes) -> None:
    def service(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    with pytest.raises(ValueError):
        _run(service, _pool(2), 1, batch_size=2)


def test_cross_batch_rank_is_rejected() -> None:
    def service(request: httpx.Request) -> httpx.Response:
        ranks = [item["rank"] for item in json.loads(request.content)["candidates"]]
        if ranks == [3, 4]:
            ranks = [1, 4]  # rank 1 belongs to the first batch
        return httpx.Response(200, json={"scores": [{"rank": rank, "score": 0.5} for rank in ranks]})

    with pytest.raises(HTTPRerankResponseError):
        _run(service, _pool(4), 2, batch_size=2)


def test_local_batch_index_is_rejected() -> None:
    def service(request: httpx.Request) -> httpx.Response:
        count = len(json.loads(request.content)["candidates"])
        return httpx.Response(200, json={"scores": [{"rank": i, "score": 0.5} for i in range(1, count + 1)]})

    with pytest.raises(ValueError):
        _run(service, _pool(4), 2, batch_size=2)


# --- HTTP and transport errors --------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 404, 429, 500, 503])
def test_non_2xx_raises_http_status_error(status: int) -> None:
    service = ScoringService(lambda rank, _text: float(rank), fault=lambda _n: httpx.Response(status, json={}))
    with pytest.raises(httpx.HTTPStatusError) as caught:
        _run(service, _pool(3), 1, batch_size=2)
    assert caught.value.response.status_code == status
    assert len(service.bodies) == 1


def test_redirect_is_not_treated_as_success() -> None:
    service = ScoringService(
        lambda rank, _text: float(rank),
        fault=lambda _n: httpx.Response(307, headers={"location": "https://elsewhere.invalid"}),
    )
    with pytest.raises(httpx.HTTPStatusError):
        _run(service, _pool(1), 1, batch_size=2)


@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError]
)
def test_transport_errors_propagate_unwrapped(error_type: type[httpx.TransportError]) -> None:
    def service(request: httpx.Request) -> httpx.Response:
        raise error_type("offline", request=request)

    with pytest.raises(error_type):
        _run(service, _pool(2), 1, batch_size=1)


def test_partial_batch_failure_stops_and_propagates() -> None:
    service = ScoringService(
        lambda rank, _text: float(rank),
        fault=lambda n: httpx.Response(500) if n == 2 else None,
    )
    with pytest.raises(httpx.HTTPStatusError):
        _run(service, _pool(7), 3, batch_size=3)
    assert len(service.bodies) == 2  # no hidden retries, no requests after the failure


def test_client_remains_usable_and_is_not_closed() -> None:
    async def scenario() -> None:
        service = ScoringService(lambda rank, _text: float(rank))
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            reranker = HTTPMemoryReranker(ENDPOINT, client=client, batch_size=2)
            first = await reranker.rerank("q", _pool(3), 1)
            second = await reranker.rerank("q", _pool(5), 2)
            assert not client.is_closed
        assert first.usage.requests == 2
        assert second.usage.requests == 3
        assert first.selected_ranks == (3,)
        assert second.selected_ranks == (5, 4)

    asyncio.run(scenario())


# --- native Memory integration and compatibility --------------------------------------------


def test_native_search_preserves_identity_and_reports_real_request_count() -> None:
    service = ScoringService(lambda _rank, text: 1.0 if "gamma" in text else 0.0)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            reranker = HTTPMemoryReranker(ENDPOINT, client=client, batch_size=2)
            async with open_builtin_contexts(BuiltinConfig(database=SQLiteConfig()), memory_reranker=reranker) as ctx:
                memory_service = (await ctx.get("retrieval-01-local-native")).artifacts.memory
                memory = await memory_service.remember(
                    memory=None,
                    entries=tuple(
                        MemoryEntryInput(kind="fact", text=f"Project {name} fact.")
                        for name in ("alpha", "beta", "gamma", "delta", "epsilon")
                    ),
                    mode="append",
                )
                assert memory is not None
                result = await memory_service.search("project", memories=(memory,), limit=2, mode="fts")
                assert result.rerank is not None
                trace = result.rerank
                pool = trace.candidate_hits
                assert trace.policy_id == "http-cross-encoder-v1"
                assert trace.usage.requests == len(service.bodies) == math.ceil(len(pool) / 2)
                assert len(result.hits) == 2
                for hit, rank in zip(result.hits, trace.selected_ranks, strict=True):
                    assert hit is pool[rank - 1]
                assert "gamma" in result.hits[0].text
                for hit in result.hits:
                    assert (hit.memory_ref.artifact_id, hit.memory_ref.revision) == (
                        memory.artifact_id,
                        memory.revision,
                    )
                versions = await memory_service.expand(result.hits)
                assert [v.entry_version_id for v in versions] == [h.entry_version_id for h in result.hits]

    asyncio.run(scenario())


class _FakeGenerator:
    def __init__(self, ranks: tuple[int, ...]) -> None:
        self.ranks = ranks
        self.inputs: list[MemoryRerankInput] = []

    async def generate(self, value: MemoryRerankInput) -> GenerationResult[MemoryRerankOutput]:
        self.inputs.append(value)
        return GenerationResult(
            output=MemoryRerankOutput(selected_ranks=self.ranks),
            usage=InferenceUsage(requests=1, input_tokens=10, output_tokens=2),
        )


def test_llm_reranker_behavior_is_unchanged() -> None:
    generator = _FakeGenerator((3, 3, 9, 1))
    decision = asyncio.run(LLMMemoryReranker(generator).rerank("q", _pool(4), 2))
    assert decision.selected_ranks == (3, 1)
    assert decision.discarded_rank_count == 2
    assert decision.usage.requests == 1
    assert len(generator.inputs[0].candidates) == 4

    fallback = asyncio.run(LLMMemoryReranker(_FakeGenerator(())).rerank("q", _pool(4), 2))
    assert fallback.used_fallback is True
    assert fallback.selected_ranks == (1, 2)


def test_search_without_reranker_is_unchanged() -> None:
    async def scenario() -> None:
        async with open_builtin_contexts(BuiltinConfig(database=SQLiteConfig())) as ctx:
            memory_service = (await ctx.get("retrieval-01-no-rerank")).artifacts.memory
            memory = await memory_service.remember(
                memory=None,
                entries=(MemoryEntryInput(kind="fact", text="Project alpha fact."),),
                mode="append",
            )
            assert memory is not None
            result = await memory_service.search("project", memories=(memory,), limit=1, mode="fts")
            assert result.rerank is None
            assert len(result.hits) == 1

    asyncio.run(scenario())
