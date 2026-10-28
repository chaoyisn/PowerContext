import hashlib
import io

import pytest
from pypdf import PdfWriter

from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pdf_pages import PDFDocumentInput, PDF_PAGE_SOURCE_DEFINITION, parse_pdf_document, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def pdf(*, encrypted=False):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt(user_password="", owner_password="owner")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("data", [b"", b"not a PDF", b"%PDF-1.7\ntruncated"])
def test_invalid_pdf(data):
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="id", content=data))


@pytest.mark.parametrize("encrypted", [False, True])
async def test_pages_identity_and_projection(encrypted):
    data = pdf(encrypted=encrypted)
    pages = parse_pdf_document(PDFDocumentInput(document_id="文档" * 200, content=data))
    assert [(p.page_number, p.text) for p in pages] == [(1, ""), (2, "")]
    assert all(p.document_sha256 == hashlib.sha256(data).hexdigest() for p in pages)
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    sources = [await registry.resolve(p) for p in pages]
    assert sources[0].name != sources[1].name and len(sources[0].name) <= 256
    assert (await registry.resolve(pages[0])).name == sources[0].name
    assert await registry.read(sources[0]) == pages[0]
    projection = project_source_for_transport(registry, sources[0]).projection(TEXT_EVIDENCE_PROJECTION_KEY)
    assert projection == {"source_type": "pdf-page", "source_id": sources[0].name,
                          "content": pages[0].document_id + "\n", "metadata": {
                              "document_id": pages[0].document_id, "document_sha256": pages[0].document_sha256,
                              "page_number": 1}}
    different = pages[0].model_copy(update={"document_id": "other"})
    assert (await registry.resolve(different)).name != sources[0].name


async def test_empty_query_does_not_search():
    assert await search_pdf_pages(None, " ") == ()
    assert await search_pdf_pages(None, "income", limit=0) == ()


def test_page_failure_is_atomic(monkeypatch):
    class Page:
        def extract_text(self):
            raise RuntimeError("unreadable page")

    class Reader:
        is_encrypted = False
        pages = [Page()]

    monkeypatch.setattr("powercontext.sources.pdf_pages.PdfReader", lambda *args, **kwargs: Reader())
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="id", content=b"%PDF-1.7"))
