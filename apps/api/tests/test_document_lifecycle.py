"""Removing an uploaded document, and the limits the uploader advertises.

These cover the two endpoints the browser upload workflow needed that did not
exist before: ``DELETE /v1/documents/{id}`` and ``GET /v1/upload-limits``.
"""

from __future__ import annotations

from conftest import ATTORNEY, PARALEGAL, READONLY, upload_text_document

from app.config import get_settings
from app.ingestion.storage import get_object_store


def _audit_events(client, case_id: str) -> list[str]:
    response = client.get(f"/v1/cases/{case_id}/audit?limit=500", headers=ATTORNEY)
    assert response.status_code == 200, response.text
    return [event["event"] for event in response.json()]


# ------------------------------------------------------------------ upload limits


def test_upload_limits_report_what_the_scanner_actually_accepts(client):
    limits = client.get("/v1/upload-limits", headers=READONLY).json()
    settings = get_settings()

    assert limits["max_upload_bytes"] == settings.max_upload_bytes
    assert set(limits["allowed_mime_types"]) == set(settings.allowed_upload_mime)
    # Every advertised extension must map back to an allowed MIME type; an
    # uploader that offers ".exe" because a list drifted is the failure here.
    assert ".pdf" in limits["allowed_extensions"]
    assert ".docx" in limits["allowed_extensions"]
    assert ".exe" not in limits["allowed_extensions"]
    assert limits["template_extensions"] == [".docx"]
    assert limits["max_template_bytes"] > 0


def test_upload_limits_require_authentication(client):
    assert client.get("/v1/upload-limits").status_code == 401


# --------------------------------------------------------------------- removal


def test_removing_a_document_deletes_its_pages_bytes_and_leaves_an_audit_trail(
    client, seeded_case
):
    case_id = seeded_case["case_id"]
    document = upload_text_document(client, case_id, "wrong-file.txt", "uploaded by mistake")
    storage_key = document["storage_key"]
    assert get_object_store().exists(storage_key)

    response = client.delete(f"/v1/documents/{document['id']}", headers=ATTORNEY)
    assert response.status_code == 204, response.text

    assert client.get(f"/v1/cases/{case_id}/documents", headers=ATTORNEY).json() == []
    assert client.get(f"/v1/documents/{document['id']}", headers=ATTORNEY).status_code == 404
    assert not get_object_store().exists(storage_key)
    assert "DOCUMENT_REMOVED" in _audit_events(client, case_id)


def test_a_document_a_fact_cites_cannot_be_removed(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    document_id = seeded_case_with_facts["document_id"]

    response = client.delete(f"/v1/documents/{document_id}", headers=ATTORNEY)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "cite" in detail["message"]
    assert len(detail["fact_ids"]) > 0

    # Still on file, bytes intact — the refusal must not half-delete anything.
    assert client.get(f"/v1/documents/{document_id}", headers=ATTORNEY).status_code == 200
    assert "DOCUMENT_REMOVED" not in _audit_events(client, case_id)


def test_a_rejected_facts_citation_still_protects_its_document(client, seeded_case):
    """Provenance for a rejection matters as much as provenance for a fact."""
    case_id = seeded_case["case_id"]
    document = upload_text_document(client, case_id, "disputed.txt", "contested passage")

    fact = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "liability",
            "value": {"basis": "narrative"},
            "summary": "A claim the attorney went on to reject",
            "sources": [
                {
                    "document_id": document["id"],
                    "page_number": 1,
                    "excerpt": "contested passage",
                }
            ],
        },
        headers=ATTORNEY,
    ).json()
    reject = client.post(
        f"/v1/facts/{fact['id']}/reject",
        json={"reason": "not supported by the underlying record"},
        headers=ATTORNEY,
    )
    assert reject.status_code == 200, reject.text

    assert client.delete(f"/v1/documents/{document['id']}", headers=ATTORNEY).status_code == 409


def test_readonly_user_cannot_remove_a_document(client, seeded_case):
    case_id = seeded_case["case_id"]
    document = upload_text_document(client, case_id, "keep.txt", "still here")

    assert client.delete(f"/v1/documents/{document['id']}", headers=READONLY).status_code == 403
    assert client.get(f"/v1/documents/{document['id']}", headers=ATTORNEY).status_code == 200


def test_paralegal_may_remove_a_document_they_uploaded_in_error(client, seeded_case):
    case_id = seeded_case["case_id"]
    document = upload_text_document(client, case_id, "para.txt", "data", headers=PARALEGAL)
    assert client.delete(f"/v1/documents/{document['id']}", headers=PARALEGAL).status_code == 204


def test_removing_an_unknown_document_is_a_404(client):
    assert client.delete("/v1/documents/doc_missing", headers=ATTORNEY).status_code == 404


def test_removal_is_scoped_to_one_case(client, seeded_case):
    """Deleting a document must not touch another case's evidence."""
    case_id = seeded_case["case_id"]
    other = client.post(
        "/v1/cases",
        json={"reference": "OTHER-0001", "client_display_name": "Other Client"},
        headers=ATTORNEY,
    ).json()

    mine = upload_text_document(client, case_id, "mine.txt", "case one bytes")
    theirs = upload_text_document(client, other["id"], "theirs.txt", "case two bytes")

    assert client.delete(f"/v1/documents/{mine['id']}", headers=ATTORNEY).status_code == 204
    remaining = client.get(f"/v1/cases/{other['id']}/documents", headers=ATTORNEY).json()
    assert [doc["id"] for doc in remaining] == [theirs["id"]]


def test_the_same_file_can_be_uploaded_again_after_removal(client, seeded_case):
    """Removal must clear the duplicate constraint, or a mistake is permanent."""
    case_id = seeded_case["case_id"]
    first = upload_text_document(client, case_id, "retry.txt", "identical bytes")
    assert client.delete(f"/v1/documents/{first['id']}", headers=ATTORNEY).status_code == 204

    second = upload_text_document(client, case_id, "retry.txt", "identical bytes")
    assert second["sha256"] == first["sha256"]
    assert second["id"] != first["id"]


# ------------------------------------------------------------------- extraction


def test_extraction_records_started_and_completed_audit_events(client, seeded_case):
    case_id = seeded_case["case_id"]
    upload_text_document(
        client,
        case_id,
        "records.txt",
        "Provider: Vermont Spine and Injury\n"
        "DIAGNOSIS: Lumbar disc displacement (M51.26) documented on examination.",
    )

    response = client.post(f"/v1/cases/{case_id}/extract-async", json={}, headers=ATTORNEY)
    assert response.status_code == 202, response.text

    events = _audit_events(client, case_id)
    assert "EXTRACTION_STARTED" in events
    assert "EXTRACTION_COMPLETED" in events
