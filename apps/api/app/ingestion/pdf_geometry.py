"""Native PDF text extraction *with* word geometry.

Only PDFs that carry their own text layer are handled here — this is not OCR,
and it never guesses. When the backend is unavailable or a page has no text
layer, the caller falls back to plain text extraction and the pages simply have
no geometry, which the citation model represents honestly.

The canonical page text is built from the words themselves: words on a line are
joined with a single space, lines with a newline. Doing it this way means the
offsets stored on a citation and the boxes drawn on the page come from one
source, so ``page_text[word.start:word.end] == word.text`` by construction
rather than by hopeful coincidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..provenance.geometry import NATIVE, BoundingBox, PageGeometry, Word


@dataclass(frozen=True)
class GeometryPage:
    """One page: its canonical text and the geometry that produced it."""

    text: str
    geometry: PageGeometry


def is_available() -> bool:
    return _load() is not None


def _load():
    try:  # PyMuPDF ships as ``pymupdf`` (>=1.24) and historically as ``fitz``.
        import pymupdf  # type: ignore

        return pymupdf
    except ImportError:  # pragma: no cover - exercised only without the extra
        try:
            import fitz  # type: ignore

            return fitz
        except ImportError:
            return None


def extract(data: bytes) -> list[GeometryPage] | None:
    """Words and page sizes for every page, or ``None`` if unavailable.

    ``None`` means "this backend cannot speak for this file" — no geometry, no
    canonical text — and the caller must fall back rather than treat the file as
    empty.
    """
    module = _load()
    if module is None:
        return None
    try:
        document = module.open(stream=data, filetype="pdf")
    except Exception:  # pragma: no cover - depends on the file
        return None

    pages: list[GeometryPage] = []
    try:
        for index, page in enumerate(document, start=1):
            pages.append(_page(page, index))
    except Exception:  # pragma: no cover - depends on the file
        return None
    finally:
        document.close()
    return pages


def _page(page, page_number: int) -> GeometryPage:
    rect = page.rect
    width = float(rect.width)
    height = float(rect.height)

    # (x0, y0, x1, y1, word, block_no, line_no, word_no) — sorted into reading
    # order rather than the order the content stream happened to draw them in.
    raw = sorted(page.get_text("words"), key=lambda item: (item[5], item[6], item[7]))

    pieces: list[str] = []
    words: list[Word] = []
    cursor = 0
    line_key: tuple[int, int] | None = None

    for x0, y0, x1, y1, text, block_no, line_no, _word_no in raw:
        if not text:
            continue
        key = (block_no, line_no)
        if line_key is None:
            separator = ""
        elif key == line_key:
            separator = " "
        else:
            separator = "\n"
        line_key = key

        if separator:
            pieces.append(separator)
            cursor += len(separator)

        start = cursor
        pieces.append(text)
        cursor += len(text)
        words.append(
            Word(
                text=text,
                start=start,
                end=cursor,
                bbox=BoundingBox.from_rect(x0, y0, x1, y1, width, height),
            )
        )

    return GeometryPage(
        text="".join(pieces),
        geometry=PageGeometry(
            page_number=page_number,
            width=width,
            height=height,
            extraction_method=NATIVE,
            words=tuple(words),
        ),
    )
