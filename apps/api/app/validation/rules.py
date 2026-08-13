"""The rule set.

Each rule is small, named by code, and answers one question a reviewer would
otherwise have to answer by hand. Codes are stable so a saved issue can be
traced back to the rule that raised it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence

from ..domain.enums import BillStatus, FactStatus, PartyRole, SectionSource, Severity
from ..domain.money import to_money
from ..generation.context import DemandContext
from . import text_guard
from .engine import Issue, RenderedSection

AI_SECTION_KEYS = {"liability", "medical_summary", "imaging_summary", "pain_and_suffering"}
CITATION_REQUIRED_SECTIONS = {"medical_summary", "imaging_summary"}


def _section(sections: Sequence[RenderedSection], key: str) -> RenderedSection | None:
    return next((s for s in sections if s.key == key), None)


# --------------------------------------------------------------------------- dates


@dataclass(frozen=True)
class DemandExpirationAfterLetterDate:
    """DATE_001 — a demand cannot expire before the letter that makes it."""

    code: str = "DATE_001"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        settlement = context.settlement
        if settlement is None:
            return [
                Issue(
                    code=self.code,
                    severity=Severity.BLOCKING,
                    message="No settlement terms are on file, so the demand has no expiration.",
                )
            ]
        expires_on = settlement.expires_at.date()
        if expires_on <= context.letter_date:
            return [
                Issue(
                    code=self.code,
                    severity=self.severity,
                    message=(
                        f"Demand expiration ({expires_on.isoformat()}) is not after the letter "
                        f"date ({context.letter_date.isoformat()})."
                    ),
                    section_key="demand_title",
                    details={
                        "expires_on": expires_on.isoformat(),
                        "letter_date": context.letter_date.isoformat(),
                    },
                )
            ]
        return []


@dataclass(frozen=True)
class TreatmentAfterLoss:
    """DATE_002 — treatment cannot predate the collision it is attributed to."""

    code: str = "DATE_002"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        loss_date = None
        if context.accident:
            loss_date = context.accident.occurred_on
        elif context.claim:
            loss_date = context.claim.date_of_loss
        if loss_date is None:
            return []
        issues = []
        for entry in context.timeline:
            if entry.kind == "collision":
                continue
            if entry.entry_date < loss_date:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=self.severity,
                        message=(
                            f"Timeline entry '{entry.title}' on {entry.entry_date.isoformat()} "
                            f"predates the date of loss ({loss_date.isoformat()})."
                        ),
                        details={"entry": entry.title, "entry_date": entry.entry_date.isoformat()},
                    )
                )
        return issues


@dataclass(frozen=True)
class TreatmentNotInFuture:
    """DATE_003 — a treatment date after today is a data-entry error."""

    code: str = "DATE_003"
    severity: Severity = Severity.WARNING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        today = datetime.now(timezone.utc).date()
        issues = []
        for entry in context.timeline:
            if entry.entry_date > today:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=self.severity,
                        message=(
                            f"Timeline entry '{entry.title}' is dated "
                            f"{entry.entry_date.isoformat()}, which is in the future."
                        ),
                        details={"entry_date": entry.entry_date.isoformat()},
                    )
                )
        return issues


@dataclass(frozen=True)
class LossDateAgreement:
    """DATE_004 — the accident record and the claim record must agree."""

    code: str = "DATE_004"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        if not (context.accident and context.claim):
            return []
        if context.accident.occurred_on != context.claim.date_of_loss:
            return [
                Issue(
                    code=self.code,
                    severity=self.severity,
                    message=(
                        f"Accident record date ({context.accident.occurred_on.isoformat()}) does "
                        f"not match the claim date of loss "
                        f"({context.claim.date_of_loss.isoformat()})."
                    ),
                    details={
                        "accident_date": context.accident.occurred_on.isoformat(),
                        "claim_date_of_loss": context.claim.date_of_loss.isoformat(),
                    },
                )
            ]
        return []


# --------------------------------------------------------------------------- parties


@dataclass(frozen=True)
class PartyRolesRecorded:
    """PARTY_001 — insured and driver are distinct roles and must both be recorded.

    A different driver from the named insured is common and legitimate; what is
    not acceptable is leaving the relationship undocumented.
    """

    code: str = "PARTY_001"
    severity: Severity = Severity.WARNING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        issues: list[Issue] = []
        if context.client is None:
            issues.append(
                Issue(
                    code=self.code,
                    severity=Severity.BLOCKING,
                    message="No party is recorded with the 'client' role.",
                )
            )
        insured, driver = context.insured, context.driver
        if insured is None:
            issues.append(
                Issue(
                    code=self.code,
                    severity=Severity.WARNING,
                    message="No party is recorded with the 'insured' role.",
                )
            )
        if insured and driver and insured.full_name != driver.full_name:
            documented = any(
                assignment.relationship_note
                for party in (insured, driver)
                for assignment in party.role_assignments
                if assignment.role in (PartyRole.INSURED.value, PartyRole.DRIVER.value)
            )
            if not documented:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=self.severity,
                        message=(
                            f"Named insured ({insured.full_name}) and driver "
                            f"({driver.full_name}) are different people, but no relationship "
                            "is recorded on either role."
                        ),
                        details={"insured": insured.full_name, "driver": driver.full_name},
                    )
                )
        if insured and driver is None:
            issues.append(
                Issue(
                    code=self.code,
                    severity=Severity.INFO,
                    message=(
                        "No separate driver is recorded; the letter will treat the named "
                        "insured as the driver."
                    ),
                )
            )
        return issues


# --------------------------------------------------------------------------- claim metadata

_CLAIM_NUMBER_RE = re.compile(r"claim\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Za-z0-9\-]{4,})", re.I)


@dataclass(frozen=True)
class ClaimNumberConsistent:
    """CLAIM_001 — the claim number must be identical everywhere it appears."""

    code: str = "CLAIM_001"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        if context.claim is None:
            return [
                Issue(
                    code=self.code,
                    severity=self.severity,
                    message="No claim record is on file; the letter cannot state a claim number.",
                )
            ]
        expected = context.claim.claim_number.strip()
        issues: list[Issue] = []
        seen_anywhere = False
        for section in sections:
            for match in _CLAIM_NUMBER_RE.finditer(section.body):
                seen_anywhere = True
                found = match.group(1).strip()
                if found != expected:
                    issues.append(
                        Issue(
                            code=self.code,
                            severity=self.severity,
                            message=(
                                f"Section '{section.key}' states claim number {found!r}, "
                                f"but the case record says {expected!r}."
                            ),
                            section_key=section.key,
                            details={"found": found, "expected": expected},
                        )
                    )
        if not seen_anywhere and sections:
            issues.append(
                Issue(
                    code=self.code,
                    severity=self.severity,
                    message="The letter never states the claim number.",
                    details={"expected": expected},
                )
            )
        return issues


# --------------------------------------------------------------------------- money

_TOTAL_RE = re.compile(
    r"total known medical expenses to date:\s*\$([\d,]+(?:\.\d{2})?)", re.I
)


@dataclass(frozen=True)
class DisplayedMedicalTotalMatches:
    """MONEY_001 — the printed total must equal the calculator's sum."""

    code: str = "MONEY_001"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        section = _section(sections, "medical_expense_summary")
        if section is None:
            return []
        match = _TOTAL_RE.search(section.body)
        if not match:
            return [
                Issue(
                    code=self.code,
                    severity=self.severity,
                    message="The medical expense summary does not state a total.",
                    section_key="medical_expense_summary",
                )
            ]
        displayed = to_money(match.group(1))
        expected = context.damages.current_medical_expenses
        if displayed != expected:
            return [
                Issue(
                    code=self.code,
                    severity=self.severity,
                    message=(
                        f"Displayed medical total ${displayed:,.2f} does not equal the sum of "
                        f"known bills (${expected:,.2f})."
                    ),
                    section_key="medical_expense_summary",
                    details={"displayed": str(displayed), "expected": str(expected)},
                )
            ]
        return []


