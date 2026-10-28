"""Unit tests that need no external service."""

from __future__ import annotations

import io
import json

import pytest

from app.errors import FileTooLargeError, UnsupportedFileTypeError
from app.ingestion.chunking import chunk_page_text, doc_prefix, page_id_for
from app.ingestion.hashing import content_type_for, safe_filename, sha256_bytes, validate_upload
from app.ingestion.parsers import parse_document, parse_pdf, parse_text
from app.memory.models import EvidencePointer, ResearchProgress, decode_entry, encode_item_text
from app.retrieval.relevance import (
    combined_relevance,
    content_tokens,
    lexical_coverage,
    normalize_score,
    passes_gate,
)


# --------------------------------------------------------------------- hashing


def test_sha256_is_content_addressed():
    assert sha256_bytes(b"same") == sha256_bytes(b"same")
    assert sha256_bytes(b"same") != sha256_bytes(b"other")
    assert len(sha256_bytes(b"x")) == 64


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\x.txt", "x.txt"),
        ("/absolute/path/a.md", "a.md"),
        ("", "upload"),
        ("...", "upload"),
        ("a\x00b.pdf", "ab.pdf"),
    ],
)
def test_safe_filename_blocks_traversal(raw, expected):
    assert safe_filename(raw) == expected


def test_content_type_mapping():
    assert content_type_for("a.pdf") == "pdf"
    assert content_type_for("a.MD") == "markdown"
    assert content_type_for("a.markdown") == "markdown"
    assert content_type_for("a.txt") == "text"
    with pytest.raises(UnsupportedFileTypeError):
        content_type_for("a.exe")


def test_validate_upload_rejects_disallowed_and_oversize(settings):
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("virus.exe", b"MZ", settings)
    with pytest.raises(FileTooLargeError):
        validate_upload("big.pdf", b"%PDF-" + b"0" * (settings.upload_max_bytes + 1), settings)
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("empty.pdf", b"", settings)
    assert validate_upload("ok.pdf", b"%PDF-1.7", settings) == "pdf"


# --------------------------------------------------------------------- chunking


def test_chunk_offsets_point_back_into_the_page_text():
    text = "First sentence about seekdb. " * 40 + "Second paragraph about PowerContext."
    chunks = chunk_page_text(text, page_no=3, target_chars=120, overlap_chars=20)
    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.page_no == 3
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunking_is_deterministic_and_ids_are_stable():
    text = "向量检索与全文检索可以在同一条 SQL 中完成。" * 20
    first = chunk_page_text(text, page_no=1)
    second = chunk_page_text(text, page_no=1)
    prefix = doc_prefix(sha256_bytes(b"doc"))
    assert [c.chunk_id(prefix) for c in first] == [c.chunk_id(prefix) for c in second]
    assert first[0].chunk_id(prefix) == f"{prefix}:p0001:c000"
    assert page_id_for(sha256_bytes(b"doc"), 12) == f"{prefix}:p0012"


def test_empty_page_yields_no_chunks_but_keeps_identity():
    assert chunk_page_text("", page_no=4) == []
    assert chunk_page_text("   \n\t ", page_no=4) == []
    assert page_id_for("a" * 64, 4).endswith(":p0004")


# --------------------------------------------------------------------- parsing


def _pdf_with_blank_page() -> bytes:
    import fitz

    document = fitz.open()
    for index in range(4):
        page = document.new_page(width=400, height=400)
        if index != 2:  # page 3 (1-based) stays blank on purpose
            page.insert_textbox(
                fitz.Rect(40, 40, 360, 360), f"Physical page {index + 1} content marker."
            )
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def test_pdf_page_numbers_are_physical_and_one_based():
    parsed = parse_pdf(_pdf_with_blank_page(), "blank.pdf")
    assert parsed.page_count == 4
    assert [page.page_no for page in parsed.pages] == [1, 2, 3, 4]
    assert parsed.empty_pages == [3]
    assert "Physical page 1" in parsed.pages[0].text
    assert "Physical page 4" in parsed.pages[3].text
    assert parsed.pages[2].text.strip() == ""


def test_pdf_rejects_non_pdf_bytes():
    with pytest.raises(Exception) as info:
        parse_pdf(b"not a pdf at all", "fake.pdf")
    assert "magic" in str(info.value).lower() or "parse" in str(info.value).lower()


