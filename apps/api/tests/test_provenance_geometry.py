"""Document → page → span → bounding box, end to end.

The unit of trust here is not "did we draw a box" but "does the box cover the
words the citation quotes, and does the system refuse to draw one when it
cannot know". Every test below is one of those two questions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.enums import CitationStatus
from app.ingestion import pdf_geometry
from app.ingestion.extraction import extract
from app.provenance import geometry
from app.provenance import service as provenance
from app.provenance.geometry import BoundingBox, Word

PDF_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "provenance" / "mri-report.pdf"
PDF_MIME = "application/pdf"

#: The passage an attorney would actually cite, wrapped over three lines in the
#: fixture exactly as it is in a real report.
L5_S1_QUOTE = (
    "Broad-based disc extrusion measuring 9 x 10 x 5 mm,\n"
    "extending into the right lateral recess with contact upon the\n"
    "traversing right S1 nerve root."
)

needs_pdf_geometry = pytest.mark.skipif(
    not pdf_geometry.is_available(),
    reason="PyMuPDF is not installed; native PDF geometry is unavailable",
)


def _synthetic_page() -> tuple[str, tuple[Word, ...]]:
    """A two-line page with hand-written geometry, so the maths is checkable."""
    text = "L5-S1 disc extrusion\nmeasuring 9 mm"
    boxes = [
        # line one, y = 0.10, height 0.02
        ("L5-S1", 0.10, 0.10, 0.08),
        ("disc", 0.19, 0.10, 0.06),
        ("extrusion", 0.26, 0.10, 0.12),
        # line two, y = 0.14
        ("measuring", 0.10, 0.14, 0.11),
        ("9", 0.22, 0.14, 0.02),
        ("mm", 0.25, 0.14, 0.04),
    ]
    words: list[Word] = []
    cursor = 0
    for index, (word_text, x, y, width) in enumerate(boxes):
        start = text.index(word_text, cursor)
        cursor = start + len(word_text)
        words.append(
            Word(
                text=word_text,
                start=start,
                end=cursor,
                bbox=BoundingBox(x=x, y=y, width=width, height=0.02),
            )
        )
        assert text[words[index].start : words[index].end] == word_text
    return text, tuple(words)


# --------------------------------------------------------------- normalization


def test_a_rectangle_is_normalized_against_the_page_it_sits_on():
    box = BoundingBox.from_rect(72.0, 79.2, 306.0, 99.0, page_width=612.0, page_height=792.0)

    assert box.x == pytest.approx(72 / 612)
    assert box.y == pytest.approx(0.1)
    assert box.width == pytest.approx((306 - 72) / 612)
    assert box.height == pytest.approx((99 - 79.2) / 792)
    assert 0.0 <= box.x <= 1.0 and 0.0 <= box.y <= 1.0


def test_a_rectangle_outside_the_page_is_clamped_not_extrapolated():
    box = BoundingBox.from_rect(-10.0, -10.0, 700.0, 900.0, page_width=612.0, page_height=792.0)

    assert (box.x, box.y) == (0.0, 0.0)
    assert box.width == 1.0 and box.height == 1.0


# ------------------------------------------------------------------ span → box


def test_a_span_on_one_line_produces_one_box_covering_its_words():
    text, words = _synthetic_page()
    start = text.index("disc extrusion")
    boxes = geometry.boxes_for_span(words, start, start + len("disc extrusion"))

    assert len(boxes) == 1
    assert boxes[0].x == pytest.approx(0.19)
    # From the left edge of "disc" to the right edge of "extrusion".
    assert boxes[0].width == pytest.approx(0.26 + 0.12 - 0.19)


def test_a_span_across_two_lines_produces_one_box_per_line():
    text, words = _synthetic_page()
    boxes = geometry.boxes_for_span(words, 0, len(text))

    assert len(boxes) == 2
    assert [round(box.y, 3) for box in boxes] == [0.10, 0.14]


def test_geometry_is_withheld_when_the_words_do_not_spell_the_span():
    """The guard against silently highlighting the wrong passage."""
    text, words = _synthetic_page()
    start = text.index("disc")

    honest = geometry.boxes_for_span(words, start, start + 4, expected_text="disc")
    drifted = geometry.boxes_for_span(words, start, start + 4, expected_text="extrusion")

    assert len(honest) == 1
    assert drifted == []


def test_words_can_be_realigned_onto_page_text_stored_by_another_extractor():
    stored = "L5-S1   disc  extrusion"
    unaligned = (
        Word("L5-S1", 0, 5, BoundingBox(0.1, 0.1, 0.05, 0.02)),
        Word("disc", 6, 10, BoundingBox(0.16, 0.1, 0.04, 0.02)),
        Word("extrusion", 11, 20, BoundingBox(0.21, 0.1, 0.09, 0.02)),
    )

    aligned = geometry.align_words_to_text(stored, unaligned)

    assert aligned is not None
    assert all(stored[word.start : word.end] == word.text for word in aligned)


def test_words_that_are_not_in_the_stored_text_align_to_nothing():
    assert geometry.align_words_to_text("a different page entirely", (
        Word("L5-S1", 0, 5, BoundingBox(0.1, 0.1, 0.05, 0.02)),
    )) is None


# ------------------------------------------------------- citation construction


def test_an_exact_quote_becomes_an_exact_citation_with_boxes():
    text, words = _synthetic_page()
    fields = provenance.build_citation(page_text=text, quote="disc extrusion", words=words)

    assert fields.citation_status == CitationStatus.EXACT
    assert text[fields.start_offset : fields.end_offset] == "disc extrusion"
    assert fields.confidence == 1.0
    assert len(fields.bounding_boxes) == 1


def test_a_quote_the_page_repeats_is_ambiguous_and_gets_no_span():
    text = "L5-S1 disc extrusion\nImpression: L5-S1 disc extrusion"
    fields = provenance.build_citation(page_text=text, quote="L5-S1 disc extrusion")

    assert fields.citation_status == CitationStatus.AMBIGUOUS
    assert fields.start_offset is None and fields.end_offset is None
    assert fields.bounding_boxes is None
    # The claim is kept so a reviewer can see what was quoted and choose.
    assert fields.excerpt == "L5-S1 disc extrusion"


def test_a_paraphrase_is_text_only_and_never_gets_a_rectangle():
    text, words = _synthetic_page()
    fields = provenance.build_citation(
        page_text=text, quote="L5-S1 disc extrusion measuring 9 millimetres", words=words
    )

    assert fields.citation_status == CitationStatus.TEXT_ONLY
    assert fields.bounding_boxes is None
    assert fields.confidence is not None and fields.confidence < 1.0


def test_a_quote_the_page_does_not_contain_stays_unresolved():
    text, words = _synthetic_page()
    fields = provenance.build_citation(
        page_text=text, quote="cervical fracture at C4 with cord compression", words=words
    )

    assert fields.citation_status == CitationStatus.UNRESOLVED
    assert fields.start_offset is None
    assert fields.bounding_boxes is None


def test_an_exact_quote_on_a_page_without_geometry_is_exact_but_boxless():
    """Span-level certainty and box-level certainty are different things."""
    text, _ = _synthetic_page()
    fields = provenance.build_citation(page_text=text, quote="disc extrusion", words=())

    assert fields.citation_status == CitationStatus.EXACT
    assert fields.bounding_boxes is None


# ------------------------------------------------------------ reviewer choices


def test_a_reviewer_can_pin_an_ambiguous_citation_to_one_occurrence():
    text = "L5-S1 disc extrusion\nImpression: L5-S1 disc extrusion"
    second = text.rindex("L5-S1 disc extrusion")

    fields = provenance.citation_from_selection(
        page_text=text,
        start=second,
        end=second + len("L5-S1 disc extrusion"),
        claimed_quote="L5-S1 disc extrusion",
    )

    assert fields.citation_status == CitationStatus.EXACT
    assert fields.start_offset == second


def test_a_reviewer_cannot_repoint_a_citation_at_different_words():
    text, _ = _synthetic_page()
    with pytest.raises(provenance.SelectionError):
        provenance.citation_from_selection(
            page_text=text,
            start=0,
            end=5,
            claimed_quote="disc extrusion",
        )


# ------------------------------------------------------------- native PDF path


@needs_pdf_geometry
def test_native_pdf_extraction_yields_canonical_text_that_indexes_its_own_words():
    result = extract(PDF_FIXTURE.read_bytes(), PDF_MIME, "mri-report.pdf")

    assert result.page_count == 3
    page = result.pages[2]
    assert page.extraction_method == geometry.NATIVE
    assert (page.width, page.height) == (612.0, 792.0)
    assert page.words
    # The invariant the whole model rests on.
    for word in page.words:
        assert page.text[word.start : word.end] == word.text


@needs_pdf_geometry
def test_a_multi_line_finding_highlights_as_one_box_per_line():
    result = extract(PDF_FIXTURE.read_bytes(), PDF_MIME, "mri-report.pdf")
    page = result.pages[2]

    fields = provenance.build_citation(
        page_text=page.text, quote=L5_S1_QUOTE, words=page.words
    )

    assert fields.citation_status == CitationStatus.EXACT
    assert len(fields.bounding_boxes) == 3
    # Boxes descend the page and stay inside it.
    tops = [box["y"] for box in fields.bounding_boxes]
    assert tops == sorted(tops)
    for box in fields.bounding_boxes:
        assert 0.0 <= box["x"] and box["x"] + box["width"] <= 1.0
        assert 0.0 <= box["y"] and box["y"] + box["height"] <= 1.0


@needs_pdf_geometry
def test_the_cited_page_is_the_page_the_finding_is_printed_on():
    result = extract(PDF_FIXTURE.read_bytes(), PDF_MIME, "mri-report.pdf")

    pages_mentioning = [
        index for index, page in enumerate(result.pages, start=1) if "L5-S1" in page.text
    ]
    assert pages_mentioning == [3]
