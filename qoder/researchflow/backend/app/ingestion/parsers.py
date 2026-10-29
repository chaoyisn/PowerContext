"""PDF / Markdown / TXT parsing.

PDF page numbers are **real physical pages starting at 1** (PyMuPDF ``page.number + 1``).
An empty page still produces a ``PageText`` record so page identity is preserved.
Markdown and TXT have no physical pagination, so they are represented as exactly one
page (``page_no=1``) rather than inventing page numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import DocumentParseError
from ..logging_setup import get_logger

logger = get_logger(__name__)

_MAGIC_PDF = b"%PDF-"

# Parsing is a DoS surface: a hostile PDF can declare thousands of pages or gigabytes of
# text. Caps are far above any legitimate research document and far below exhaustion.
MAX_PDF_PAGES = 1000
MAX_EXTRACTED_CHARS = 8_000_000


@dataclass
class PageText:
    page_no: int
    text: str
    is_empty: bool = False

    def __post_init__(self) -> None:
        self.text = self.text or ""
        self.is_empty = len(self.text.strip()) == 0


@dataclass
class ParsedDocument:
    content_type: str
    pages: list[PageText] = field(default_factory=list)
    title: str = ""

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def empty_pages(self) -> list[int]:
        return [p.page_no for p in self.pages if p.is_empty]


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _first_heading(text: str, filename: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:200]
        return stripped[:200]
    return filename


def parse_pdf(data: bytes, filename: str) -> ParsedDocument:
    if not data.startswith(_MAGIC_PDF):
        raise DocumentParseError(
            "file does not start with the %PDF- magic bytes",
            detail={"filename": filename},
        )
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise DocumentParseError("PyMuPDF is not installed", detail={"reason": str(exc)}) from exc

    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise DocumentParseError(
                    "PDF is password protected", detail={"filename": filename}
                )
            if document.page_count > MAX_PDF_PAGES:
                raise DocumentParseError(
                    f"PDF has {document.page_count} pages, limit is {MAX_PDF_PAGES}",
                    detail={"filename": filename, "pages": document.page_count},
                )
            pages: list[PageText] = []
            extracted = 0
            for page in document:
                text = page.get_text("text")
                extracted += len(text)
                if extracted > MAX_EXTRACTED_CHARS:
                    raise DocumentParseError(
                        f"PDF text exceeds {MAX_EXTRACTED_CHARS} extracted characters",
                        detail={"filename": filename, "extracted": extracted},
                    )
                # page.number is 0-based; ResearchFlow always exposes 1-based physical pages.
                pages.append(PageText(page_no=page.number + 1, text=text))
            meta_title = (document.metadata or {}).get("title") or ""
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError(
            f"failed to parse PDF: {type(exc).__name__}: {exc}", detail={"filename": filename}
        ) from exc

    if not pages:
        raise DocumentParseError("PDF contains no pages", detail={"filename": filename})

    title = meta_title.strip()[:200]
    if not title:
        for page in pages:
            if not page.is_empty:
                title = _first_heading(page.text, filename)
                break
    if not title:
        title = filename
    logger.info(
        "parsed pdf",
        fields={"filename": filename, "pages": len(pages), "empty_pages": len(pages) - sum(1 for p in pages if not p.is_empty)},
    )
    return ParsedDocument(content_type="pdf", pages=pages, title=title)


def parse_markdown(data: bytes, filename: str) -> ParsedDocument:
    text = _decode(data)
    return ParsedDocument(
        content_type="markdown",
        pages=[PageText(page_no=1, text=text)],
        title=_first_heading(text, filename),
    )


def parse_text(data: bytes, filename: str) -> ParsedDocument:
    text = _decode(data)
    return ParsedDocument(
        content_type="text",
        pages=[PageText(page_no=1, text=text)],
        title=_first_heading(text, filename),
    )


_PARSERS = {"pdf": parse_pdf, "markdown": parse_markdown, "text": parse_text}


def parse_document(data: bytes, filename: str, content_type: str) -> ParsedDocument:
    parser = _PARSERS.get(content_type)
    if parser is None:
        raise DocumentParseError(
            f"no parser for content type '{content_type}'", detail={"filename": filename}
        )
    return parser(data, filename)