def test_markdown_and_text_are_single_page():
    markdown = parse_document(b"# Title\n\nbody", "plan.md", "markdown")
    assert markdown.page_count == 1
    assert markdown.pages[0].page_no == 1
    assert markdown.title == "Title"

    plain = parse_text("第一行\n第二行".encode("utf-8"), "log.txt")
    assert plain.page_count == 1
    assert plain.title == "第一行"


def test_gbk_encoded_text_is_decoded():
    parsed = parse_text("中文实验记录".encode("gb18030"), "log.txt")
    assert "中文实验记录" in parsed.pages[0].text


# --------------------------------------------------------------------- relevance


def test_content_tokens_drops_stopwords_and_keeps_cjk_bigrams():
    tokens = content_tokens("这篇文档里有没有关于量子纠缠实验的结果")
    assert "量子" in tokens and "纠缠" in tokens
    assert "这篇" not in tokens
    # snake_case is split so a query for "rank constant" matches stored "rank_constant"
    assert {"rank", "constant", "60"} <= content_tokens("rank_constant = 60")


def test_coverage_separates_answerable_from_unanswerable():
    evidence = "Page 5 - Reciprocal Rank Fusion. rank_constant = 60 and the RRF score is 0.0328."
    assert lexical_coverage("RRF rank constant 60", evidence) >= 0.5
    assert lexical_coverage("量子纠缠实验的结果", evidence) == 0.0


def test_normalize_score_maps_each_mode_into_unit_interval():
    assert normalize_score(0.6247, "cosine_similarity") == 0.6247
    assert 0.0 < normalize_score(2.0, "fts_relevance") < 1.0
    assert normalize_score(2 / 61, "rrf") == pytest.approx(1.0)
    assert normalize_score(1 / 61, "rrf") == pytest.approx(0.5)


def test_gate_rule():
    # lexical coverage alone qualifies a hit
    assert passes_gate(coverage=0.4)
    assert not passes_gate(coverage=0.1)
    # a paraphrase with no literal overlap qualifies on semantic similarity alone
    assert passes_gate(coverage=0.0, semantic_similarity=0.8)
    assert not passes_gate(coverage=0.0, semantic_similarity=0.3)
    assert combined_relevance(1.0, 1.0) == 1.0


# --------------------------------------------------------------------- memory models


def test_memory_text_envelope_roundtrips():
    text = encode_item_text(7, "2026-10-29T02:00:00+00:00", "D1: 使用 SHA-256 作为文档主键")
    entry = decode_entry("rf_decision", text, "art_x", 1, "active")
    assert entry.kind == "decision"
    assert entry.seq == 7
    assert entry.updated_at == "2026-10-29T02:00:00+00:00"
    assert entry.text == "D1: 使用 SHA-256 作为文档主键"
    assert entry.source == "memory"


def test_decode_tolerates_entries_without_the_envelope():
    entry = decode_entry("rf_goal", "legacy text", "art_y", 1, "active")
    assert entry.seq == 0 and entry.text == "legacy text"


def test_progress_flattens_and_fingerprints():
    progress = ResearchProgress(
        project_id="p1",
        title="t",
        objective="目标",
        completed_work=["做完 A"],
        decisions=["D1"],
        key_evidence=[
            EvidencePointer(doc_id="d", filename="f.pdf", page_no=5, chunk_id="c", quote="q")
        ],
        open_questions=["Q1"],
        next_steps=["N1"],
        seq=3,
        updated_at="2026-10-29T02:00:00+00:00",
    )
    kinds = [kind for kind, _ in progress.items()]
    assert kinds == ["goal", "completed_work", "decision", "evidence", "open_question", "next_step"]

    payload = json.loads(progress.snapshot_json())
    assert payload["seq"] == 3 and payload["next_steps"] == ["N1"]
    assert payload["key_evidence"][0]["page_no"] == 5

    other = ResearchProgress(**{**progress.__dict__, "updated_at": "2026-10-30T00:00:00+00:00", "seq": 9})
    assert other.content_fingerprint() == progress.content_fingerprint(), (
        "bookkeeping fields must not change the fingerprint"
    )
    changed = ResearchProgress(**{**progress.__dict__, "next_steps": ["N1", "N2"]})
    assert changed.content_fingerprint() != progress.content_fingerprint()


def test_progress_requires_something_to_save():
    with pytest.raises(Exception):
        ResearchProgress(project_id="p1").validate()
