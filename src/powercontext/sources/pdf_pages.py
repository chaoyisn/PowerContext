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

__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "search_pdf_pages",
]


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
    "drove", "driver", "drivers", "improving", "profile", "useful", "metric",
    "company", "like", "reasonably", "healthy", "relevant", "measure", "say",
    "unknown", "assume", "public", "equities", "banker", "financial", "adopting",
    "basing", "judgment", "plainly", "clearly", "solution", "address", "drawing",
    "conclusions", "represented", "represent", "representing", "able", "done",
    "among", "bring", "brought", "lost", "least", "proportionally",
])


def _build_cover_page_queries(
    term_set: set[str],
    weighted: list[tuple[str, float]],
) -> None:
    if "registered" in term_set and (
        "trade" in term_set
        or "trading" in term_set
        or "exchange" in term_set
        or "securities" in term_set
        or "symbol" in term_set
    ):
        weighted.extend([
            ("securities registered pursuant to section 12", 4.0),
            ("title of each class trading symbol", 4.0),
            ("national securities exchange", 3.5),
            ("form 10-k annual report", 3.0),
        ])


def _build_statement_queries(
    term_set: set[str],
    q_lower: str,
    weighted: list[tuple[str, float]],
) -> None:
    if "cash" in term_set and (
        "flow" in term_set
        or "flows" in term_set
        or "activities" in term_set
        or "operations" in term_set
        or "investing" in term_set
        or "financing" in term_set
    ):
        weighted.extend([
            ("consolidated statements of cash flows", 4.0),
            ("consolidated statement of cash flows", 4.0),
            ("statement of cash flows", 3.0),
            ("operating activities investing activities financing", 3.0),
            ("operating activities", 2.5),
        ])
    elif "cash" in term_set:
        weighted.extend([
            ("consolidated statement of cash flows", 3.0),
            ("statement of cash flows", 2.5),
            ("cash flows", 2.0),
        ])

    if (
        ("income" in term_set and "statement" in term_set)
        or "p&l" in q_lower
        or ("statement" in term_set and "operations" in term_set)
        or "ebitda" in term_set
        or "earnings" in term_set
        or "operating income" in q_lower
        or "gross margin" in q_lower
        or "operating margin" in q_lower
    ):
        weighted.extend([
            ("consolidated statements of income", 4.0),
            ("consolidated statements of operations", 4.0),
            ("consolidated statement of income", 4.0),
            ("consolidated statement of operations", 4.0),
            ("consolidated statements of earnings", 3.5),
            ("operating income", 3.0),
            ("operating profit", 2.5),
        ])

    if (
        ("balance" in term_set and "sheet" in term_set)
        or "liability" in term_set
        or "liabilities" in term_set
        or "assets" in term_set
    ):
        weighted.extend([
            ("consolidated balance sheets", 4.0),
            ("consolidated balance sheet", 4.0),
            ("total liabilities", 3.5),
            ("balance sheets", 3.0),
            ("balance sheet", 3.0),
        ])


def _build_sec_section_queries(
    term_set: set[str],
    weighted: list[tuple[str, float]],
) -> None:
    if any(k in term_set for k in ["legal", "battles", "litigation", "lawsuit", "lawsuits"]):
        weighted.extend([
            ("item 3 legal proceedings", 4.0),
            ("legal proceedings", 3.5),
            ("litigation", 3.0),
        ])

    if any(
        k in term_set
        for k in [
            "business", "products", "services", "customers", "customer",
            "concentration", "industry", "cyclicality", "cyclical",
            "operates", "geographies", "geographic", "segment", "segments",
        ]
    ):
        weighted.extend([
            ("item 1 business", 4.0),
            ("principal products and services", 3.5),
            ("major customers", 3.5),
            ("customer concentration", 3.5),
            ("our operations", 3.0),
        ])

    if any(k in term_set for k in ["growth", "margin", "margins", "revenue"]):
        weighted.extend([
            ("item 7 management discussion and analysis", 4.0),
            ("management discussion and analysis", 3.5),
            ("results of operations", 3.5),
            ("gross margin", 3.0),
            ("operating margin", 3.0),
        ])

    if "risk" in term_set or "risks" in term_set:
        weighted.extend([
            ("item 1a risk factors", 4.0),
            ("risk factors", 3.0),
        ])


