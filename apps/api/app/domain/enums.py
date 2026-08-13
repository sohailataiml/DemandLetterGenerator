from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class UserRole(StrEnum):
    ADMIN = "admin"
    ATTORNEY = "attorney"
    PARALEGAL = "paralegal"
    REVIEWER = "reviewer"
    READONLY = "readonly"


class PartyRole(StrEnum):
    CLIENT = "client"
    INSURED = "insured"
    DRIVER = "driver"
    VEHICLE_OWNER = "vehicle_owner"
    ADJUSTER = "adjuster"
    ATTORNEY = "attorney"
    WITNESS = "witness"


class CaseStatus(StrEnum):
    INTAKE = "intake"
    TREATING = "treating"
    DEMAND_PREP = "demand_prep"
    DEMAND_SENT = "demand_sent"
    CLOSED = "closed"


class DocumentType(StrEnum):
    POLICE_REPORT = "POLICE_REPORT"
    PHOTOGRAPH = "PHOTOGRAPH"
    MEDICAL_RECORD = "MEDICAL_RECORD"
    CHIROPRACTIC_RECORD = "CHIROPRACTIC_RECORD"
    MRI_REPORT = "MRI_REPORT"
    IMAGING_REPORT = "IMAGING_REPORT"
    BILL = "BILL"
    DECLARATION_PAGE = "DECLARATION_PAGE"
    CORRESPONDENCE = "CORRESPONDENCE"
    PRIOR_DEMAND = "PRIOR_DEMAND"
    OTHER = "OTHER"


class DocumentStatus(StrEnum):
    STORED = "stored"
    EXTRACTED = "extracted"
    EXTRACTION_FAILED = "extraction_failed"
    NEEDS_OCR = "needs_ocr"


class FactStatus(StrEnum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class FactType(StrEnum):
    DIAGNOSIS = "diagnosis"
    IMAGING_FINDING = "imaging_finding"
    TREATMENT_EVENT = "treatment_event"
    MEDICAL_EXPENSE = "medical_expense"
    FUTURE_TREATMENT = "future_treatment"
    LIABILITY = "liability"
    FUNCTIONAL_LIMITATION = "functional_limitation"
    POLICY_LIMIT = "policy_limit"
    OTHER = "other"


class BillStatus(StrEnum):
    KNOWN = "KNOWN"
    PENDING = "PENDING"
    ESTIMATED = "ESTIMATED"


class TreatmentEventType(StrEnum):
    COLLISION = "collision"
    EVALUATION = "evaluation"
    TREATMENT = "treatment"
    IMAGING = "imaging"
    CONSULT = "consult"
    FOLLOW_UP = "follow_up"
    PROCEDURE = "procedure"


class DamageCategory(StrEnum):
    GENERAL = "general"
    LOST_WAGES = "lost_wages"
    PROPERTY = "property"
    OUT_OF_POCKET = "out_of_pocket"
    OTHER = "other"


class DemandStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    SENT = "sent"
    VOID = "void"


class SectionSource(StrEnum):
    TEMPLATE = "template"
    AI = "ai"
    HUMAN = "human"


class ClaimStatus(StrEnum):
    """How well one atomic factual claim is backed by the verified fact store."""

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class RevisionStatus(StrEnum):
    """An AI revision proposal is a proposal until an attorney decides."""

    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INVALID = "INVALID"
    SUPERSEDED = "SUPERSEDED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


SEVERITY_ORDER = {Severity.INFO: 0, Severity.WARNING: 1, Severity.BLOCKING: 2}
