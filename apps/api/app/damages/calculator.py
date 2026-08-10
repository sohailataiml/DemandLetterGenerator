"""Deterministic damages arithmetic.

No language model ever computes a number that appears in a demand letter. This
module is the only source of monetary totals; generated prose is checked against
its output before a draft can be approved.

Two rules do most of the work:

* A bill with ``amount = None`` (status ``PENDING``) is **excluded** from the
  numeric total and listed separately. It is never counted as zero.
* Estimates are kept apart from incurred charges, and future care is expressed
  as a low/high range rather than a single invented figure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import BillStatus, DamageCategory
from ..domain.models import DamageClaim, FutureTreatment, MedicalBill
from ..domain.money import ZERO, money_sum, to_money


@dataclass(frozen=True)
class PendingBill:
    bill_id: str
    provider_name: str
    description: str | None = None


@dataclass(frozen=True)
class DamagesSummary:
    current_medical_expenses: Decimal
    pending_bills: list[PendingBill]
    estimated_bill_total: Decimal
    future_medical_low: Decimal
    future_medical_high: Decimal
    general_damages: Decimal
    other_damages: Decimal
    known_claimed_damages_low: Decimal
    known_claimed_damages_high: Decimal
    line_items: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_pending_bills(self) -> bool:
        return bool(self.pending_bills)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_medical_expenses": str(self.current_medical_expenses),
            "pending_bills": [
                {
                    "bill_id": b.bill_id,
                    "provider_name": b.provider_name,
                    "description": b.description,
                }
                for b in self.pending_bills
            ],
            "estimated_bill_total": str(self.estimated_bill_total),
            "future_medical_low": str(self.future_medical_low),
            "future_medical_high": str(self.future_medical_high),
            "general_damages": str(self.general_damages),
            "other_damages": str(self.other_damages),
            "known_claimed_damages_low": str(self.known_claimed_damages_low),
            "known_claimed_damages_high": str(self.known_claimed_damages_high),
            "line_items": self.line_items,
        }

    def all_amounts(self) -> list[Decimal]:
        """Every figure the letter is allowed to state, for output validation."""
        amounts = [
            self.current_medical_expenses,
            self.estimated_bill_total,
            self.future_medical_low,
            self.future_medical_high,
            self.general_damages,
            self.other_damages,
            self.known_claimed_damages_low,
            self.known_claimed_damages_high,
        ]
        for item in self.line_items:
            if item.get("amount") is not None:
                amounts.append(to_money(item["amount"]))
        return [a for a in amounts if a is not None]


def current_medical_expenses(bills: Iterable[MedicalBill]) -> Decimal:
    """Sum of *known* incurred charges. Pending and estimated bills excluded."""
    return money_sum(
        bill.amount
        for bill in bills
        if bill.status == BillStatus.KNOWN and bill.amount is not None
    )


def pending_bills(bills: Iterable[MedicalBill]) -> list[PendingBill]:
    return [
        PendingBill(
            bill_id=bill.id, provider_name=bill.provider_name, description=bill.description
        )
        for bill in bills
        if bill.amount is None or bill.status == BillStatus.PENDING
    ]


def estimated_bill_total(bills: Iterable[MedicalBill]) -> Decimal:
    return money_sum(
        bill.amount
        for bill in bills
        if bill.status == BillStatus.ESTIMATED and bill.amount is not None
    )


def future_medical_range(treatments: Iterable[FutureTreatment]) -> tuple[Decimal, Decimal]:
    low = ZERO
    high = ZERO
    for treatment in treatments:
        quantity = max(1, treatment.quantity or 1)
        item_low = treatment.cost_low if treatment.cost_low is not None else treatment.cost_high
        item_high = treatment.cost_high if treatment.cost_high is not None else treatment.cost_low
        if item_low is not None:
            low += to_money(item_low) * quantity
        if item_high is not None:
            high += to_money(item_high) * quantity
    return to_money(low), to_money(high)


def _category_total(claims: Iterable[DamageClaim], category: DamageCategory) -> Decimal:
    return money_sum(c.amount for c in claims if c.category == category and c.amount is not None)


def summarize(
    bills: Sequence[MedicalBill],
    future_treatments: Sequence[FutureTreatment],
    damage_claims: Sequence[DamageClaim],
) -> DamagesSummary:
    current = current_medical_expenses(bills)
    pending = pending_bills(bills)
    estimated = estimated_bill_total(bills)
    future_low, future_high = future_medical_range(future_treatments)
    general = _category_total(damage_claims, DamageCategory.GENERAL)
    other = money_sum(
        c.amount
        for c in damage_claims
        if c.category != DamageCategory.GENERAL and c.amount is not None
    )

    known_low = to_money(current + future_low + general + other)
    known_high = to_money(current + estimated + future_high + general + other)

    line_items: list[dict[str, Any]] = []
    for bill in bills:
        line_items.append(
            {
                "kind": "medical_bill",
                "id": bill.id,
                "provider_name": bill.provider_name,
                "description": bill.description,
                "status": str(bill.status),
                "amount": str(bill.amount) if bill.amount is not None else None,
            }
        )
    for treatment in future_treatments:
        line_items.append(
            {
                "kind": "future_treatment",
                "id": treatment.id,
                "description": treatment.description,
                "provider_name": treatment.provider_name,
                "quantity": treatment.quantity,
                "amount": str(treatment.cost_low) if treatment.cost_low is not None else None,
                "amount_high": str(treatment.cost_high) if treatment.cost_high is not None else None,
            }
        )
    for claim in damage_claims:
        line_items.append(
            {
                "kind": "damage_claim",
                "id": claim.id,
                "category": str(claim.category),
                "description": claim.description,
                "amount": str(claim.amount) if claim.amount is not None else None,
            }
        )

    return DamagesSummary(
        current_medical_expenses=current,
        pending_bills=pending,
        estimated_bill_total=estimated,
        future_medical_low=future_low,
        future_medical_high=future_high,
        general_damages=general,
        other_damages=other,
        known_claimed_damages_low=known_low,
        known_claimed_damages_high=known_high,
        line_items=line_items,
    )


def summarize_case(session: Session, case_id: str) -> DamagesSummary:
    bills = list(session.scalars(select(MedicalBill).where(MedicalBill.case_id == case_id)))
    future = list(
        session.scalars(select(FutureTreatment).where(FutureTreatment.case_id == case_id))
    )
    claims = list(session.scalars(select(DamageClaim).where(DamageClaim.case_id == case_id)))
    return summarize(bills, future, claims)
