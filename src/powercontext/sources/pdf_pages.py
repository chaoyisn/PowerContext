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
    if not value.document_id.strip() or b"%PDF-" not in value.content[:1024]:
        raise ValueError("invalid document id or PDF")
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=False)
        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
                if not decrypted:
                    raise ValueError("PDF requires a password")
            except Exception as e:
                raise ValueError("PDF requires a password") from e
        if not len(reader.pages):
            raise ValueError("PDF has no pages")
        digest = hashlib.sha256(value.content).hexdigest()
        pages = []
        for i, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            pages.append(
                PDFPageInput(
                    document_id=value.document_id,
                    document_sha256=digest,
                    page_number=i,
                    text=text,
                )
            )
        return tuple(pages)
    except ValueError:
        raise
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
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{page.document_id}\n{page.text}",
            metadata={
                "document_id": page.document_id,
                "document_sha256": page.document_sha256,
                "page_number": page.page_number,
            },
        )


@dataclass(frozen=True)
class _Definition:
    name = "pdf-page"
    version = "1"
    input_class = PDFPageInput
    source_class = PDFPageSource
    projections = (_Projection(),)

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = json.dumps(
            [value.document_id, value.document_sha256, value.page_number],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        return PDFPageSource(
            name="pdf-page:" + hashlib.sha256(identity).hexdigest(),
            materialization=SourceMaterialization.CAPTURED,
            page=value,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return source.page


PDF_PAGE_SOURCE_DEFINITION = _Definition()

_BASE_STOP = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "if",
    "of",
    "at",
    "by",
    "for",
    "with",
    "about",
    "against",
    "between",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "to",
    "from",
    "up",
    "down",
    "in",
    "out",
    "on",
    "off",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "when",
    "where",
    "why",
    "how",
    "all",
    "any",
    "both",
    "each",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "s",
    "t",
    "can",
    "will",
    "just",
    "don",
    "should",
    "now",
    "d",
    "ll",
    "m",
    "o",
    "re",
    "ve",
    "y",
])


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    if limit <= 0 or not question.strip():
        return ()

    q_lower = question.lower()
    raw_tokens = re.findall(r"[a-z]+|\d+", q_lower)
    terms = [t for t in raw_tokens if t not in _BASE_STOP and (len(t) > 1 or t.isdigit())]

    queries: list[str] = []

    # Domain financial mappings for 10-K / 10-Q SEC filings
    term_set = set(terms)
    if "legal" in term_set or "battles" in term_set or "litigation" in term_set:
        queries.extend(["item 3 legal proceedings", "legal proceedings", "litigation", "legal"])
    if "cash" in term_set and ("flow" in term_set or "flows" in term_set):
        queries.extend([
            "consolidated statements of cash flows",
            "statement of cash flows",
            "cash flows",
            "operating activities",
        ])
    elif "cash" in term_set:
        queries.extend(["cash flows", "statement of cash flows"])
    if "income" in term_set and "statement" in term_set:
        queries.extend(["consolidated statements of income", "statement of income", "operating income"])
    elif "p&l" in q_lower or ("statement" in term_set and "operations" in term_set):
        queries.extend(["consolidated statements of income", "results of operations", "operating income"])
    if "balance" in term_set and "sheet" in term_set:
        queries.extend(["consolidated balance sheets", "balance sheet", "financial position"])
    elif "sheet" in term_set:
        queries.extend(["balance sheet", "balance sheets"])
    if "restructuring" in term_set:
        queries.extend(["restructuring", "restructuring charges", "restructuring costs"])
    if "geographies" in term_set or "geographic" in term_set or "operates" in term_set:
        queries.extend(["geographies", "geographic", "divisions", "our operations", "reportable segments"])
    if "ebitda" in term_set:
        queries.extend(["operating income", "depreciation and amortization", "amortization"])
    if "capex" in term_set or ("capital" in term_set and "expenditure" in term_set):
        queries.extend(["capital expenditures", "additions to property", "property plant and equipment"])
    if "inventory" in term_set or "inventories" in term_set:
        queries.extend(["inventories", "inventory turnover", "cost of sales"])
    if "acquisitions" in term_set or "acquisition" in term_set:
        queries.extend(["acquisitions", "business combinations"])
    if "quick" in term_set and "ratio" in term_set:
        queries.extend(["quick ratio", "current assets", "current liabilities", "liquidity"])
    if "debt" in term_set and "securities" in term_set:
        queries.extend(["debt securities", "registered to trade", "national securities exchange"])

    # Bigrams (sliding window of 2 words)
    for i in range(len(terms) - 1):
        queries.append(f"{terms[i]} {terms[i + 1]}")

    # Trigrams (sliding window of 3 words)
    for i in range(len(terms) - 2):
        queries.append(f"{terms[i]} {terms[i + 1]} {terms[i + 2]}")

    # Individual key informational words
    for t in terms:
        if len(t) >= 5 or t.isdigit():
            queries.append(t)

    # Full query without filler words (up to 12 words)
    if terms:
        queries.append(" ".join(terms[:12]))

    candidates: dict[tuple[str, str], list[object]] = {}
    seen_queries = set()
    for query in queries:
        query = query.strip()
        if not query or query in seen_queries:
            continue
        seen_queries.add(query)
        result = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=35))
        for rank, hit in enumerate(result.hits):
            key = (hit.entry_id, hit.entry_version_id)
            if key not in candidates:
                candidates[key] = [hit, 0.0]
            candidates[key][1] += 1.0 / (10.0 + rank)

    ranked = sorted(candidates.values(), key=lambda item: (-item[1], item[0].entry_id, item[0].entry_version_id))
    seen_sources = set()
    seen_entries = set()
    citations = []
    for hit, _ in ranked:
        if hit.entry_id in seen_entries:
            continue
        citation = MemoryCitation(
            memory_ref=hit.memory_ref,
            entry_id=hit.entry_id,
            entry_version_id=hit.entry_version_id,
        )
        record = await memory.get(GetMemoryEntryRequest(citation=citation))
        refs = tuple((ref.source_type, ref.source_id) for ref in record.entry.sources if ref.source_type == "pdf-page")
        if len(refs) != 1 or refs[0] in seen_sources:
            continue
        seen_sources.add(refs[0])
        seen_entries.add(hit.entry_id)
        citations.append(citation)
        if len(citations) >= limit:
            break
    return tuple(citations)
