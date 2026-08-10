"""Document ingestion: screening, immutability, provenance."""

from __future__ import annotations

from conftest import ATTORNEY, READONLY, upload_text_document

from app.ingestion.scanner import EICAR


def test_malware_signature_is_refused_and_nothing_is_stored(client, seeded_case):
    case_id = seeded_case["case_id"]
    response = client.post(
        f"/v1/cases/{case_id}/documents",
        files={"file": ("payload.txt", EICAR, "text/plain")},
        headers=ATTORNEY,
    )
    assert response.status_code == 400
    assert "malware" in response.json()["detail"].lower()
    assert client.get(f"/v1/cases/{case_id}/documents", headers=ATTORNEY).json() == []


def test_unsupported_content_type_is_refused(client, seeded_case):
    response = client.post(
        f"/v1/cases/{seeded_case['case_id']}/documents",
        files={"file": ("nefarious.exe", b"MZ\x90\x00binary", "application/x-msdownload")},
        headers=ATTORNEY,
    )
    assert response.status_code == 400
    assert "unsupported content type" in response.json()["detail"]


def test_ingested_document_records_hash_pages_and_uploader(client, seeded_case):
    case_id = seeded_case["case_id"]
    body = "Provider: MAX MRI Radiology\nMRI LUMBAR SPINE\fPage two: impression."
    document = upload_text_document(client, case_id, "mri-report.txt", body)

    assert len(document["sha256"]) == 64
    assert document["page_count"] == 2
    assert document["uploaded_by"] == "attorney_45"
    assert document["document_type"] == "MRI_REPORT"
    assert document["provider_name"] == "MAX MRI Radiology"

    detail = client.get(f"/v1/documents/{document['id']}", headers=ATTORNEY).json()
    assert detail["pages"][1]["page_number"] == 2
    assert "impression" in detail["pages"][1]["text"]


def test_reuploading_identical_bytes_is_a_conflict_not_a_second_copy(client, seeded_case):
    case_id = seeded_case["case_id"]
    upload_text_document(client, case_id, "record.txt", "same bytes")

    response = client.post(
        f"/v1/cases/{case_id}/documents",
        files={"file": ("record-copy.txt", b"same bytes", "text/plain")},
        headers=ATTORNEY,
    )
    assert response.status_code == 409
    assert len(client.get(f"/v1/cases/{case_id}/documents", headers=ATTORNEY).json()) == 1


def test_stored_original_is_byte_identical_on_download(client, seeded_case):
    case_id = seeded_case["case_id"]
    body = "Original bytes that must never change."
    document = upload_text_document(client, case_id, "original.txt", body)

    response = client.get(f"/v1/documents/{document['id']}/content", headers=READONLY)
    assert response.status_code == 200
    assert response.content == body.encode("utf-8")
    assert response.headers["X-Content-SHA256"] == document["sha256"]


def test_readonly_user_cannot_upload(client, seeded_case):
    response = client.post(
        f"/v1/cases/{seeded_case['case_id']}/documents",
        files={"file": ("x.txt", b"data", "text/plain")},
        headers=READONLY,
    )
    assert response.status_code == 403
