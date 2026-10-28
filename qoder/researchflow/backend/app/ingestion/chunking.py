"""Page-scoped chunking with stable, recomputable chunk ids.

Chunking is deterministic: the same page text always yields the same spans, so
``chunk_id`` stays stable across re-uploads and citations never drift.
"""

from __future__ import annotations

from dataclasses import dataclass

_TERMINATORS = "。！？；…\n.!?;"


@dataclass(frozen=True)
class Chunk:
    page_no: int
    chunk_index: int
    char_start: int
    char_end: int
    text: str

    def chunk_id(self, doc_prefix: str) -> str:
        return f"{doc_prefix}:p{self.page_no:04d}:c{self.chunk_index:03d}"

    def page_id(self, doc_prefix: str) -> str:
        return f"{doc_prefix}:p{self.page_no:04d}"


def _find_break(text: str, start: int, limit: int) -> int:
    """Back off from ``limit`` to a sentence/paragraph boundary, never past the midpoint."""
    floor = start + max(1, (limit - start) // 2)
    for index in range(limit, floor, -1):
        if text[index - 1] in _TERMINATORS:
            return index
    return limit


def chunk_page_text(
    text: str,
    page_no: int,
    *,
    target_chars: int = 700,
    overlap_chars: int = 120,
    min_chars: int = 24,
) -> list[Chunk]:
    """Split one page into chunks. Whitespace-only regions are dropped, positions are absolute."""
    if not text:
        return []
    length = len(text)
    chunks: list[Chunk] = []
    position = 0
    index = 0
    while position < length:
        end = min(position + target_chars, length)
        if end < length:
            end = _find_break(text, position, end)
        piece = text[position:end]
        if len(piece.strip()) >= min_chars:
            chunks.append(
                Chunk(
                    page_no=page_no,
                    chunk_index=index,
                    char_start=position,
                    char_end=end,
                    text=piece,
                )
            )
            index += 1
        if end >= length:
            break
        overlapped = end - overlap_chars
        position = end if overlapped <= position else overlapped
    return chunks


def doc_prefix(doc_id: str) -> str:
    """Stable short prefix used to build page/chunk ids from the content hash."""
    return doc_id[:16]


def page_id_for(doc_id: str, page_no: int) -> str:
    return f"{doc_prefix(doc_id)}:p{page_no:04d}"