@dataclass(frozen=True)
class PendingBillsDisclosed:
    """MONEY_002 — a pending bill is never silently counted as zero."""

    code: str = "MONEY_002"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        pending = context.damages.pending_bills
        if not pending:
            return []
        section = _section(sections, "medical_expense_summary")
        issues: list[Issue] = []
        body = section.body.lower() if section else ""
        for bill in pending:
            if bill.provider_name.lower() not in body:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=self.severity,
                        message=(
                            f"Bill from {bill.provider_name} has no amount on file and is not "
                            "disclosed as outstanding in the expense summary."
                        ),
                        section_key="medical_expense_summary",
                        details={"bill_id": bill.bill_id, "provider": bill.provider_name},
                    )
                )
        # Listing a provider is not disclosure. The letter has to say plainly
        # that the stated total is incomplete, or the reader will treat it as final.
        if section and not any(
            phrase in body for phrase in ("not included", "outstanding", "will increase")
        ):
            issues.append(
                Issue(
                    code=self.code,
                    severity=self.severity,
                    message=(
                        f"{len(pending)} bill(s) have no amount on file, but the expense summary "
                        "does not state that the total is incomplete."
                    ),
                    section_key="medical_expense_summary",
                )
            )
        return issues


@dataclass(frozen=True)
class PolicyLimitConfirmed:
    """MONEY_003 — a policy-limits demand rests on a confirmed limit."""

    code: str = "MONEY_003"
    severity: Severity = Severity.WARNING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        settlement = context.settlement
        if settlement is None or not settlement.demand_is_policy_limits:
            return []
        claim = context.claim
        if claim is None or claim.policy_limit is None:
            return [
                Issue(
                    code=self.code,
                    severity=self.severity,
                    message="Policy limits are demanded but no policy limit is recorded.",
                    section_key="demand_for_settlement",
                )
            ]
        if not claim.policy_limit_confirmed:
            return [
                Issue(
                    code=self.code,
                    severity=self.severity,
                    message=(
                        f"Policy limit of ${claim.policy_limit:,.2f} is recorded but not marked "
                        "confirmed against a declarations page."
                    ),
                    section_key="demand_for_settlement",
                )
            ]
        return []


