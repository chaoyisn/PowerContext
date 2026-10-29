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


def _fail_pdf(msg: str = "invalid PDF", cause: Exception | None = None) -> None:
    if cause is not None:
        raise ValueError(msg) from cause
    raise ValueError(msg)


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    if not value.document_id.strip() or b"%PDF-" not in value.content[:1024]:
        _fail_pdf("invalid PDF")
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=False)
        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
                if not decrypted:
                    _fail_pdf("PDF encrypted")
            except Exception as e:
                _fail_pdf("PDF password required", e)
        if not len(reader.pages):
            _fail_pdf("empty PDF")
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
        _fail_pdf("parse failed", error)


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
    "a", "an", "the", "and", "or", "but", "if", "of", "at", "by", "for", "with",
    "about", "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "up", "down", "in", "out", "on", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "s", "t", "can", "will", "just", "don", "should", "now", "d", "ll",
    "m", "o", "re", "ve", "y", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "as", "what", "which", "who", "whom",
    "this", "that", "these", "those", "am", "it", "its", "their", "theirs",
    "define", "calculate", "using", "details", "shown", "within", "assuming",
    "perspective", "investment", "analyst", "give", "response", "relying", "relies",
    "answer", "usd", "millions", "billions", "state", "explicitly", "outlined",
    "outline", "based", "consider", "whether", "please", "would", "could",
])


def _build_financial_statement_queries(
    term_set: set[str],
    q_lower: str,
    weighted_queries: list[tuple[str, float]],
) -> None:
    if "cash" in term_set and ("flow" in term_set or "flows" in term_set):
        weighted_queries.extend([
            ("consolidated statements of cash flows", 3.0),
            ("consolidated statement of cash flows", 3.0),
            ("statement of cash flows", 2.0),
            ("statements of cash flows", 2.0),
            ("operating activities", 1.5),
        ])
    elif "cash" in term_set:
        weighted_queries.extend([
            ("consolidated statement of cash flows", 2.5),
            ("statement of cash flows", 2.0),
            ("cash flows", 1.5),
        ])

    if (
        ("income" in term_set and "statement" in term_set)
        or "p&l" in q_lower
        or ("statement" in term_set and "operations" in term_set)
        or "ebitda" in term_set
        or "margin" in term_set
    ):
        weighted_queries.extend([
            ("consolidated statement of income", 3.0),
            ("consolidated statements of income", 3.0),
            ("statement of income", 2.0),
            ("statements of income", 2.0),
            ("consolidated statement of operations", 2.5),
            ("consolidated statements of operations", 2.5),
            ("statement of operations", 2.0),
            ("operating income", 1.5),
            ("operating profit", 1.5),
        ])

    if "balance" in term_set and "sheet" in term_set:
        weighted_queries.extend([
            ("consolidated balance sheets", 3.0),
            ("consolidated balance sheet", 3.0),
            ("balance sheets", 2.0),
            ("balance sheet", 2.0),
        ])
    elif "sheet" in term_set:
        weighted_queries.extend([
            ("consolidated balance sheets", 2.5),
            ("consolidated balance sheet", 2.5),
            ("balance sheet", 1.5),
        ])


def _build_domain_item_queries(
    term_set: set[str],
    weighted_queries: list[tuple[str, float]],
) -> None:
    if "legal" in term_set or "battles" in term_set or "litigation" in term_set or "lawsuit" in term_set:
        weighted_queries.extend([
            ("item 3 legal proceedings", 3.0),
            ("legal proceedings", 2.0),
            ("litigation", 1.5),
        ])

    if "restructuring" in term_set:
        weighted_queries.extend([
            ("restructuring", 2.0),
            ("restructuring charges", 2.5),
            ("restructuring costs", 2.5),
            ("restructuring and impairment", 2.5),
        ])

    if any(
        k in term_set
        for k in [
            "geographies", "geographic", "operates", "products",
            "services", "customers", "segment", "segments", "divisions",
        ]
    ):
        weighted_queries.extend([
            ("item 1 business", 3.0),
            ("our operations", 2.0),
            ("reportable segments", 2.0),
            ("divisions", 1.5),
            ("geographies", 1.5),
            ("geographic", 1.5),
        ])

    if "ebitda" in term_set:
        weighted_queries.extend([
            ("operating income", 2.0),
            ("operating profit", 2.0),
            ("depreciation and amortization", 2.5),
            ("consolidated statement of income", 3.0),
            ("consolidated statement of cash flows", 3.0),
        ])

    if (
        "capex" in term_set
        or ("capital" in term_set and "expenditure" in term_set)
        or ("capital" in term_set and "expenditures" in term_set)
    ):
        weighted_queries.extend([
            ("capital expenditures", 2.5),
            ("additions to property", 2.0),
            ("property plant and equipment", 2.0),
        ])

    if "inventory" in term_set or "inventories" in term_set:
        weighted_queries.extend([
            ("inventories", 2.5),
            ("inventory", 2.0),
            ("cost of sales", 1.5),
        ])

    if "quick" in term_set and "ratio" in term_set:
        weighted_queries.extend([
            ("quick ratio", 3.0),
            ("current assets", 2.0),
            ("current liabilities", 2.0),
            ("consolidated balance sheets", 2.5),
            ("balance sheet", 2.0),
        ])

    if "debt" in term_set and "securities" in term_set:
        weighted_queries.extend([
            ("debt securities", 3.0),
            ("registered to trade", 2.5),
            ("national securities exchange", 2.5),
        ])

    if "tax" in term_set or "taxes" in term_set:
        weighted_queries.extend([
            ("effective tax rate", 3.0),
            ("provision for income taxes", 2.5),
            ("income taxes", 2.0),
        ])


