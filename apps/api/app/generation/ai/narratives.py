"""Section-specific retrieval + drafting jobs.

Retrieval is deliberately narrow: each section only ever sees verified facts of
the types it is allowed to talk about, plus the deterministic case data it needs
for dates and names. A model that never receives a stray fact cannot cite one.
"""

from __future__ import annotations

from ...domain.money import format_money
from ..context import DemandContext, format_date
from .prompts import SECTION_SPECS, SectionSpec
from .provider import FactPayload, LLMProvider, NarrativeRequest, NarrativeResult

NARRATIVE_SECTION_KEYS = tuple(SECTION_SPECS)


def build_context_block(ctx: DemandContext) -> str:
    lines: list[str] = []
    lines.append(f"Client: {ctx.client_name}")
    if ctx.insured:
        lines.append(f"Named insured: {ctx.insured.full_name}")
    if ctx.driver:
        lines.append(f"Driver at time of collision: {ctx.driver.full_name}")
    if ctx.insured and ctx.driver and ctx.insured.full_name != ctx.driver.full_name:
        lines.append(
            "Note: the named insured and the driver are different people; "
            "do not conflate them."
        )
    if ctx.claim:
        lines.append(f"Claim number: {ctx.claim.claim_number}")
        lines.append(f"Date of loss: {format_date(ctx.claim.date_of_loss)}")
        if ctx.claim.carrier:
            lines.append(f"Carrier: {ctx.claim.carrier.name}")
    if ctx.accident:
        lines.append(f"Collision date: {format_date(ctx.accident.occurred_on)}")
        if ctx.accident.location:
            lines.append(f"Collision location: {ctx.accident.location}")
        if ctx.accident.description:
            lines.append(f"Collision description of record: {ctx.accident.description}")

    if ctx.timeline:
        lines.append("")
        lines.append("Treatment timeline (authoritative, do not alter dates):")
        for entry in ctx.timeline:
            provider = f" — {entry.provider}" if entry.provider else ""
            detail = f" ({entry.detail})" if entry.detail else ""
            lines.append(f"  {format_date(entry.entry_date)}: {entry.title}{provider}{detail}")

    if ctx.imaging_findings:
        lines.append("")
        lines.append("Imaging of record:")
        for imaging in ctx.imaging_findings:
            parts = [p for p in (imaging.level, imaging.finding, imaging.measurement) if p]
            lines.append(
                f"  {format_date(imaging.study_date)} {imaging.modality} "
                f"{imaging.body_region or ''}: {' · '.join(parts)}".rstrip()
            )

    lines.append("")
    lines.append(
        "Monetary totals are computed by the system and inserted separately. "
        "For reference only, do not restate: current medical expenses "
        f"{format_money(ctx.damages.current_medical_expenses)}."
    )
    return "\n".join(lines)


def facts_for_section(ctx: DemandContext, spec: SectionSpec) -> list[FactPayload]:
    payloads: list[FactPayload] = []
    for fact in ctx.facts:
        if str(fact.fact_type) not in spec.fact_types:
            continue
        citations = [
            f"{source.document_id}#p{source.page_number}" if source.page_number else source.document_id
            for source in fact.sources
        ]
        payloads.append(
            FactPayload(
                id=fact.id,
                fact_type=str(fact.fact_type),
                summary=fact.summary,
                value=fact.value,
                citations=citations,
            )
        )
    return payloads


def generate_section(
    ctx: DemandContext, spec: SectionSpec, provider: LLMProvider
) -> NarrativeResult:
    request = NarrativeRequest(
        spec=spec,
        context_block=build_context_block(ctx),
        facts=facts_for_section(ctx, spec),
    )
    result = provider.draft(request)

    # A model may only cite facts it was actually handed. Anything else is
    # dropped here rather than being carried into the provenance record.
    offered = {fact.id for fact in request.facts}
    filtered = [fact_id for fact_id in result.used_fact_ids if fact_id in offered]
    if filtered != result.used_fact_ids:
        result = NarrativeResult(
            section_key=result.section_key,
            text=result.text,
            used_fact_ids=filtered,
            insufficient_evidence=result.insufficient_evidence,
            provider=result.provider,
            model=result.model,
            prompt_version=result.prompt_version,
            missing=result.missing,
        )
    return result


def generate_narratives(
    ctx: DemandContext, provider: LLMProvider, only: list[str] | None = None
) -> dict[str, NarrativeResult]:
    keys = only or list(SECTION_SPECS)
    results: dict[str, NarrativeResult] = {}
    for key in keys:
        spec = SECTION_SPECS.get(key)
        if spec is None:
            continue
        results[key] = generate_section(ctx, spec, provider)
    return results
