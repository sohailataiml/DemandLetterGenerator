"""Fact lifecycle guarantees."""

from __future__ import annotations

from conftest import ATTORNEY, PARALEGAL, upload_text_document


def _document(client, case_id):
    return upload_text_document(client, case_id, "record.txt", "Patient chart excerpt.")


def test_ai_proposed_fact_is_not_verified_on_arrival(client, seeded_case):
    case_id = seeded_case["case_id"]
    doc = _document(client, case_id)

    response = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "imaging_finding",
            "value": {"level": "L5-S1", "finding": "disc extrusion"},
            "summary": "Disc extrusion at L5-S1",
            "confidence": 0.98,
            "sources": [{"document_id": doc["id"], "page_number": 1}],
        },
        headers=PARALEGAL,
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PROPOSED"


def test_verification_requires_a_source_citation(client, seeded_case):
    case_id = seeded_case["case_id"]
    fact = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "liability",
            "value": {"basis": "hearsay"},
            "summary": "Uncited assertion",
            "sources": [],
        },
        headers=PARALEGAL,
    ).json()

    response = client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY)
    assert response.status_code == 409
    assert "source document citation" in response.json()["detail"]


def test_source_page_must_exist_in_the_cited_document(client, seeded_case):
    case_id = seeded_case["case_id"]
    doc = _document(client, case_id)

    response = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "diagnosis",
            "value": {},
            "summary": "Cited to a page that does not exist",
            "sources": [{"document_id": doc["id"], "page_number": 99}],
        },
        headers=PARALEGAL,
    )
    assert response.status_code == 400
    assert "outside document" in response.json()["detail"]


def test_verified_fact_cannot_be_re_verified_or_rejected(client, seeded_case):
    case_id = seeded_case["case_id"]
    doc = _document(client, case_id)
    fact = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "diagnosis",
            "value": {"code": "M51.26"},
            "summary": "Lumbar disc displacement",
            "sources": [{"document_id": doc["id"], "page_number": 1}],
        },
        headers=PARALEGAL,
    ).json()
    assert client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY).status_code == 200

    assert client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY).status_code == 409
    assert (
        client.post(
            f"/v1/facts/{fact['id']}/reject", json={"reason": "changed my mind"}, headers=ATTORNEY
        ).status_code
        == 409
    )


def test_correcting_a_verified_fact_creates_a_superseding_revision(client, seeded_case):
    case_id = seeded_case["case_id"]
    doc = _document(client, case_id)
    original = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "imaging_finding",
            "value": {"measurement": "9 x 10 x 5 mm"},
            "summary": "Disc extrusion measuring 9 x 10 x 5 mm",
            "sources": [{"document_id": doc["id"], "page_number": 1}],
        },
        headers=PARALEGAL,
    ).json()
    client.post(f"/v1/facts/{original['id']}/verify", headers=ATTORNEY)

    replacement = client.post(
        f"/v1/facts/{original['id']}/supersede",
        json={
            "fact_type": "imaging_finding",
            "value": {"measurement": "9 x 10 x 6 mm"},
            "summary": "Disc extrusion measuring 9 x 10 x 6 mm",
            "reason": "Radiologist addendum corrected the measurement",
            "sources": [{"document_id": doc["id"], "page_number": 1}],
        },
        headers=ATTORNEY,
    )
    assert replacement.status_code == 201, replacement.text
    replacement = replacement.json()
    assert replacement["revision"] == 2
    assert replacement["supersedes_id"] == original["id"]
    assert replacement["status"] == "PROPOSED"

    # The original stays authoritative until the correction is itself verified.
    facts = {f["id"]: f for f in client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()}
    assert facts[original["id"]]["status"] == "VERIFIED"

    client.post(f"/v1/facts/{replacement['id']}/verify", headers=ATTORNEY)
    facts = {f["id"]: f for f in client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()}
    assert facts[original["id"]]["status"] == "SUPERSEDED"
    assert facts[original["id"]]["superseded_by_id"] == replacement["id"]


def test_rejected_fact_records_who_and_why(client, seeded_case):
    case_id = seeded_case["case_id"]
    doc = _document(client, case_id)
    fact = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "liability",
            "value": {},
            "summary": "Speculative liability assertion",
            "sources": [{"document_id": doc["id"], "page_number": 1}],
        },
        headers=PARALEGAL,
    ).json()

    response = client.post(
        f"/v1/facts/{fact['id']}/reject",
        json={"reason": "Not supported by the police report"},
        headers=ATTORNEY,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["reviewed_by"] == "attorney_45"
    assert body["rejection_reason"] == "Not supported by the police report"
