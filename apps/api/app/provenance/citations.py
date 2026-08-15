"""Resolving a quoted passage to an exact span in a stored document page.

This is the deterministic half of provenance, and the reason an extraction
model cannot fabricate a source: whatever it claims to have quoted is looked up
in the page text the ingestion pipeline stored. If the words are not there, the
citation does not resolve, and a fact with no resolved citation is never
proposed.

Three outcomes, in descending order of confidence:

``EXACT``        the quoted text is present verbatim; offsets are the real ones.
``NORMALIZED``   present once whitespace is collapsed; offsets map back to the
                 original text and are still exact character positions.
``APPROXIMATE``  only a partial overlap was found. The UI must say so rather
                 than highlight a span it is guessing at.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum

#: Below this ratio a fuzzy match is not a match at all.
MIN_SIMILARITY = 0.72
#: Quotes shorter than this are too generic to locate meaningfully.
MIN_QUOTE_LENGTH = 12

_WHITESPACE = re.compile(r"\s+")


class MatchKind(str, Enum):
    EXACT = "exact"
    NORMALIZED = "normalized"
    APPROXIMATE = "approximate"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class ResolvedCitation:
    """A quote located in a page, or the fact that it could not be."""

    start_offset: int
    end_offset: int
    quoted_text: str
    quoted_text_sha256: str
    match_kind: MatchKind
    similarity: float = 1.0

    @property
    def is_exact(self) -> bool:
        return self.match_kind in (MatchKind.EXACT, MatchKind.NORMALIZED)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Whitespace-collapsed text plus a per-character index back to the original."""
    out: list[str] = []
    index_map: list[int] = []
    previous_space = False
    for position, char in enumerate(text):
        if char.isspace():
            if previous_space or not out:
                continue
            out.append(" ")
            index_map.append(position)
            previous_space = True
        else:
            out.append(char)
            index_map.append(position)
            previous_space = False
    return "".join(out), index_map


def _exact(page_text: str, quote: str) -> ResolvedCitation | None:
    position = page_text.find(quote)
    if position == -1:
        return None
    return ResolvedCitation(
        start_offset=position,
        end_offset=position + len(quote),
        quoted_text=quote,
        quoted_text_sha256=text_hash(quote),
        match_kind=MatchKind.EXACT,
    )


def _normalized(page_text: str, quote: str) -> ResolvedCitation | None:
    haystack, index_map = _normalized_with_map(page_text)
    needle = _WHITESPACE.sub(" ", quote).strip()
    if not needle:
        return None
    position = haystack.find(needle)
    if position == -1:
        return None
    start = index_map[position]
    end_index = position + len(needle) - 1
    end = index_map[end_index] + 1
    actual = page_text[start:end]
    return ResolvedCitation(
        start_offset=start,
        end_offset=end,
        quoted_text=actual,
        quoted_text_sha256=text_hash(actual),
        match_kind=MatchKind.NORMALIZED,
    )


#: An alignment anchor shorter than this is coincidence, not a match.
MIN_ANCHOR_CHARS = 10


def _approximate(page_text: str, quote: str) -> ResolvedCitation | None:
    """Best-effort location of a paraphrase.

    The longest shared run of characters is used only as an anchor to align the
    quote against the page; the score is then the similarity of the whole
    aligned window. Scoring the anchor alone would reject a paraphrase that
    differs in several small places while accepting one that happens to repeat
    a long boilerplate phrase.
    """
    needle = _WHITESPACE.sub(" ", quote).strip()
    if len(needle) < MIN_QUOTE_LENGTH:
        return None

    anchor = SequenceMatcher(None, page_text, needle, autojunk=False).find_longest_match(
        0, len(page_text), 0, len(needle)
    )
    if anchor.size < MIN_ANCHOR_CHARS:
        return None

    start = max(0, anchor.a - anchor.b)
    end = min(len(page_text), start + len(needle))
    window = page_text[start:end]
    similarity = SequenceMatcher(None, window, needle, autojunk=False).ratio()
    if similarity < MIN_SIMILARITY:
        return None

    return ResolvedCitation(
        start_offset=start,
        end_offset=end,
        quoted_text=window,
        quoted_text_sha256=text_hash(window),
        match_kind=MatchKind.APPROXIMATE,
        similarity=round(similarity, 4),
    )


def resolve(page_text: str, quote: str) -> ResolvedCitation | None:
    """Locate ``quote`` in ``page_text``, or return ``None``.

    ``None`` means the passage is not in the document. A caller must treat that
    as "this fact has no evidence", never as "cite the whole page".
    """
    if not page_text or not quote or not quote.strip():
        return None
    return _exact(page_text, quote) or _normalized(page_text, quote) or _approximate(
        page_text, quote
    )


def count_occurrences(page_text: str, quote: str) -> int:
    """How many times the page says this, verbatim or up to whitespace.

    A count above one is not a failure of matching — the page really does say it
    twice — but it does mean no single span can be called *the* source without a
    human choosing. Counting is done on the verbatim text first and falls back
    to the whitespace-collapsed text, mirroring :func:`resolve` so the two
    cannot disagree about whether a quote is present.
    """
    if not page_text or not quote or not quote.strip():
        return 0
    verbatim = page_text.count(quote)
    if verbatim:
        return verbatim
    haystack, _ = _normalized_with_map(page_text)
    needle = _WHITESPACE.sub(" ", quote).strip()
    if not needle:
        return 0
    return haystack.count(needle)


def verify_offsets(page_text: str, start: int, end: int, expected_hash: str) -> bool:
    """Do the recorded offsets still quote the text they were recorded against?"""
    if start < 0 or end > len(page_text) or start >= end:
        return False
    return text_hash(page_text[start:end]) == expected_hash
