"""Medical records, bills, damages inputs, timeline, and the damages summary."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...audit import service as audit
from ...damages.calculator import summarize_case
from ...db import get_db
from ...domain.models import (
    Case,
    DamageClaim,
    Diagnosis,
    FutureTreatment,
    ImagingFinding,
    MedicalBill,
    MedicalProvider,
    TreatmentEvent,
)
from ...domain.schemas import (
    BillCreate,
    BillOut,
    DamageClaimCreate,
    DamageClaimOut,
    DamagesOut,
    DiagnosisCreate,
    DiagnosisOut,
    FutureTreatmentCreate,
    FutureTreatmentOut,
    ImagingFindingCreate,
    ImagingFindingOut,
    PendingBillOut,
    ProviderCreate,
    ProviderOut,
    TimelineEntryOut,
    TreatmentEventCreate,
    TreatmentEventOut,
)
from ...medical.timeline import build_timeline
from ...security.auth import CurrentUser, can_edit_case, can_read
from ..deps import get_case

router = APIRouter(tags=["medical"])


def _create(db: Session, model, case: Case, payload, user: CurrentUser, event: str):
    record = model(case_id=case.id, **payload.model_dump())
    db.add(record)
    db.flush()
    audit.record(
        db,
        event=event,
        actor=user,
        case_id=case.id,
        subject_id=record.id,
        payload=payload.model_dump(mode="json"),
    )
    return record


@router.post(
    "/cases/{case_id}/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED
)
def add_provider(
    payload: ProviderCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
):
    return _create(db, MedicalProvider, case, payload, user, "PROVIDER_ADDED")


@router.get("/cases/{case_id}/providers", response_model=list[ProviderOut])
def list_providers(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    return list(db.scalars(select(MedicalProvider).where(MedicalProvider.case_id == case.id)))


@router.post(
    "/cases/{case_id}/treatment-events",
    response_model=TreatmentEventOut,
    status_code=status.HTTP_201_CREATED,
)
def add_treatment_event(
    payload: TreatmentEventCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
):
    return _create(db, TreatmentEvent, case, payload, user, "TREATMENT_EVENT_ADDED")


@router.post(
    "/cases/{case_id}/diagnoses", response_model=DiagnosisOut, status_code=status.HTTP_201_CREATED
)
def add_diagnosis(
    payload: DiagnosisCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
):
    return _create(db, Diagnosis, case, payload, user, "DIAGNOSIS_ADDED")


@router.post(
    "/cases/{case_id}/imaging-findings",
    response_model=ImagingFindingOut,
    status_code=status.HTTP_201_CREATED,
)
def add_imaging_finding(
    payload: ImagingFindingCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
):
    return _create(db, ImagingFinding, case, payload, user, "IMAGING_FINDING_ADDED")


@router.post("/cases/{case_id}/bills", response_model=BillOut, status_code=status.HTTP_201_CREATED)
def add_bill(
    payload: BillCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
):
    return _create(db, MedicalBill, case, payload, user, "BILL_ADDED")


@router.get("/cases/{case_id}/bills", response_model=list[BillOut])
def list_bills(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    return list(db.scalars(select(MedicalBill).where(MedicalBill.case_id == case.id)))


@router.post(
    "/cases/{case_id}/future-treatments",
    response_model=FutureTreatmentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_future_treatment(
    payload: FutureTreatmentCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
):
    return _create(db, FutureTreatment, case, payload, user, "FUTURE_TREATMENT_ADDED")


@router.post(
    "/cases/{case_id}/damage-claims",
    response_model=DamageClaimOut,
    status_code=status.HTTP_201_CREATED,
)
def add_damage_claim(
    payload: DamageClaimCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
):
    return _create(db, DamageClaim, case, payload, user, "DAMAGE_CLAIM_ADDED")


@router.get("/cases/{case_id}/medical-timeline", response_model=list[TimelineEntryOut])
def medical_timeline(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    return [
        TimelineEntryOut(
            entry_date=entry.entry_date,
            kind=entry.kind,
            title=entry.title,
            provider=entry.provider,
            detail=entry.detail,
            diagnoses=entry.diagnoses,
            cost=entry.cost,
            source_document_ids=entry.source_document_ids,
        )
        for entry in build_timeline(db, case.id)
    ]


@router.get("/cases/{case_id}/damages", response_model=DamagesOut)
def damages_summary(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    summary = summarize_case(db, case.id)
    return DamagesOut(
        current_medical_expenses=summary.current_medical_expenses,
        pending_bills=[
            PendingBillOut(
                bill_id=b.bill_id, provider_name=b.provider_name, description=b.description
            )
            for b in summary.pending_bills
        ],
        estimated_bill_total=summary.estimated_bill_total,
        future_medical_low=summary.future_medical_low,
        future_medical_high=summary.future_medical_high,
        general_damages=summary.general_damages,
        other_damages=summary.other_damages,
        known_claimed_damages_low=summary.known_claimed_damages_low,
        known_claimed_damages_high=summary.known_claimed_damages_high,
        line_items=summary.line_items,
    )
