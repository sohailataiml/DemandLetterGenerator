"""The catalog of slot names a template may use, and how each one is resolved.

Every resolver reads structured case data or an already-validated section body.
None of them call a model, and none of them do arithmetic — money comes from
:mod:`app.damages.calculator` and dates come from the records. That is what
keeps INVARIANT-003 true no matter what a template asks for.

A value that has no case data behind it resolves to :data:`MISSING_MARKER`
rather than an empty string, so a gap is visible in the draft and is picked up
by ``TEMPLATE_009`` instead of quietly printing nothing where a figure belongs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Mapping, Sequence

from ..domain.enums import DamageCategory
from ..domain.money import format_money
from ..generation.context import DemandContext, format_date, format_datetime

MISSING_MARKER = "[not on file]"

#: Template slot name -> the demand section key whose body fills it.
SECTION_SLOTS: dict[str, str] = {
    "header_block": "header",
    "claim_metadata_block": "claim_metadata",
    "demand_title_section": "demand_title",
    "introduction_section": "introduction",
    "liability_section": "liability",
    "photographs_section": "photographs",
    "damages_section": "damages",
    "medical_treatment_section": "medical_summary",
    "imaging_section": "imaging_summary",
    "future_medical_section": "future_medical",
    "medical_expense_summary_section": "medical_expense_summary",
    "pain_and_suffering_section": "pain_and_suffering",
    "demand_section": "demand_for_settlement",
    "conditions_section": "conditions",
    "signature_block": "signature",
}

#: Escape hatch: ``{{section__<key>}}`` binds any demand section by its key.
SECTION_PREFIX = "section__"


@dataclass(frozen=True)
class SlotContext:
    """Everything a resolver may read. Deliberately narrow."""

    demand: DemandContext
    sections: Mapping[str, str]

    def section_body(self, key: str) -> list[str]:
        body = self.sections.get(key)
        if body is None:
            return [MISSING_MARKER]
        paragraphs = [part.strip() for part in body.split("\n\n") if part.strip()]
        return paragraphs or [""]


Resolver = Callable[[SlotContext], object]


def _text(value: str | None) -> str:
    return value if value else MISSING_MARKER


# --------------------------------------------------------------------------- inline


def _client_name(ctx: SlotContext) -> str:
    return _text(ctx.demand.client_name)


def _insured_name(ctx: SlotContext) -> str:
    insured = ctx.demand.insured
    return _text(insured.full_name if insured else None)


def _driver_name(ctx: SlotContext) -> str:
    driver = ctx.demand.driver
    return _text(driver.full_name if driver else None)


def _attorney_name(ctx: SlotContext) -> str:
    attorney = ctx.demand.signing_attorney
    return _text(attorney.full_name if attorney else None)


def _adjuster_name(ctx: SlotContext) -> str:
    claim = ctx.demand.claim
    carrier = claim.carrier if claim else None
    return _text(carrier.adjuster_name if carrier else None)


def _carrier_name(ctx: SlotContext) -> str:
    claim = ctx.demand.claim
    carrier = claim.carrier if claim else None
    return _text(carrier.name if carrier else None)


def _claim_number(ctx: SlotContext) -> str:
    return _text(ctx.demand.claim.claim_number if ctx.demand.claim else None)


def _policy_number(ctx: SlotContext) -> str:
    claim = ctx.demand.claim
    return _text(claim.policy_number if claim else None)


def _policy_limit(ctx: SlotContext) -> str:
    claim = ctx.demand.claim
    if claim is None or claim.policy_limit is None:
        return MISSING_MARKER
    return format_money(claim.policy_limit)


def _letter_date(ctx: SlotContext) -> str:
    return format_date(ctx.demand.letter_date)


def _incident_date(ctx: SlotContext) -> str:
    accident = ctx.demand.accident
    if accident:
        return format_date(accident.occurred_on)
    claim = ctx.demand.claim
    return format_date(claim.date_of_loss) if claim else MISSING_MARKER


def _incident_location(ctx: SlotContext) -> str:
    accident = ctx.demand.accident
    return _text(accident.location if accident else None)


def _demand_expiration(ctx: SlotContext) -> str:
    settlement = ctx.demand.settlement
    return format_datetime(settlement.expires_at) if settlement else MISSING_MARKER


def _demand_amount(ctx: SlotContext) -> str:
    """The authoritative demand figure. Never computed by a model."""
    settlement = ctx.demand.settlement
    if settlement is None:
        return MISSING_MARKER
    if settlement.demand_is_policy_limits:
        claim = ctx.demand.claim
        if claim is None or claim.policy_limit is None:
            return MISSING_MARKER
        return format_money(claim.policy_limit)
    if settlement.demand_amount is None:
        return MISSING_MARKER
    return format_money(settlement.demand_amount)


def _medical_expenses_total(ctx: SlotContext) -> str:
    return format_money(ctx.demand.damages.current_medical_expenses)


def _future_medical_low(ctx: SlotContext) -> str:
    return format_money(ctx.demand.damages.future_medical_low)


def _future_medical_high(ctx: SlotContext) -> str:
    return format_money(ctx.demand.damages.future_medical_high)


def _lost_wages(ctx: SlotContext) -> str:
    total = sum(
        (
            claim.amount
            for claim in ctx.demand.damage_claims
            if claim.category == DamageCategory.LOST_WAGES and claim.amount is not None
        ),
        start=Decimal("0.00"),
    )
    return format_money(total)


def _known_damages_low(ctx: SlotContext) -> str:
    return format_money(ctx.demand.damages.known_claimed_damages_low)


def _known_damages_high(ctx: SlotContext) -> str:
    return format_money(ctx.demand.damages.known_claimed_damages_high)


def _firm_name(ctx: SlotContext) -> str:
    from ..config import get_settings

    return get_settings().firm_name


INLINE_RESOLVERS: dict[str, Resolver] = {
    "client_name": _client_name,
    "insured_name": _insured_name,
    "driver_name": _driver_name,
    "attorney_name": _attorney_name,
    "adjuster_name": _adjuster_name,
    "carrier_name": _carrier_name,
    "claim_number": _claim_number,
    "policy_number": _policy_number,
    "policy_limit": _policy_limit,
    "letter_date": _letter_date,
    "incident_date": _incident_date,
    "date_of_loss": _incident_date,
    "incident_location": _incident_location,
    "demand_expiration": _demand_expiration,
    "demand_amount": _demand_amount,
    "medical_expenses_total": _medical_expenses_total,
    "future_medical_low": _future_medical_low,
    "future_medical_high": _future_medical_high,
    "lost_wages": _lost_wages,
    "known_damages_low": _known_damages_low,
    "known_damages_high": _known_damages_high,
    "firm_name": _firm_name,
}


# ------------------------------------------------------------------------- rows


def _medical_expenses_rows(ctx: SlotContext) -> list[dict[str, str]]:
    """One row per bill. A pending bill reads 'Pending', never $0.00."""
    rows: list[dict[str, str]] = []
    for item in ctx.demand.damages.line_items:
        if item.get("kind") != "medical_bill":
            continue
        amount = item.get("amount")
        if amount is None:
            rendered = "Pending"
        else:
            rendered = format_money(amount)
            if item.get("status") == "ESTIMATED":
                rendered += " (estimated)"
        rows.append(
            {
                "provider": str(item.get("provider_name") or ""),
                "description": str(item.get("description") or ""),
                "date": str(item.get("billed_on") or ""),
                "amount": rendered,
                "status": str(item.get("status") or ""),
            }
        )
    return rows


def _future_treatment_rows(ctx: SlotContext) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for treatment in ctx.demand.future_treatments:
        if treatment.cost_low is not None and treatment.cost_high is not None:
            if treatment.cost_low == treatment.cost_high:
                cost = format_money(treatment.cost_low)
            else:
                cost = f"{format_money(treatment.cost_low)}-{format_money(treatment.cost_high)}"
        elif treatment.cost_low is not None:
            cost = format_money(treatment.cost_low)
        elif treatment.cost_high is not None:
            cost = format_money(treatment.cost_high)
        else:
            cost = "Estimate pending"
        rows.append(
            {
                "description": treatment.description,
                "provider": treatment.provider_name or "",
                "quantity": str(treatment.quantity),
                "cost": cost,
            }
        )
    return rows


def _treatment_rows(ctx: SlotContext) -> list[dict[str, str]]:
    return [
        {
            "date": format_date(entry.entry_date),
            "provider": entry.provider or "",
            "description": entry.title,
            "detail": entry.detail or "",
        }
        for entry in ctx.demand.timeline
    ]


ROW_RESOLVERS: dict[str, Resolver] = {
    "medical_expenses": _medical_expenses_rows,
    "future_treatments": _future_treatment_rows,
    "treatments": _treatment_rows,
}


# --------------------------------------------------------------------------- api


class UnknownSlotError(ValueError):
    """The template asks for a slot this system has no resolver for."""

    def __init__(self, names: Sequence[str]) -> None:
        self.names = sorted(set(names))
        super().__init__(
            "template uses slots with no resolver: "
            + ", ".join(self.names)
            + ". Add a resolver in app/templates/slots.py or correct the template."
        )


def known_slot_names() -> tuple[str, ...]:
    return tuple(
        sorted({*INLINE_RESOLVERS, *ROW_RESOLVERS, *SECTION_SLOTS})
    )


def resolve(slot_name: str, ctx: SlotContext) -> object | None:
    """Resolve one slot, or ``None`` if the name is not in the catalog."""
    if slot_name in ROW_RESOLVERS:
        return ROW_RESOLVERS[slot_name](ctx)
    if slot_name in INLINE_RESOLVERS:
        return INLINE_RESOLVERS[slot_name](ctx)
    if slot_name in SECTION_SLOTS:
        return ctx.section_body(SECTION_SLOTS[slot_name])
    if slot_name.startswith(SECTION_PREFIX):
        return ctx.section_body(slot_name[len(SECTION_PREFIX):])
    return None


def build_values(
    slot_names: Sequence[str], context: DemandContext, sections: Mapping[str, str]
) -> tuple[dict[str, object], list[str]]:
    """Resolve every slot the template declares.

    Returns ``(values, unresolved)`` where ``unresolved`` names the slots whose
    value came back as :data:`MISSING_MARKER` — the case simply has no data for
    them yet. A slot name with no resolver at all raises instead; that is a
    template authoring error, not a data gap.
    """
    ctx = SlotContext(demand=context, sections=sections)
    values: dict[str, object] = {}
    unknown: list[str] = []
    unresolved: list[str] = []

    for name in dict.fromkeys(slot_names):
        # ``collection[].field`` slots are registered under the collection name.
        lookup = name.split("[].", 1)[0]
        value = resolve(lookup, ctx)
        if value is None:
            unknown.append(name)
            continue
        if value == MISSING_MARKER or value == [MISSING_MARKER]:
            unresolved.append(name)
        values[name] = value

    if unknown:
        raise UnknownSlotError(unknown)
    return values, unresolved