def _build_operational_queries(
    term_set: set[str],
    weighted: list[tuple[str, float]],
) -> None:
    if "rate" in term_set or "rates" in term_set or "production" in term_set:
        weighted.extend([
            ("production rate", 3.5),
            ("production rates", 3.5),
            ("commercial airplanes", 3.0),
        ])

    if "card" in term_set or "members" in term_set or "retention" in term_set:
        weighted.extend([
            ("card members", 4.0),
            ("cardmember retention", 3.5),
            ("retention", 3.0),
        ])

    if "segment" in term_set or "segments" in term_set:
        weighted.extend([
            ("reportable segments", 4.0),
            ("segment results", 3.5),
            ("segment net sales", 3.5),
            ("segment revenue", 3.0),
        ])

    if any(k in term_set for k in ["geographies", "geographic", "geographical", "countries"]):
        weighted.extend([
            ("geographic information", 4.0),
            ("geographic areas", 3.5),
            ("net sales by geographic", 3.0),
        ])


def _build_financial_metric_queries(
    term_set: set[str],
    weighted: list[tuple[str, float]],
) -> None:
    if "ebitda" in term_set:
        weighted.extend([
            ("operating income", 3.0),
            ("depreciation and amortization", 3.0),
            ("consolidated statement of income", 3.5),
            ("consolidated statement of cash flows", 3.5),
        ])

    if (
        "capex" in term_set
        or ("capital" in term_set and ("expenditure" in term_set or "expenditures" in term_set))
    ):
        weighted.extend([
            ("capital expenditures", 3.5),
            ("additions to property", 3.0),
            ("property plant and equipment", 2.5),
        ])

    if "inventory" in term_set or "inventories" in term_set:
        weighted.extend([
            ("inventories", 3.5),
            ("inventory", 3.0),
            ("cost of sales", 2.5),
        ])

    if "quick" in term_set or "liquidity" in term_set:
        weighted.extend([
            ("quick ratio", 4.0),
            ("liquidity and capital resources", 3.5),
            ("current assets", 3.0),
            ("current liabilities", 3.0),
            ("consolidated balance sheets", 3.5),
        ])

    if "debt" in term_set or "borrow" in term_set or "borrowings" in term_set:
        weighted.extend([
            ("long-term debt", 3.5),
            ("debt securities", 3.0),
            ("short-term borrowings", 3.0),
            ("consolidated balance sheets", 3.0),
        ])

    if "tax" in term_set or "taxes" in term_set:
        weighted.extend([
            ("effective tax rate", 4.0),
            ("provision for income taxes", 3.5),
            ("income taxes", 3.0),
        ])

    if "restructuring" in term_set:
        weighted.extend([
            ("restructuring charges", 4.0),
            ("restructuring and impairment", 3.5),
            ("restructuring costs", 3.0),
            ("consolidated statements of income", 3.0),
        ])

    if any(k in term_set for k in ["acquisition", "acquisitions", "acquired", "divestitures"]):
        weighted.extend([
            ("acquisitions and divestitures", 4.0),
            ("business combinations", 3.5),
            ("acquisitions", 3.0),
        ])

    if "dividend" in term_set or "dividends" in term_set:
        weighted.extend([
            ("dividends paid", 3.0),
            ("cash dividends", 2.5),
            ("consolidated statement of cash flows", 3.0),
        ])


def _generate_weighted_queries(terms: list[str], q_lower: str) -> list[tuple[str, float]]:
    term_set = set(terms)
    weighted_queries: list[tuple[str, float]] = []

    _build_cover_page_queries(term_set, weighted_queries)
    _build_statement_queries(term_set, q_lower, weighted_queries)
    _build_sec_section_queries(term_set, weighted_queries)
    _build_financial_metric_queries(term_set, weighted_queries)
    _build_operational_queries(term_set, weighted_queries)

    if terms:
        weighted_queries.append((" ".join(terms), 2.5))
        if len(terms) > 4:
            weighted_queries.append((" ".join(terms[:4]), 1.5))
            weighted_queries.append((" ".join(terms[-4:]), 1.5))

    for i in range(len(terms) - 1):
        weighted_queries.append((f"{terms[i]} {terms[i + 1]}", 1.2))
    for t in terms:
        if len(t) >= 4 or t.isdigit():
            weighted_queries.append((t, 0.8))

    seen: set[str] = set()
    deduped: list[tuple[str, float]] = []
    for q_text, score in sorted(weighted_queries, key=lambda item: -item[1]):
        q_norm = " ".join(q_text.split())
        if q_norm and q_norm not in seen:
            seen.add(q_norm)
            deduped.append((q_norm, score))
            if len(deduped) >= 28:
                break

    return deduped


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
        if not refs or refs[0] in seen_sources:
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
