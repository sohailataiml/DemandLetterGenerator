"""Damages arithmetic: exactness, and pending bills never counted as zero."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.damages.calculator import summarize
from app.domain.enums import BillStatus, DamageCategory
from app.domain.models import DamageClaim, FutureTreatment, MedicalBill
from app.domain.money import MoneyError, to_money


def bill(provider: str, amount, status=BillStatus.KNOWN, bill_id="bill_x") -> MedicalBill:
    return MedicalBill(
        id=bill_id,
        case_id="case_1",
        provider_name=provider,
        amount=None if amount is None else to_money(amount),
        status=status,
        description=None,
    )


def test_floats_are_rejected_outright():
    with pytest.raises(MoneyError):
        to_money(6480.10)


def test_known_bills_sum_exactly():
    summary = summarize(
        [bill("A", "6480.00", bill_id="b1"), bill("B", "3500.55", bill_id="b2")], [], []
    )
    assert summary.current_medical_expenses == Decimal("9980.55")


def test_pending_bill_is_excluded_and_listed_not_zeroed():
    bills = [
        bill("Vermont Spine", "6480.00", bill_id="b1"),
        bill("Harbor Pain Management", None, BillStatus.PENDING, bill_id="b2"),
    ]
    summary = summarize(bills, [], [])

    assert summary.current_medical_expenses == Decimal("6480.00")
    assert [p.provider_name for p in summary.pending_bills] == ["Harbor Pain Management"]
    # The pending charge must not be quietly folded into the total as $0.
    assert summary.known_claimed_damages_low == Decimal("6480.00")


def test_estimated_bills_are_separated_from_incurred_charges():
    bills = [
        bill("A", "1000.00", bill_id="b1"),
        bill("B", "250.00", BillStatus.ESTIMATED, bill_id="b2"),
    ]
    summary = summarize(bills, [], [])

    assert summary.current_medical_expenses == Decimal("1000.00")
    assert summary.estimated_bill_total == Decimal("250.00")
    assert summary.known_claimed_damages_low == Decimal("1000.00")
    assert summary.known_claimed_damages_high == Decimal("1250.00")


def test_future_care_is_a_range_multiplied_by_quantity():
    future = [
        FutureTreatment(
            id="fut_1",
            case_id="case_1",
            description="Injection series",
            quantity=2,
            cost_low=to_money("4200.00"),
            cost_high=to_money("5600.00"),
        )
    ]
    summary = summarize([], future, [])

    assert summary.future_medical_low == Decimal("8400.00")
    assert summary.future_medical_high == Decimal("11200.00")


def test_claimed_total_combines_every_component():
    bills = [bill("A", "6480.00", bill_id="b1")]
    future = [
        FutureTreatment(
            id="fut_1",
            case_id="case_1",
            description="Injections",
            quantity=1,
            cost_low=to_money("4200.00"),
            cost_high=to_money("4200.00"),
        )
    ]
    claims = [
        DamageClaim(
            id="dmg_1",
            case_id="case_1",
            category=DamageCategory.GENERAL,
            description="General damages",
            amount=to_money("40000.00"),
        ),
        DamageClaim(
            id="dmg_2",
            case_id="case_1",
            category=DamageCategory.LOST_WAGES,
            description="Missed work",
            amount=to_money("3120.00"),
        ),
    ]
    summary = summarize(bills, future, claims)

    assert summary.general_damages == Decimal("40000.00")
    assert summary.other_damages == Decimal("3120.00")
    assert summary.known_claimed_damages_low == Decimal("53800.00")


def test_damage_claim_without_an_amount_contributes_nothing():
    claims = [
        DamageClaim(
            id="dmg_1",
            case_id="case_1",
            category=DamageCategory.OUT_OF_POCKET,
            description="Mileage, still being compiled",
            amount=None,
        )
    ]
    summary = summarize([], [], claims)
    assert summary.other_damages == Decimal("0.00")
