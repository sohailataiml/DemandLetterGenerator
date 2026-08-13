"""AI revisions are proposals. Only an attorney's acceptance changes a document."""

from __future__ import annotations

import pytest

from app.revisions import constraints
from app.revisions.constraints import RevisionConstraint
from app.revisions.provider import RevisionRequest, RhetoricalStubProvider
from conftest import ATTORNEY, PARALEGAL, READONLY

HEDGED = (
    "It appears that the insured driver may have failed to stop. "
    "Apparently our client was somewhat injured in the collision."
)


@pytest.fixture
def drafted_demand(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    return {**seeded_case_with_facts, "demand_id": demand["id"]}


def _propose(client, demand_id, instruction="Make the liability section more forceful.",
             section="liability", headers=ATTORNEY, **constraint_overrides):
    return client.post(
        f"/v1/demands/{demand_id}/revisions",
        json={
            "section_key": section,
            "instruction": instruction,
            "constraints": {
                "preserve_facts": True,
                "preserve_amounts": True,
                "preserve_dates": True,
                "allow_new_facts": False,
                **constraint_overrides,
            },
        },
        headers=headers,
    )


# ------------------------------------------------------------------- constraints


def test_a_revision_that_changes_an_amount_is_rejected():
    violations = constraints.check(
        "Medical expenses total $9,980.00 to date.",
        "Medical expenses total $19,980.00 to date.",
        RevisionConstraint(),
    )
    assert [v.code for v in violations] == [constraints.REVISION_AMOUNT_CHANGED]


def test_a_revision_that_adds_an_amount_is_rejected():
    violations = constraints.check(
        "The client was treated for months.",
        "The client was treated for months and lost $12,000.00 in wages.",
        RevisionConstraint(),
    )
    assert constraints.REVISION_AMOUNT_CHANGED in [v.code for v in violations]


def test_a_revision_that_changes_a_date_is_rejected():
    violations = constraints.check(
        "The collision occurred on March 4, 2024.",
        "The collision occurred on March 5, 2024.",
        RevisionConstraint(),
    )
    assert constraints.REVISION_DATE_CHANGED in [v.code for v in violations]


def test_a_revision_that_names_a_new_entity_is_rejected():
    violations = constraints.check(
        "The insured driver failed to stop.",
        "The insured driver failed to stop, as Officer Daniel Reyes confirmed.",
        RevisionConstraint(),
    )
    assert constraints.REVISION_NEW_ENTITY in [v.code for v in violations]


def test_a_revision_that_deletes_the_section_is_rejected():
    violations = constraints.check("Some real content here.", "   ", RevisionConstraint())
    assert [v.code for v in violations] == [constraints.REVISION_EMPTY]


def test_a_runaway_rewrite_is_rejected():
    violations = constraints.check(
        "Short section.", "Padding sentence. " * 40, RevisionConstraint()
    )
    assert constraints.REVISION_RUNAWAY_LENGTH in [v.code for v in violations]


def test_required_literals_must_survive():
    violations = constraints.check(
        "This demand expires on the stated deadline.",
        "This demand remains open.",
        RevisionConstraint(preserve_literals=("expires on",)),
    )
    assert constraints.REVISION_LITERAL_DROPPED in [v.code for v in violations]


def test_a_purely_rhetorical_rewrite_passes():
    violations = constraints.check(
        "It appears that the driver may have failed to stop.",
        "The driver failed to stop.",
        RevisionConstraint(),
    )
    assert violations == []


def test_a_patch_written_against_stale_text_is_refused():
    stale = constraints.check_freshness("the text as it is now", constraints.text_hash("older"))
    assert stale is not None
    assert stale.code == constraints.REVISION_STALE
    assert constraints.check_freshness("same", constraints.text_hash("same")) is None


# ---------------------------------------------------------------- stub provider


def test_the_stub_provider_strengthens_without_touching_literals():
    draft = RhetoricalStubProvider().revise(
        RevisionRequest(
            section_key="liability",
            section_title="Liability",
            current_text=HEDGED,
            instruction="Make this more forceful.",
        )
    )
    assert draft.changed
    assert "it appears that" not in draft.text.lower()
    assert "apparently" not in draft.text.lower()
    assert constraints.check(HEDGED, draft.text, RevisionConstraint()) == []


def test_the_stub_provider_says_so_when_it_cannot_help():
    draft = RhetoricalStubProvider().revise(
        RevisionRequest(
            section_key="liability",
            section_title="Liability",
            current_text=HEDGED,
            instruction="Add a paragraph about the client's childhood.",
        )
    )
    assert draft.changed is False
    assert "offline drafter" in draft.explanation


# --------------------------------------------------------------- through the API


@pytest.mark.invariant
def test_proposing_a_revision_does_not_change_the_document(client, drafted_demand):
    """INVARIANT-008 — a proposal is inert until someone accepts it."""
    demand_id = drafted_demand["demand_id"]
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability",
        json={"body": HEDGED},
        headers=ATTORNEY,
    )
    before = client.get(f"/v1/demands/{demand_id}", headers=ATTORNEY).json()
    before_body = next(s for s in before["sections"] if s["key"] == "liability")["body"]

    response = _propose(client, demand_id)
    assert response.status_code == 201, response.text
    assert response.json()["valid"] is True

    after = client.get(f"/v1/demands/{demand_id}", headers=ATTORNEY).json()
    after_body = next(s for s in after["sections"] if s["key"] == "liability")["body"]
    assert after_body == before_body


