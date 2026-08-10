"""Read-only audit trail access."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...audit import service as audit
from ...db import get_db
from ...domain.models import AuditEvent, Case
from ...domain.schemas import AuditEventOut
from ...security.auth import CurrentUser, can_read
from ..deps import get_case

router = APIRouter(tags=["audit"])


@router.get("/cases/{case_id}/audit", response_model=list[AuditEventOut])
def case_audit_trail(
    limit: int = Query(default=200, le=1000),
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[AuditEvent]:
    return audit.list_events(db, case_id=case.id, limit=limit)


@router.get("/demands/{demand_id}/audit", response_model=list[AuditEventOut])
def demand_audit_trail(
    demand_id: str,
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[AuditEvent]:
    return audit.list_events(db, demand_id=demand_id, limit=limit)
