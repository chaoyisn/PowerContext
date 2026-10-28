"""Offline PDF physical pages and scoped evidence retrieval."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass

from pydantic import BaseModel
from pypdf import PdfReader

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.runtime import GetMemoryEntryRequest, SearchMemoryRequest
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TextEvidence


class PDFDocumentInput(BaseModel):
    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    if not value.document_id.strip() or not value.content.startswith(b"%PDF-"):
        raise ValueError("invalid document id or PDF")
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")
        if not len(reader.pages):
            raise ValueError("PDF has no pages")
        digest = hashlib.sha256(value.content).hexdigest()
        return tuple(
            PDFPageInput(document_id=value.document_id, document_sha256=digest, page_number=i, text=page.extract_text() or "")
            for i, page in enumerate(reader.pages, 1)
        )
    except Exception as error:
        raise ValueError("PDF cannot be completely parsed") from error


class PDFPageSource(Source):
    page: PDFPageInput


@dataclass(frozen=True)
class _Projection:
    name = "powercontext.text-evidence"
    version = "1"
    source_class = PDFPageSource
    output_class = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        page = source.page
        return TextEvidence(source_type="pdf-page", source_id=source.name, content=f"{page.document_id}\n{page.text}",
                            metadata={"document_id": page.document_id, "document_sha256": page.document_sha256,
                                      "page_number": page.page_number})


@dataclass(frozen=True)
class _Definition:
    name = "pdf-page"
    version = "1"
    input_class = PDFPageInput
    source_class = PDFPageSource
    projections = (_Projection(),)

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = json.dumps([value.document_id, value.document_sha256, value.page_number], ensure_ascii=True,
                              separators=(",", ":")).encode("ascii")
        return PDFPageSource(name="pdf-page:" + hashlib.sha256(identity).hexdigest(),
                             materialization=SourceMaterialization.CAPTURED, page=value)

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return source.page


PDF_PAGE_SOURCE_DEFINITION = _Definition()

_STOP = frozenset("a an and are as at be by can could did do does for from has have how in into is it of on or s that the their then to use was were what when where which who with year years fy unadjusted question statement details shown answer calculate using reported company".split())


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    if limit <= 0 or not question.strip():
        return ()
    tokens = list(dict.fromkeys(re.findall(r"[a-z]+|\d+", question.lower())))
    terms = [t for t in tokens if t not in _STOP and (len(t) > 2 or t.isdigit())]
    queries = [" ".join(terms[:24])]
    queries.extend(" ".join(terms[i:i + 3]) for i in range(0, min(len(terms), 18), 3))
    candidates = {}
    for query in dict.fromkeys(q for q in queries if q):
        result = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=50))
        for rank, hit in enumerate(result.hits):
            key = (hit.entry_id, hit.entry_version_id)
            if key not in candidates:
                candidates[key] = [hit, 0.0]
            candidates[key][1] += 1 / (20 + rank)
    ranked = sorted(candidates.values(), key=lambda item: (-item[1], item[0].entry_id, item[0].entry_version_id))
    seen = set()
    citations = []
    for hit, _ in ranked:
        citation = MemoryCitation(memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id)
        record = await memory.get(GetMemoryEntryRequest(citation=citation))
        refs = tuple((ref.source_type, ref.source_id) for ref in record.entry.sources if ref.source_type == "pdf-page")
        if len(refs) != 1 or refs[0] in seen:
            continue
        seen.add(refs[0])
        citations.append(citation)
        if len(citations) >= limit:
            break
    return tuple(citations)