def test_the_proposal_carries_a_readable_diff(client, drafted_demand):
    demand_id = drafted_demand["demand_id"]
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability", json={"body": HEDGED}, headers=ATTORNEY
    )
    body = _propose(client, demand_id).json()

    assert body["before"] == HEDGED
    assert body["after"] != HEDGED
    assert "---" in body["unified_diff"] and "+++" in body["unified_diff"]
    assert body["violations"] == []


def test_accepting_a_revision_changes_the_section(client, drafted_demand):
    demand_id = drafted_demand["demand_id"]
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability", json={"body": HEDGED}, headers=ATTORNEY
    )
    proposal = _propose(client, demand_id).json()["proposal"]

    response = client.post(
        f"/v1/revisions/{proposal['id']}/accept", json={"note": "Reads better."},
        headers=ATTORNEY,
    )
    assert response.status_code == 200, response.text
    assert response.json()["proposal"]["status"] == "ACCEPTED"

    detail = client.get(f"/v1/demands/{demand_id}", headers=ATTORNEY).json()
    section = next(s for s in detail["sections"] if s["key"] == "liability")
    assert "It appears that" not in section["body"]
    assert section["edited_by"] == "attorney_45"


def test_rejecting_a_revision_leaves_the_section_alone(client, drafted_demand):
    demand_id = drafted_demand["demand_id"]
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability", json={"body": HEDGED}, headers=ATTORNEY
    )
    proposal = _propose(client, demand_id).json()["proposal"]

    response = client.post(
        f"/v1/revisions/{proposal['id']}/reject", json={"note": "Too blunt."}, headers=ATTORNEY
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"

    detail = client.get(f"/v1/demands/{demand_id}", headers=ATTORNEY).json()
    assert next(s for s in detail["sections"] if s["key"] == "liability")["body"] == HEDGED


def test_only_an_attorney_may_accept(client, drafted_demand):
    demand_id = drafted_demand["demand_id"]
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability", json={"body": HEDGED}, headers=ATTORNEY
    )
    proposal = _propose(client, demand_id, headers=PARALEGAL).json()["proposal"]

    assert (
        client.post(
            f"/v1/revisions/{proposal['id']}/accept", json={}, headers=PARALEGAL
        ).status_code
        == 403
    )
    assert (
        client.post(f"/v1/revisions/{proposal['id']}/accept", json={}, headers=ATTORNEY).status_code
        == 200
    )


def test_a_reader_cannot_propose_a_revision(client, drafted_demand):
    assert _propose(client, drafted_demand["demand_id"], headers=READONLY).status_code == 403


