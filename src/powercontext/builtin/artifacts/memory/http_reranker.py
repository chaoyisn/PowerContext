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

"""Pointwise Memory reranking through a batched HTTP scoring service.

Protocol (one POST per batch, JSON bodies)::

    request:  {"query": str, "candidates": [{"rank": int, "text": str}, ...]}
    response: {"scores": [{"rank": int, "score": finite number}, ...]}

``rank`` is always the one-based position in the *complete* candidate pool; batching never
renumbers candidates. Every batch response must cover exactly the ranks sent in that batch.
Scores from all batches participate in one global selection ordered by score descending and,
for equal scores, by original rank ascending.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any, ClassVar

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

HTTP_RERANK_POLICY_ID = "http-cross-encoder-v1"
DEFAULT_HTTP_RERANK_BATCH_SIZE = 32

_RESPONSE_KEYS = frozenset({"scores"})
_SCORE_KEYS = frozenset({"rank", "score"})


class HTTPRerankArgumentError(ValueError):
    """A reranker construction or call argument violates the HTTP rerank contract."""

    _MESSAGES: ClassVar[Mapping[str, str]] = {
        "endpoint": "HTTP rerank endpoint must be a non-empty string",
        "batch-size": "HTTP rerank batch_size must be a positive integer",
        "policy-id": "HTTP rerank policy_id must be a non-empty string",
        "candidates": "rerank requires at least one candidate",
        "limit": "rerank limit must be between one and the candidate count",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._MESSAGES.get(code, f"invalid HTTP rerank argument: {code}"))


class HTTPRerankResponseError(ValueError):
    """The scoring service returned a body that violates the offline rerank protocol.

    Messages carry only structural reasons and ranks, never query or candidate text.
    """

    _MESSAGES: ClassVar[Mapping[str, str]] = {
        "json": "body is not valid JSON",
        "body-shape": "body must be an object with exactly 'scores'",
        "scores-type": "'scores' must be a list",
        "entry-shape": "each score must be an object with exactly 'rank' and 'score'",
        "rank-type": "score rank must be an integer",
        "rank-foreign": "score rank was not sent in this batch",
        "rank-duplicate": "score rank is duplicated",
        "coverage": "response does not cover every rank in the batch",
        "score-type": "score must be a number",
        "score-range": "score is out of the float range",
        "score-finite": "score must be finite",
    }

    def __init__(self, code: str, rank: int | None = None) -> None:
        self.code = code
        self.rank = rank
        message = self._MESSAGES.get(code, code)
        if rank is not None:
            message = f"{message}: {rank}"
        super().__init__(f"invalid HTTP rerank response: {message}")


class HTTPMemoryReranker:
    """Select Memory hits with scores from an HTTP service, batching under a size cap.

    The caller owns ``client``; this adapter never closes it. Non-2xx responses and transport
    failures propagate as the original ``httpx`` exceptions, without retries. Malformed JSON or
    schema violations raise ``ValueError``. Candidate identity is never rewritten: the decision
    only carries original ranks, which the Memory service maps back onto its own ``MemoryHit``
    objects.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = DEFAULT_HTTP_RERANK_BATCH_SIZE,
        policy_id: str = HTTP_RERANK_POLICY_ID,
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise HTTPRerankArgumentError("endpoint")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise HTTPRerankArgumentError("batch-size")
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise HTTPRerankArgumentError("policy-id")
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    @property
    def endpoint(self) -> str:
        """Return the configured scoring endpoint."""

        return self._endpoint

    @property
    def batch_size(self) -> int:
        """Return the maximum number of candidates sent in one HTTP request."""

        return self._batch_size

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every candidate in bounded batches and select the global top ``limit``."""

        candidate_count = len(candidates)
        if candidate_count < 1:
            raise HTTPRerankArgumentError("candidates")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= candidate_count:
            raise HTTPRerankArgumentError("limit")

        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, candidate_count, self._batch_size):
            batch_ranks = tuple(range(start + 1, min(start + self._batch_size, candidate_count) + 1))
            payload = {
                "query": query,
                "candidates": [{"rank": rank, "text": candidates[rank - 1].text} for rank in batch_ranks],
            }
            requests += 1
            response = await self._client.post(self._endpoint, json=payload)
            response.raise_for_status()
            scores.update(_parse_batch_scores(response.content, batch_ranks))

        # Every rank 1..N is present: batches partition the pool and each batch is fully covered.
        order = sorted(scores, key=lambda rank: (-scores[rank], rank))
        return MemoryRerankDecision(
            selected_ranks=tuple(order[:limit]),
            usage=InferenceUsage(requests=requests),
        )


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for key, value in pairs:
        if key in body:
            raise HTTPRerankResponseError("json")
        body[key] = value
    return body


def _parse_batch_scores(content: bytes, batch_ranks: tuple[int, ...]) -> dict[int, float]:
    try:
        body: Any = json.loads(content, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPRerankResponseError("json") from error
    if not isinstance(body, Mapping) or set(body) != _RESPONSE_KEYS:
        raise HTTPRerankResponseError("body-shape")
    entries = body["scores"]
    if not isinstance(entries, list):
        raise HTTPRerankResponseError("scores-type")
    expected = frozenset(batch_ranks)
    parsed: dict[int, float] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != _SCORE_KEYS:
            raise HTTPRerankResponseError("entry-shape")
        rank = entry["rank"]
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise HTTPRerankResponseError("rank-type")
        if rank not in expected:
            raise HTTPRerankResponseError("rank-foreign", rank)
        if rank in parsed:
            raise HTTPRerankResponseError("rank-duplicate", rank)
        parsed[rank] = _finite_score(entry["score"])
    if len(parsed) != len(expected):
        raise HTTPRerankResponseError("coverage")
    return parsed


def _finite_score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise HTTPRerankResponseError("score-type")
    try:
        score = float(value)
    except OverflowError as error:
        raise HTTPRerankResponseError("score-range") from error
    if not math.isfinite(score):
        raise HTTPRerankResponseError("score-finite")
    return score


__all__ = [
    "DEFAULT_HTTP_RERANK_BATCH_SIZE",
    "HTTP_RERANK_POLICY_ID",
    "HTTPMemoryReranker",
    "HTTPRerankArgumentError",
    "HTTPRerankResponseError",
]
