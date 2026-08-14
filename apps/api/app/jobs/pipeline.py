"""The stages a generation job runs through.

Each stage is a named step that writes its own progress before and after doing
work, so a stalled job is visible as a stage that started and never finished
rather than as silence.

Nothing here is new behaviour. The stages call the same services the
synchronous endpoints call, which is deliberate: moving work off the request
path must not create a second implementation that can drift from the first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from ..audit import service as audit
from ..domain.enums import Severity
from ..domain.models import Demand, GenerationJob
from ..extraction import service as extraction
from ..generation.composer import generate_demand, validate_demand
from ..security.auth import CurrentUser
from . import store

#: Stage names are part of the API — the UI renders them. Keep them stable.
EXTRACT = "extracting"
RESOLVE = "resolving_verified_context"
DRAFT = "drafting_sections"
CLAIMS = "validating_claims"
FINANCIAL = "validating_financials"
BIND = "binding_template"
FIDELITY = "validating_template_fidelity"
ARTIFACT = "creating_artifact"

FINANCIAL_CODES = ("MONEY_001", "MONEY_002", "MONEY_003", "MONEY_004")
CLAIM_CODES = ("CLAIM_001", "CLAIM_002", "CLAIM_003", "CLAIM_004", "NARRATIVE_001")
TEMPLATE_CODES = tuple(f"TEMPLATE_00{n}" for n in range(1, 10))


class JobFailed(RuntimeError):
    """A stage could not complete. The job records this and stops."""


@dataclass
class StageRunner:
    """Wraps a stage so its start and end are always recorded."""

    session: Session
    job: GenerationJob
    notify: Callable[[], None]

    def run(self, stage: str, work):
        store.append_stage(self.session, self.job, stage, "running")
        self.notify()
        try:
            result = work()
        except Exception as exc:
            store.append_stage(self.session, self.job, stage, "failed", detail=str(exc)[:400])
            self.notify()
            raise
        detail = result if isinstance(result, str) else None
        store.append_stage(self.session, self.job, stage, "completed", detail=detail)
        self.notify()
        return result

    def skip(self, stage: str, reason: str) -> None:
        store.append_stage(self.session, self.job, stage, "skipped", detail=reason)
        self.notify()


def run_generation(
    session: Session,
    job: GenerationJob,
    demand: Demand,
    actor: CurrentUser,
    notify: Callable[[], None] = lambda: None,
) -> dict:
    """Extract, draft, validate, bind, and report. Returns the job result."""
    runner = StageRunner(session=session, job=job, notify=notify)
    payload = job.payload or {}
    result: dict = {"demand_id": demand.id}

    if payload.get("extract", False):
        reports = runner.run(
            EXTRACT,
            lambda: extraction.extract_case(
                session, demand.case_id, actor=actor, document_ids=payload.get("document_ids")
            ),
        )
        result["extraction"] = {
            "documents": len(reports),
            "proposed": sum(r.proposed for r in reports),
            "rejected": sum(len(r.rejected) for r in reports),
        }
    else:
        runner.skip(EXTRACT, "extraction was not requested for this run")

    # Building the context is what enforces INVARIANT-001: only VERIFIED facts
    # are ever loaded, so nothing downstream can reach an unverified one.
    def _resolve() -> str:
        from ..generation.context import build_context

        context = build_context(session, demand)
        return f"{len(context.facts)} verified fact(s) in scope"

    result["context"] = runner.run(RESOLVE, _resolve)

    def _draft() -> str:
        _, context = generate_demand(
            session, demand, actor=actor, regenerate_sections=payload.get("regenerate_sections")
        )
        return f"{len(demand.sections)} section(s) drafted"

    result["drafting"] = runner.run(DRAFT, _draft)

    issues = runner.run(CLAIMS, lambda: validate_demand(session, demand, actor=actor))
    by_code = {}
    for issue in issues:
        by_code.setdefault(issue.code, 0)
        by_code[issue.code] += 1

    runner.run(
        FINANCIAL,
        lambda: _summarize(issues, FINANCIAL_CODES, "financial"),
    )

    if demand.template_id:
        runner.run(BIND, lambda: f"bound into template {demand.template_sha256[:12]}")
        runner.run(FIDELITY, lambda: _summarize(issues, TEMPLATE_CODES, "template fidelity"))
    else:
        runner.skip(BIND, "no template is bound to this demand")
        runner.skip(FIDELITY, "no template is bound to this demand")

    def _artifact() -> str:
        from ..documents.finalize import build_docx

        _, key, digest = build_docx(session, demand, actor=actor, store=None, final=False)
        result["artifact"] = {"key": key, "sha256": digest}
        return f"draft artifact {digest[:12]}"

    runner.run(ARTIFACT, _artifact)

    blocking = [i for i in issues if i.severity == Severity.BLOCKING]
    result["validation"] = {
        "blocking": len(blocking),
        "warnings": sum(1 for i in issues if i.severity == Severity.WARNING),
        "codes": sorted(by_code),
        "blocking_codes": sorted({i.code for i in blocking}),
    }
    result["claims"] = demand.claim_report
    result["fidelity"] = demand.fidelity_report
    return result


def _summarize(issues, codes, label: str) -> str:
    matching = [i for i in issues if i.code in codes]
    blocking = [i for i in matching if i.severity == Severity.BLOCKING]
    if not matching:
        return f"no {label} issues"
    return f"{len(blocking)} blocking, {len(matching) - len(blocking)} advisory {label} issue(s)"


def run_extraction_only(
    session: Session,
    job: GenerationJob,
    case_id: str,
    actor: CurrentUser,
    notify: Callable[[], None] = lambda: None,
) -> dict:
    runner = StageRunner(session=session, job=job, notify=notify)
    payload = job.payload or {}
    reports = runner.run(
        EXTRACT,
        lambda: extraction.extract_case(
            session, case_id, actor=actor, document_ids=payload.get("document_ids")
        ),
    )
    result = {
        "documents": len(reports),
        "proposed": sum(r.proposed for r in reports),
        "rejected": sum(len(r.rejected) for r in reports),
        "reports": [r.to_dict() for r in reports],
    }
    audit.record(
        session,
        event="EXTRACTION_COMPLETED",
        actor=actor,
        case_id=case_id,
        subject_id=job.id,
        payload={key: result[key] for key in ("documents", "proposed", "rejected")},
    )
    session.flush()
    return result
