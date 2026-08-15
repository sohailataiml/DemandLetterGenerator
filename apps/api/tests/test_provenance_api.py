"""The provenance chain over HTTP: fact → citation → document → page → box.

These exercise what an attorney's browser actually does, including the parts
that are refusals: a page endpoint that will not hand out another page, a
citation that will not pretend to know where it came from, and a source
endpoint that will not leak where the file lives on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion import pdf_geometry

from conftest import ATTORNEY, PARALEGAL, READONLY, _post, upload_text_document

PDF_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "provenance" / "mri-report.pdf"
PDF_MIME = "application/pdf"

L5_S1_QUOTE = (
    "Broad-based disc extrusion measuring 9 x 10 x 5 mm,\n"
    "extending into the right lateral recess with contact upon the\n"
    "traversing right S1 nerve root."
)

needs_pdf_geometry = pytest.mark.skipif(
    not pdf_geometry.is_available(),
    reason="PyMuPDF is not installed; native PDF geometry is unavailable",
)


def upload_pdf(client, case_id: str) -> dict:
    response = client.post(
        f"/v1/cases/{case_id}/documents",
        files={"file": ("mri-report.pdf", PDF_FIXTURE.read_bytes(), PDF_MIME)},
        data={"document_type": "MRI_REPORT", "provider_name": "MAX MRI Radiology"},
        headers=ATTORNEY,
    )
    assert response.status_code == 201, response.text
    return response.json()


def cite(client, case_id: str, document_id: str, page: int, excerpt: str | None) -> dict:
    return _post(
        client,
        f"/v1/cases/{case_id}/facts",
        {
            "fact_type": "imaging_finding",
            "value": {"level": "L5-S1", "finding": "disc extrusion"},
            "summary": "MRI showed a disc extrusion at L5-S1 measuring 9 x 10 x 5 mm",
            "sources": [
                {"document_id": document_id, "page_number": page, "excerpt": excerpt}
            ],
        },
    )


@pytest.fixture
def pdf_case(client, seeded_case) -> dict:
    document = upload_pdf(client, seeded_case["case_id"])
    return {**seeded_case, "document_id": document["id"], "document": document}


# ------------------------------------------------------------- page endpoints


@needs_pdf_geometry
def test_a_page_endpoint_returns_only_the_page_that_was_asked_for(client, pdf_case):
    response = client.get(
        f"/v1/documents/{pdf_case['document_id']}/pages/3", headers=ATTORNEY
    )

    assert response.status_code == 200
    page = response.json()
    assert page["page_number"] == 3
    assert "L5-S1" in page["text"]
    assert (page["width"], page["height"]) == (612.0, 792.0)
    assert page["extraction_method"] == "native"
    assert page["has_geometry"] is True
    # The word array is large and is not part of this response.
    assert "words" not in page


def test_asking_for_a_page_the_document_does_not_have_is_a_404(client, pdf_case):
    response = client.get(
        f"/v1/documents/{pdf_case['document_id']}/pages/99", headers=ATTORNEY
    )
    assert response.status_code == 404


@needs_pdf_geometry
def test_page_geometry_is_fetched_separately_and_indexes_the_page_text(client, pdf_case):
    document_id = pdf_case["document_id"]
    text = client.get(f"/v1/documents/{document_id}/pages/3", headers=ATTORNEY).json()["text"]

    response = client.get(
        f"/v1/documents/{document_id}/pages/3/geometry", headers=ATTORNEY
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page_number"] == 3
    assert payload["extraction_method"] == "native"
    assert payload["words"]
    for word in payload["words"]:
        assert text[word["start"] : word["end"]] == word["text"]
        box = word["bbox"]
        assert 0.0 <= box["x"] <= 1.0 and 0.0 <= box["y"] <= 1.0


def test_a_page_of_a_plain_text_document_has_no_geometry_and_says_so(client, seeded_case):
    document = upload_text_document(
        client, seeded_case["case_id"], "note.txt", "Lumbar pain after the collision."
    )

    page = client.get(f"/v1/documents/{document['id']}/pages/1", headers=ATTORNEY).json()
    geometry = client.get(
        f"/v1/documents/{document['id']}/pages/1/geometry", headers=ATTORNEY
    ).json()

    assert page["has_geometry"] is False
    assert page["extraction_method"] == "text"
    assert geometry["words"] == []


def test_page_and_geometry_endpoints_require_a_known_role(client, pdf_case):
    document_id = pdf_case["document_id"]

    assert client.get(f"/v1/documents/{document_id}/pages/1").status_code == 401
    assert (
        client.get(f"/v1/documents/{document_id}/pages/1/geometry").status_code == 401
    )
    # A read-only reviewer may look at evidence; that is the whole job.
    assert (
        client.get(f"/v1/documents/{document_id}/pages/1", headers=READONLY).status_code == 200
    )


def test_the_source_endpoint_serves_bytes_and_never_a_filesystem_path(client, pdf_case):
    response = client.get(
        f"/v1/documents/{pdf_case['document_id']}/content", headers=ATTORNEY
    )

    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-"
    assert response.headers["X-Content-SHA256"] == pdf_case["document"]["sha256"]
    serialized = " ".join(f"{key}: {value}" for key, value in response.headers.items())
    assert "storage" not in serialized.lower()
    assert ":\\" not in serialized and "/var/" not in serialized


# ----------------------------------------------------------------- citations


@needs_pdf_geometry
def test_a_verbatim_citation_carries_a_box_per_line_of_the_passage(client, pdf_case):
    fact = cite(client, pdf_case["case_id"], pdf_case["document_id"], 3, L5_S1_QUOTE)

    citation = fact["sources"][0]
    assert citation["citation_status"] == "EXACT"
    assert citation["page_number"] == 3
    assert citation["confidence"] == 1.0
    assert len(citation["bounding_boxes"]) == 3

    # The same records are reachable on their own, for one fact at a time.
    listed = client.get(f"/v1/facts/{fact['id']}/citations", headers=ATTORNEY)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [citation["id"]]


@needs_pdf_geometry
def test_a_paraphrased_citation_is_text_only_and_carries_no_box(client, pdf_case):
    fact = cite(
        client,
        pdf_case["case_id"],
        pdf_case["document_id"],
        3,
        "Broad based disc extrusion measuring 9 x 10 x 5 millimetres",
    )

    citation = fact["sources"][0]
    assert citation["citation_status"] == "TEXT_ONLY"
    assert citation["bounding_boxes"] is None


def test_a_citation_with_no_excerpt_is_unresolved_but_still_evidence(client, pdf_case):
    fact = cite(client, pdf_case["case_id"], pdf_case["document_id"], 3, None)

    citation = fact["sources"][0]
    assert citation["citation_status"] == "UNRESOLVED"
    assert citation["start_offset"] is None
    assert citation["bounding_boxes"] is None

    # Page-level provenance is thin, but it is provenance: this still verifies.
    verified = client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY)
    assert verified.status_code == 200
    assert verified.json()["status"] == "VERIFIED"


def test_a_quote_the_page_repeats_is_ambiguous_until_a_reviewer_chooses(client, seeded_case):
    document = upload_text_document(
        client,
        seeded_case["case_id"],
        "repeated.txt",
        "L5-S1 disc extrusion noted.\nIMPRESSION\nL5-S1 disc extrusion noted.",
    )
    fact = cite(
        client, seeded_case["case_id"], document["id"], 1, "L5-S1 disc extrusion noted."
    )

    citation = fact["sources"][0]
    assert citation["citation_status"] == "AMBIGUOUS"
    assert citation["start_offset"] is None

    page_text = client.get(
        f"/v1/documents/{document['id']}/pages/1", headers=ATTORNEY
    ).json()["text"]
    second = page_text.rindex("L5-S1 disc extrusion noted.")

    resolved = client.post(
        f"/v1/citations/{citation['id']}/resolve",
        json={"start_offset": second, "end_offset": second + len("L5-S1 disc extrusion noted.")},
        headers=ATTORNEY,
    )

    assert resolved.status_code == 200
    assert resolved.json()["citation_status"] == "EXACT"
    assert resolved.json()["start_offset"] == second


def test_a_reviewer_cannot_repoint_a_citation_at_a_different_passage(client, seeded_case):
    document = upload_text_document(
        client, seeded_case["case_id"], "note.txt", "L5-S1 disc extrusion. Cervical strain."
    )
    fact = cite(client, seeded_case["case_id"], document["id"], 1, "L5-S1 disc extrusion")
    citation = fact["sources"][0]

    response = client.post(
        f"/v1/citations/{citation['id']}/resolve",
        json={"start_offset": 22, "end_offset": 37},
        headers=ATTORNEY,
    )

    assert response.status_code == 400
    assert "supersede" in response.json()["detail"]


def test_resolving_a_citation_needs_a_role_that_may_verify(client, seeded_case):
    document = upload_text_document(
        client, seeded_case["case_id"], "note.txt", "L5-S1 disc extrusion."
    )
    fact = cite(client, seeded_case["case_id"], document["id"], 1, "L5-S1 disc extrusion")
    citation = fact["sources"][0]

    response = client.post(
        f"/v1/citations/{citation['id']}/resolve",
        json={"start_offset": 0, "end_offset": 20},
        headers=READONLY,
    )

    assert response.status_code == 403


# --------------------------------------------------- verified facts stay fixed


def test_enriching_a_citation_does_not_change_the_verified_fact_it_supports(
    client, seeded_case
):
    """Provenance enrichment is not a fact edit — INVARIANT: verified is final."""
    document = upload_text_document(
        client,
        seeded_case["case_id"],
        "repeated.txt",
        "L5-S1 disc extrusion noted.\nIMPRESSION\nL5-S1 disc extrusion noted.",
    )
    fact = cite(
        client, seeded_case["case_id"], document["id"], 1, "L5-S1 disc extrusion noted."
    )
    verified = client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY).json()
    citation = verified["sources"][0]
    assert citation["citation_status"] == "AMBIGUOUS"

    client.post(
        f"/v1/citations/{citation['id']}/resolve",
        json={"start_offset": 0, "end_offset": len("L5-S1 disc extrusion noted.")},
        headers=PARALEGAL,
    )

    after = client.get(
        f"/v1/cases/{seeded_case['case_id']}/facts", headers=ATTORNEY
    ).json()
    same_fact = next(item for item in after if item["id"] == fact["id"])

    assert same_fact["status"] == "VERIFIED"
    assert same_fact["summary"] == verified["summary"]
    assert same_fact["value"] == verified["value"]
    assert same_fact["revision"] == verified["revision"]
    assert same_fact["reviewed_by"] == verified["reviewed_by"]
    assert same_fact["sources"][0]["citation_status"] == "EXACT"


def test_the_resolution_is_attributed_in_the_audit_trail(client, seeded_case):
    document = upload_text_document(
        client, seeded_case["case_id"], "note.txt", "L5-S1 disc extrusion noted."
    )
    fact = cite(
        client, seeded_case["case_id"], document["id"], 1, "L5-S1 disc extrusion noted."
    )
    client.post(
        f"/v1/citations/{fact['sources'][0]['id']}/resolve",
        json={"start_offset": 0, "end_offset": 27},
        headers=PARALEGAL,
    )

    events = client.get(
        f"/v1/cases/{seeded_case['case_id']}/audit?limit=200", headers=ATTORNEY
    ).json()
    resolved = [event for event in events if event["event"] == "CITATION_RESOLVED"]

    assert len(resolved) == 1
    assert resolved[0]["actor"] == PARALEGAL["X-User-Id"]
