"""Run against the public workload using the official fixture, without gold data."""

import asyncio
import json
import re
import tempfile
import time
from pathlib import Path

from powercontext.builtin.runtime import GetMemoryEntryRequest, open_builtin_runtime
from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pdf_pages import PDFDocumentInput, PDF_PAGE_SOURCE_DEFINITION, parse_pdf_document, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from selftest_support.source_acceptance import persist


async def main():
    workload = Path('/selftest/challenges/source-03-pdf-retrieval/workload/public')
    case = json.loads((workload / 'cases.json').read_text())['cases'][0]
    start = time.perf_counter()
    pages = parse_pdf_document(PDFDocumentInput(document_id=case['document_id'], content=(workload / case['file']).read_bytes()))
    parse_seconds = time.perf_counter() - start
    counts = [len(re.findall(r'[a-z]+|\d+', p.text.lower())) for p in pages]
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
    with tempfile.TemporaryDirectory() as directory:
        start = time.perf_counter()
        config, scope, stored = await persist(Path(directory), PDF_PAGE_SOURCE_DEFINITION, observations)
        persist_seconds = time.perf_counter() - start
        queries = []
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope)
            for item in case['questions']:
                start = time.perf_counter()
                citations = await search_pdf_pages(memory, item['question'], 20)
                locations = []
                for citation in citations:
                    record = await memory.get(GetMemoryEntryRequest(citation=citation))
                    ref = record.entry.sources[0]
                    metadata = stored[ref.source_id].projection(TEXT_EVIDENCE_PROJECTION_KEY)['metadata']
                    locations.append(metadata['page_number'])
                queries.append({'question': item['question'], 'pages': locations,
                                'seconds_including_recheck': round(time.perf_counter() - start, 3)})
    print(json.dumps({'pages': len(pages), 'parse_seconds': round(parse_seconds, 3),
                      'persistence_seconds': round(persist_seconds, 3), 'empty_pages': sum(not p.text for p in pages),
                      'token_counts': counts, 'queries': queries}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
