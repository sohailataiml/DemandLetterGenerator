"""Page geometry: where on the rendered page a stretch of text actually sits.

This is the last link in the provenance chain — document, page, span, *region*.
Three rules keep it honest:

1. Coordinates are **normalized** to the rendered page: ``x``, ``y``, ``width``
   and ``height`` are fractions of page width/height in ``[0, 1]``. A viewer can
   then draw them at any zoom without knowing the PDF's point size.
2. Offsets are **page-local** indexes into the canonical page text stored in
   ``document_pages.text``. They are Python string indexes, i.e. Unicode code
   points, not bytes and not grapheme clusters.
3. A span only gets boxes when the words underneath it actually spell the span.
   :func:`boxes_for_span` re-reads the words it selected and compares them with
   the text it was asked to cover; a mismatch returns no boxes at all rather
   than a rectangle over the wrong words.

The word list is the only thing an extraction backend has to produce, so a
future OCR engine plugs in here by emitting the same ``Word`` records with
``extraction_method="ocr"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

#: How the words on a page were obtained. ``native`` means the PDF carried its
#: own text layer; ``ocr`` is reserved for a recognition engine; ``text`` means
#: a format with characters but no geometry (``.txt``, ``.docx``); ``none``
#: means no text at all.
NATIVE = "native"
OCR = "ocr"
TEXT = "text"
NONE = "none"

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _clamp(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


@dataclass(frozen=True)
class BoundingBox:
    """A rectangle on the rendered page, in normalized page coordinates."""

    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return {
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "width": round(self.width, 6),
            "height": round(self.height, 6),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "BoundingBox":
        return cls(
            x=float(payload["x"]),
            y=float(payload["y"]),
            width=float(payload["width"]),
            height=float(payload["height"]),
        )

    @classmethod
    def from_rect(
        cls, x0: float, y0: float, x1: float, y1: float, page_width: float, page_height: float
    ) -> "BoundingBox":
        """Normalize a rectangle given in page units (PDF points, OCR pixels)."""
        if page_width <= 0 or page_height <= 0:
            raise ValueError("page dimensions must be positive to normalize a rectangle")
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        x = _clamp(left / page_width)
        y = _clamp(top / page_height)
        return cls(
            x=x,
            y=y,
            width=_clamp(right / page_width) - x,
            height=_clamp(bottom / page_height) - y,
        )

    def union(self, other: "BoundingBox") -> "BoundingBox":
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        right = max(self.x + self.width, other.x + other.width)
        bottom = max(self.y + self.height, other.y + other.height)
        return BoundingBox(x=x, y=y, width=right - x, height=bottom - y)


@dataclass(frozen=True)
class Word:
    """One word of the canonical page text, and the region it occupies.

    ``start``/``end`` index ``document_pages.text`` for this page, so
    ``page_text[word.start:word.end] == word.text`` holds for every word a
    backend emits.
    """

    text: str
    start: int
    end: int
    bbox: BoundingBox

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "bbox": self.bbox.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Word":
        return cls(
            text=payload["text"],
            start=int(payload["start"]),
            end=int(payload["end"]),
            bbox=BoundingBox.from_dict(payload["bbox"]),
        )


@dataclass(frozen=True)
class PageGeometry:
    """The renderable description of one page: its size and its words."""

    page_number: int
    width: float
    height: float
    extraction_method: str
    words: tuple[Word, ...] = ()

    @property
    def has_geometry(self) -> bool:
        return bool(self.words) and self.width > 0 and self.height > 0

    def words_as_json(self) -> list[dict]:
        return [word.to_dict() for word in self.words]


def words_from_json(payload: Iterable[dict] | None) -> tuple[Word, ...]:
    if not payload:
        return ()
    return tuple(Word.from_dict(item) for item in payload)


def boxes_to_json(boxes: Sequence[BoundingBox]) -> list[dict]:
    return [box.to_dict() for box in boxes]


#: Two words belong to the same visual line when their vertical centres are
#: within this fraction of the taller word's height.
_SAME_LINE_TOLERANCE = 0.6


def _same_line(previous: Word, current: Word) -> bool:
    previous_centre = previous.bbox.y + previous.bbox.height / 2
    current_centre = current.bbox.y + current.bbox.height / 2
    tolerance = _SAME_LINE_TOLERANCE * max(previous.bbox.height, current.bbox.height, 1e-6)
    return abs(previous_centre - current_centre) <= tolerance


def words_in_span(words: Sequence[Word], start: int, end: int) -> list[Word]:
    """Words whose own span overlaps ``[start, end)``, in reading order."""
    if end <= start:
        return []
    return [word for word in words if word.start < end and word.end > start]


def boxes_for_span(
    words: Sequence[Word],
    start: int,
    end: int,
    *,
    expected_text: str | None = None,
) -> list[BoundingBox]:
    """Rectangles covering ``[start, end)`` — one per visual line, or none.

    A passage that wraps across three lines produces three boxes, because a
    single rectangle around all three would also cover text the citation does
    not quote.

    ``expected_text`` is the page text the offsets are supposed to select. When
    it is given, the words picked out here must spell it (ignoring whitespace);
    otherwise the geometry and the text have drifted apart and the honest answer
    is no geometry at all.
    """
    selected = words_in_span(words, start, end)
    if not selected:
        return []

    if expected_text is not None:
        covered = _normalize(" ".join(word.text for word in selected))
        if covered != _normalize(expected_text):
            return []

    lines: list[BoundingBox] = []
    current: BoundingBox | None = None
    previous: Word | None = None
    for word in selected:
        if current is None or previous is None or not _same_line(previous, word):
            if current is not None:
                lines.append(current)
            current = word.bbox
        else:
            current = current.union(word.bbox)
        previous = word
    if current is not None:
        lines.append(current)
    return lines


def align_words_to_text(page_text: str, words: Sequence[Word]) -> tuple[Word, ...] | None:
    """Re-index words against page text that was stored by another extractor.

    Used when geometry is added to a document that was ingested before this
    feature existed: the page text on file must not change (offsets already
    recorded against it would move), so the words are walked forward through it
    instead. Returns ``None`` if the word sequence is not present in reading
    order, which is the signal to leave that page without geometry.
    """
    aligned: list[Word] = []
    cursor = 0
    for word in words:
        if not word.text:
            continue
        position = page_text.find(word.text, cursor)
        if position == -1:
            return None
        end = position + len(word.text)
        aligned.append(Word(text=word.text, start=position, end=end, bbox=word.bbox))
        cursor = end
    return tuple(aligned) or None
