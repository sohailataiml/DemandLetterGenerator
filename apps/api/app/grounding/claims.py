"""Breaking generated prose into atomic factual claims.

Segmentation is the one part of grounding a model is allowed to touch, and even
then only under supervision: whatever it returns must be locatable in the text
it was given, using the same citation resolver that checks extraction. A
"decomposition" containing a sentence the section never said is discarded and
the deterministic segmenter is used instead.

The deterministic segmenter is the default. It is a sentence splitter, which is
a coarse notion of "atomic", and that is stated plainly rather than dressed up:
a sentence carrying two assertions is checked as one claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Abbreviations that end in a period without ending a sentence.
_ABBREVIATIONS = (
    "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "Inc.", "Ltd.", "Co.", "St.", "Ave.",
    "No.", "vs.", "approx.", "Jr.", "Sr.", "e.g.", "i.e.",
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_PLACEHOLDER = "\x00"
#: "1." and "  2." open a list item; they do not close a sentence.
_LIST_MARKER = re.compile(r"(?:(?<=^)|(?<=\s))(\d{1,2})\.(?=\s)")


@dataclass(frozen=True)
class Claim:
    """One assertion, and where it sits in the section body."""

    text: str
    start_offset: int
    end_offset: int
    position: int

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def _protect_abbreviations(text: str) -> str:
    protected = text
    for abbreviation in _ABBREVIATIONS:
        protected = protected.replace(abbreviation, abbreviation.replace(".", _PLACEHOLDER))
    return _LIST_MARKER.sub(rf"\1{_PLACEHOLDER}", protected)


def segment(body: str) -> list[Claim]:
    """Split a section body into claims, with offsets into ``body``."""
    if not body or not body.strip():
        return []

    claims: list[Claim] = []
    position = 0
    # Paragraphs and list lines are claim boundaries in their own right; a
    # bulleted list is a list of assertions, not one long sentence.
    line_offset = 0
    for line in body.split("\n"):
        if line.strip():
            for piece_start, piece in _split_sentences(line):
                start = line_offset + piece_start
                claims.append(
                    Claim(
                        text=piece.strip(),
                        start_offset=start,
                        end_offset=start + len(piece),
                        position=position,
                    )
                )
                position += 1
        line_offset += len(line) + 1
    return [claim for claim in claims if not claim.is_empty]


def _split_sentences(line: str) -> list[tuple[int, str]]:
    protected = _protect_abbreviations(line)
    pieces: list[tuple[int, str]] = []
    cursor = 0
    for match in _SENTENCE_END.finditer(protected):
        end = match.start()
        pieces.append((cursor, line[cursor:end]))
        cursor = match.end()
    if cursor < len(line):
        pieces.append((cursor, line[cursor:]))
    return [(start, text) for start, text in pieces if text.strip()]


def verify_segmentation(body: str, texts: list[str]) -> list[Claim] | None:
    """Accept a model's decomposition only if every piece is really in ``body``.

    Returns ``None`` when it is not, which tells the caller to use
    :func:`segment` instead. A model cannot introduce an assertion by claiming
    the text already contained it.
    """
    claims: list[Claim] = []
    cursor = 0
    for position, text in enumerate(texts):
        stripped = text.strip()
        if not stripped:
            continue
        found = body.find(stripped, cursor)
        if found == -1:
            found = body.find(stripped)
        if found == -1:
            return None
        claims.append(
            Claim(
                text=stripped,
                start_offset=found,
                end_offset=found + len(stripped),
                position=position,
            )
        )
        cursor = found + len(stripped)
    return claims or None
