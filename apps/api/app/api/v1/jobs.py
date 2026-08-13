"""Asynchronous generation jobs and their progress stream.

``POST`` returns 202 with a job id immediately; the expensive work happens off
the request path. ``GET /jobs/{id}/events`` streams stage transitions as
server-sent events, reading the persisted job row so the stream is correct even
for a job this process did not start.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...db import get_db, session_scope
from ...domain.models import Case, Demand, GenerationJob
from ...domain.schemas import GenerationJobOut, JobRequestIn
from ...jobs import runner as job_runner
from ...jobs import store as job_store
from ...security.auth import CurrentUser, can_edit_case, can_read
from ..deps import get_case

router = APIRouter(tags=["jobs"])

#: How often the stream re-reads the job row when no signal arrives.
POLL_SECONDS = 0.25
#: Give up on a stream that never terminates rather than hold the socket open.
STREAM_TIMEOUT_SECONDS = 900


def get_job(job_id: str, db: Session = Depends(get_db)) -> GenerationJob:
    job = job_store.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"job {job_id} not found")
    return job


@router.post(
    "/cases/{case_id}/generate",
    response_model=GenerationJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_generation(
    payload: JobRequestIn,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> GenerationJob:
    """Queue a full generation run. Returns immediately with a job id."""
    demand_id = payload.demand_id
    if demand_id:
        demand = db.get(Demand, demand_id)
        if demand is None or demand.case_id != case.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"demand {demand_id} is not part of case {case.id}",
            )
        if demand.locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"demand {demand_id} is approved and locked",
            )
    else:
        from ...generation.composer import create_demand

        demand = create_demand(db, case_id=case.id, actor=user, letter_date=payload.letter_date)
        demand_id = demand.id
        if payload.template_id:
            from ...domain.models import LetterTemplate
            from ...templates import service as template_service

            template = db.get(LetterTemplate, payload.template_id)
            if template is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"template {payload.template_id} not found",
                )
            template_service.bind_template_to_demand(db, demand, template, actor=user)

    job = job_store.create_job(
        db,
        case_id=case.id,
        demand_id=demand_id,
        kind=job_runner.GENERATE,
        requested_by=user.id,
        payload={
            "extract": payload.extract,
            "document_ids": payload.document_ids,
            "regenerate_sections": payload.regenerate_sections,
        },
    )
    # Commit before handing the id to the runner: the worker opens its own
    # session and must be able to see the row.
    db.commit()
    job_runner.get_runner().submit(job.id, user)
    return _reload(job.id)


@router.post(
    "/cases/{case_id}/extract-async",
    response_model=GenerationJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_extraction(
    payload: JobRequestIn,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> GenerationJob:
    """Queue extraction of the case materials into PROPOSED facts."""
    job = job_store.create_job(
        db,
        case_id=case.id,
        kind=job_runner.EXTRACT,
        requested_by=user.id,
        payload={"document_ids": payload.document_ids},
    )
    db.commit()
    job_runner.get_runner().submit(job.id, user)
    return _reload(job.id)


def _reload(job_id: str) -> GenerationJob:
    """Re-read the job so the response reflects anything an inline runner did."""
    with session_scope() as session:
        job = job_store.get_job(session, job_id)
        session.expunge(job)
        return job


@router.get("/cases/{case_id}/jobs", response_model=list[GenerationJobOut])
def list_jobs(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[GenerationJob]:
    return job_store.list_jobs(db, case.id)


@router.get("/jobs/{job_id}", response_model=GenerationJobOut)
def get_job_detail(
    job: GenerationJob = Depends(get_job), user: CurrentUser = Depends(can_read)
) -> GenerationJob:
    return job


@router.get("/jobs/{job_id}/events")
async def stream_job_events(
    job_id: str, request: Request, user: CurrentUser = Depends(can_read)
) -> StreamingResponse:
    """Server-sent events, one per stage transition, then a terminal event."""
    with session_scope() as session:
        if job_store.get_job(session, job_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"job {job_id} not found"
            )

    return StreamingResponse(
        _event_stream(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _event_stream(job_id: str, request: Request) -> AsyncIterator[str]:
    emitted = 0
    waited = 0.0
    signal = job_store.signals.event_for(job_id)

    try:
        while True:
            if await request.is_disconnected():
                return

            with session_scope() as session:
                job = job_store.get_job(session, job_id)
                if job is None:  # pragma: no cover - existence checked before streaming
                    return
                stages = list(job.stages or [])
                terminal = job_store.is_terminal(job)
                # SQLite hands the column back as a plain string; str() covers
                # both that and the enum without pretending to know which.
                status_value = str(job.status)
                result = job.result
                error = job.error

            for stage in stages[emitted:]:
                yield _format("stage", stage)
            emitted = len(stages)

            if terminal:
                yield _format(
                    "done",
                    {"job_id": job_id, "status": status_value, "result": result, "error": error},
                )
                return

            signal.clear()
            try:
                await asyncio.wait_for(signal.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                waited += POLL_SECONDS
                if waited >= STREAM_TIMEOUT_SECONDS:
                    yield _format(
                        "done",
                        {
                            "job_id": job_id,
                            "status": status_value,
                            "error": "the event stream timed out; poll /jobs/{id} instead",
                        },
                    )
                    return
                # A comment frame keeps proxies from closing an idle stream.
                yield ": keep-alive\n\n"
    finally:
        job_store.signals.clear(job_id)
