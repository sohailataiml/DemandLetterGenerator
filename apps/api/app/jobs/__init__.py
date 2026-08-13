"""Asynchronous generation jobs.

    POST /cases/{id}/generate  -> 202 {job_id}
    GET  /jobs/{id}/events     -> server-sent stage transitions
    GET  /jobs/{id}            -> the same state, as a single response

The database row is the source of truth for a job. The runner is swappable and
holds no state of its own — see ``runner.py`` for what the default one can and
cannot do.
"""

from .pipeline import (
    ARTIFACT,
    BIND,
    CLAIMS,
    DRAFT,
    EXTRACT,
    FIDELITY,
    FINANCIAL,
    RESOLVE,
    JobFailed,
    run_extraction_only,
    run_generation,
)
from .runner import InlineJobRunner, JobRunner, ThreadJobRunner, get_runner, set_runner
from .store import (
    StageEvent,
    append_stage,
    create_job,
    get_job,
    is_terminal,
    list_jobs,
    mark_completed,
    mark_failed,
    mark_running,
    signals,
)

__all__ = [
    "ARTIFACT",
    "BIND",
    "CLAIMS",
    "DRAFT",
    "EXTRACT",
    "FIDELITY",
    "FINANCIAL",
    "RESOLVE",
    "InlineJobRunner",
    "JobFailed",
    "JobRunner",
    "StageEvent",
    "ThreadJobRunner",
    "append_stage",
    "create_job",
    "get_job",
    "get_runner",
    "is_terminal",
    "list_jobs",
    "mark_completed",
    "mark_failed",
    "mark_running",
    "run_extraction_only",
    "run_generation",
    "set_runner",
    "signals",
]
