"""Running jobs off the request path.

The default runner executes the pipeline in a worker thread of the API process.
That is the lightest thing that fits this repository: the MVP deliberately has
no Redis, no broker and no second process to deploy, and a job's entire state
lives in the database rather than in the runner, so nothing is lost if the
runner is swapped.

**Its limit, stated plainly:** a job is bound to the process that accepted it.
Run more than one API worker and a job started on worker A is invisible to a
`/jobs/{id}/events` stream that lands on worker B — the stream will fall back to
reading the row, so it still reports correctly, just less promptly. A
multi-process deployment should implement :class:`JobRunner` against a real
queue (Redis + ARQ is the intended shape) and register it here. The pipeline
and the persisted job state need no changes for that; only this file does.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Protocol

from ..db import session_scope
from ..domain.models import GenerationJob
from ..security.auth import CurrentUser
from . import pipeline, store

logger = logging.getLogger(__name__)

GENERATE = "generate"
EXTRACT = "extract"


class JobRunner(Protocol):
    def submit(self, job_id: str, actor: CurrentUser) -> None: ...


def _execute(job_id: str, actor: CurrentUser, notify) -> None:
    """Run one job to completion in its own database session."""
    with session_scope() as session:
        job = store.get_job(session, job_id)
        if job is None:  # pragma: no cover - job is created before submit
            logger.warning("job %s vanished before it ran", job_id)
            return
        store.mark_running(session, job)
        notify()
        try:
            if job.kind == EXTRACT:
                result = pipeline.run_extraction_only(
                    session, job, job.case_id, actor, notify=notify
                )
            else:
                demand = _demand_for(session, job)
                result = pipeline.run_generation(session, job, demand, actor, notify=notify)
        except Exception as exc:  # noqa: BLE001 - a job failure is data, not a crash
            logger.exception("job %s failed", job_id)
            store.mark_failed(session, job, f"{type(exc).__name__}: {exc}")
            notify()
            return
        store.mark_completed(session, job, result)
        notify()


def _demand_for(session, job: GenerationJob):
    from ..domain.models import Demand

    if not job.demand_id:
        raise pipeline.JobFailed("a generation job needs a demand")
    demand = session.get(Demand, job.demand_id)
    if demand is None:
        raise pipeline.JobFailed(f"demand {job.demand_id} no longer exists")
    return demand


class ThreadJobRunner:
    """Runs jobs on a background thread of this process.

    The pipeline is synchronous SQLAlchemy, so it runs on a thread rather than
    on the event loop; putting it on the loop would block every other request
    for the duration of the job, which is the problem this exists to solve.
    """

    name = "thread"

    def __init__(self) -> None:
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def submit(self, job_id: str, actor: CurrentUser) -> None:
        loop = _running_loop()

        def _notify() -> None:
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(store.signals.notify, job_id)
            else:  # pragma: no cover - no loop in a plain script
                store.signals.notify(job_id)

        thread = threading.Thread(
            target=_execute,
            args=(job_id, actor, _notify),
            name=f"dlg-job-{job_id[:12]}",
            daemon=True,
        )
        with self._lock:
            self._threads[job_id] = thread
        thread.start()

    def wait(self, job_id: str, timeout: float = 60.0) -> bool:
        """Block until a job finishes. For tests and scripts, not for handlers."""
        with self._lock:
            thread = self._threads.get(job_id)
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()


class InlineJobRunner:
    """Runs the job synchronously on submit.

    Used by the test suite so a job's effects are observable without waiting on
    a thread. It is the same pipeline; only the scheduling differs.
    """

    name = "inline"

    def submit(self, job_id: str, actor: CurrentUser) -> None:
        _execute(job_id, actor, lambda: store.signals.notify(job_id))

    def wait(self, job_id: str, timeout: float = 60.0) -> bool:  # noqa: ARG002
        return True


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - called outside a request
        return None


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        from ..config import get_settings

        _runner = (
            InlineJobRunner() if get_settings().job_runner == "inline" else ThreadJobRunner()
        )
    return _runner


def set_runner(runner: JobRunner | None) -> None:
    """Swap the runner. Tests use this; production sets it via configuration."""
    global _runner
    _runner = runner
