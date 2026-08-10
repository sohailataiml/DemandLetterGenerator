"""Chronological medical timeline assembled from case data.

Entries are always derived from stored records — never from narrative text — so
the letter and the timeline cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import (
    Accident,
    Diagnosis,
    ImagingFinding,
    MedicalBill,
    MedicalProvider,
    TreatmentEvent,
)


@dataclass(frozen=True)
class TimelineEntry:
    entry_date: date
    kind: str
    title: str
    provider: str | None = None
    detail: str | None = None
    diagnoses: list[str] = field(default_factory=list)
    cost: Decimal | None = None
    source_document_ids: list[str] = field(default_factory=list)


def build_timeline(session: Session, case_id: str) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []

    accident = session.scalar(select(Accident).where(Accident.case_id == case_id))
    if accident is not None:
        entries.append(
            TimelineEntry(
                entry_date=accident.occurred_on,
                kind="collision",
                title="Collision",
                detail=accident.description or accident.location,
            )
        )

    providers = {
        p.id: p
        for p in session.scalars(
            select(MedicalProvider).where(MedicalProvider.case_id == case_id)
        )
    }

    diagnoses_by_event: dict[str, list[str]] = {}
    standalone_diagnoses: list[Diagnosis] = []
    for diagnosis in session.scalars(select(Diagnosis).where(Diagnosis.case_id == case_id)):
        label = (
            f"{diagnosis.code} {diagnosis.description}".strip()
            if diagnosis.code
            else diagnosis.description
        )
        if diagnosis.treatment_event_id:
            diagnoses_by_event.setdefault(diagnosis.treatment_event_id, []).append(label)
        elif diagnosis.diagnosed_on:
            standalone_diagnoses.append(diagnosis)

    # Bills attach cost to the treatment they paid for where the dates line up.
    bills = list(session.scalars(select(MedicalBill).where(MedicalBill.case_id == case_id)))
    cost_by_provider_date: dict[tuple[str | None, date | None], Decimal] = {}
    for bill in bills:
        if bill.amount is None or bill.billed_on is None:
            continue
        key = (bill.provider_id, bill.billed_on)
        cost_by_provider_date[key] = cost_by_provider_date.get(key, Decimal("0.00")) + bill.amount

    for event in session.scalars(
        select(TreatmentEvent).where(TreatmentEvent.case_id == case_id)
    ):
        provider = providers.get(event.provider_id) if event.provider_id else None
        entries.append(
            TimelineEntry(
                entry_date=event.event_date,
                kind=str(event.event_type),
                title=event.description,
                provider=provider.name if provider else None,
                detail=", ".join(event.body_regions) if event.body_regions else None,
                diagnoses=diagnoses_by_event.get(event.id, []),
                cost=cost_by_provider_date.get((event.provider_id, event.event_date)),
                source_document_ids=[event.source_document_id] if event.source_document_id else [],
            )
        )

    for imaging in session.scalars(
        select(ImagingFinding).where(ImagingFinding.case_id == case_id)
    ):
        provider = providers.get(imaging.provider_id) if imaging.provider_id else None
        detail_parts = [part for part in (imaging.level, imaging.finding, imaging.measurement) if part]
        entries.append(
            TimelineEntry(
                entry_date=imaging.study_date,
                kind="imaging",
                title=f"{imaging.modality} — {imaging.body_region or 'study'}",
                provider=provider.name if provider else None,
                detail=" · ".join(detail_parts),
                source_document_ids=(
                    [imaging.source_document_id] if imaging.source_document_id else []
                ),
            )
        )

    for diagnosis in standalone_diagnoses:
        entries.append(
            TimelineEntry(
                entry_date=diagnosis.diagnosed_on,  # type: ignore[arg-type]
                kind="diagnosis",
                title=diagnosis.description,
                diagnoses=[diagnosis.description],
                source_document_ids=(
                    [diagnosis.source_document_id] if diagnosis.source_document_id else []
                ),
            )
        )

    entries.sort(key=lambda e: (e.entry_date, e.kind, e.title))
    return entries
