"""Append-only audit trail.

Every mutation records who did what to which subject. Nothing here ever updates
or deletes an existing row — reconstructing how a final document was produced
depends on that.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import AuditEvent
from ..security.auth import CurrentUser


def record(
    session: Session,
    *,
    event: str,
    actor: CurrentUser | str,
    case_id: str | None = None,
    demand_id: str | None = None,
    subject_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    if isinstance(actor, CurrentUser):
        actor_id, actor_role = actor.id, actor.role.value
    else:
        actor_id, actor_role = actor, None

    entry = AuditEvent(
        event=event,
        actor=actor_id,
        actor_role=actor_role,
        case_id=case_id,
        demand_id=demand_id,
        subject_id=subject_id,
        payload=payload or {},
    )
    session.add(entry)
    return entry


def list_events(
    session: Session,
    *,
    case_id: str | None = None,
    demand_id: str | None = None,
    limit: int = 200,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if case_id:
        stmt = stmt.where(AuditEvent.case_id == case_id)
    if demand_id:
        stmt = stmt.where(AuditEvent.demand_id == demand_id)
    return list(session.scalars(stmt))
