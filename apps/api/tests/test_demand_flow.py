"""End-to-end: draft → validate → approve → immutable artifact, with the audit
trail that has to be able to reconstruct it."""

from __future__ import annotations

from conftest import ATTORNEY, PARALEGAL, READONLY


def _generate(client, case_id):
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    return client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY).json()


def test_generated_letter_contains_every_expected_section(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    keys = [s["key"] for s in demand["sections"]]

    assert keys == [
        "header",
        "claim_metadata",
        "demand_title",
        "introduction",
        "liability",
        "photographs",
        "damages",
        "medical_summary",
        "imaging_summary",
        "future_medical",
        "medical_expense_summary",
        "pain_and_suffering",
        "demand_for_settlement",
        "conditions",
        "signature",
    ]
    assert demand["template_version"] == "policy_limits_v1"
    assert demand["provider_name"] == "stub"


def test_metadata_and_totals_come_from_structured_data(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    sections = {s["key"]: s["body"] for s in demand["sections"]}

    metadata = dict(
        (part.strip() for part in line.split(":", 1))
        for line in sections["claim_metadata"].splitlines()
    )
    assert metadata["Claim Number"] == "017204635"
    assert metadata["Our Client"] == "Patrick Donahue"
    # The named insured and the driver are different people and stay that way.
    assert metadata["Your Insured"] == "Marisol Reyes"
    assert metadata["Driver"] == "Andre Whitfield"

    # 6480.00 + 3500.00; the pending Harbor bill is excluded and disclosed.
    assert "Total known medical expenses to date: $9,980.00" in sections["medical_expense_summary"]
    assert "Harbor Pain Management" in sections["medical_expense_summary"]
    assert "amount pending" in sections["medical_expense_summary"]
    assert "$8,400.00 to $11,200.00" in sections["future_medical"]


def test_narrative_sections_carry_the_fact_ids_they_used(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    imaging = next(s for s in demand["sections"] if s["key"] == "imaging_summary")

    assert imaging["source"] == "ai"
    assert imaging["used_fact_ids"], "an AI section must record its provenance"

    facts = {
        f["id"]: f
        for f in client.get(
            f"/v1/cases/{seeded_case_with_facts['case_id']}/facts", headers=ATTORNEY
        ).json()
    }
    for fact_id in imaging["used_fact_ids"]:
        assert facts[fact_id]["status"] == "VERIFIED"
        assert facts[fact_id]["sources"], "every cited fact traces to a source document"


def test_attorney_can_approve_a_clean_draft_and_it_locks(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = _generate(client, case_id)

    response = client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case_with_facts["reference"]},
        headers=ATTORNEY,
    )
    assert response.status_code == 200, response.text
    approved = response.json()

    assert approved["status"] == "approved"
    assert approved["locked"] is True
    assert approved["approved_by"] == "attorney_45"
    assert len(approved["docx_sha256"]) == 64

    # A locked demand cannot be regenerated or edited.
    assert (
        client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY).status_code
        == 409
    )
    assert (
        client.patch(
            f"/v1/demands/{demand['id']}/sections/introduction",
            json={"body": "rewritten after approval"},
            headers=ATTORNEY,
        ).status_code
        == 409
    )


def test_approval_is_refused_while_a_blocking_issue_stands(client, seeded_case):
    """No verified facts → narrative sections cannot be drafted → no approval."""
    case_id = seeded_case["case_id"]
    demand = _generate(client, case_id)

    response = client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case["reference"]},
        headers=ATTORNEY,
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "blocking validation issue" in detail["message"]
    assert "NARRATIVE_002" in {i["code"] for i in detail["blocking_issues"]}

    assert client.get(f"/v1/demands/{demand['id']}", headers=ATTORNEY).json()["locked"] is False


def test_approval_requires_the_reviewer_to_confirm_the_case_reference(
    client, seeded_case_with_facts
):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    response = client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": "whatever"},
        headers=ATTORNEY,
    )
    assert response.status_code == 409
    assert "case reference" in response.json()["detail"]["message"]


def test_paralegal_cannot_approve(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    response = client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case_with_facts["reference"]},
        headers=PARALEGAL,
    )
    assert response.status_code == 403


def test_docx_downloads_and_is_a_real_word_file(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    response = client.get(f"/v1/demands/{demand['id']}/docx", headers=READONLY)

    assert response.status_code == 200
    assert response.content[:2] == b"PK"  # DOCX is a zip container
    assert len(response.headers["X-Content-SHA256"]) == 64


def test_human_edits_survive_regeneration_of_other_sections(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    client.patch(
        f"/v1/demands/{demand['id']}/sections/liability",
        json={"body": "Counsel's own liability paragraph."},
        headers=ATTORNEY,
    )

    regenerated = client.post(
        f"/v1/demands/{demand['id']}/generate",
        json={"regenerate_sections": ["medical_summary"]},
        headers=ATTORNEY,
    ).json()

    liability = next(s for s in regenerated["sections"] if s["key"] == "liability")
    assert liability["body"] == "Counsel's own liability paragraph."
    assert liability["source"] == "human"


def test_audit_trail_reconstructs_how_the_document_was_produced(
    client, seeded_case_with_facts
):
    case_id = seeded_case_with_facts["case_id"]
    demand = _generate(client, case_id)
    client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case_with_facts["reference"]},
        headers=ATTORNEY,
    )

    events = client.get(f"/v1/demands/{demand['id']}/audit", headers=ATTORNEY).json()
    by_type = {e["event"]: e for e in events}

    assert {"DEMAND_CREATED", "DEMAND_GENERATED", "DEMAND_VALIDATED", "DEMAND_APPROVED"} <= set(
        by_type
    )

    generated = by_type["DEMAND_GENERATED"]["payload"]
    assert generated["template_version"] == "policy_limits_v1"
    assert generated["prompt_version"] == "narrative_v1"
    assert generated["fact_ids_supplied"], "the facts given to the model are recorded"

    approved = by_type["DEMAND_APPROVED"]["payload"]
    assert approved["approved_by"] == "attorney_45"
    assert len(approved["docx_sha256"]) == 64

    case_events = client.get(f"/v1/cases/{case_id}/audit", headers=ATTORNEY).json()
    assert {"CASE_CREATED", "FACT_PROPOSED", "FACT_VERIFIED", "DOCUMENT_INGESTED"} <= {
        e["event"] for e in case_events
    }


def test_second_demand_version_is_numbered_independently(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    first = _generate(client, case_id)
    second = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()

    assert first["version"] == 1
    assert second["version"] == 2
