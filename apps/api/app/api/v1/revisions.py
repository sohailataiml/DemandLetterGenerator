"""Attorney AI revisions: propose, review a diff, accept or reject."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...db import get_db
from ...domain.models import Demand, RevisionProposal
from ...domain.schemas import (
    RevisionDecisionIn,
    RevisionProposalDetailOut,
    RevisionProposalOut,
    RevisionRequestIn,
)
from ...revisions import service as revisions
from ...revisions.constraints import RevisionConstraint
from ...revisions.provider import RevisionError
from ...security.auth import CurrentUser, can_approve, can_edit_case, can_read
from ..deps import get_demand
from .ai_errors import provider_failure

router = APIRouter(tags=["revisions"])


def get_proposal(proposal_id: str, db: Session = Depends(get_db)) -> RevisionProposal:
    proposal = db.get(RevisionProposal, proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"revision {proposal_id} not found"
        )
    return proposal


def _detail(view: revisions.ProposalView) -> RevisionProposalDetailOut:
    return RevisionProposalDetailOut(
        proposal=RevisionProposalOut.model_validate(view.proposal),
        before=view.before,
        after=view.after,
        unified_diff=view.unified_diff,
        violations=view.violations,
        valid=view.is_valid,
    )


@router.post(
    "/demands/{demand_id}/revisions",
    response_model=RevisionProposalDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def propose_revision(
    payload: RevisionRequestIn,
    demand: Demand = Depends(get_demand),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> RevisionProposalDetailOut:
    """Ask the model for a bounded edit.

    This creates a proposal and returns a diff. It does not change the demand:
    the section keeps its current text until an attorney accepts.
    """
    constraint = RevisionConstraint(
        preserve_facts=payload.constraints.preserve_facts,
        preserve_amounts=payload.constraints.preserve_amounts,
        preserve_dates=payload.constraints.preserve_dates,
        allow_new_facts=payload.constraints.allow_new_facts,
        preserve_literals=tuple(payload.constraints.preserve_literals),
    )
    try:
        view = revisions.propose(
            db,
            demand,
            section_key=payload.section_key,
            instruction=payload.instruction,
            constraint=constraint,
            actor=user,
        )
    except revisions.RevisionStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RevisionError as exc:
        # A proposal is inert until accepted, so nothing about this failure can
        # have touched the demand — the message says so.
        raise provider_failure(exc, action="revision") from exc
    return _detail(view)


@router.get("/demands/{demand_id}/revisions", response_model=list[RevisionProposalOut])
def list_revisions(
    section_key: str | None = Query(default=None),
    demand: Demand = Depends(get_demand),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[RevisionProposal]:
    return revisions.list_proposals(db, demand.id, section_key)


@router.get("/revisions/{proposal_id}", response_model=RevisionProposalDetailOut)
def get_revision(
    proposal: RevisionProposal = Depends(get_proposal),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> RevisionProposalDetailOut:
    return _detail(revisions.view(db, proposal))


@router.post("/revisions/{proposal_id}/accept", response_model=RevisionProposalDetailOut)
def accept_revision(
    payload: RevisionDecisionIn,
    proposal: RevisionProposal = Depends(get_proposal),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_approve),
) -> RevisionProposalDetailOut:
    """Apply the proposal. Attorney only, and re-validated at this moment."""
    try:
        revisions.accept(db, proposal, actor=user, note=payload.note)
    except revisions.RevisionStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.refresh(proposal)
    return _detail(revisions.view(db, proposal))


@router.post("/revisions/{proposal_id}/reject", response_model=RevisionProposalOut)
def reject_revision(
    payload: RevisionDecisionIn,
    proposal: RevisionProposal = Depends(get_proposal),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> RevisionProposal:
    try:
        return revisions.reject(db, proposal, actor=user, note=payload.note)
    except revisions.RevisionStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
