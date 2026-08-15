"""Fact proposal and human verification."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...db import get_db
from ...domain.enums import FactStatus
from ...domain.models import Case, Fact, FactSource
from ...domain.schemas import (
    CitationSelectionIn,
    ExtractionReportOut,
    ExtractionRunIn,
    FactCreate,
    FactOut,
    FactRejection,
    FactSourceOut,
    FactSupersede,
)
from ...extraction import service as extraction
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


@router.get("/facts/{fact_id}/citations", response_model=list[FactSourceOut])
def list_fact_citations(
    fact: Fact = Depends(get_fact),
    user: CurrentUser = Depends(can_read),
) -> list[FactSource]:
    """The citations behind one fact.

    The same records are embedded in the fact itself; this endpoint exists so
    the evidence viewer can refresh a single fact's provenance — after a
    reviewer resolves an ambiguous citation, say — without refetching the whole
    case fact list.
    """
    return list(fact.sources)


@router.post("/citations/{citation_id}/resolve", response_model=FactSourceOut)
def resolve_citation(
    payload: CitationSelectionIn,
    citation_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_verify_facts),
) -> FactSource:
    """Pin a citation to the passage the reviewer selected on the page.

    This is provenance enrichment, not a change of evidence: the selection must
    be an occurrence of the passage the citation already quotes, and the fact's
    own content — its value, its summary, its status — is not touched. That is
    what makes it safe to run against a VERIFIED fact, whose meaning is
    immutable and stays immutable here.
    """
    citation = db.get(FactSource, citation_id)
    if citation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"citation {citation_id} not found"
        )
    try:
        updated = facts.apply_citation_selection(
            db,
            citation=citation,
            start=payload.start_offset,
            end=payload.end_offset,
            actor=user,
        )
    except facts.FactStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return updated


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
    "/cases/{case_id}/extract",
    response_model=list[ExtractionReportOut],
    status_code=status.HTTP_202_ACCEPTED,
)
def extract_facts(
    payload: ExtractionRunIn,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> list[ExtractionReportOut]:
    """Read the case materials and propose facts from them.

    Every fact created here is ``PROPOSED``. Nothing this endpoint does can put
    a fact into evidence — that still needs a human on ``/facts/{id}/verify``.

    This is the synchronous path, kept for scripting and tests. The UI uses the
    asynchronous job in ``/cases/{case_id}/jobs`` so a long extraction does not
    hold a request open.
    """
    try:
        reports = extraction.extract_case(
            db, case.id, actor=user, document_ids=payload.document_ids
        )
    except extraction.ExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"extraction failed: {exc}"
        ) from exc
    return [ExtractionReportOut(**report.to_dict()) for report in reports]


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
