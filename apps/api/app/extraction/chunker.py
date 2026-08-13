"""Splitting stored document pages into model-sized chunks.

Chunks carry their offset within the page, which is what lets a quote found
inside a chunk be converted into a span in the page a reviewer can open.
Splitting happens on paragraph boundaries so a sentence is never cut in half
and then quoted as if it were complete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.models import SourceDocument
from .prompts import ExtractionRequest

DEFAULT_CHUNK_CHARS = 6000
MIN_CHUNK_CHARS = 200

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    page_number: int
    chunk_index: int
    page_offset: int
    text: str

    @property
    def end_offset(self) -> int:
        return self.page_offset + len(self.text)


def split_page(page_number: int, text: str, max_chars: int = DEFAULT_CHUNK_CHARS) -> list[Chunk]:
    """Break one page into chunks, preserving each chunk's offset in the page."""
    if not text.strip():
        return []
    if len(text) <= max_chars:
        return [Chunk(page_number=page_number, chunk_index=0, page_offset=0, text=text)]

    chunks: list[Chunk] = []
    cursor = 0
    index = 0
    while cursor < len(text):
        window_end = min(cursor + max_chars, len(text))
        if window_end < len(text):
            # Prefer a paragraph break, then a line break, then a hard cut.
            candidates = [
                m.start() for m in _PARAGRAPH_BREAK.finditer(text, cursor, window_end)
            ]
            split_at = candidates[-1] if candidates else text.rfind("\n", cursor, window_end)
            if split_at <= cursor + MIN_CHUNK_CHARS:
                split_at = window_end
        else:
            split_at = window_end

        piece = text[cursor:split_at]
        if piece.strip():
            chunks.append(
                Chunk(
                    page_number=page_number,
                    chunk_index=index,
                    page_offset=cursor,
                    text=piece,
                )
            )
            index += 1
        cursor = split_at if split_at > cursor else window_end
    return chunks


def chunk_document(
    document: SourceDocument, max_chars: int = DEFAULT_CHUNK_CHARS
) -> list[ExtractionRequest]:
    """Every chunk of every page of one document, ready to hand to a provider."""
    requests: list[ExtractionRequest] = []
    for page in sorted(document.pages, key=lambda p: p.page_number):
        for chunk in split_page(page.page_number, page.text, max_chars):
            requests.append(
                ExtractionRequest(
                    document_id=document.id,
                    document_type=str(document.document_type),
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    page_offset=chunk.page_offset,
                    text=chunk.text,
                )
            )
    return requests