# --------------------------------------------------------------------------- provenance


@dataclass(frozen=True)
class NarrativeFactsCited:
    """SOURCE_001 — generated medical assertions must map to verified facts."""

    code: str = "SOURCE_001"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        verified = context.verified_fact_ids()
        issues: list[Issue] = []
        for section in sections:
            # Template sections are rendered from structured data by definition;
            # everything else — model-drafted or human-edited — is checked.
            if section.source == SectionSource.TEMPLATE.value:
                continue
            body = section.body.strip()
            if not body or body.startswith("["):
                continue
            unknown = [fid for fid in section.used_fact_ids if fid not in verified]
            if unknown:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=self.severity,
                        message=(
                            f"Section '{section.key}' cites fact IDs that are not verified: "
                            f"{', '.join(unknown)}."
                        ),
                        section_key=section.key,
                        details={"unknown_fact_ids": unknown},
                    )
                )
            # Machine-drafted medical assertions must cite a fact. Attorney-authored
            # text is the attorney's own assertion and is not held to that.
            if (
                section.source == SectionSource.AI.value
                and section.key in CITATION_REQUIRED_SECTIONS
                and not section.used_fact_ids
            ):
                issues.append(
                    Issue(
                        code=self.code,
                        severity=self.severity,
                        message=(
                            f"Section '{section.key}' makes medical assertions but cites no "
                            "verified fact."
                        ),
                        section_key=section.key,
                    )
                )
        return issues


@dataclass(frozen=True)
class NarrativeStaysGrounded:
    """NARRATIVE_001 — no amount, date, or name in generated prose without support."""

    code: str = "NARRATIVE_001"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        allowed_amounts: set[Decimal] = context.allowed_amounts()
        allowed_dates: set[date] = context.allowed_dates()
        allowed_names: set[str] = context.allowed_names()
        issues: list[Issue] = []
        for section in sections:
            if section.source == SectionSource.TEMPLATE.value:
                continue
            body = section.body
            if not body.strip() or body.strip().startswith("["):
                continue

            bad_amounts = text_guard.unsupported_amounts(body, allowed_amounts)
            if bad_amounts:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=Severity.BLOCKING,
                        message=(
                            f"Section '{section.key}' states dollar amount(s) that appear nowhere "
                            f"in the case data: {', '.join(f'${a:,.2f}' for a in bad_amounts)}."
                        ),
                        section_key=section.key,
                        details={"amounts": [str(a) for a in bad_amounts]},
                    )
                )

            bad_dates = text_guard.unsupported_dates(body, allowed_dates)
            if bad_dates:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=Severity.BLOCKING,
                        message=(
                            f"Section '{section.key}' states date(s) that appear nowhere in the "
                            f"case data: {', '.join(d.isoformat() for d in bad_dates)}."
                        ),
                        section_key=section.key,
                        details={"dates": [d.isoformat() for d in bad_dates]},
                    )
                )

            impossible = text_guard.extract_impossible_dates(body)
            if impossible:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=Severity.BLOCKING,
                        message=(
                            f"Section '{section.key}' states date(s) that do not exist: "
                            f"{', '.join(impossible)}."
                        ),
                        section_key=section.key,
                        details={"impossible_dates": impossible},
                    )
                )

            bad_names = text_guard.unsupported_names(body, allowed_names)
            if bad_names:
                issues.append(
                    Issue(
                        code=self.code,
                        # Heuristic: a capitalized phrase is not proof of a proper
                        # noun, so this warns for review rather than blocking.
                        severity=Severity.WARNING,
                        message=(
                            f"Section '{section.key}' names entities not found in the case "
                            f"record: {', '.join(bad_names)}."
                        ),
                        section_key=section.key,
                        details={"names": bad_names},
                    )
                )
        return issues


