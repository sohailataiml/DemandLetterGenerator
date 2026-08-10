"""Rule-based document classification.

Keyword rules, not a model: classification steers reviewer workflow, and a
deterministic rule that a paralegal can correct beats a confident guess. The
returned type is always a suggestion — the upload endpoint accepts an explicit
override.
"""

from __future__ import annotations

import re
from datetime import date

from ..domain.enums import DocumentType

_RULES: list[tuple[DocumentType, tuple[str, ...]]] = [
    (DocumentType.MRI_REPORT, ("mri", "magnetic resonance")),
    (DocumentType.IMAGING_REPORT, ("x-ray", "xray", "ct scan", "radiolog", "ultrasound")),
    (DocumentType.POLICE_REPORT, ("traffic collision report", "police report", "crash report")),
    (DocumentType.DECLARATION_PAGE, ("declaration page", "policy limits", "coverage limits")),
    (DocumentType.BILL, ("invoice", "statement of account", "billing summary", "amount due")),
    (DocumentType.CHIROPRACTIC_RECORD, ("chiropract", "adjustment notes")),
    (DocumentType.PRIOR_DEMAND, ("policy limits demand", "demand for settlement")),
    (DocumentType.CORRESPONDENCE, ("dear ", "re:", "sincerely")),
    (DocumentType.MEDICAL_RECORD, ("patient", "diagnosis", "treatment plan", "chief complaint")),
]

_DATE_PATTERNS = (
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
)

_PROVIDER_PATTERN = re.compile(
    r"(?im)^\s*(?:provider|facility|clinic|imaging center)\s*[:\-]\s*(.+?)\s*$"
)


def classify(filename: str, text: str, mime_type: str) -> DocumentType:
    haystack = f"{filename}\n{text[:8000]}".lower()
    if mime_type.startswith("image/"):
        return DocumentType.PHOTOGRAPH
    for doc_type, keywords in _RULES:
        if any(keyword in haystack for keyword in keywords):
            return doc_type
    return DocumentType.OTHER


def guess_document_date(text: str) -> date | None:
    head = text[:4000]
    for pattern in _DATE_PATTERNS:
        match = pattern.search(head)
        if not match:
            continue
        try:
            if pattern.pattern.startswith(r"\b(\d{4})"):
                year, month, day = (int(g) for g in match.groups())
            else:
                month, day, year = (int(g) for g in match.groups())
            return date(year, month, day)
        except ValueError:
            continue
    return None


def guess_provider(text: str) -> str | None:
    match = _PROVIDER_PATTERN.search(text[:4000])
    if match:
        return match.group(1).strip()[:200]
    return None
