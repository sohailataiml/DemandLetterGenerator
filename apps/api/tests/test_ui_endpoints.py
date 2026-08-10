"""Read-only endpoints and CORS support added for the review UI.

These add no behavior to the domain — they project existing records into the
shapes the case list and workspace need.
"""

from __future__ import annotations

from conftest import ATTORNEY, READONLY, upload_text_document


def test_case_summaries_carry_claim_and_demand_state(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    summaries = client.get("/v1/case-summaries", headers=ATTORNEY).json()
    summary = next(item for item in summaries if item["id"] == case_id)

    assert summary["client_display_name"] == "Patrick Donahue"
    assert summary["claim_number"] == "017204635"
    assert summary["carrier_name"] == "Meridian Casualty Insurance"
    assert summary["demand"]["version"] == 1
    assert summary["demand"]["status"] == "draft"
    assert summary["demand"]["locked"] is False


def test_case_summary_reports_no_validation_until_it_has_run(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    before = client.get("/v1/case-summaries", headers=ATTORNEY).json()
    assert next(item for item in before if item["id"] == case_id)["validation"] is None

    client.post(f"/v1/demands/{demand['id']}/validate", headers=ATTORNEY)

    after = next(
        item
        for item in client.get("/v1/case-summaries", headers=ATTORNEY).json()
        if item["id"] == case_id
    )
    assert after["validation"]["blocking"] == 0
    assert after["validation"]["last_validated_at"] is not None


def test_case_summary_counts_blocking_issues(client, seeded_case):
    """A case with no verified facts cannot draft its narrative sections."""
    case_id = seeded_case["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    client.post(f"/v1/demands/{demand['id']}/validate", headers=ATTORNEY)

    summary = next(
        item
        for item in client.get("/v1/case-summaries", headers=ATTORNEY).json()
        if item["id"] == case_id
    )
    assert summary["validation"]["blocking"] > 0


def test_case_without_a_demand_summarizes_cleanly(client):
    response = client.post(
        "/v1/cases",
        json={"reference": "EMPTY-1", "client_display_name": "No Demand Yet"},
        headers=ATTORNEY,
    )
    case_id = response.json()["id"]

    summary = next(
        item
        for item in client.get("/v1/case-summaries", headers=ATTORNEY).json()
        if item["id"] == case_id
    )
    assert summary["demand"] is None
    assert summary["validation"] is None
    assert summary["claim_number"] is None


def test_accident_and_settlement_terms_are_readable(client, seeded_case):
    case_id = seeded_case["case_id"]

    accident = client.get(f"/v1/cases/{case_id}/accident", headers=READONLY)
    assert accident.status_code == 200
    assert accident.json()["impact_type"] == "rear-end"

    terms = client.get(f"/v1/cases/{case_id}/settlement-terms", headers=READONLY)
    assert terms.status_code == 200
    assert terms.json()["demand_is_policy_limits"] is True


def test_missing_optional_records_return_404_not_a_fabricated_blank(client):
    case_id = client.post(
        "/v1/cases",
        json={"reference": "BARE-1", "client_display_name": "Bare Case"},
        headers=ATTORNEY,
    ).json()["id"]

    assert client.get(f"/v1/cases/{case_id}/accident", headers=ATTORNEY).status_code == 404
    assert client.get(f"/v1/cases/{case_id}/settlement-terms", headers=ATTORNEY).status_code == 404
    assert client.get(f"/v1/cases/{case_id}/vehicles", headers=ATTORNEY).json() == []


def test_facts_expose_their_creation_time(client, seeded_case):
    case_id = seeded_case["case_id"]
    document = upload_text_document(client, case_id, "note.txt", "Chart note.")

    fact = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "diagnosis",
            "value": {},
            "summary": "Cervical strain",
            "sources": [{"document_id": document["id"], "page_number": 1}],
        },
        headers=ATTORNEY,
    ).json()

    assert fact["created_at"]


def test_readonly_role_can_read_summaries_but_not_write(client, seeded_case):
    assert client.get("/v1/case-summaries", headers=READONLY).status_code == 200
    assert (
        client.post(
            f"/v1/cases/{seeded_case['case_id']}/demands", json={}, headers=READONLY
        ).status_code
        == 403
    )


def test_browser_origin_is_allowed_by_cors(client, seeded_case):
    response = client.get(
        "/v1/case-summaries",
        headers={**ATTORNEY, "Origin": "http://localhost:3000"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    # Download headers must be readable by the browser for DOCX/PDF handling.
    assert "X-Content-SHA256" in response.headers.get("access-control-expose-headers", "")


def test_unknown_origin_is_not_granted_access(client, seeded_case):
    response = client.get(
        "/v1/case-summaries",
        headers={**ATTORNEY, "Origin": "http://evil.example"},
    )
    assert "access-control-allow-origin" not in response.headers
