"""Rule framework.

A rule sees the whole demand context plus the rendered sections and returns
issues. Severity is the gate: a demand carrying any ``BLOCKING`` issue cannot be
approved, no matter who is asking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from ..domain.enums import SEVERITY_ORDER, Severity
from ..generation.context import DemandContext


@dataclass(frozen=True)
class RenderedSection:
    key: str
    title: str
    body: str
    source: str
    used_fact_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    message: str
    section_key: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ValidationRule(Protocol):
    code: str
    severity: Severity

    def evaluate(
        self, context: DemandContext, sections: Sequence[RenderedSection]
    ) -> list[Issue]: ...


class ValidationEngine:
    def __init__(self, rules: Sequence[ValidationRule] | None = None) -> None:
        self._rules: list[ValidationRule] = list(rules or [])

    def register(self, rule: ValidationRule) -> None:
        self._rules.append(rule)

    @property
    def rules(self) -> list[ValidationRule]:
        return list(self._rules)

    def run(
        self, context: DemandContext, sections: Sequence[RenderedSection]
    ) -> list[Issue]:
        issues: list[Issue] = []
        for rule in self._rules:
            issues.extend(rule.evaluate(context, sections))
        issues.sort(key=lambda i: (-SEVERITY_ORDER[i.severity], i.code))
        return issues


def has_blocking(issues: Sequence[Issue]) -> bool:
    return any(issue.severity == Severity.BLOCKING for issue in issues)


def default_engine() -> ValidationEngine:
    from .rules import ALL_RULES

    return ValidationEngine(ALL_RULES)
