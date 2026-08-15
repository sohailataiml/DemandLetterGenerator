"""Turning a claimed quote into a citation — the one place that decision lives.

Hand-entered citations, machine-extracted citations and the geometry backfill
all come through :func:`build_citation`, so there is exactly one implementation
of "how sure are we where this came from", and it is the same one whether the
quote was typed by a paralegal or produced by a model.

What comes out is deliberately conservative:

* a passage found once, verbatim or up to whitespace, is ``EXACT`` and gets
  offsets — and rectangles too if the page has geometry;
* a passage found more than once is ``AMBIGUOUS`` and gets neither, because
  picking one occurrence would be the system inventing an answer;
* a paraphrase is ``TEXT_ONLY``: offsets good enough to scroll to, never a
  rectangle;
* anything else is ``UNRESOLVED`` and cites a page and nothing finer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from ..domain.enums import CitationStatus
from . import citations
from .geometry import BoundingBox, Word, boxes_for_span, boxes_to_json

_WHITESPACE = re.compile(r"\s+")


def _normalized(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


@dataclass(frozen=True)
class CitationFields:
    """The provenance columns of one citation, ready to persist."""

    excerpt: str | None
    start_offset: int | None
    end_offset: int | None
    quoted_text_sha256: str | None
    match_kind: str | None
    citation_status: CitationStatus
    bounding_boxes: list[dict] | None
    confidence: float | None

    @property
    def is_exact(self) -> bool:
        return self.citation_status == CitationStatus.EXACT

    @property
    def has_geometry(self) -> bool:
        return bool(self.bounding_boxes)

    def as_kwargs(self) -> dict:
        return {
            "excerpt": self.excerpt,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "quoted_text_sha256": self.quoted_text_sha256,
            "match_kind": self.match_kind,
            "citation_status": self.citation_status,
            "bounding_boxes": self.bounding_boxes,
            "confidence": self.confidence,
        }


def unresolved(excerpt: str | None = None) -> CitationFields:
    return CitationFields(
        excerpt=excerpt,
        start_offset=None,
        end_offset=None,
        quoted_text_sha256=None,
        match_kind=None,
        citation_status=CitationStatus.UNRESOLVED,
        bounding_boxes=None,
        confidence=None,
    )


def build_citation(
    *,
    page_text: str,
    quote: str | None,
    words: Sequence[Word] = (),
) -> CitationFields:
    """Locate ``quote`` on the page and describe how well it was located."""
    if not quote or not quote.strip():
        return unresolved(quote)

    occurrences = citations.count_occurrences(page_text, quote)
    if occurrences > 1:
        # Several passages on this page say the same thing. Which one supports
        # the fact is a question only the reviewer can answer.
        return CitationFields(
            excerpt=quote,
            start_offset=None,
            end_offset=None,
            quoted_text_sha256=None,
            match_kind=None,
            citation_status=CitationStatus.AMBIGUOUS,
            bounding_boxes=None,
            confidence=None,
        )

    resolved = citations.resolve(page_text, quote)
    if resolved is None:
        return unresolved(quote)

    if not resolved.is_exact:
        # A paraphrase. Offsets point at the closest window so the reviewer can
        # be taken to the right part of the page; no rectangle is drawn, and the
        # UI says the highlight is approximate.
        return CitationFields(
            excerpt=resolved.quoted_text,
            start_offset=resolved.start_offset,
            end_offset=resolved.end_offset,
            quoted_text_sha256=resolved.quoted_text_sha256,
            match_kind=resolved.match_kind.value,
            citation_status=CitationStatus.TEXT_ONLY,
            bounding_boxes=None,
            confidence=resolved.similarity,
        )

    boxes = geometry_for_span(
        page_text, words, resolved.start_offset, resolved.end_offset
    )
    return CitationFields(
        excerpt=resolved.quoted_text,
        start_offset=resolved.start_offset,
        end_offset=resolved.end_offset,
        quoted_text_sha256=resolved.quoted_text_sha256,
        match_kind=resolved.match_kind.value,
        citation_status=CitationStatus.EXACT,
        bounding_boxes=boxes_to_json(boxes) if boxes else None,
        confidence=1.0,
    )


class SelectionError(ValueError):
    """A reviewer's span selection cannot be accepted as it stands."""


def citation_from_selection(
    *,
    page_text: str,
    start: int,
    end: int,
    claimed_quote: str | None,
    words: Sequence[Word] = (),
) -> CitationFields:
    """Turn a reviewer's page selection into an ``EXACT`` citation.

    The guard rail is ``claimed_quote``: when the citation already says what it
    quotes, the selection has to be an occurrence of *that* passage. A reviewer
    settling an ambiguity is choosing which of several identical passages is
    meant — a legitimate act of judgement — whereas pointing a fact at different
    words would be rewriting its evidence, and that is what supersession is for.
    """
    if end <= start:
        raise SelectionError("the selection is empty")
    if start < 0 or end > len(page_text):
        raise SelectionError("the selection is outside the text of this page")

    selected = page_text[start:end]
    if not selected.strip():
        raise SelectionError("the selection contains no text")
    if claimed_quote and _normalized(selected) != _normalized(claimed_quote):
        raise SelectionError(
            "the selected passage is not the one this citation quotes; "
            "supersede the fact instead of re-pointing its citation"
        )

    boxes = geometry_for_span(page_text, words, start, end)
    return CitationFields(
        excerpt=selected,
        start_offset=start,
        end_offset=end,
        quoted_text_sha256=citations.text_hash(selected),
        match_kind=citations.MatchKind.EXACT.value,
        citation_status=CitationStatus.EXACT,
        bounding_boxes=boxes_to_json(boxes) if boxes else None,
        confidence=1.0,
    )


def geometry_for_span(
    page_text: str, words: Sequence[Word], start: int, end: int
) -> list[BoundingBox]:
    """Rectangles for an already-verified span, or an empty list.

    Empty is a normal answer: plain-text sources have no layout, and a scanned
    page has none until OCR provides it. The caller must not treat the absence
    of rectangles as an error, only as the absence of rectangles.
    """
    if not words or start is None or end is None or end <= start:
        return []
    return boxes_for_span(words, start, end, expected_text=page_text[start:end])
