"""Running claim grounding across a demand and reporting what it found.

Ordering matters here. A claim is graded against the facts its section cites,
but the *status* of those facts is checked separately, because "well supported
by a fact nobody verified" is not support at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import ClaimStatus, FactStatus, SectionSource
from ..domain.models import Demand, Fact, SectionClaim
from ..generation.context import DemandContext
from ..validation.engine import RenderedSection
from . import claims as segmentation
from .checker import ClaimVerdict, GroundingContext, check_claim, content_tokens

CLAIM_UNSUPPORTED = "CLAIM_001"
CLAIM_PROPOSED_ONLY = "CLAIM_002"
CLAIM_CONTRADICTS = "CLAIM_003"
CLAIM_SUPERSEDED = "CLAIM_004"

#: Only machine-drafted prose is graded. Attorney-authored text is the
#: attorney's own assertion and is theirs to stand behind.
GRADED_SOURCES = {SectionSource.AI.value}


@dataclass(frozen=True)
class GradedClaim:
    section_key: str
    verdict: ClaimVerdict

    def to_dict(self) -> dict:
        return {"section_key": self.section_key, **self.verdict.to_dict()}


@dataclass
class GroundingReport:
    graded: list[GradedClaim] = field(default_factory=list)
    section_keys: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.graded)

    @property
    def unsupported(self) -> list[GradedClaim]:
        return [g for g in self.graded if g.verdict.status == ClaimStatus.UNSUPPORTED]

    @property
    def partially_supported(self) -> list[GradedClaim]:
        return [g for g in self.graded if g.verdict.status == ClaimStatus.PARTIALLY_SUPPORTED]

    @property
    def supported(self) -> list[GradedClaim]:
        return [g for g in self.graded if g.verdict.status == ClaimStatus.SUPPORTED]

    def to_dict(self) -> dict:
        return {
            "claims_checked": self.total,
            "supported": len(self.supported),
            "partially_supported": len(self.partially_supported),
            "unsupported": len(self.unsupported),
            "sections": list(self.section_keys),
            "unsupported_claims": [g.to_dict() for g in self.unsupported],
        }


def _known_literals(context: DemandContext) -> frozenset[str]:
    """Words the deterministic layer put in the letter and stands behind."""
    pieces: list[str] = [context.client_name, context.case.client_display_name]
    pieces.extend(context.allowed_names())
    if context.claim:
        pieces.append(context.claim.claim_number)
    for value in context.allowed_amounts():
        pieces.append(f"{value:,.2f}")
    for entry in context.allowed_dates():
        pieces.append(entry.isoformat())
        pieces.append(f"{entry.strftime('%B')} {entry.day} {entry.year}")
    return content_tokens(" ".join(pieces))


def evaluate(context: DemandContext, sections: Sequence[RenderedSection]) -> GroundingReport:
    """Grade every machine-drafted claim in the demand."""
    grounding = GroundingContext(facts=context.facts, known_literals=_known_literals(context))
    report = GroundingReport()

    for section in sections:
        if section.source not in GRADED_SOURCES:
            continue
        body = section.body.strip()
        if not body or body.startswith("["):
            continue

        report.section_keys.append(section.key)
        for claim in segmentation.segment(section.body):
            report.graded.append(
                GradedClaim(
                    section_key=section.key,
                    verdict=check_claim(claim, grounding, section.used_fact_ids),
                )
            )
    return report


def persist(session: Session, demand: Demand, report: GroundingReport) -> None:
    """Replace the demand's stored claim rows with this run's results."""
    for existing in session.scalars(
        select(SectionClaim).where(SectionClaim.demand_id == demand.id)
    ):
        session.delete(existing)
    session.flush()

    for graded in report.graded:
        verdict = graded.verdict
        session.add(
            SectionClaim(
                demand_id=demand.id,
                section_key=graded.section_key,
                position=verdict.claim.position,
                text=verdict.claim.text,
                start_offset=verdict.claim.start_offset,
                end_offset=verdict.claim.end_offset,
                status=verdict.status,
                score=verdict.score,
                fact_ids=list(verdict.fact_ids),
                citation_ids=list(verdict.citation_ids),
                reason=verdict.reason or None,
            )
        )
    session.flush()


def stale_reliance(
    context: DemandContext, sections: Sequence[RenderedSection], all_facts: Sequence[Fact]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Sections leaning on PROPOSED or SUPERSEDED facts.

    Returns ``(proposed_only, superseded)`` as ``(section_key, fact_id)`` pairs.
    ``context.facts`` holds only verified facts, so a cited id that is not there
    is either unknown or not verified; ``all_facts`` resolves which.
    """
    by_id = {fact.id: fact for fact in all_facts}
    verified = context.verified_fact_ids()
    proposed_only: list[tuple[str, str]] = []
    superseded: list[tuple[str, str]] = []

    for section in sections:
        for fact_id in section.used_fact_ids:
            fact = by_id.get(fact_id)
            if fact is None:
                continue
            if fact_id in verified:
                if fact.superseded_by_id:
                    superseded.append((section.key, fact_id))
                continue
            if fact.status == FactStatus.PROPOSED:
                proposed_only.append((section.key, fact_id))
            elif fact.status == FactStatus.SUPERSEDED:
                superseded.append((section.key, fact_id))
    return proposed_only, superseded
