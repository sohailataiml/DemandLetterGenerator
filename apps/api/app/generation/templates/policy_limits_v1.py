"""Time-limited policy limits demand — template v1.

Everything a mistake would be expensive in — claim metadata, deadlines, totals,
conditions of acceptance — is rendered deterministically from structured data.
The model only ever fills narrative slots, and even those are re-checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...config import get_settings
from ...domain.enums import DocumentType, SectionSource
from ...domain.money import format_money
from ..context import DemandContext, format_date, format_datetime

TEMPLATE_VERSION = "policy_limits_v1"

# (key, title, source) — position is the index in this list.
SECTION_ORDER: list[tuple[str, str, SectionSource]] = [
    ("header", "Letterhead", SectionSource.TEMPLATE),
    ("claim_metadata", "Claim Information", SectionSource.TEMPLATE),
    ("demand_title", "Time-Limited Policy Limits Demand", SectionSource.TEMPLATE),
    ("introduction", "Introduction", SectionSource.TEMPLATE),
    ("liability", "Liability", SectionSource.AI),
    ("photographs", "Accident Photographs", SectionSource.TEMPLATE),
    ("damages", "Damages", SectionSource.TEMPLATE),
    ("medical_summary", "Medical History and Treatment", SectionSource.AI),
    ("imaging_summary", "Diagnostic Imaging Findings", SectionSource.AI),
    ("future_medical", "Future Medical Care", SectionSource.TEMPLATE),
    ("medical_expense_summary", "Medical Expense Summary", SectionSource.TEMPLATE),
    ("pain_and_suffering", "Pain, Suffering, and Inconvenience", SectionSource.AI),
    ("demand_for_settlement", "Demand for Settlement", SectionSource.TEMPLATE),
    ("conditions", "Conditions of Acceptance", SectionSource.TEMPLATE),
    ("signature", "Signature", SectionSource.TEMPLATE),
]

DEFAULT_CONDITIONS = [
    "Payment of the full policy limits within the time stated above.",
    "A certified copy of the declarations page confirming all applicable coverage.",
    "A sworn statement from the adjuster confirming no additional applicable coverage exists.",
    "Confirmation that no liens or subrogation interests are being asserted by your insured.",
    "This demand is for the claim referenced above only and releases no other party.",
]


@dataclass
class SectionDraft:
    key: str
    title: str
    position: int
    body: str
    source: SectionSource
    used_fact_ids: list[str] = field(default_factory=list)


def render(ctx: DemandContext, narratives: dict) -> list[SectionDraft]:
    """Render every section. ``narratives`` maps section key → NarrativeResult."""
    drafts: list[SectionDraft] = []
    for position, (key, title, source) in enumerate(SECTION_ORDER):
        if source == SectionSource.AI:
            result = narratives.get(key)
            if result is None:
                body = f"[Not generated: no draft was produced for the {key} section.]"
                used: list[str] = []
            elif result.insufficient_evidence or not result.text.strip():
                body = (
                    "[Drafting could not be completed — insufficient verified evidence. "
                    f"{result.missing or 'No supporting facts are on file.'}]"
                )
                used = []
            else:
                body = result.text.strip()
                used = list(result.used_fact_ids)
            drafts.append(
                SectionDraft(
                    key=key,
                    title=title,
                    position=position,
                    body=body,
                    source=SectionSource.AI,
                    used_fact_ids=used,
                )
            )
            continue

        renderer = _TEMPLATE_RENDERERS[key]
        drafts.append(
            SectionDraft(
                key=key,
                title=title,
                position=position,
                body=renderer(ctx).strip(),
                source=SectionSource.TEMPLATE,
            )
        )
    return drafts


# --------------------------------------------------------------------------- blocks


def _header(ctx: DemandContext) -> str:
    settings = get_settings()
    lines = [settings.firm_name, *settings.firm_address_lines]
    if settings.firm_phone:
        lines.append(f"Tel: {settings.firm_phone}")
    if settings.firm_email:
        lines.append(settings.firm_email)
    lines.append("")
    lines.append(format_date(ctx.letter_date))
    lines.append("")

    carrier = ctx.claim.carrier if ctx.claim else None
    if carrier:
        if carrier.adjuster_name:
            lines.append(carrier.adjuster_name)
        lines.append(carrier.name)
        if carrier.address:
            lines.extend(carrier.address.splitlines())
    delivery = ctx.settlement.delivery_method if ctx.settlement else "email"
    lines.append("")
    lines.append(f"Via {delivery}")
    return "\n".join(lines)


def _claim_metadata(ctx: DemandContext) -> str:
    rows = [("Our Client", ctx.client_name)]
    if ctx.claim:
        rows.append(("Claim Number", ctx.claim.claim_number))
    if ctx.insured:
        rows.append(("Your Insured", ctx.insured.full_name))
    if ctx.driver and (not ctx.insured or ctx.driver.full_name != ctx.insured.full_name):
        rows.append(("Driver", ctx.driver.full_name))
    if ctx.claim:
        rows.append(("Date of Loss", format_date(ctx.claim.date_of_loss)))
    if ctx.claim and ctx.claim.policy_number:
        rows.append(("Policy Number", ctx.claim.policy_number))
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label.ljust(width)} : {value}" for label, value in rows)


def _demand_title(ctx: DemandContext) -> str:
    if ctx.settlement is None:
        return (
            "TIME-LIMITED POLICY LIMITS DEMAND\n"
            "[No settlement terms are on file; expiration cannot be stated.]"
        )
    return (
        "TIME-LIMITED POLICY LIMITS DEMAND\n"
        f"This offer expires on {format_datetime(ctx.settlement.expires_at)}."
    )


def _introduction(ctx: DemandContext) -> str:
    carrier_name = ctx.claim.carrier.name if ctx.claim and ctx.claim.carrier else "your company"
    insured_clause = f" your insured, {ctx.insured.full_name}," if ctx.insured else " your insured"
    loss_date = format_date(ctx.claim.date_of_loss) if ctx.claim else "the date of loss"
    return (
        f"This firm represents {ctx.client_name} for injuries sustained in the collision of "
        f"{loss_date} involving{insured_clause} for which {carrier_name} provides coverage. "
        "This letter sets out the liability and damages evidence supporting a demand for the "
        "applicable policy limits, and the conditions on which that demand may be accepted."
    )


def _photographs(ctx: DemandContext) -> str:
    photos = ctx.documents_of_type(DocumentType.PHOTOGRAPH)
    if not photos:
        return "No photographs are enclosed with this demand."
    lines = ["The following photographs are enclosed and are part of this demand:"]
    for index, photo in enumerate(photos, start=1):
        taken = f" ({format_date(photo.document_date)})" if photo.document_date else ""
        lines.append(f"  {index}. {photo.original_filename}{taken}")
    return "\n".join(lines)


def _damages(ctx: DemandContext) -> str:
    diagnosis_count = len(ctx.diagnoses)
    provider_count = len({p.id for p in ctx.providers})
    parts = [
        f"{ctx.client_name} was treated by {provider_count} "
        f"provider{'s' if provider_count != 1 else ''} following the collision."
    ]
    if diagnosis_count:
        parts.append(
            f"{diagnosis_count} diagnos{'es are' if diagnosis_count != 1 else 'is is'} "
            "documented in the enclosed records."
        )
    parts.append(
        "The treatment history, imaging findings, future care, and expenses are set out below."
    )
    return " ".join(parts)


def _future_medical(ctx: DemandContext) -> str:
    if not ctx.future_treatments:
        return "No future medical care has been recommended in the records on file."
    lines = ["The following future care is recommended in the records on file:"]
    for treatment in ctx.future_treatments:
        provider = f" — {treatment.provider_name}" if treatment.provider_name else ""
        quantity = f" (x{treatment.quantity})" if treatment.quantity and treatment.quantity > 1 else ""
        if treatment.cost_low is not None and treatment.cost_high is not None and treatment.cost_low != treatment.cost_high:
            cost = f"{format_money(treatment.cost_low)}–{format_money(treatment.cost_high)}"
        elif treatment.cost_low is not None:
            cost = format_money(treatment.cost_low)
        elif treatment.cost_high is not None:
            cost = format_money(treatment.cost_high)
        else:
            cost = "estimate pending"
        lines.append(f"  • {treatment.description}{provider}{quantity}: {cost}")
    low, high = ctx.damages.future_medical_low, ctx.damages.future_medical_high
    if low == high:
        lines.append(f"Estimated future medical expenses: {format_money(low)}")
    else:
        lines.append(
            f"Estimated future medical expenses: {format_money(low)} to {format_money(high)}"
        )
    return "\n".join(lines)


def _medical_expense_summary(ctx: DemandContext) -> str:
    damages = ctx.damages
    lines = ["Medical expenses incurred to date:"]
    for item in damages.line_items:
        if item["kind"] != "medical_bill":
            continue
        amount = item.get("amount")
        status = item.get("status")
        if amount is None:
            rendered = "amount pending"
        else:
            rendered = format_money(amount)
            if status == "ESTIMATED":
                rendered += " (estimated)"
        description = f" — {item['description']}" if item.get("description") else ""
        lines.append(f"  {item['provider_name']}{description}: {rendered}")

    lines.append("")
    lines.append(
        f"Total known medical expenses to date: "
        f"{format_money(damages.current_medical_expenses)}"
    )
    if damages.estimated_bill_total > 0:
        lines.append(f"Estimated charges not yet finalized: {format_money(damages.estimated_bill_total)}")
    if damages.pending_bills:
        lines.append("")
        lines.append(
            "The following charges are still outstanding and are NOT included in the total "
            "above; the total will increase once they are received:"
        )
        for pending in damages.pending_bills:
            detail = f" — {pending.description}" if pending.description else ""
            lines.append(f"  {pending.provider_name}{detail}: amount pending")
    return "\n".join(lines)


def _demand_for_settlement(ctx: DemandContext) -> str:
    damages = ctx.damages
    lines = []
    if damages.known_claimed_damages_low == damages.known_claimed_damages_high:
        lines.append(
            f"Known claimed damages total {format_money(damages.known_claimed_damages_low)}."
        )
    else:
        lines.append(
            f"Known claimed damages total between "
            f"{format_money(damages.known_claimed_damages_low)} and "
            f"{format_money(damages.known_claimed_damages_high)}."
        )
    if damages.pending_bills:
        lines.append(
            "This figure excludes charges still outstanding and is therefore a floor, not a cap."
        )

    settlement = ctx.settlement
    if settlement is None:
        lines.append("[No settlement terms are on file; no demand amount can be stated.]")
        return "\n".join(lines)

    if settlement.demand_is_policy_limits:
        limit = ctx.claim.policy_limit if ctx.claim else None
        if limit is not None:
            lines.append(
                f"Demand is hereby made for the applicable policy limits of {format_money(limit)}."
            )
        else:
            lines.append(
                "Demand is hereby made for the applicable policy limits. "
                "[Policy limit not confirmed in the file.]"
            )
    elif settlement.demand_amount is not None:
        lines.append(f"Demand is hereby made in the amount of {format_money(settlement.demand_amount)}.")
    else:
        lines.append("[No demand amount is recorded.]")

    lines.append(
        f"This demand expires on {format_datetime(settlement.expires_at)}, "
        "after which it is withdrawn without further notice."
    )
    return "\n".join(lines)


def _conditions(ctx: DemandContext) -> str:
    conditions = list(ctx.settlement.conditions) if ctx.settlement and ctx.settlement.conditions else list(DEFAULT_CONDITIONS)
    lines = ["Acceptance of this demand is conditioned on each of the following:"]
    for index, condition in enumerate(conditions, start=1):
        lines.append(f"  {index}. {condition}")
    return "\n".join(lines)


def _signature(ctx: DemandContext) -> str:
    settings = get_settings()
    attorney = ctx.signing_attorney
    lines = ["Very truly yours,", ""]
    lines.append(attorney.full_name if attorney else "[Attorney of record not assigned]")
    lines.append(settings.firm_name)
    if attorney and attorney.email:
        lines.append(attorney.email)
    return "\n".join(lines)


_TEMPLATE_RENDERERS = {
    "header": _header,
    "claim_metadata": _claim_metadata,
    "demand_title": _demand_title,
    "introduction": _introduction,
    "photographs": _photographs,
    "damages": _damages,
    "future_medical": _future_medical,
    "medical_expense_summary": _medical_expense_summary,
    "demand_for_settlement": _demand_for_settlement,
    "conditions": _conditions,
    "signature": _signature,
}
