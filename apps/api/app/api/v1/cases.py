"""Case, party, claim, accident, and settlement-terms endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...audit import service as audit
from ...db import get_db
from ...domain.enums import Severity
from ...domain.models import (
    Accident,
    AuditEvent,
    Carrier,
    Case,
    Claim,
    Demand,
    Party,
    PartyRoleAssignment,
    SettlementTerms,
    ValidationIssueRecord,
    Vehicle,
)
from ...domain.schemas import (
    AccidentOut,
    AccidentUpsert,
    CaseCreate,
    CaseOut,
    CaseSummaryOut,
    CaseUpdate,
    ClaimOut,
    ClaimUpsert,
    DemandSummaryOut,
    PartyCreate,
    PartyOut,
    PartyUpdate,
    SettlementTermsOut,
    SettlementTermsUpsert,
    ValidationCountsOut,
    VehicleOut,
)
from ...security.auth import CurrentUser, can_edit_case, can_read
from ..deps import get_case

router = APIRouter(tags=["cases"])


@router.post("/cases", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Case:
    if db.scalar(select(Case).where(Case.reference == payload.reference)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"case reference {payload.reference!r} is already in use",
        )
    case = Case(**payload.model_dump())
    db.add(case)
    db.flush()
    audit.record(db, event="CASE_CREATED", actor=user, case_id=case.id, payload=payload.model_dump())
    return case


@router.get("/cases", response_model=list[CaseOut])
def list_cases(
    db: Session = Depends(get_db), user: CurrentUser = Depends(can_read)
) -> list[Case]:
    return list(db.scalars(select(Case).order_by(Case.created_at.desc())))


@router.get("/case-summaries", response_model=list[CaseSummaryOut])
def list_case_summaries(
    db: Session = Depends(get_db), user: CurrentUser = Depends(can_read)
) -> list[CaseSummaryOut]:
    """Case list rows: claim metadata, latest demand, and validation health.

    Read-only projection over existing records — the counts come from the issues
    persisted by the last validation run, never recomputed here.
    """
    summaries: list[CaseSummaryOut] = []
    for case in db.scalars(select(Case).order_by(Case.updated_at.desc())):
        claim = db.scalar(select(Claim).where(Claim.case_id == case.id))
        demand = db.scalar(
            select(Demand)
            .where(Demand.case_id == case.id)
            .order_by(Demand.version.desc())
            .limit(1)
        )

        validation = None
        if demand is not None:
            last_run = db.scalar(
                select(AuditEvent)
                .where(
                    AuditEvent.demand_id == demand.id,
                    AuditEvent.event == "DEMAND_VALIDATED",
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(1)
            )
            if last_run is not None:
                issues = list(
                    db.scalars(
                        select(ValidationIssueRecord).where(
                            ValidationIssueRecord.demand_id == demand.id
                        )
                    )
                )
                validation = ValidationCountsOut(
                    blocking=sum(1 for i in issues if i.severity == Severity.BLOCKING),
                    warning=sum(1 for i in issues if i.severity == Severity.WARNING),
                    info=sum(1 for i in issues if i.severity == Severity.INFO),
                    last_validated_at=last_run.created_at,
                )

        updated_at = case.updated_at
        if demand is not None and demand.updated_at > updated_at:
            updated_at = demand.updated_at

        summaries.append(
            CaseSummaryOut(
                id=case.id,
                reference=case.reference,
                client_display_name=case.client_display_name,
                status=case.status,
                claim_number=claim.claim_number if claim else None,
                date_of_loss=claim.date_of_loss if claim else None,
                carrier_name=claim.carrier.name if claim and claim.carrier else None,
                demand=DemandSummaryOut.model_validate(demand) if demand else None,
                validation=validation,
                updated_at=updated_at,
            )
        )
    return summaries


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case_detail(case: Case = Depends(get_case), user: CurrentUser = Depends(can_read)) -> Case:
    return case


@router.patch("/cases/{case_id}", response_model=CaseOut)
def update_case(
    payload: CaseUpdate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Case:
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(case, field, value)
    audit.record(db, event="CASE_UPDATED", actor=user, case_id=case.id, payload=changes)
    return case


# --------------------------------------------------------------------------- parties


@router.post(
    "/cases/{case_id}/parties", response_model=PartyOut, status_code=status.HTTP_201_CREATED
)
def add_party(
    payload: PartyCreate,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Party:
    data = payload.model_dump(exclude={"roles"})
    party = Party(case_id=case.id, **data)
    db.add(party)
    db.flush()
    for role in payload.roles:
        db.add(
            PartyRoleAssignment(
                party_id=party.id, role=role.role, relationship_note=role.relationship_note
            )
        )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="duplicate role for this party"
        ) from exc
    audit.record(
        db,
        event="PARTY_ADDED",
        actor=user,
        case_id=case.id,
        subject_id=party.id,
        payload={"full_name": party.full_name, "roles": [r.role.value for r in payload.roles]},
    )
    db.refresh(party)
    return party


@router.get("/cases/{case_id}/parties", response_model=list[PartyOut])
def list_parties(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[Party]:
    return list(db.scalars(select(Party).where(Party.case_id == case.id)))


@router.patch("/parties/{party_id}", response_model=PartyOut)
def update_party(
    party_id: str,
    payload: PartyUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Party:
    party = db.get(Party, party_id)
    if party is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="party not found")

    changes = payload.model_dump(exclude_unset=True, exclude={"roles"})
    for field, value in changes.items():
        setattr(party, field, value)

    if payload.roles is not None:
        for assignment in list(party.role_assignments):
            db.delete(assignment)
        db.flush()
        for role in payload.roles:
            db.add(
                PartyRoleAssignment(
                    party_id=party.id, role=role.role, relationship_note=role.relationship_note
                )
            )
    db.flush()
    audit.record(
        db,
        event="PARTY_UPDATED",
        actor=user,
        case_id=party.case_id,
        subject_id=party.id,
        payload={
            **changes,
            "roles": [r.role.value for r in payload.roles] if payload.roles is not None else None,
        },
    )
    db.refresh(party)
    return party


# --------------------------------------------------------------------------- claim


@router.put("/cases/{case_id}/claim", response_model=ClaimOut)
def upsert_claim(
    payload: ClaimUpsert,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Claim:
    claim = db.scalar(select(Claim).where(Claim.case_id == case.id))
    if claim is None:
        claim = Claim(case_id=case.id, claim_number=payload.claim_number, date_of_loss=payload.date_of_loss)
        db.add(claim)
        db.flush()

    claim.claim_number = payload.claim_number
    claim.date_of_loss = payload.date_of_loss
    claim.policy_number = payload.policy_number
    claim.policy_limit = payload.policy_limit
    claim.policy_limit_confirmed = payload.policy_limit_confirmed

    if payload.carrier is not None:
        carrier = db.get(Carrier, claim.carrier_id) if claim.carrier_id else None
        if carrier is None:
            carrier = Carrier(case_id=case.id, name=payload.carrier.name)
            db.add(carrier)
            db.flush()
            claim.carrier_id = carrier.id
        for field, value in payload.carrier.model_dump().items():
            setattr(carrier, field, value)

    db.flush()
    audit.record(
        db,
        event="CLAIM_UPSERTED",
        actor=user,
        case_id=case.id,
        subject_id=claim.id,
        payload={"claim_number": claim.claim_number, "date_of_loss": claim.date_of_loss.isoformat()},
    )
    db.refresh(claim)
    return claim


@router.get("/cases/{case_id}/claim", response_model=ClaimOut)
def get_claim(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> Claim:
    claim = db.scalar(select(Claim).where(Claim.case_id == case.id))
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no claim on file")
    return claim


# --------------------------------------------------------------------------- accident


@router.put("/cases/{case_id}/accident", response_model=AccidentOut)
def upsert_accident(
    payload: AccidentUpsert,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Accident:
    accident = db.scalar(select(Accident).where(Accident.case_id == case.id))
    if accident is None:
        accident = Accident(case_id=case.id, occurred_on=payload.occurred_on)
        db.add(accident)
        db.flush()
    for field, value in payload.model_dump().items():
        setattr(accident, field, value)
    db.flush()
    audit.record(
        db,
        event="ACCIDENT_UPSERTED",
        actor=user,
        case_id=case.id,
        subject_id=accident.id,
        payload={"occurred_on": accident.occurred_on.isoformat()},
    )
    return accident


@router.get("/cases/{case_id}/accident", response_model=AccidentOut)
def get_accident(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> Accident:
    accident = db.scalar(select(Accident).where(Accident.case_id == case.id))
    if accident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no accident record on file"
        )
    return accident


@router.get("/cases/{case_id}/vehicles", response_model=list[VehicleOut])
def list_vehicles(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[Vehicle]:
    return list(db.scalars(select(Vehicle).where(Vehicle.case_id == case.id)))


# --------------------------------------------------------------------- settlement terms


@router.put("/cases/{case_id}/settlement-terms", response_model=SettlementTermsOut)
def upsert_settlement_terms(
    payload: SettlementTermsUpsert,
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> SettlementTerms:
    terms = db.scalar(select(SettlementTerms).where(SettlementTerms.case_id == case.id))
    if terms is None:
        terms = SettlementTerms(case_id=case.id, expires_at=payload.expires_at)
        db.add(terms)
        db.flush()
    for field, value in payload.model_dump().items():
        setattr(terms, field, value)
    db.flush()
    audit.record(
        db,
        event="SETTLEMENT_TERMS_UPSERTED",
        actor=user,
        case_id=case.id,
        subject_id=terms.id,
        payload={"expires_at": terms.expires_at.isoformat()},
    )
    return terms


@router.get("/cases/{case_id}/settlement-terms", response_model=SettlementTermsOut)
def get_settlement_terms(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> SettlementTerms:
    terms = db.scalar(select(SettlementTerms).where(SettlementTerms.case_id == case.id))
    if terms is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no settlement terms on file"
        )
    return terms
