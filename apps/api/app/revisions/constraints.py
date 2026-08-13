"""What an AI revision is allowed to change, checked deterministically.

An attorney asking for "stronger, without changing any facts" is stating a
constraint, and a constraint that is only expressed in a prompt is a wish. Each
one here is enforced by comparing the proposed text against the text it
replaces, using the same literal extractors the narrative guard already uses.

The checks run before an attorney ever sees the diff, so a proposal that
violates its own constraints is presented as invalid rather than as an option.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from ..validation import text_guard


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RevisionConstraint:
    """The envelope a revision must stay inside."""

    preserve_facts: bool = True
    preserve_amounts: bool = True
    preserve_dates: bool = True
    allow_new_facts: bool = False
    #: Substrings that must survive verbatim (a claim number, a deadline).
    preserve_literals: tuple[str, ...] = ()
    max_growth_ratio: float = 2.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["preserve_literals"] = list(self.preserve_literals)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RevisionConstraint:
        payload = dict(data or {})
        payload["preserve_literals"] = tuple(payload.get("preserve_literals") or ())
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in payload.items() if k in known})


@dataclass(frozen=True)
class ConstraintViolation:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


REVISION_STALE = "REVISION_001"
REVISION_AMOUNT_CHANGED = "REVISION_002"
REVISION_DATE_CHANGED = "REVISION_003"
REVISION_NEW_ENTITY = "REVISION_004"
REVISION_LITERAL_DROPPED = "REVISION_005"
REVISION_RUNAWAY_LENGTH = "REVISION_006"
REVISION_EMPTY = "REVISION_007"


def check(
    before: str, after: str, constraint: RevisionConstraint
) -> list[ConstraintViolation]:
    """Every way ``after`` breaks the envelope it was supposed to stay inside."""
    violations: list[ConstraintViolation] = []

    if not after.strip():
        violations.append(
            ConstraintViolation(
                code=REVISION_EMPTY,
                message="The proposed text is empty; a revision cannot delete a section.",
            )
        )
        return violations

    if constraint.preserve_amounts:
        before_amounts = text_guard.extract_amounts(before)
        after_amounts = text_guard.extract_amounts(after)
        added = sorted(after_amounts - before_amounts)
        removed = sorted(before_amounts - after_amounts)
        if added or removed:
            violations.append(
                ConstraintViolation(
                    code=REVISION_AMOUNT_CHANGED,
                    message=(
                        "The revision changes the monetary figures in this section. "
                        "Amounts come from the calculator, not from a rewrite."
                    ),
                    details={
                        "added": [str(a) for a in added],
                        "removed": [str(a) for a in removed],
                    },
                )
            )

    if constraint.preserve_dates:
        before_dates = text_guard.extract_dates(before)
        after_dates = text_guard.extract_dates(after)
        added_dates = sorted(after_dates - before_dates)
        removed_dates = sorted(before_dates - after_dates)
        if added_dates or removed_dates:
            violations.append(
                ConstraintViolation(
                    code=REVISION_DATE_CHANGED,
                    message="The revision changes the dates stated in this section.",
                    details={
                        "added": [d.isoformat() for d in added_dates],
                        "removed": [d.isoformat() for d in removed_dates],
                    },
                )
            )

    if constraint.preserve_facts and not constraint.allow_new_facts:
        before_names = text_guard.extract_name_candidates(before)
        new_names = sorted(text_guard.extract_name_candidates(after) - before_names)
        if new_names:
            violations.append(
                ConstraintViolation(
                    code=REVISION_NEW_ENTITY,
                    message=(
                        "The revision names entities the original section did not: "
                        + ", ".join(new_names)
                    ),
                    details={"names": new_names},
                )
            )

    for literal in constraint.preserve_literals:
        if literal and literal in before and literal not in after:
            violations.append(
                ConstraintViolation(
                    code=REVISION_LITERAL_DROPPED,
                    message=f"The revision drops required text: {literal!r}.",
                    details={"literal": literal},
                )
            )

    if before.strip() and len(after) > len(before) * constraint.max_growth_ratio:
        violations.append(
            ConstraintViolation(
                code=REVISION_RUNAWAY_LENGTH,
                message=(
                    f"The revision is {len(after) / max(len(before), 1):.1f}x the length of the "
                    "original; a rewrite that long is adding content, not sharpening it."
                ),
                details={"before_chars": len(before), "after_chars": len(after)},
            )
        )

    return violations


def check_freshness(current_body: str, before_hash: str) -> ConstraintViolation | None:
    """Refuse to apply a patch written against text that has since changed."""
    if text_hash(current_body) == before_hash:
        return None
    return ConstraintViolation(
        code=REVISION_STALE,
        message=(
            "The section has changed since this revision was proposed. "
            "Regenerate the proposal against the current text."
        ),
        details={"expected_hash": before_hash, "actual_hash": text_hash(current_body)},
    )


def summarize(violations: Sequence[ConstraintViolation]) -> dict[str, Any]:
    return {
        "valid": not violations,
        "violations": [v.to_dict() for v in violations],
    }
