"""INVARIANT-001 through 005 and 007, stated as tests.

Each one is written against the guarantee rather than the implementation, so a
refactor that keeps the promise keeps these passing, and one that quietly
breaks it does not.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from conftest import ATTORNEY, PARALEGAL, READONLY, upload_text_document

pytestmark = pytest.mark.invariant


def _fact(client, case_id, document_id, summary="A fact worth checking", fact_type="diagnosis"):
    return client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": fact_type,
            "value": {"note": summary},
            "summary": summary,
            "sources": [{"document_id": document_id, "page_number": 1, "excerpt": "lumbar pain"}],
        },
        headers=ATTORNEY,
    ).json()


# ------------------------------------------- INVARIANT-001: unverified never authoritative


def test_a_new_fact_starts_proposed_whoever_creates_it(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    document_id = seeded_case_with_facts["document_id"]
    assert _fact(client, case_id, document_id)["status"] == "PROPOSED"


def test_generation_context_holds_only_verified_facts(client, seeded_case_with_facts, db):
    from app.domain.models import Demand
    from app.generation.context import build_context

    case_id = seeded_case_with_facts["case_id"]
    _fact(client, case_id, seeded_case_with_facts["document_id"], "An unverified assertion")

    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    db.expire_all()
    context = build_context(db, db.get(Demand, demand["id"]))
    assert context.facts
    assert all(str(fact.status) == "VERIFIED" for fact in context.facts)


def test_a_fact_cannot_be_verified_without_a_citation(client, seeded_case):
    case_id = seeded_case["case_id"]
    fact = client.post(
        f"/v1/cases/{case_id}/facts",
        json={"fact_type": "diagnosis", "value": {}, "summary": "No source at all", "sources": []},
        headers=ATTORNEY,
    ).json()
    response = client.post(f"/v1/facts/{fact['id']}/verify", headers=ATTORNEY)
    assert response.status_code == 409
    assert "citation" in response.json()["detail"]


def test_a_citation_must_point_at_a_document_in_this_case(client, seeded_case_with_facts):
    other = client.post(
        "/v1/cases",
        json={"reference": "OTHER-9", "client_display_name": "Somebody Else"},
        headers=ATTORNEY,
    ).json()
    foreign = upload_text_document(client, other["id"], "elsewhere.txt", "Unrelated content.")

    response = client.post(
        f"/v1/cases/{seeded_case_with_facts['case_id']}/facts",
        json={
            "fact_type": "diagnosis",
            "value": {},
            "summary": "Borrowed evidence",
            "sources": [{"document_id": foreign["id"], "page_number": 1}],
        },
        headers=ATTORNEY,
    )
    assert response.status_code == 400


def test_a_readonly_user_cannot_verify_a_fact(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    fact = _fact(client, case_id, seeded_case_with_facts["document_id"])
    assert client.post(f"/v1/facts/{fact['id']}/verify", headers=READONLY).status_code == 403


# ------------------------------------------------- INVARIANT-002: verified is immutable


def test_there_is_no_endpoint_that_edits_a_fact(client):
    """The absence of a write path is the guarantee; check it stays absent."""
    paths = client.get("/openapi.json").json()["paths"]
    fact_paths = {
        (path, method.upper())
        for path, methods in paths.items()
        for method in methods
        if "/facts/{fact_id}" in path
    }
    mutating = {(p, m) for p, m in fact_paths if m in ("PUT", "PATCH", "DELETE")}
    assert not mutating, f"a fact mutation endpoint exists: {mutating}"


def test_a_verified_fact_cannot_be_verified_or_rejected_again(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    verified = next(
        f
        for f in client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
        if f["status"] == "VERIFIED"
    )
    assert client.post(f"/v1/facts/{verified['id']}/verify", headers=ATTORNEY).status_code == 409
    assert (
        client.post(
            f"/v1/facts/{verified['id']}/reject", json={"reason": "changed my mind"},
            headers=ATTORNEY,
        ).status_code
        == 409
    )


def test_correcting_a_verified_fact_creates_a_revision_and_leaves_the_original(
    client, seeded_case_with_facts
):
    case_id = seeded_case_with_facts["case_id"]
    document_id = seeded_case_with_facts["document_id"]
    original = next(
        f
        for f in client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
        if f["status"] == "VERIFIED"
    )

    replacement = client.post(
        f"/v1/facts/{original['id']}/supersede",
        json={
            "fact_type": original["fact_type"],
            "value": {"corrected": True},
            "summary": "A corrected statement of the same fact",
            "sources": [{"document_id": document_id, "page_number": 1, "excerpt": "lumbar pain"}],
            "reason": "The original overstated the finding.",
        },
        headers=ATTORNEY,
    ).json()

    assert replacement["status"] == "PROPOSED"
    assert replacement["revision"] == original["revision"] + 1
    assert replacement["supersedes_id"] == original["id"]

    # The original is still authoritative until the correction is verified.
    still = client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
    assert next(f for f in still if f["id"] == original["id"])["status"] == "VERIFIED"

    client.post(f"/v1/facts/{replacement['id']}/verify", headers=ATTORNEY)
    after = client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
    assert next(f for f in after if f["id"] == original["id"])["status"] == "SUPERSEDED"


def test_a_fact_cannot_be_superseded_twice(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    document_id = seeded_case_with_facts["document_id"]
    original = next(
        f
        for f in client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
        if f["status"] == "VERIFIED"
    )
    payload = {
        "fact_type": original["fact_type"],
        "value": {},
        "summary": "A correction",
        "sources": [{"document_id": document_id, "page_number": 1}],
        "reason": "correcting",
    }
    first = client.post(
        f"/v1/facts/{original['id']}/supersede", json=payload, headers=ATTORNEY
    )
    assert first.status_code == 201
    client.post(f"/v1/facts/{first.json()['id']}/verify", headers=ATTORNEY)

    second = client.post(
        f"/v1/facts/{original['id']}/supersede", json=payload, headers=ATTORNEY
    )
    assert second.status_code == 409


# ----------------------------------------------- INVARIANT-003: no arithmetic by an LLM


def test_totals_come_from_the_calculator_not_from_prose(client, seeded_case_with_facts):
    from app.damages.calculator import summarize_case

    case_id = seeded_case_with_facts["case_id"]
    reported = client.get(f"/v1/cases/{case_id}/damages", headers=ATTORNEY).json()
    assert Decimal(reported["current_medical_expenses"]) == Decimal("9980.00")


def test_money_is_decimal_all_the_way_to_the_wire(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    damages = client.get(f"/v1/cases/{case_id}/damages", headers=ATTORNEY).json()
    for key in (
        "current_medical_expenses",
        "future_medical_low",
        "future_medical_high",
        "known_claimed_damages_low",
        "known_claimed_damages_high",
    ):
        assert isinstance(damages[key], str), f"{key} crossed the wire as a float"
        Decimal(damages[key])  # raises if it is not exact


def test_the_drafting_prompt_forbids_arithmetic():
    from app.generation.ai.prompts import SYSTEM_PROMPT as DRAFT_PROMPT
    from app.extraction.prompts import SYSTEM_PROMPT as EXTRACT_PROMPT

    assert "arithmetic" in EXTRACT_PROMPT.lower()
    assert "do not" in EXTRACT_PROMPT.lower()
    assert "comput" in DRAFT_PROMPT.lower() or "arithmetic" in DRAFT_PROMPT.lower()


# --------------------------------------------- INVARIANT-004: pending is not zero


def test_a_pending_bill_is_excluded_not_counted_as_zero(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    damages = client.get(f"/v1/cases/{case_id}/damages", headers=ATTORNEY).json()

    assert damages["pending_bills"], "the seeded case has one pending bill"
    pending_names = {bill["provider_name"] for bill in damages["pending_bills"]}
    assert "Harbor Pain Management" in pending_names

    # It contributes nothing to the total, and it is not stored as 0.00 either.
    bills = client.get(f"/v1/cases/{case_id}/bills", headers=ATTORNEY).json()
    pending = next(b for b in bills if b["provider_name"] == "Harbor Pain Management")
    assert pending["amount"] is None
    assert pending["status"] == "PENDING"


def test_the_letter_says_the_total_is_incomplete(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    detail = client.get(f"/v1/demands/{demand['id']}", headers=ATTORNEY).json()

    summary = next(s for s in detail["sections"] if s["key"] == "medical_expense_summary")
    assert "Harbor Pain Management" in summary["body"]
    assert "amount pending" in summary["body"]
    assert "NOT included" in summary["body"] or "not included" in summary["body"]
    assert "$0.00" not in summary["body"]


# ------------------------------- INVARIANT-005: generated prose traces to evidence


def test_every_machine_drafted_section_cites_the_facts_it_used(
    client, seeded_case_with_facts
):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    detail = client.get(f"/v1/demands/{demand['id']}", headers=ATTORNEY).json()

    verified = {
        f["id"]
        for f in client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
        if f["status"] == "VERIFIED"
    }
    ai_sections = [s for s in detail["sections"] if s["source"] == "ai"]
    assert ai_sections
    for section in ai_sections:
        assert section["used_fact_ids"], f"{section['key']} cites nothing"
        assert set(section["used_fact_ids"]) <= verified


def test_every_cited_fact_traces_to_a_document_span(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    facts = client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
    for fact in facts:
        if fact["status"] != "VERIFIED":
            continue
        assert fact["sources"]
        for source in fact["sources"]:
            assert source["document_id"]
            assert source["page_number"] is not None


def test_a_model_cannot_cite_a_fact_it_was_not_given(client, seeded_case_with_facts, db):
    """The provider's claimed fact ids are filtered to what it actually saw."""
    from app.generation.ai.narratives import generate_section
    from app.generation.ai.prompts import SECTION_SPECS
    from app.generation.context import build_context
    from app.domain.models import Demand
    from app.generation.ai.provider import NarrativeResult

    class _Liar:
        name = "liar"
        model = None

        def draft(self, request):
            return NarrativeResult(
                section_key=request.spec.key,
                text="A confident sentence.",
                used_fact_ids=["fact_that_was_never_offered"],
                insufficient_evidence=False,
                provider=self.name,
            )

    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    db.expire_all()
    context = build_context(db, db.get(Demand, demand["id"]))

    result = generate_section(context, SECTION_SPECS["liability"], _Liar())
    assert result.used_fact_ids == []


