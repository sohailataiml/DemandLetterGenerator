"""Demand drafting, validation, attorney approval, and artifact download."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...documents.finalize import (
    ApprovalBlockedError,
    PdfUnavailableError,
    load_or_build_docx,
    load_or_build_pdf,
)
from ...documents.finalize import approve_demand as approve_demand_service
from ...domain.models import Case, Demand
from ...domain.schemas import (
    ApprovalIn,
    DemandCreate,
    DemandGenerate,
    DemandOut,
    SectionEdit,
    ValidationIssueOut,
)
from ...generation.ai.provider import ProviderError
from ...generation.composer import (
    DemandLockedError,
    create_demand,
    edit_section,
    generate_demand,
    validate_demand,
)
from ...security.auth import CurrentUser, can_approve, can_edit_case, can_read
from ...templates.service import TemplateError
from ..deps import get_case, get_demand

router = APIRouter(tags=["demands"])


@router.post(
    "/cases/{case_id}/demands", response_model=DemandOut, status_code=status.HTTP_201_CREATED
)
def create_demand_draft(
    payload: DemandCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Demand:
    return create_demand(db, case_id=case.id, actor=user, letter_date=payload.letter_date)


@router.get("/cases/{case_id}/demands", response_model=list[DemandOut])
def list_demands(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[Demand]:
    return list(
        db.scalars(select(Demand).where(Demand.case_id == case.id).order_by(Demand.version.desc()))
    )


@router.get("/demands/{demand_id}", response_model=DemandOut)
def get_demand_detail(
    demand: Demand = Depends(get_demand), user: CurrentUser = Depends(can_read)
) -> Demand:
    return demand


@router.post("/demands/{demand_id}/generate", response_model=DemandOut)
def generate(
    payload: DemandGenerate,
    demand: Demand = Depends(get_demand),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Demand:
    try:
        updated, _ = generate_demand(
            db, demand, actor=user, regenerate_sections=payload.regenerate_sections
        )
    except DemandLockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"drafting failed: {exc}"
        ) from exc
    return updated


@router.post("/demands/{demand_id}/validate", response_model=list[ValidationIssueOut])
def validate(
    demand: Demand = Depends(get_demand),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[ValidationIssueOut]:
    issues = validate_demand(db, demand, actor=user)
    return [
        ValidationIssueOut(
            code=issue.code,
            severity=issue.severity,
            message=issue.message,
            section_key=issue.section_key,
            details=issue.details,
        )
        for issue in issues
    ]


@router.patch("/demands/{demand_id}/sections/{key}", response_model=DemandOut)
def update_section(
    key: str,
    payload: SectionEdit,
    demand: Demand = Depends(get_demand),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Demand:
    try:
        edit_section(db, demand, key, payload.body, actor=user)
    except DemandLockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"section {key!r} not found"
        ) from exc
    db.refresh(demand)
    return demand


@router.post("/demands/{demand_id}/approve", response_model=DemandOut)
def approve(
    payload: ApprovalIn,
    demand: Demand = Depends(get_demand),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_approve),
) -> Demand:
    try:
        return approve_demand_service(
            db, demand, actor=user, acknowledgement=payload.acknowledgement
        )
    except ApprovalBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "blocking_issues": [
                    {"code": i.code, "message": i.message, "section_key": i.section_key}
                    for i in exc.issues
                ],
            },
        ) from exc


@router.get("/demands/{demand_id}/docx")
def download_docx(
    demand: Demand = Depends(get_demand),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> Response:
    if not demand.sections:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="demand has not been generated yet"
        )
    try:
        data, digest = load_or_build_docx(db, demand, actor=user)
    except TemplateError as exc:
        # The template cannot be bound. Serving a partially filled letter would
        # be worse than serving none, so this is a conflict, not a fallback.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"the letter could not be bound into its template: {exc}",
        ) from exc
    name = "final.docx" if demand.locked else f"draft-v{demand.version}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-SHA256": digest,
        },
    )


@router.get("/demands/{demand_id}/pdf")
def download_pdf(
    demand: Demand = Depends(get_demand),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> Response:
    if not demand.sections:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="demand has not been generated yet"
        )
    try:
        data, digest = load_or_build_pdf(db, demand, actor=user)
    except PdfUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    name = "final.pdf" if demand.locked else f"draft-v{demand.version}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-SHA256": digest,
        },
    )
