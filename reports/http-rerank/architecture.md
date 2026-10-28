# HTTP Memory Reranker 架构

## 数据流

Memory Search
-> FTS / vector candidates
-> existing RRF fusion
-> tuple of MemoryHit objects in coarse order
-> HTTPMemoryReranker splits bounded POST batches
-> validate each response against that batch's global ranks
-> sort all scores by score descending, then global rank ascending
-> MemoryService resolves ranks to the original MemoryHit objects
-> MemorySearchResult.hits and MemoryRerankTrace

HTTPMemoryReranker implements the existing MemoryReranker protocol. It accepts an httpx.AsyncClient supplied by the caller and never closes it. The application owns the client's lifetime, endpoint, timeout, authentication headers, and transport settings.

## Mapping and ordering

Input positions are assigned once as one-based ranks over the full candidate tuple. Each request includes only its own candidates while retaining those original ranks. Responses are validated batch by batch and accumulated into a rank-to-score mapping. The final decision sorts the complete mapping by score descending, then rank ascending, and returns no more than limit ranks.

MemoryService._reranked_search_result maps each selected rank back with hits[rank - 1]. It reuses the exact object and records the full coarse pool, selected ranks, latency, policy ID, and usage in MemoryRerankTrace. Existing MemoryHit identity fields include memory_ref, entry_id, and entry_version_id; expand() continues to resolve the selected version and its evidence.

## Configuration and ownership

The existing Runtime injection point is open_builtin_contexts(..., memory_reranker=...). The application reads its HTTP endpoint and timeout from its own existing settings, constructs the caller-owned client, then injects the adapter:

    async with httpx.AsyncClient(timeout=deployment_timeout) as client:
        reranker = HTTPMemoryReranker(
            deployment_endpoint,
            client=client,
            batch_size=deployment_batch_size,
        )
        async with open_builtin_contexts(config, memory_reranker=reranker) as contexts:
            ...

The adapter honors the httpx.AsyncClient timeout and headers without adding a second client lifecycle or changing the LLM rerank settings. With no injected reranker, the Runtime keeps its default reranking-disabled behavior.

## Errors and accounting

There are no automatic retries. A non-success HTTP status raises the original httpx.HTTPStatusError; connection, connect-timeout, read-timeout, and protocol errors propagate unchanged. Invalid JSON, duplicate JSON keys, malformed fields, non-finite scores, rank duplication, foreign ranks, or incomplete coverage raise a structural ValueError without including candidate text in the message.

Each attempted POST increments a local request counter before the call. On successful completion, InferenceUsage.requests equals the number of actual POSTs. The Memory trace exposes that value. On a failed search, the existing contract propagates the exception rather than returning a partial result or a fabricated success trace.
