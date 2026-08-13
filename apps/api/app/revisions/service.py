"""Proposing, validating, and deciding on AI revisions.

The shape of this module is the guarantee. ``propose`` writes a
:class:`RevisionProposal` and touches nothing else; ``accept`` is the only
function that changes a section, it requires an attorney, and it re-checks the
constraints against the section as it stands at that moment.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import service as audit
from ..domain.enums import RevisionStatus, SectionSource
from ..domain.models import Demand, DemandSection, RevisionOperation, RevisionProposal
from ..security.auth import CurrentUser
from . import constraints as constraint_checks
from .constraints import ConstraintViolation, RevisionConstraint, text_hash
from .provider import RevisionError, RevisionProvider, RevisionRequest, get_revision_provider


class RevisionStateError(ValueError):
    """The proposal's state forbids this operation."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _section(demand: Demand, key: str) -> DemandSection:
    section = next((s for s in demand.sections if s.key == key), None)
    if section is None:
        raise RevisionStateError(f"demand has no section {key!r}")
    return section


def _constraint_lines(constraint: RevisionConstraint) -> tuple[str, ...]:
    lines: list[str] = []
    if constraint.preserve_amounts:
        lines.append("Do not add, remove or alter any dollar amount.")
    if constraint.preserve_dates:
        lines.append("Do not add, remove or alter any date.")
    if constraint.preserve_facts and not constraint.allow_new_facts:
        lines.append("Do not assert any fact the current text does not already assert.")
        lines.append("Do not name any person or organisation not already named.")
    for literal in constraint.preserve_literals:
        lines.append(f"The text {literal!r} must appear unchanged.")
    return tuple(lines)


@dataclass(frozen=True)
class ProposalView:
    """A proposal plus the diff a reviewer needs to decide on it."""

    proposal: RevisionProposal
    before: str
    after: str
    unified_diff: str
    violations: list[dict]

    @property
    def is_valid(self) -> bool:
        return not self.violations


def unified_diff(before: str, after: str, section_key: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{section_key} (current)",
            tofile=f"{section_key} (proposed)",
            n=3,
        )
    )


# --------------------------------------------------------------------------- propose


def propose(
    session: Session,
    demand: Demand,
    *,
    section_key: str,
    instruction: str,
    constraint: RevisionConstraint | None = None,
    actor: CurrentUser,
    provider: RevisionProvider | None = None,
) -> ProposalView:
    """Ask for a revision. Changes nothing about the demand — INVARIANT-008."""
    if demand.locked:
        raise RevisionStateError(f"demand {demand.id} is approved and locked")

    section = _section(demand, section_key)
    constraint = constraint or RevisionConstraint()
    provider = provider or get_revision_provider()

    draft = provider.revise(
        RevisionRequest(
            section_key=section.key,
            section_title=section.title,
            current_text=section.body,
            instruction=instruction,
            constraint_lines=_constraint_lines(constraint),
        )
    )

    before = section.body
    after = draft.text.strip()
    violations: list[ConstraintViolation] = []
    if not draft.changed and after == before.strip():
        violations.append(
            ConstraintViolation(
                code="REVISION_008",
                message=(
                    draft.explanation
                    or "The drafter returned the section unchanged; there is nothing to accept."
                ),
            )
        )
    else:
        violations = constraint_checks.check(before, after, constraint)

    proposal = RevisionProposal(
        demand_id=demand.id,
        section_key=section.key,
        instruction=instruction,
        constraints=constraint.to_dict(),
        status=RevisionStatus.PROPOSED if not violations else RevisionStatus.INVALID,
        provider_name=draft.provider,
        model_name=draft.model,
        prompt_version=draft.prompt_version,
        validation={
            **constraint_checks.summarize(violations),
            "explanation": draft.explanation,
        },
        requested_by=actor.id,
    )
    session.add(proposal)
    session.flush()

    session.add(
        RevisionOperation(
            proposal_id=proposal.id,
            position=0,
            op="replace",
            paragraph_id=section.key,
            before_text=before,
            before_hash=text_hash(before),
            after_text=after,
            fact_ids=list(section.used_fact_ids or []),
        )
    )

    audit.record(
        session,
        event="REVISION_PROPOSED",
        actor=actor,
        case_id=demand.case_id,
        demand_id=demand.id,
        subject_id=proposal.id,
        payload={
            "section_key": section.key,
            "instruction": instruction,
            "constraints": constraint.to_dict(),
            "provider": draft.provider,
            "model": draft.model,
            "before_hash": text_hash(before),
            "valid": not violations,
            "violations": [v.code for v in violations],
            # The proposal is recorded, not applied. The section is untouched.
            "applied": False,
        },
    )
    session.flush()
    session.refresh(proposal)

    return ProposalView(
        proposal=proposal,
        before=before,
        after=after,
        unified_diff=unified_diff(before, after, section.key),
        violations=[v.to_dict() for v in violations],
    )


# ---------------------------------------------------------------------- decisions


