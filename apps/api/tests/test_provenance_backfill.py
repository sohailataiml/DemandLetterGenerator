"""Backfilling geometry onto evidence that was ingested before it existed.

The demo cases in this repository predate page geometry, and so will any real
deployment's. What matters is that catching up is additive: the page text does
not move, the facts do not move, and nothing acquires a precision it did not
earn.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain.enums import CitationStatus
from app.domain.models import DocumentPage, Fact, FactSource
from app.ingestion import pdf_geometry
from app.provenance import backfill

from conftest import ATTORNEY, _post

PDF_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "provenance" / "mri-report.pdf"
PDF_MIME = "application/pdf"

L5_S1_QUOTE = (
    "Broad-based disc extrusion measuring 9 x 10 x 5 mm,\n"
    "extending into the right lateral recess with contact upon the\n"
    "traversing right S1 nerve root."
)

pytestmark = pytest.mark.skipif(
    not pdf_geometry.is_available(),
    reason="PyMuPDF is not installed; native PDF geometry is unavailable",
)


@pytest.fixture
def legacy_pdf_case(client, seeded_case, monkeypatch, db):
    """A case ingested as it would have been before this feature shipped.

    Geometry extraction is switched off for the upload only, so the page text on
    file is pypdf's — a genuinely different extractor from the one the backfill
    will later align words against.
    """
    monkeypatch.setattr(pdf_geometry, "extract", lambda data: None)
    response = client.post(
        f"/v1/cases/{seeded_case['case_id']}/documents",
        files={"file": ("mri-report.pdf", PDF_FIXTURE.read_bytes(), PDF_MIME)},
        headers=ATTORNEY,
    )
    assert response.status_code == 201, response.text
    monkeypatch.undo()
    return {**seeded_case, "document_id": response.json()["id"]}


def _cite(client, case_id, document_id, excerpt, page=3):
    return _post(
        client,
        f"/v1/cases/{case_id}/facts",
        {
            "fact_type": "imaging_finding",
            "value": {"level": "L5-S1"},
            "summary": "MRI showed a disc extrusion at L5-S1",
            "sources": [
                {"document_id": document_id, "page_number": page, "excerpt": excerpt}
            ],
        },
    )


def test_a_document_ingested_without_geometry_starts_without_geometry(
    client, legacy_pdf_case
):
    page = client.get(
        f"/v1/documents/{legacy_pdf_case['document_id']}/pages/3", headers=ATTORNEY
    ).json()

    assert page["has_geometry"] is False
    assert "L5-S1" in page["text"]


def test_backfill_adds_boxes_to_an_exact_citation_without_moving_the_page_text(
    client, legacy_pdf_case, db
):
    case_id = legacy_pdf_case["case_id"]
    document_id = legacy_pdf_case["document_id"]
    fact = _cite(client, case_id, document_id, L5_S1_QUOTE)
    citation_id = fact["sources"][0]["id"]
    assert fact["sources"][0]["citation_status"] == "EXACT"
    assert fact["sources"][0]["bounding_boxes"] is None

    before = db.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document_id, DocumentPage.page_number == 3
        )
    )
    text_before = before.text
    offsets_before = (fact["sources"][0]["start_offset"], fact["sources"][0]["end_offset"])

    report = backfill.run(db, case_id=case_id)
    db.commit()

    page = db.get(DocumentPage, before.id)
    db.refresh(page)
    citation = db.get(FactSource, citation_id)

    assert page.text == text_before, "backfill must never rewrite stored page text"
    assert page.has_geometry
    assert (citation.start_offset, citation.end_offset) == offsets_before
    assert citation.citation_status == CitationStatus.EXACT
    assert len(citation.bounding_boxes) == 3
    assert report.pages_with_geometry == 3
    assert report.boxes_added == 1


def test_backfill_leaves_a_paraphrase_text_only(client, legacy_pdf_case, db):
    fact = _cite(
        client,
        legacy_pdf_case["case_id"],
        legacy_pdf_case["document_id"],
        "Broad based disc extrusion measuring 9 x 10 x 5 millimetres",
    )
    citation_id = fact["sources"][0]["id"]
    assert fact["sources"][0]["match_kind"] == "approximate"

    report = backfill.run(db, case_id=legacy_pdf_case["case_id"])
    db.commit()

    citation = db.get(FactSource, citation_id)
    assert citation.citation_status == CitationStatus.TEXT_ONLY
    assert citation.bounding_boxes is None
    assert report.text_only == 1
    assert report.boxes_added == 0


def test_backfill_does_not_touch_the_facts_themselves(client, legacy_pdf_case, db):
    fact = _cite(
        client, legacy_pdf_case["case_id"], legacy_pdf_case["document_id"], L5_S1_QUOTE
    )
    verified = client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY).json()
    before = db.get(Fact, fact["id"])
    snapshot = (
        before.status,
        before.summary,
        dict(before.value),
        before.revision,
        before.reviewed_by,
        before.reviewed_at,
        before.updated_at,
    )

    backfill.run(db, case_id=legacy_pdf_case["case_id"])
    db.commit()

    after = db.get(Fact, fact["id"])
    db.refresh(after)
    assert (
        after.status,
        after.summary,
        dict(after.value),
        after.revision,
        after.reviewed_by,
        after.reviewed_at,
        after.updated_at,
    ) == snapshot
    assert verified["status"] == "VERIFIED"


def test_backfill_is_idempotent(client, legacy_pdf_case, db):
    _cite(client, legacy_pdf_case["case_id"], legacy_pdf_case["document_id"], L5_S1_QUOTE)

    first = backfill.run(db, case_id=legacy_pdf_case["case_id"])
    db.commit()
    second = backfill.run(db, case_id=legacy_pdf_case["case_id"])
    db.commit()

    assert first.pages_with_geometry == 3
    assert second.pages_with_geometry == 0, "already-indexed pages are not redone"
    assert second.boxes_added == 0


def test_a_page_whose_words_do_not_align_is_left_without_geometry(
    client, legacy_pdf_case, db, monkeypatch
):
    """An honest failure: no alignment, no rectangles, and it says which page."""
    page = db.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == legacy_pdf_case["document_id"],
            DocumentPage.page_number == 3,
        )
    )
    page.text = "a completely different transcription of this page"
    db.flush()

    report = backfill.run(db, case_id=legacy_pdf_case["case_id"])
    db.commit()

    db.refresh(page)
    assert page.word_count == 0
    assert report.pages_unalignable == 1
    assert any("do not align" in note for note in report.notes)
