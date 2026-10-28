"""Exercise the integrated competition features together through the public Runtime."""

import importlib
import json

import httpx

from powercontext.builtin.artifacts.memory.http_reranker import HTTPMemoryReranker
from powercontext.builtin.runtime import (
    GetMemoryEntryRequest,
    PrepareContextRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackDelta, apply_context_pack_delta
from powercontext.sources import (
    CSV_ROW_SOURCE_DEFINITION,
    PI_EVENT_SOURCE_DEFINITION,
    CSVDocumentInput,
    PiSessionInput,
    SourceDefinitionRegistry,
    manifest_for_definition,
    parse_csv_document,
    parse_pi_session,
    project_source_for_transport,
)

checks = importlib.import_module("challenges.processing-01-count-trigger.acceptance.checks")


async def test_csv_pi_count_trigger_and_http_rerank_together(tmp_path, monkeypatch):
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION, PI_EVENT_SOURCE_DEFINITION))
    csv_row = parse_csv_document(
        CSVDocumentInput(document_id="integrated", primary_key="id", content=b"id,text\n1,csv evidence\n")
    )[0]
    pi_lines = [
        {"type": "session", "version": 3, "id": "integrated-pi"},
        {"type": "message", "id": "p1", "parentId": None, "message": {"role": "user", "content": "pi evidence"}},
    ]
    pi_event = parse_pi_session(PiSessionInput(content="\n".join(map(json.dumps, pi_lines)).encode()))[0]
    observations = [
        project_source_for_transport(registry, await registry.resolve(item)) for item in (csv_row, pi_event)
    ]
    calls = []

    def scorer(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(
            200, json={"scores": [{"rank": item["rank"], "score": item["rank"]} for item in payload["candidates"]]}
        )

    with checks.provider(monkeypatch) as server:
        settings = checks.config(
            tmp_path / "integrated.db", server, memory_source_count_threshold=2, memory_rerank_enabled=True
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(scorer)) as client:
            reranker = HTTPMemoryReranker("https://rerank.invalid/score", client=client, batch_size=1)
            async with open_builtin_runtime(settings, memory_reranker=reranker) as runtime:
                sid = await checks.scope(runtime)
                for definition in (CSV_ROW_SOURCE_DEFINITION, PI_EVENT_SOURCE_DEFINITION):
                    await runtime.ingestion.register(manifest_for_definition(definition))
                first = await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=sid, observation=observations[0])
                )
                await checks.stay_refs(runtime, sid, "memory", set())
                second = await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=sid, observation=observations[1])
                )
                expected = checks.receipt_refs([first, second])
                await checks.wait_refs(runtime, sid, "memory", expected)
                app = runtime.memory.for_scope(sid)
                page = await app.search(SearchMemoryRequest(query="CountEvidence", mode="fts", limit=2))
                assert page.rerank is not None
                assert page.rerank.selected_ranks == (2, 1)
                assert page.rerank.usage.requests == len(calls) == 2
                assert page.hits == tuple(page.rerank.candidate_hits[i - 1] for i in (2, 1))
                entries = (await app.list()).entries
                for row in entries:
                    assert (await app.get(GetMemoryEntryRequest(citation=row.citation))).entry == row.entry
                context = runtime.context.for_scope(sid)
                request = PrepareContextRequest(query="CountEvidence", max_bytes=4096)
                base = await context.prepare_incremental(request=request)
                assert isinstance(base, ContextPack)
                delta = await context.prepare_incremental(request=request, base_pack=base)
                assert isinstance(delta, ContextPackDelta)
                rebuilt = apply_context_pack_delta(
                    ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(delta.to_bytes())
                )
                assert b"".join(rebuilt.items).decode("utf-8") == (await context.prepare(request)).content
            async with open_builtin_runtime(settings, memory_reranker=reranker) as runtime:
                assert await checks.source_refs(runtime, sid, "memory") == expected