def test_an_invalid_proposal_cannot_be_accepted(client, drafted_demand, db):
    """A proposal that broke its constraints is shown, and refused."""
    from app.domain.models import RevisionOperation, RevisionProposal
    from app.domain.enums import RevisionStatus

    demand_id = drafted_demand["demand_id"]
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability", json={"body": HEDGED}, headers=ATTORNEY
    )
    proposal = _propose(client, demand_id).json()["proposal"]

    # Simulate a provider that smuggled a figure past the prompt.
    stored = db.get(RevisionProposal, proposal["id"])
    operation = stored.operations[0]
    operation.after_text = HEDGED + " Damages exceed $250,000.00."
    stored.validation = {"valid": False, "violations": [{"code": "REVISION_002"}]}
    stored.status = RevisionStatus.INVALID
    db.commit()

    response = client.post(
        f"/v1/revisions/{proposal['id']}/accept", json={}, headers=ATTORNEY
    )
    assert response.status_code == 409

    detail = client.get(f"/v1/demands/{demand_id}", headers=ATTORNEY).json()
    assert next(s for s in detail["sections"] if s["key"] == "liability")["body"] == HEDGED


def test_a_proposal_written_against_stale_text_is_refused(client, drafted_demand):
    demand_id = drafted_demand["demand_id"]
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability", json={"body": HEDGED}, headers=ATTORNEY
    )
    proposal = _propose(client, demand_id).json()["proposal"]

    # The attorney edits the section by hand before deciding on the proposal.
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability",
        json={"body": "A completely different account of liability."},
        headers=ATTORNEY,
    )

    response = client.post(
        f"/v1/revisions/{proposal['id']}/accept", json={}, headers=ATTORNEY
    )
    assert response.status_code == 409
    assert "changed since" in response.json()["detail"]


def test_a_locked_demand_takes_no_revisions(client, drafted_demand):
    demand_id = drafted_demand["demand_id"]
    approve = client.post(
        f"/v1/demands/{demand_id}/approve",
        json={"acknowledgement": drafted_demand["reference"]},
        headers=ATTORNEY,
    )
    assert approve.status_code == 200, approve.text
    assert _propose(client, demand_id).status_code == 409


def test_an_ai_revision_is_distinguishable_in_the_audit_trail(client, drafted_demand):
    case_id = drafted_demand["case_id"]
    demand_id = drafted_demand["demand_id"]
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability", json={"body": HEDGED}, headers=ATTORNEY
    )
    proposal = _propose(client, demand_id).json()["proposal"]
    client.post(f"/v1/revisions/{proposal['id']}/accept", json={}, headers=ATTORNEY)

    events = client.get(f"/v1/cases/{case_id}/audit", headers=ATTORNEY).json()
    proposed = next(e for e in events if e["event"] == "REVISION_PROPOSED")
    accepted = next(e for e in events if e["event"] == "REVISION_ACCEPTED")

    assert proposed["payload"]["applied"] is False
    assert proposed["payload"]["instruction"]
    assert accepted["payload"]["applied"] is True
    assert accepted["payload"]["origin"] == "ai_revision"
    assert accepted["actor"] == "attorney_45"


def test_accepting_one_proposal_supersedes_the_others_for_that_section(client, drafted_demand):
    demand_id = drafted_demand["demand_id"]
    client.patch(
        f"/v1/demands/{demand_id}/sections/liability", json={"body": HEDGED}, headers=ATTORNEY
    )
    first = _propose(client, demand_id).json()["proposal"]
    second = _propose(client, demand_id, instruction="Strengthen this section.").json()["proposal"]

    client.post(f"/v1/revisions/{first['id']}/accept", json={}, headers=ATTORNEY)

    proposals = client.get(f"/v1/demands/{demand_id}/revisions", headers=ATTORNEY).json()
    by_id = {p["id"]: p["status"] for p in proposals}
    assert by_id[first["id"]] == "ACCEPTED"
    assert by_id[second["id"]] == "SUPERSEDED"


def test_a_revision_the_stub_cannot_make_is_reported_not_faked(client, drafted_demand):
    demand_id = drafted_demand["demand_id"]
    response = _propose(
        client, demand_id, instruction="Add a paragraph about future lost earning capacity."
    )
    body = response.json()
    assert body["valid"] is False
    assert body["proposal"]["status"] == "INVALID"
    assert body["before"] == body["after"] or body["violations"]
