"""Claim grounding: prose is graded against verified evidence, not against a model."""

from __future__ import annotations

import pytest

from app.domain.enums import ClaimStatus, FactStatus, FactType
from app.grounding import checker, claims
from app.grounding.checker import GroundingContext, check_claim
from conftest import ATTORNEY, upload_text_document


class _StubSource:
    def __init__(self, excerpt: str, source_id: str = "fsrc_1") -> None:
        self.id = source_id
        self.excerpt = excerpt


class _StubFact:
    """A fact-shaped object; the checker only reads these attributes."""

    def __init__(self, fact_id, summary, value=None, excerpt=None,
                 status=FactStatus.VERIFIED, superseded_by_id=None):
        self.id = fact_id
        self.summary = summary
        self.value = value or {}
        self.status = status
        self.superseded_by_id = superseded_by_id
        self.sources = [_StubSource(excerpt)] if excerpt else []
        self.fact_type = FactType.DIAGNOSIS


def _grade(text: str, facts, known: str = "") -> checker.ClaimVerdict:
    context = GroundingContext(
        facts=facts, known_literals=checker.content_tokens(known)
    )
    claim = claims.segment(text)[0]
    return check_claim(claim, context, [f.id for f in facts])


# --------------------------------------------------------------------- segmentation


def test_a_paragraph_splits_into_sentences():
    body = "The vehicle was struck from behind. Our client was taken by ambulance."
    segmented = claims.segment(body)
    assert [c.text for c in segmented] == [
        "The vehicle was struck from behind.",
        "Our client was taken by ambulance.",
    ]


def test_claim_offsets_index_the_section_body():
    body = "First sentence here. Second sentence here.\nA third on its own line."
    for claim in claims.segment(body):
        assert body[claim.start_offset : claim.end_offset].strip() == claim.text


def test_abbreviations_do_not_end_a_sentence():
    body = "Dr. Reyes examined the patient. No fracture was seen."
    segmented = claims.segment(body)
    assert segmented[0].text == "Dr. Reyes examined the patient."
    assert len(segmented) == 2


def test_list_lines_are_separate_claims():
    body = "Recommended care:\n  1. Injection series\n  2. Physical therapy"
    assert len(claims.segment(body)) == 3


def test_an_empty_body_yields_no_claims():
    assert claims.segment("") == []
    assert claims.segment("   \n  ") == []


def test_a_model_decomposition_is_accepted_only_if_it_is_in_the_text():
    body = "The MRI showed a disc extrusion at L5-S1. Treatment continued for months."
    honest = claims.verify_segmentation(
        body, ["The MRI showed a disc extrusion at L5-S1.", "Treatment continued for months."]
    )
    assert honest is not None and len(honest) == 2

    invented = claims.verify_segmentation(
        body, ["The MRI showed permanent nerve damage requiring surgery."]
    )
    assert invented is None


# ------------------------------------------------------------------------- grading


def test_a_claim_restating_a_verified_fact_is_supported():
    fact = _StubFact(
        "fact_1",
        "MRI at MAX MRI Radiology showed a disc extrusion at L5-S1 measuring 9 x 10 x 5 mm",
    )
    verdict = _grade(
        "MRI at MAX MRI Radiology showed a disc extrusion at L5-S1 measuring 9 x 10 x 5 mm.",
        [fact],
    )
    assert verdict.status == ClaimStatus.SUPPORTED
    assert verdict.fact_ids == ("fact_1",)


def test_a_claim_with_no_supporting_fact_is_unsupported():
    fact = _StubFact("fact_1", "Chiropractic treatment began three days after the collision")
    verdict = _grade(
        "Our client sustained a traumatic brain injury with cognitive deficits.", [fact]
    )
    assert verdict.status == ClaimStatus.UNSUPPORTED
    assert "no verified fact" in verdict.reason or "do not cover" in verdict.reason


def test_a_claim_covering_only_part_of_the_evidence_is_partially_supported():
    fact = _StubFact("fact_1", "Lumbar disc extrusion at L5-S1 was reported on imaging")
    verdict = _grade(
        "Lumbar imaging was performed and the client also reported persistent headaches "
        "along with intermittent blurred vision.",
        [fact],
    )
    assert verdict.status in (ClaimStatus.PARTIALLY_SUPPORTED, ClaimStatus.UNSUPPORTED)


