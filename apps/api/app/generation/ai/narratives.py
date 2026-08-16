"""Section-specific retrieval + drafting jobs.

Retrieval is deliberately narrow: each section only ever sees verified facts of
the types it is allowed to talk about, plus the deterministic case data it needs
for dates and names. A model that never receives a stray fact cannot cite one.
"""

from __future__ import annotations

from ..context import DemandContext
from .prompts import SECTION_SPECS, SectionSpec
from .provider import FactPayload, LLMProvider, NarrativeRequest, NarrativeResult
from .serialization import build_case_context

NARRATIVE_SECTION_KEYS = tuple(SECTION_SPECS)


def build_context_block(ctx: DemandContext) -> str:
    """The case context, serialized so a privacy transformation cannot rewrite it.

    This used to be prose — ``Named insured: <name>`` on one line, ``Driver at
    time of collision: <name>`` on the next — and in production a detected
    PERSON span crossed the newline and swallowed the word "Driver", leaving the
    model a sentence that made the insured and the driver the same person. See
    ``serialization.py`` for the full account. Roles now live outside values, in
    records a replaced value cannot merge.
    """
    return build_case_context(ctx)


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
            gateway=result.gateway,
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
