"""Fact proposal and human verification."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...db import get_db
from ...domain.enums import FactStatus
from ...domain.models import Case, Fact
from ...domain.schemas import FactCreate, FactOut, FactRejection, FactSupersede
from ...facts import service as facts
from ...security.auth import CurrentUser, can_edit_case, can_read, can_verify_facts
from ..deps import get_case, get_fact

router = APIRouter(tags=["facts"])


@router.post("/cases/{case_id}/facts", response_model=FactOut, status_code=status.HTTP_201_CREATED)
def propose_fact(
    payload: FactCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Fact:
    try:
        return facts.propose_fact(
            db,
            case_id=case.id,
            fact_type=payload.fact_type,
            value=payload.value,
            summary=payload.summary,
            sources=payload.sources,
            actor=user,
            confidence=payload.confidence,
        )
    except facts.FactStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/cases/{case_id}/facts", response_model=list[FactOut])
def list_facts(
    status_filter: FactStatus | None = Query(default=None, alias="status"),
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[Fact]:
    return facts.list_facts(db, case.id, status_filter)


@router.post("/facts/{fact_id}/verify", response_model=FactOut)
def verify_fact(
    fact: Fact = Depends(get_fact),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_verify_facts),
) -> Fact:
    try:
        return facts.verify_fact(db, fact, user)
    except facts.FactStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/facts/{fact_id}/reject", response_model=FactOut)
def reject_fact(
    payload: FactRejection,
    fact: Fact = Depends(get_fact),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_verify_facts),
) -> Fact:
    try:
        return facts.reject_fact(db, fact, user, payload.reason)
    except facts.FactStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/facts/{fact_id}/supersede", response_model=FactOut, status_code=status.HTTP_201_CREATED
)
def supersede_fact(
    payload: FactSupersede,
    fact: Fact = Depends(get_fact),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_verify_facts),
) -> Fact:
    """Propose a correction to a verified fact. The original stands until the
    replacement is itself verified."""
    try:
        return facts.supersede_fact(
            db,
            fact,
            fact_type=payload.fact_type,
            value=payload.value,
            summary=payload.summary,
            sources=payload.sources,
            reason=payload.reason,
            actor=user,
        )
    except facts.FactStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
