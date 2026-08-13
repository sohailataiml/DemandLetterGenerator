"""Citations resolve to real spans, or they do not resolve at all."""

from __future__ import annotations

import pytest

from app.provenance import citations

PAGE = """MAX MRI RADIOLOGY
Patient: Patrick Donahue
Study Date: December 21, 2024

FINDINGS
L5-S1: Broad-based disc extrusion measuring 9 x 10 x 5 mm, extending
into the right lateral recess with contact upon the traversing right
S1 nerve root.

IMPRESSION
1. L5-S1 disc extrusion with right S1 nerve root contact.
"""


def test_an_exact_quote_resolves_to_its_real_offsets():
    quote = "L5-S1: Broad-based disc extrusion measuring 9 x 10 x 5 mm"
    resolved = citations.resolve(PAGE, quote)

    assert resolved is not None
    assert resolved.match_kind == citations.MatchKind.EXACT
    assert PAGE[resolved.start_offset : resolved.end_offset] == quote
    assert resolved.is_exact


def test_a_quote_that_differs_only_in_whitespace_still_resolves_exactly():
    quote = "disc  extrusion   measuring 9 x 10 x 5 mm"
    resolved = citations.resolve(PAGE, quote)

    assert resolved is not None
    assert resolved.match_kind == citations.MatchKind.NORMALIZED
    assert resolved.is_exact
    # The offsets index the original text, not the normalized copy.
    assert PAGE[resolved.start_offset : resolved.end_offset] == resolved.quoted_text
    assert "disc extrusion measuring 9 x 10 x 5 mm" in " ".join(resolved.quoted_text.split())


def test_a_quote_spanning_a_line_break_resolves():
    quote = "extending into the right lateral recess"
    resolved = citations.resolve(PAGE, quote)
    assert resolved is not None
    assert resolved.is_exact


def test_a_near_quote_resolves_only_as_approximate():
    quote = "L5-S1: Broad based disc extrusion measuring 9 x 10 x 5 millimetres"
    resolved = citations.resolve(PAGE, quote)

    assert resolved is not None
    assert resolved.match_kind == citations.MatchKind.APPROXIMATE
    assert not resolved.is_exact
    assert resolved.similarity < 1.0


def test_a_fabricated_quote_does_not_resolve():
    invented = "The collision caused permanent nerve damage requiring lifelong care."
    assert citations.resolve(PAGE, invented) is None


def test_an_empty_quote_does_not_resolve():
    assert citations.resolve(PAGE, "") is None
    assert citations.resolve(PAGE, "   ") is None
    assert citations.resolve("", "anything") is None


def test_a_trivially_short_quote_does_not_fuzzy_match():
    """Two characters match almost anything; that is not provenance."""
    assert citations.resolve(PAGE, "zq") is None


def test_offsets_can_be_re_verified_against_the_page():
    resolved = citations.resolve(PAGE, "S1 nerve root")
    assert resolved is not None
    assert citations.verify_offsets(
        PAGE, resolved.start_offset, resolved.end_offset, resolved.quoted_text_sha256
    )


def test_verification_fails_if_the_page_text_moved():
    resolved = citations.resolve(PAGE, "S1 nerve root")
    assert resolved is not None
    shifted = "PREFIX ADDED\n" + PAGE
    assert not citations.verify_offsets(
        shifted, resolved.start_offset, resolved.end_offset, resolved.quoted_text_sha256
    )


@pytest.mark.parametrize(
    "start,end",
    [(-1, 5), (0, 10_000), (10, 10), (20, 5)],
)
def test_verification_rejects_impossible_offsets(start, end):
    assert not citations.verify_offsets(PAGE, start, end, "irrelevant")


def test_the_quoted_hash_identifies_the_quoted_text():
    resolved = citations.resolve(PAGE, "IMPRESSION")
    assert resolved is not None
    assert resolved.quoted_text_sha256 == citations.text_hash("IMPRESSION")
