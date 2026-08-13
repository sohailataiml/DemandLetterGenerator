"""Job state, persisted.

The database row is the single source of truth for a job's progress. An
in-memory signal exists only to wake a listening SSE connection promptly; if it
is missed the stream still converges, because it re-reads the row. That keeps
the streaming layer honest about a job it did not itself start.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import JobStatus
from ..domain.models import GenerationJob

TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class StageEvent:
    stage: str
    status: str
    detail: str | None = None
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {"stage": self.stage, "status": self.status, "at": self.at or _now().isoformat()}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class _Signals:
    """One asyncio.Event per job, so a listener wakes without polling hard."""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def event_for(self, job_id: str) -> asyncio.Event:
        event = self._events.get(job_id)
        if event is None:
            event = asyncio.Event()
            self._events[job_id] = event
        return event

    def notify(self, job_id: str) -> None:
        event = self._events.get(job_id)
        if event is not None:
            event.set()

    def clear(self, job_id: str) -> None:
        self._events.pop(job_id, None)


signals = _Signals()


def create_job(
    session: Session,
    *,
    case_id: str,
    kind: str,
    requested_by: str,
    demand_id: str | None = None,
    payload: dict | None = None,
) -> GenerationJob:
    job = GenerationJob(
        case_id=case_id,
        demand_id=demand_id,
        kind=kind,
        status=JobStatus.QUEUED,
        payload=payload or {},
        stages=[StageEvent(stage="queued", status="completed").to_dict()],
        requested_by=requested_by,
    )
    session.add(job)
    session.flush()
    return job


def append_stage(
    session: Session, job: GenerationJob, stage: str, status: str, detail: str | None = None
) -> None:
    """Record one pipeline step. The list is append-only, like the audit trail."""
    event = StageEvent(stage=stage, status=status, detail=detail).to_dict()
    # Reassign rather than mutate: SQLAlchemy does not track in-place JSON edits.
    job.stages = list(job.stages or []) + [event]
    session.flush()


def mark_running(session: Session, job: GenerationJob) -> None:
    job.status = JobStatus.RUNNING
    job.started_at = _now()
    session.flush()


def mark_completed(session: Session, job: GenerationJob, result: dict) -> None:
    job.status = JobStatus.COMPLETED
    job.result = result
    job.finished_at = _now()
    session.flush()


def mark_failed(session: Session, job: GenerationJob, error: str) -> None:
    job.status = JobStatus.FAILED
    job.error = error
    job.finished_at = _now()
    session.flush()


def get_job(session: Session, job_id: str) -> GenerationJob | None:
    return session.get(GenerationJob, job_id)


def list_jobs(session: Session, case_id: str, limit: int = 50) -> list[GenerationJob]:
    return list(
        session.scalars(
            select(GenerationJob)
            .where(GenerationJob.case_id == case_id)
            .order_by(GenerationJob.created_at.desc())
            .limit(limit)
        )
    )


def is_terminal(job: GenerationJob) -> bool:
    return job.status in TERMINAL_STATUSES