@pytest.mark.parametrize(
    "sentence,category",
    [
        ("The collision caused permanent nerve damage at L5-S1.", "permanence"),
        ("The disc extrusion at L5-S1 was caused by the collision.", "causation"),
        ("The disc extrusion at L5-S1 will require future surgery.", "prognosis"),
        ("The disc extrusion at L5-S1 left the client totally disabled.", "degree"),
    ],
)
def test_an_escalated_assertion_is_unsupported_even_when_the_words_overlap(sentence, category):
    """The evidence describes a finding; the prose upgrades it to a conclusion."""
    fact = _StubFact(
        "fact_1",
        "MRI showed a disc extrusion at L5-S1 with contact upon the right S1 nerve root",
        excerpt="L5-S1: Broad-based disc extrusion with contact upon the traversing right S1 root",
    )
    verdict = _grade(sentence, [fact])
    assert verdict.status == ClaimStatus.UNSUPPORTED
    assert category in verdict.escalations


def test_an_escalated_assertion_is_supported_when_the_evidence_says_it_too():
    fact = _StubFact(
        "fact_1",
        "The treating surgeon recorded that the L5-S1 injury is permanent",
        excerpt="Impression: permanent injury at L5-S1; no further improvement expected.",
    )
    verdict = _grade("The L5-S1 injury is permanent.", [fact])
    assert verdict.status == ClaimStatus.SUPPORTED


def test_a_claim_negating_the_evidence_is_unsupported():
    fact = _StubFact("fact_1", "Imaging demonstrated a fracture of the left wrist")
    verdict = _grade("Imaging demonstrated no fracture of the left wrist.", [fact])
    assert verdict.status == ClaimStatus.UNSUPPORTED
    assert "negates" in verdict.reason


def test_connective_text_is_not_treated_as_a_factual_claim():
    verdict = _grade("As set out below.", [_StubFact("fact_1", "Something unrelated")])
    assert verdict.status == ClaimStatus.SUPPORTED
    assert "no checkable factual content" in verdict.reason


def test_deterministic_literals_count_as_evidence():
    """A name or figure the calculator produced is evidence, not a hallucination."""
    fact = _StubFact("fact_1", "Treatment was provided following the collision")
    verdict = _grade(
        "Patrick Donahue incurred 9,980.00 in medical expenses following the collision.",
        [fact],
        known="Patrick Donahue medical expenses incurred 9,980.00",
    )
    assert verdict.status == ClaimStatus.SUPPORTED


def test_a_verdict_records_the_span_it_graded():
    fact = _StubFact("fact_1", "Chiropractic treatment began three days after the collision")
    verdict = _grade("Chiropractic treatment began three days after the collision.", [fact])
    payload = verdict.to_dict()
    assert payload["start_offset"] == 0
    assert payload["end_offset"] > 0
    assert payload["status"] == "SUPPORTED"


# ------------------------------------------------------------------- through the API


def _draft_with_body(client, case_id, body: str) -> dict:
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    client.patch(
        f"/v1/demands/{demand['id']}/sections/liability",
        json={"body": body},
        headers=ATTORNEY,
    )
    return demand


def test_the_demand_carries_a_claim_report_after_validation(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    client.post(f"/v1/demands/{demand['id']}/validate", headers=ATTORNEY)

    detail = client.get(f"/v1/demands/{demand['id']}", headers=ATTORNEY).json()
    report = detail["claim_report"]
    assert report["claims_checked"] > 0
    assert report["unsupported"] == 0
    assert "liability" in report["sections"]


def test_a_clean_draft_raises_no_claim_issues(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    issues = client.post(f"/v1/demands/{demand['id']}/validate", headers=ATTORNEY).json()
    assert not [i for i in issues if i["code"].startswith("CLAIM_")]


def test_a_section_relying_on_an_unverified_fact_blocks_approval(
    client, seeded_case_with_facts, db
):
    """CLAIM_002 — a PROPOSED fact cannot hold up generated prose."""
    from app.domain.models import Demand, DemandSection

    case_id = seeded_case_with_facts["case_id"]
    document_id = seeded_case_with_facts["document_id"]

    proposed = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "diagnosis",
            "value": {},
            "summary": "A cervical disc herniation was identified",
            "sources": [{"document_id": document_id, "page_number": 1, "excerpt": "lumbar pain"}],
        },
        headers=ATTORNEY,
    ).json()
    assert proposed["status"] == "PROPOSED"

    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    # Force the section to cite the unverified fact, the way a bug or a
    # tampered payload would.
    stored = db.get(Demand, demand["id"])
    section = next(s for s in stored.sections if s.key == "liability")
    section.used_fact_ids = list(section.used_fact_ids) + [proposed["id"]]
    db.commit()

    issues = client.post(f"/v1/demands/{demand['id']}/validate", headers=ATTORNEY).json()
    codes = {i["code"] for i in issues if i["severity"] == "BLOCKING"}
    assert "CLAIM_002" in codes

    response = client.post(
        f"/v1/demands/{demand['id']}/approve",
        json={"acknowledgement": seeded_case_with_facts["reference"]},
        headers=ATTORNEY,
    )
    assert response.status_code == 409
