"""Downloading the approved artifact must return the approved bytes.

Regression: the download endpoints used to re-render the document on every
request. python-docx stamps each render with the current time, so the bytes
differed from the ones that were approved and hashed — the write-once store
refused the overwrite and the request 500'd. Worse, had the write succeeded,
the reader would have received a document that was never approved.
"""

from __future__ import annotations

from conftest import ATTORNEY, READONLY


def _approved_demand(client, seeded_case_with_facts) -> str:
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    response = client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case_with_facts["reference"]},
        headers=ATTORNEY,
    )
    assert response.status_code == 200, response.text
    return demand["id"]


def test_approved_docx_downloads_repeatedly_and_never_changes(
    client, seeded_case_with_facts
):
    demand_id = _approved_demand(client, seeded_case_with_facts)

    first = client.get(f"/v1/demands/{demand_id}/docx", headers=ATTORNEY)
    second = client.get(f"/v1/demands/{demand_id}/docx", headers=READONLY)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.content == second.content
    assert first.content[:2] == b"PK"


def test_downloaded_bytes_match_the_hash_recorded_at_approval(
    client, seeded_case_with_facts
):
    import hashlib

    demand_id = _approved_demand(client, seeded_case_with_facts)
    approved = client.get(f"/v1/demands/{demand_id}", headers=ATTORNEY).json()

    downloaded = client.get(f"/v1/demands/{demand_id}/docx", headers=ATTORNEY)

    assert hashlib.sha256(downloaded.content).hexdigest() == approved["docx_sha256"]
    assert downloaded.headers["X-Content-SHA256"] == approved["docx_sha256"]


def test_pdf_on_an_approved_demand_reports_unavailability_rather_than_failing(
    client, seeded_case_with_facts
):
    """Without a converter this must be a clean 503, not a 500."""
    demand_id = _approved_demand(client, seeded_case_with_facts)

    response = client.get(f"/v1/demands/{demand_id}/pdf", headers=ATTORNEY)

    assert response.status_code in (200, 503)
    if response.status_code == 503:
        assert "LibreOffice" in response.json()["detail"]
    else:
        assert response.content[:5] == b"%PDF-"


def test_draft_docx_still_renders_on_demand(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    first = client.get(f"/v1/demands/{demand['id']}/docx", headers=ATTORNEY)
    second = client.get(f"/v1/demands/{demand['id']}/docx", headers=ATTORNEY)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content[:2] == b"PK"
