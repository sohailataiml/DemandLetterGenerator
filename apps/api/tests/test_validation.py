"""Validation rules — the checks that stand between a draft and release."""

from __future__ import annotations

from datetime import timedelta

from conftest import ATTORNEY, EXPIRES_AT, PARALEGAL


def _generate(client, case_id):
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    response = client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    assert response.status_code == 200, response.text
    return response.json()


def _codes(client, demand_id, severity=None):
    issues = client.post(f"/v1/demands/{demand_id}/validate", headers=ATTORNEY).json()
    return {i["code"] for i in issues if severity is None or i["severity"] == severity}


def test_expiration_before_letter_date_is_blocking(client, seeded_case_with_facts):
    """The inconsistency visible in the supplied letter: a demand that expires
    before the date it was written."""
    case_id = seeded_case_with_facts["case_id"]
    demand = _generate(client, case_id)

    # Move the letter date past the expiration.
    stale_expiry = (EXPIRES_AT - timedelta(days=90)).isoformat()
    client.put(
        f"/v1/cases/{case_id}/settlement-terms",
        json={"expires_at": stale_expiry, "demand_is_policy_limits": True},
        headers=ATTORNEY,
    )
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    assert "DATE_001" in _codes(client, demand["id"], "BLOCKING")


def test_clean_case_produces_no_blocking_issues(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    assert _codes(client, demand["id"], "BLOCKING") == set()


def test_edited_total_that_disagrees_with_the_calculator_is_blocking(
    client, seeded_case_with_facts
):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    body = next(s for s in demand["sections"] if s["key"] == "medical_expense_summary")["body"]
    tampered = body.replace("$9,980.00", "$19,980.00")
    assert tampered != body, "fixture totals changed; update this test"

    client.patch(
        f"/v1/demands/{demand['id']}/sections/medical_expense_summary",
        json={"body": tampered},
        headers=ATTORNEY,
    )
    assert "MONEY_001" in _codes(client, demand["id"], "BLOCKING")


def test_dropping_the_pending_bill_disclosure_is_blocking(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    section = next(s for s in demand["sections"] if s["key"] == "medical_expense_summary")
    trimmed = section["body"].split("\n\nThe following charges")[0]

    client.patch(
        f"/v1/demands/{demand['id']}/sections/medical_expense_summary",
        json={"body": trimmed},
        headers=ATTORNEY,
    )
    assert "MONEY_002" in _codes(client, demand["id"], "BLOCKING")


def test_claim_number_mismatch_anywhere_is_blocking(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    client.patch(
        f"/v1/demands/{demand['id']}/sections/introduction",
        json={"body": "Reference: Claim Number 017204699 for our client."},
        headers=ATTORNEY,
    )
    assert "CLAIM_001" in _codes(client, demand["id"], "BLOCKING")


def test_expiration_stated_two_different_ways_is_blocking(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    client.patch(
        f"/v1/demands/{demand['id']}/sections/introduction",
        json={"body": "This offer expires on January 2, 2027 unless accepted."},
        headers=ATTORNEY,
    )
    assert "DOCUMENT_001" in _codes(client, demand["id"], "BLOCKING")


def test_unsupported_amount_in_narrative_prose_is_blocking(client, seeded_case_with_facts):
    """A dollar figure invented in a narrative section has no fact behind it."""
    demand = _generate(client, seeded_case_with_facts["case_id"])
    section = next(s for s in demand["sections"] if s["key"] == "medical_summary")

    client.patch(
        f"/v1/demands/{demand['id']}/sections/medical_summary",
        json={"body": section["body"] + " Treatment charges totalled $41,250.00."},
        headers=ATTORNEY,
    )
    issues = client.post(f"/v1/demands/{demand['id']}/validate", headers=ATTORNEY).json()
    narrative = [i for i in issues if i["code"] == "NARRATIVE_001"]
    assert narrative, issues
    assert any("41,250.00" in i["message"] for i in narrative)


def test_unsupported_date_in_narrative_prose_is_blocking(client, seeded_case_with_facts):
    demand = _generate(client, seeded_case_with_facts["case_id"])
    section = next(s for s in demand["sections"] if s["key"] == "liability")

    client.patch(
        f"/v1/demands/{demand['id']}/sections/liability",
        json={"body": section["body"] + " A second collision occurred on March 3, 2019."},
        headers=ATTORNEY,
    )
    issues = client.post(f"/v1/demands/{demand['id']}/validate", headers=ATTORNEY).json()
    assert any(i["code"] == "NARRATIVE_001" and "2019-03-03" in i["message"] for i in issues)


def test_case_without_facts_cannot_draft_its_narrative_sections(client, seeded_case):
    demand = _generate(client, seeded_case["case_id"])
    assert "NARRATIVE_002" in _codes(client, demand["id"], "BLOCKING")

    body = next(s for s in demand["sections"] if s["key"] == "medical_summary")["body"]
    assert "Drafting could not be completed" in body
    assert "No verified facts" in body


def test_accident_and_claim_dates_must_agree(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = _generate(client, case_id)
    accident = client.get(f"/v1/cases/{case_id}/claim", headers=ATTORNEY).json()

    client.put(
        f"/v1/cases/{case_id}/accident",
        json={"occurred_on": "2001-01-01", "location": "elsewhere"},
        headers=ATTORNEY,
    )
    codes = _codes(client, demand["id"], "BLOCKING")
    assert "DATE_004" in codes
    assert accident["claim_number"] == "017204635"


def test_insured_and_driver_differences_must_be_documented(client, seeded_case_with_facts):
    """Different insured and driver is legitimate — leaving it unexplained is not."""
    case_id = seeded_case_with_facts["case_id"]
    demand = _generate(client, case_id)
    assert "PARTY_001" not in _codes(client, demand["id"])

    driver = next(
        p
        for p in client.get(f"/v1/cases/{case_id}/parties", headers=ATTORNEY).json()
        if any(r["role"] == "driver" for r in p["role_assignments"])
    )
    insured = next(
        p
        for p in client.get(f"/v1/cases/{case_id}/parties", headers=ATTORNEY).json()
        if any(r["role"] == "insured" for r in p["role_assignments"])
    )
    for party in (driver, insured):
        role = "driver" if party is driver else "insured"
        client.patch(
            f"/v1/parties/{party['id']}",
            json={"roles": [{"role": role}]},
            headers=PARALEGAL,
        )

    assert "PARTY_001" in _codes(client, demand["id"], "WARNING")