# ------------------------------------ INVARIANT-007: approval is a server decision


def test_approval_is_refused_while_a_blocking_issue_stands(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    client.patch(
        f"/v1/demands/{demand['id']}/sections/liability",
        json={"body": "Damages of $4,321,000.00 are demanded."},
        headers=ATTORNEY,
    )
    response = client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case_with_facts["reference"]},
        headers=ATTORNEY,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["blocking_issues"]


def test_approval_revalidates_rather_than_trusting_the_stored_issues(
    client, seeded_case_with_facts, db
):
    """Clearing the saved issue list must not clear the gate."""
    from app.domain.models import Demand, ValidationIssueRecord

    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    client.patch(
        f"/v1/demands/{demand['id']}/sections/liability",
        json={"body": "Damages of $4,321,000.00 are demanded."},
        headers=ATTORNEY,
    )
    client.post(f"/v1/demands/{demand['id']}/validate", headers=ATTORNEY)

    db.expire_all()
    for issue in db.query(ValidationIssueRecord).filter(
        ValidationIssueRecord.demand_id == demand["id"]
    ):
        db.delete(issue)
    db.commit()

    response = client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case_with_facts["reference"]},
        headers=ATTORNEY,
    )
    assert response.status_code == 409


def test_only_an_attorney_may_approve(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    for headers in (PARALEGAL, READONLY):
        response = client.post(
            f"/v1/demands/{demand['id']}/approve",
            json={"acknowledgement": seeded_case_with_facts["reference"]},
            headers=headers,
        )
        assert response.status_code == 403


def test_approval_is_recorded_with_the_actor_and_the_hash(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case_with_facts["reference"]},
        headers=ATTORNEY,
    )

    events = client.get(f"/v1/demands/{demand['id']}/audit", headers=ATTORNEY).json()
    approved = next(e for e in events if e["event"] == "DEMAND_APPROVED")
    assert approved["actor"] == "attorney_45"
    assert approved["payload"]["docx_sha256"]
    assert approved["payload"]["approved_by"] == "attorney_45"
