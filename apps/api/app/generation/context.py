"""The single input object for template rendering, AI drafting, and validation.

Building all three from one context is what keeps the letter, the totals, and
the validation report describing the same case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..damages.calculator import DamagesSummary, summarize_case
from ..domain.enums import DocumentType, PartyRole
from ..domain.models import (
    Accident,
    Case,
    Claim,
    DamageClaim,
    Demand,
    Diagnosis,
    Fact,
    FutureTreatment,
    ImagingFinding,
    MedicalProvider,
    Party,
    SettlementTerms,
    SourceDocument,
)
from ..facts.service import verified_facts
from ..medical.timeline import TimelineEntry, build_timeline


@dataclass
class DemandContext:
    case: Case
    demand: Demand
    letter_date: date
    claim: Claim | None
    accident: Accident | None
    settlement: SettlementTerms | None
    parties: list[Party]
    providers: list[MedicalProvider]
    diagnoses: list[Diagnosis]
    imaging_findings: list[ImagingFinding]
    future_treatments: list[FutureTreatment]
    damage_claims: list[DamageClaim]
    timeline: list[TimelineEntry]
    facts: list[Fact]
    damages: DamagesSummary
    documents: list[SourceDocument] = field(default_factory=list)

    def documents_of_type(self, document_type: DocumentType) -> list[SourceDocument]:
        return [d for d in self.documents if d.document_type == document_type]

    # ---------------------------------------------------------------- parties

    def parties_with_role(self, role: PartyRole) -> list[Party]:
        return [p for p in self.parties if p.has_role(role)]

    def first_with_role(self, role: PartyRole) -> Party | None:
        found = self.parties_with_role(role)
        return found[0] if found else None

    @property
    def client(self) -> Party | None:
        return self.first_with_role(PartyRole.CLIENT)

    @property
    def insured(self) -> Party | None:
        return self.first_with_role(PartyRole.INSURED)

    @property
    def driver(self) -> Party | None:
        return self.first_with_role(PartyRole.DRIVER)

    @property
    def adjuster(self) -> Party | None:
        return self.first_with_role(PartyRole.ADJUSTER)

    @property
    def signing_attorney(self) -> Party | None:
        return self.first_with_role(PartyRole.ATTORNEY)

    @property
    def client_name(self) -> str:
        client = self.client
        return client.full_name if client else self.case.client_display_name

    # ------------------------------------------------------- allowed literals
    # These sets define what generated prose is permitted to assert. Anything a
    # model writes that is not in here is flagged by the validation engine.

    def allowed_names(self) -> set[str]:
        names: set[str] = set()
        for party in self.parties:
            names.add(party.full_name)
            if party.organization:
                names.add(party.organization)
        for provider in self.providers:
            names.add(provider.name)
        for treatment in self.future_treatments:
            if treatment.provider_name:
                names.add(treatment.provider_name)
        for item in self.damages.line_items:
            provider_name = item.get("provider_name")
            if provider_name:
                names.add(provider_name)
        if self.claim and self.claim.carrier:
            names.add(self.claim.carrier.name)
            if self.claim.carrier.adjuster_name:
                names.add(self.claim.carrier.adjuster_name)
        names.add(self.case.client_display_name)
        return {n.strip() for n in names if n and n.strip()}

    def allowed_dates(self) -> set[date]:
        dates: set[date] = {self.letter_date}
        if self.accident:
            dates.add(self.accident.occurred_on)
        if self.claim:
            dates.add(self.claim.date_of_loss)
        if self.settlement:
            dates.add(self.settlement.expires_at.date())
        for entry in self.timeline:
            dates.add(entry.entry_date)
        for imaging in self.imaging_findings:
            dates.add(imaging.study_date)
        for diagnosis in self.diagnoses:
            if diagnosis.diagnosed_on:
                dates.add(diagnosis.diagnosed_on)
        for treatment in self.future_treatments:
            if treatment.recommended_on:
                dates.add(treatment.recommended_on)
        return dates

    def allowed_amounts(self) -> set[Decimal]:
        amounts = set(self.damages.all_amounts())
        if self.claim and self.claim.policy_limit is not None:
            amounts.add(self.claim.policy_limit)
        if self.settlement and self.settlement.demand_amount is not None:
            amounts.add(self.settlement.demand_amount)
        return amounts

    def verified_fact_ids(self) -> set[str]:
        return {fact.id for fact in self.facts}


def build_context(session: Session, demand: Demand) -> DemandContext:
    case = session.get(Case, demand.case_id)
    if case is None:  # pragma: no cover - foreign key makes this unreachable
        raise ValueError(f"case {demand.case_id} not found")

    case_id = case.id
    return DemandContext(
        case=case,
        demand=demand,
        letter_date=demand.letter_date,
        claim=session.scalar(select(Claim).where(Claim.case_id == case_id)),
        accident=session.scalar(select(Accident).where(Accident.case_id == case_id)),
        settlement=session.scalar(
            select(SettlementTerms).where(SettlementTerms.case_id == case_id)
        ),
        parties=list(session.scalars(select(Party).where(Party.case_id == case_id))),
        providers=list(
            session.scalars(select(MedicalProvider).where(MedicalProvider.case_id == case_id))
        ),
        diagnoses=list(session.scalars(select(Diagnosis).where(Diagnosis.case_id == case_id))),
        imaging_findings=list(
            session.scalars(
                select(ImagingFinding)
                .where(ImagingFinding.case_id == case_id)
                .order_by(ImagingFinding.study_date)
            )
        ),
        future_treatments=list(
            session.scalars(select(FutureTreatment).where(FutureTreatment.case_id == case_id))
        ),
        damage_claims=list(
            session.scalars(select(DamageClaim).where(DamageClaim.case_id == case_id))
        ),
        timeline=build_timeline(session, case_id),
        facts=verified_facts(session, case_id),
        damages=summarize_case(session, case_id),
        documents=list(
            session.scalars(
                select(SourceDocument)
                .where(SourceDocument.case_id == case_id)
                .order_by(SourceDocument.created_at)
            )
        ),
    )


def format_date(value: date | datetime) -> str:
    """``June 6, 2025`` — built without platform-specific strftime modifiers."""
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def format_datetime(value: datetime) -> str:
    """``June 29, 2026 at 5:00 PM``."""
    hour = value.hour % 12 or 12
    meridiem = "AM" if value.hour < 12 else "PM"
    return f"{format_date(value.date())} at {hour}:{value.minute:02d} {meridiem}"