def accept(
    session: Session, proposal: RevisionProposal, *, actor: CurrentUser, note: str | None = None
) -> DemandSection:
    """Apply a proposal. The only path by which AI text enters the document."""
    if proposal.status != RevisionStatus.PROPOSED:
        raise RevisionStateError(
            f"only a PROPOSED revision can be accepted; {proposal.id} is {proposal.status}"
        )
    if not proposal.validation.get("valid"):
        raise RevisionStateError(
            "this revision failed its own constraints and cannot be accepted"
        )
    if not actor.is_attorney:
        raise RevisionStateError("only an attorney may accept an AI revision")

    demand = session.get(Demand, proposal.demand_id)
    if demand is None:  # pragma: no cover - FK guarantees this
        raise RevisionStateError(f"demand {proposal.demand_id} no longer exists")
    if demand.locked:
        raise RevisionStateError(f"demand {demand.id} is approved and locked")

    section = _section(demand, proposal.section_key)
    operation = proposal.operations[0]

    # Re-check against the text as it stands now, not as it stood when proposed.
    stale = constraint_checks.check_freshness(section.body, operation.before_hash)
    if stale is not None:
        proposal.status = RevisionStatus.INVALID
        proposal.validation = {"valid": False, "violations": [stale.to_dict()]}
        session.flush()
        raise RevisionStateError(stale.message)

    constraint = RevisionConstraint.from_dict(proposal.constraints)
    violations = constraint_checks.check(section.body, operation.after_text, constraint)
    if violations:  # pragma: no cover - propose() already rejected these
        proposal.status = RevisionStatus.INVALID
        proposal.validation = constraint_checks.summarize(violations)
        session.flush()
        raise RevisionStateError("this revision no longer satisfies its constraints")

    previous = section.body
    section.body = operation.after_text
    # An accepted AI revision is an attorney's edit: they chose it, and the
    # audit trail records that it came from the model.
    section.source = SectionSource.HUMAN
    section.edited_by = actor.id

    proposal.status = RevisionStatus.ACCEPTED
    proposal.decided_by = actor.id
    proposal.decided_at = _now()
    proposal.decision_note = note

    # A section can only carry one accepted revision at a time; anything else
    # still open was written against text that no longer exists.
    for other in session.scalars(
        select(RevisionProposal).where(
            RevisionProposal.demand_id == demand.id,
            RevisionProposal.section_key == proposal.section_key,
            RevisionProposal.status == RevisionStatus.PROPOSED,
            RevisionProposal.id != proposal.id,
        )
    ):
        other.status = RevisionStatus.SUPERSEDED

    audit.record(
        session,
        event="REVISION_ACCEPTED",
        actor=actor,
        case_id=demand.case_id,
        demand_id=demand.id,
        subject_id=proposal.id,
        payload={
            "section_key": section.key,
            "instruction": proposal.instruction,
            "provider": proposal.provider_name,
            "model": proposal.model_name,
            "origin": "ai_revision",
            "before_hash": operation.before_hash,
            "after_hash": text_hash(operation.after_text),
            "previous_length": len(previous),
            "new_length": len(section.body),
            "note": note,
            "applied": True,
        },
    )
    session.flush()
    return section


def reject(
    session: Session, proposal: RevisionProposal, *, actor: CurrentUser, note: str | None = None
) -> RevisionProposal:
    if proposal.status not in (RevisionStatus.PROPOSED, RevisionStatus.INVALID):
        raise RevisionStateError(
            f"only an open revision can be rejected; {proposal.id} is {proposal.status}"
        )
    proposal.status = RevisionStatus.REJECTED
    proposal.decided_by = actor.id
    proposal.decided_at = _now()
    proposal.decision_note = note

    audit.record(
        session,
        event="REVISION_REJECTED",
        actor=actor,
        case_id=session.get(Demand, proposal.demand_id).case_id,
        demand_id=proposal.demand_id,
        subject_id=proposal.id,
        payload={"section_key": proposal.section_key, "note": note, "applied": False},
    )
    session.flush()
    return proposal


def list_proposals(
    session: Session, demand_id: str, section_key: str | None = None
) -> list[RevisionProposal]:
    stmt = select(RevisionProposal).where(RevisionProposal.demand_id == demand_id)
    if section_key:
        stmt = stmt.where(RevisionProposal.section_key == section_key)
    return list(session.scalars(stmt.order_by(RevisionProposal.created_at.desc())))


def view(session: Session, proposal: RevisionProposal) -> ProposalView:
    demand = session.get(Demand, proposal.demand_id)
    section = _section(demand, proposal.section_key) if demand else None
    operation = proposal.operations[0]
    current = section.body if section else operation.before_text
    return ProposalView(
        proposal=proposal,
        before=current,
        after=operation.after_text,
        unified_diff=unified_diff(current, operation.after_text, proposal.section_key),
        violations=list(proposal.validation.get("violations") or []),
    )


__all__ = [
    "ProposalView",
    "RevisionConstraint",
    "RevisionError",
    "RevisionStateError",
    "accept",
    "list_proposals",
    "propose",
    "reject",
    "unified_diff",
    "view",
]
