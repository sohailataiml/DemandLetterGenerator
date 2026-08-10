"""Assembles a demand draft: context → narratives → template → persisted sections."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import service as audit
from ..domain.enums import DemandStatus, SectionSource, Severity
from ..domain.models import Demand, DemandSection, ValidationIssueRecord
from ..security.auth import CurrentUser
from ..validation.engine import Issue, RenderedSection, default_engine
from .ai.narratives import generate_narratives
from .ai.prompts import PROMPT_VERSION
from .ai.provider import LLMProvider, get_provider
from .context import DemandContext, build_context
from .templates import TEMPLATE_VERSION, render


class DemandLockedError(RuntimeError):
    """The demand has been approved and can no longer be modified."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_demand(
    session: Session, *, case_id: str, actor: CurrentUser, letter_date: date | None = None
) -> Demand:
    next_version = (
        session.scalar(select(func.max(Demand.version)).where(Demand.case_id == case_id)) or 0
    ) + 1
    demand = Demand(
        case_id=case_id,
        version=next_version,
        status=DemandStatus.DRAFT,
        letter_date=letter_date or _now().date(),
        created_by=actor.id,
    )
    session.add(demand)
    session.flush()
    audit.record(
        session,
        event="DEMAND_CREATED",
        actor=actor,
        case_id=case_id,
        demand_id=demand.id,
        payload={"version": next_version, "letter_date": demand.letter_date.isoformat()},
    )
    session.flush()
    return demand


def generate_demand(
    session: Session,
    demand: Demand,
    *,
    actor: CurrentUser,
    provider: LLMProvider | None = None,
    regenerate_sections: list[str] | None = None,
) -> tuple[Demand, DemandContext]:
    if demand.locked:
        raise DemandLockedError(f"demand {demand.id} is approved and locked")

    provider = provider or get_provider()
    context = build_context(session, demand)

    # Human edits survive regeneration unless the caller explicitly asks for
    # that section to be rewritten.
    existing = {section.key: section for section in demand.sections}
    preserved_keys = {
        key
        for key, section in existing.items()
        if section.source == SectionSource.HUMAN
        and (regenerate_sections is None or key not in regenerate_sections)
    }

    narratives = generate_narratives(context, provider, only=regenerate_sections)
    if regenerate_sections:
        # Carry forward previously generated narrative bodies for untouched sections.
        for key, section in existing.items():
            if key in narratives or section.source != SectionSource.AI:
                continue
            narratives[key] = _ExistingNarrative(
                section_key=key,
                text=section.body,
                used_fact_ids=list(section.used_fact_ids or []),
            )

    drafts = render(context, narratives)

    for draft in drafts:
        section = existing.get(draft.key)
        if draft.key in preserved_keys and section is not None:
            continue
        if section is None:
            section = DemandSection(demand_id=demand.id, key=draft.key, position=draft.position)
            session.add(section)
        section.title = draft.title
        section.position = draft.position
        section.body = draft.body
        section.source = draft.source
        section.used_fact_ids = draft.used_fact_ids
        section.edited_by = None

    demand.template_version = TEMPLATE_VERSION
    demand.provider_name = provider.name
    demand.model_name = getattr(provider, "model", None)
    demand.prompt_version = PROMPT_VERSION
    demand.generated_at = _now()
    demand.damages_snapshot = context.damages.to_dict()
    if demand.status == DemandStatus.APPROVED:  # pragma: no cover - guarded above
        demand.status = DemandStatus.DRAFT

    audit.record(
        session,
        event="DEMAND_GENERATED",
        actor=actor,
        case_id=demand.case_id,
        demand_id=demand.id,
        payload={
            "template_version": TEMPLATE_VERSION,
            "provider": provider.name,
            "model": getattr(provider, "model", None),
            "prompt_version": PROMPT_VERSION,
            "regenerated": regenerate_sections or "all",
            "fact_ids_supplied": sorted(context.verified_fact_ids()),
            "sections": [d.key for d in drafts],
        },
    )
    session.flush()
    session.refresh(demand)
    return demand, context


class _ExistingNarrative:
    """Adapter so previously stored AI text re-renders without another model call."""

    insufficient_evidence = False
    missing = None

    def __init__(self, section_key: str, text: str, used_fact_ids: list[str]) -> None:
        self.section_key = section_key
        self.text = text
        self.used_fact_ids = used_fact_ids


def rendered_sections(demand: Demand) -> list[RenderedSection]:
    return [
        RenderedSection(
            key=section.key,
            title=section.title,
            body=section.body,
            source=str(section.source),
            used_fact_ids=list(section.used_fact_ids or []),
        )
        for section in sorted(demand.sections, key=lambda s: s.position)
    ]


def validate_demand(
    session: Session, demand: Demand, *, actor: CurrentUser
) -> list[Issue]:
    context = build_context(session, demand)
    issues = default_engine().run(context, rendered_sections(demand))

    for previous in list(demand.issues):
        session.delete(previous)
    session.flush()

    for issue in issues:
        session.add(
            ValidationIssueRecord(
                demand_id=demand.id,
                code=issue.code,
                severity=issue.severity,
                message=issue.message,
                section_key=issue.section_key,
                details=issue.details,
            )
        )

    blocking = sum(1 for i in issues if i.severity == Severity.BLOCKING)
    warnings = sum(1 for i in issues if i.severity == Severity.WARNING)
    audit.record(
        session,
        event="DEMAND_VALIDATED",
        actor=actor,
        case_id=demand.case_id,
        demand_id=demand.id,
        payload={
            "blocking": blocking,
            "warnings": warnings,
            "codes": sorted({i.code for i in issues}),
        },
    )
    session.flush()
    session.refresh(demand)
    return issues


def edit_section(
    session: Session, demand: Demand, key: str, body: str, *, actor: CurrentUser
) -> DemandSection:
    if demand.locked:
        raise DemandLockedError(f"demand {demand.id} is approved and locked")
    section = next((s for s in demand.sections if s.key == key), None)
    if section is None:
        raise KeyError(key)
    previous = section.body
    section.body = body
    section.source = SectionSource.HUMAN
    section.edited_by = actor.id
    audit.record(
        session,
        event="DEMAND_SECTION_EDITED",
        actor=actor,
        case_id=demand.case_id,
        demand_id=demand.id,
        subject_id=section.id,
        payload={"key": key, "previous_length": len(previous), "new_length": len(body)},
    )
    session.flush()
    return section