def _generate_weighted_queries(terms: list[str], q_lower: str) -> list[tuple[str, float]]:
    term_set = set(terms)
    weighted_queries: list[tuple[str, float]] = []

    _build_financial_statement_queries(term_set, q_lower, weighted_queries)
    _build_domain_item_queries(term_set, weighted_queries)

    for i in range(len(terms) - 1):
        weighted_queries.append((f"{terms[i]} {terms[i + 1]}", 1.0))
    for i in range(len(terms) - 2):
        weighted_queries.append((f"{terms[i]} {terms[i + 1]} {terms[i + 2]}", 1.0))
    for t in terms:
        if len(t) >= 4 or t.isdigit():
            weighted_queries.append((t, 0.8))
    if terms:
        weighted_queries.append((" ".join(terms[:10]), 1.0))

    return weighted_queries


async def _resolve_ranked_citations(
    memory: object,
    ranked_candidates: list[object],
    limit: int,
) -> tuple[MemoryCitation, ...]:
    seen_sources: set[tuple[str, str]] = set()
    seen_entries: set[str] = set()
    citations: list[MemoryCitation] = []
    for hit in ranked_candidates:
        entry_id = hit.entry_id
        if entry_id in seen_entries:
            continue
        citation = MemoryCitation(
            memory_ref=hit.memory_ref,
            entry_id=entry_id,
            entry_version_id=hit.entry_version_id,
        )
        record = await memory.get(GetMemoryEntryRequest(citation=citation))  # type: ignore[attr-defined]
        refs = tuple((ref.source_type, ref.source_id) for ref in record.entry.sources if ref.source_type == "pdf-page")
        if len(refs) != 1 or refs[0] in seen_sources:
            continue
        seen_sources.add(refs[0])
        seen_entries.add(entry_id)
        citations.append(citation)
        if len(citations) >= limit:
            break
    return tuple(citations)


async def search_pdf_pages(memory: object, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    if limit <= 0 or not question.strip():
        return ()

    q_lower = question.lower()
    raw_tokens = re.findall(r"[a-z]+|\d+", q_lower)
    terms = [t for t in raw_tokens if t not in _BASE_STOP and (len(t) > 1 or t.isdigit())]
    weighted_queries = _generate_weighted_queries(terms, q_lower)

    candidates: dict[tuple[str, str], list[object]] = {}
    seen_queries: set[str] = set()
    for query, weight in weighted_queries:
        query_text = query.strip()
        if not query_text or query_text in seen_queries:
            continue
        seen_queries.add(query_text)
        result = await memory.search(SearchMemoryRequest(query=query_text, mode="fts", limit=35))  # type: ignore[attr-defined]
        for rank, hit in enumerate(result.hits):
            key = (hit.entry_id, hit.entry_version_id)
            if key not in candidates:
                candidates[key] = [hit, 0.0]
            candidates[key][1] = float(candidates[key][1]) + (weight / (10.0 + rank))

    ranked = sorted(
        candidates.values(),
        key=lambda item: (-float(item[1]), item[0].entry_id, item[0].entry_version_id),
    )
    ranked_hits = [item[0] for item in ranked]
    return await _resolve_ranked_citations(memory, ranked_hits, limit)
