"""Deterministic scan of generated prose for unsupported literals.

This is the backstop behind the prompt contract: every dollar amount, date, and
proper name that appears in generated text must also appear in the structured
case data. Amounts and dates are checked exactly. Names are heuristic — a
capitalized phrase is not proof of a proper noun — so name findings are reported
at a lower severity than numeric ones.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from ..domain.money import to_money

_AMOUNT_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_LONG_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.IGNORECASE,
)
_SLASH_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_NAME_RE = re.compile(r"\b([A-Z][A-Za-z'’\-\.]+(?:\s+[A-Z][A-Za-z'’\-\.]+)+)\b")

# Capitalized phrases that are ordinary letter language rather than proper nouns.
_NAME_STOPWORDS = {
    *(_MONTHS.keys()),
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "the",
    "this",
    "that",
    "your",
    "our",
    "his",
    "her",
    "their",
    "insured",
    "driver",
    "client",
    "claim",
    "number",
    "policy",
    "limits",
    "limit",
    "demand",
    "settlement",
    "medical",
    "expenses",
    "expense",
    "summary",
    "treatment",
    "history",
    "imaging",
    "findings",
    "future",
    "care",
    "pain",
    "suffering",
    "inconvenience",
    "liability",
    "damages",
    "acceptance",
    "conditions",
    "date",
    "loss",
    "time",
    "limited",
    "very",
    "truly",
    "yours",
    "tel",
    "via",
    "email",
    "mri",
    "ct",
    "no",
    "not",
    "acceptance",
    "total",
    "known",
    "estimated",
    "pending",
    "amount",
    "drafting",
    "could",
    "completed",
    "insufficient",
    "verified",
    "evidence",
    "letterhead",
    "signature",
    "attorney",
    "record",
    "assigned",
    "generated",
    "section",
}


def extract_amounts(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for match in _AMOUNT_RE.finditer(text):
        try:
            found.add(to_money(match.group(1)))
        except (InvalidOperation, ValueError):  # pragma: no cover - regex guarantees shape
            continue
    return found


def extract_dates(text: str) -> set[date]:
    found: set[date] = set()
    for match in _LONG_DATE_RE.finditer(text):
        month = _MONTHS[match.group(1).lower()]
        try:
            found.add(date(int(match.group(3)), month, int(match.group(2))))
        except ValueError:
            continue
    for match in _SLASH_DATE_RE.finditer(text):
        try:
            found.add(date(int(match.group(3)), int(match.group(1)), int(match.group(2))))
        except ValueError:
            continue
    for match in _ISO_DATE_RE.finditer(text):
        try:
            found.add(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    return found


def extract_impossible_dates(text: str) -> list[str]:
    """Date-shaped text that is not a date — "February 29, 2019", "13/40/2024".

    :func:`extract_dates` drops these, which is correct for "is this date
    supported by the record", but it means a letter can state a day that never
    existed and no check notices. They are reported separately so it does.
    """
    impossible: list[str] = []
    for match in _LONG_DATE_RE.finditer(text):
        month = _MONTHS[match.group(1).lower()]
        try:
            date(int(match.group(3)), month, int(match.group(2)))
        except ValueError:
            impossible.append(match.group(0))
    for match in _SLASH_DATE_RE.finditer(text):
        try:
            date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        except ValueError:
            impossible.append(match.group(0))
    for match in _ISO_DATE_RE.finditer(text):
        try:
            date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            impossible.append(match.group(0))
    return impossible


def extract_name_candidates(text: str) -> set[str]:
    candidates: set[str] = set()
    for match in _NAME_RE.finditer(text):
        phrase = match.group(1).strip(" .")
        words = [w.strip(".'’-").lower() for w in phrase.split()]
        if not words:
            continue
        if all(word in _NAME_STOPWORDS for word in words):
            continue
        candidates.add(phrase)
    return candidates


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def unsupported_amounts(text: str, allowed: set[Decimal]) -> list[Decimal]:
    return sorted(extract_amounts(text) - set(allowed))


def unsupported_dates(text: str, allowed: set[date]) -> list[date]:
    return sorted(extract_dates(text) - set(allowed))


def unsupported_names(text: str, allowed: set[str]) -> list[str]:
    normalized_allowed = [_normalize(name) for name in allowed if name]
    unmatched: list[str] = []
    for candidate in sorted(extract_name_candidates(text)):
        normalized = _normalize(candidate)
        if not normalized:
            continue
        if any(
            normalized in allowed_name or allowed_name in normalized
            for allowed_name in normalized_allowed
            if allowed_name
        ):
            continue
        unmatched.append(candidate)
    return unmatched
