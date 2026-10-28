# 官方契约

来源：官方 2026-competition `competition/challenges/source-03-pdf-retrieval/instruction.md`，公开分支 dab240063bfcfa7917898dc44da4baadb3747bd0；冻结版本 9db1753434162c0aa7c9f1189a1722e617880a52 是其祖先。题目文档网页未能直接访问，使用相同官方仓库公开题面核对。

`PDFDocumentInput(document_id: str, content: bytes)`；`PDFPageInput(document_id: str, document_sha256: str, page_number: int, text: str)`；`parse_pdf_document(value) -> tuple[PDFPageInput, ...]`；`PDF_PAGE_SOURCE_DEFINITION`；`async search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]`。评测仅载入产品 src/。固定环境 Python 3.12、pypdf 6.19.0。