@dataclass(frozen=True)
class NarrativeDrafted:
    """NARRATIVE_002 — an undraftable section blocks release rather than shipping empty."""

    code: str = "NARRATIVE_002"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        issues = []
        for section in sections:
            if section.source == SectionSource.TEMPLATE.value:
                continue
            body = section.body.strip()
            if not body or body.startswith("["):
                issues.append(
                    Issue(
                        code=self.code,
                        severity=self.severity,
                        message=(
                            f"Section '{section.key}' was not drafted: {body or 'empty section'}"
                        ),
                        section_key=section.key,
                    )
                )
        return issues


@dataclass(frozen=True)
class ExpirationConsistentEverywhere:
    """DOCUMENT_001 — every expiration reference in the letter must agree."""

    code: str = "DOCUMENT_001"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        if context.settlement is None:
            return []
        expected = context.settlement.expires_at.date()
        issues: list[Issue] = []
        for section in sections:
            for line in section.body.splitlines():
                if "expire" not in line.lower():
                    continue
                for found in sorted(text_guard.extract_dates(line)):
                    if found != expected:
                        issues.append(
                            Issue(
                                code=self.code,
                                severity=self.severity,
                                message=(
                                    f"Section '{section.key}' states an expiration of "
                                    f"{found.isoformat()}, but the demand expires "
                                    f"{expected.isoformat()}."
                                ),
                                section_key=section.key,
                                details={"found": found.isoformat(), "expected": expected.isoformat()},
                            )
                        )
        return issues


@dataclass(frozen=True)
class BillDataIntegrity:
    """MONEY_004 — bill records themselves must be internally coherent."""

    code: str = "MONEY_004"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        issues = []
        for item in context.damages.line_items:
            if item.get("kind") != "medical_bill":
                continue
            if item.get("status") == BillStatus.PENDING.value and item.get("amount") is not None:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=self.severity,
                        message=(
                            f"Bill {item['id']} is marked PENDING but carries an amount; "
                            "a pending charge must have no amount until it is received."
                        ),
                        details={"bill_id": item["id"]},
                    )
                )
        return issues


@dataclass(frozen=True)
class FactsSupersededCleanly:
    """SOURCE_002 — the letter must not rely on a superseded or rejected fact."""

    code: str = "SOURCE_002"
    severity: Severity = Severity.BLOCKING

    def evaluate(self, context: DemandContext, sections) -> list[Issue]:
        stale = {
            fact.id
            for fact in context.facts
            if fact.status != FactStatus.VERIFIED or fact.superseded_by_id
        }
        if not stale:
            return []
        issues = []
        for section in sections:
            used = set(section.used_fact_ids) & stale
            if used:
                issues.append(
                    Issue(
                        code=self.code,
                        severity=self.severity,
                        message=(
                            f"Section '{section.key}' relies on superseded or unverified facts: "
                            f"{', '.join(sorted(used))}."
                        ),
                        section_key=section.key,
                    )
                )
        return issues


ALL_RULES = [
    DemandExpirationAfterLetterDate(),
    TreatmentAfterLoss(),
    TreatmentNotInFuture(),
    LossDateAgreement(),
    PartyRolesRecorded(),
    ClaimNumberConsistent(),
    DisplayedMedicalTotalMatches(),
    PendingBillsDisclosed(),
    PolicyLimitConfirmed(),
    BillDataIntegrity(),
    NarrativeFactsCited(),
    NarrativeStaysGrounded(),
    NarrativeDrafted(),
    ExpirationConsistentEverywhere(),
    FactsSupersededCleanly(),
]
