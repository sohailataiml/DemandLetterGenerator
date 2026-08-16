"""Pydantic request/response models.

Money fields are typed ``Decimal`` and serialized as strings so no float ever
appears on the wire.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import (
    BillStatus,
    CaseStatus,
    CitationStatus,
    DamageCategory,
    DemandStatus,
    DocumentStatus,
    DocumentType,
    FactStatus,
    FactType,
    PartyRole,
    SectionSource,
    Severity,
    TreatmentEventType,
)
from .money import to_money


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# --------------------------------------------------------------------------- cases


class CaseCreate(BaseModel):
    reference: str = Field(min_length=1, max_length=64)
    client_display_name: str = Field(min_length=1, max_length=200)
    notes: str | None = None


class CaseUpdate(BaseModel):
    client_display_name: str | None = None
    status: CaseStatus | None = None
    notes: str | None = None


class CaseOut(ApiModel):
    id: str
    reference: str
    client_display_name: str
    status: CaseStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- parties


class PartyRoleIn(BaseModel):
    role: PartyRole
    relationship_note: str | None = None


class PartyCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    roles: list[PartyRoleIn] = Field(default_factory=list)
    date_of_birth: date | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    organization: str | None = None
    notes: str | None = None


class PartyUpdate(BaseModel):
    full_name: str | None = None
    roles: list[PartyRoleIn] | None = None
    date_of_birth: date | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    organization: str | None = None
    notes: str | None = None


class PartyRoleOut(ApiModel):
    role: PartyRole
    relationship_note: str | None


class PartyOut(ApiModel):
    id: str
    case_id: str
    full_name: str
    date_of_birth: date | None
    phone: str | None
    email: str | None
    address: str | None
    organization: str | None
    notes: str | None
    role_assignments: list[PartyRoleOut] = Field(default_factory=list, alias="role_assignments")


# --------------------------------------------------------------------------- claim


class CarrierIn(BaseModel):
    name: str
    adjuster_name: str | None = None
    adjuster_email: str | None = None
    adjuster_phone: str | None = None
    address: str | None = None


class ClaimUpsert(BaseModel):
    claim_number: str = Field(min_length=1, max_length=64)
    date_of_loss: date
    policy_number: str | None = None
    policy_limit: Decimal | None = None
    policy_limit_confirmed: bool = False
    carrier: CarrierIn | None = None

    @field_validator("policy_limit")
    @classmethod
    def _exact_money(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else to_money(v)


class CarrierOut(ApiModel):
    id: str
    name: str
    adjuster_name: str | None
    adjuster_email: str | None
    adjuster_phone: str | None
    address: str | None


class ClaimOut(ApiModel):
    id: str
    claim_number: str
    date_of_loss: date
    policy_number: str | None
    policy_limit: Decimal | None
    policy_limit_confirmed: bool
    carrier: CarrierOut | None


class AccidentUpsert(BaseModel):
    occurred_on: date
    occurred_time: str | None = None
    location: str | None = None
    description: str | None = None
    police_report_number: str | None = None
    impact_type: str | None = None


class AccidentOut(ApiModel):
    id: str
    occurred_on: date
    occurred_time: str | None
    location: str | None
    description: str | None
    police_report_number: str | None
    impact_type: str | None


class VehicleOut(ApiModel):
    id: str
    year: int | None
    make: str | None
    model: str | None
    plate: str | None
    owner_party_id: str | None
    driver_party_id: str | None
    is_client_vehicle: bool


# --------------------------------------------------------------------------- medical


class ProviderCreate(BaseModel):
    name: str
    provider_type: str | None = None
    address: str | None = None
    phone: str | None = None


class ProviderOut(ApiModel):
    id: str
    name: str
    provider_type: str | None
    address: str | None
    phone: str | None


class TreatmentEventCreate(BaseModel):
    event_date: date
    event_type: TreatmentEventType
    description: str
    provider_id: str | None = None
    body_regions: list[str] = Field(default_factory=list)
    source_document_id: str | None = None


class TreatmentEventOut(ApiModel):
    id: str
    event_date: date
    event_type: TreatmentEventType
    description: str
    provider_id: str | None
    body_regions: list[str]
    source_document_id: str | None


class DiagnosisCreate(BaseModel):
    description: str
    code: str | None = None
    diagnosed_on: date | None = None
    treatment_event_id: str | None = None
    source_document_id: str | None = None


class DiagnosisOut(ApiModel):
    id: str
    description: str
    code: str | None
    diagnosed_on: date | None
    treatment_event_id: str | None
    source_document_id: str | None


class ImagingFindingCreate(BaseModel):
    study_date: date
    finding: str
    modality: str = "MRI"
    provider_id: str | None = None
    body_region: str | None = None
    level: str | None = None
    measurement: str | None = None
    impression: str | None = None
    source_document_id: str | None = None


class ImagingFindingOut(ApiModel):
    id: str
    study_date: date
    modality: str
    finding: str
    provider_id: str | None
    body_region: str | None
    level: str | None
    measurement: str | None
    impression: str | None
    source_document_id: str | None


class BillCreate(BaseModel):
    provider_name: str
    amount: Decimal | None = None
    status: BillStatus = BillStatus.KNOWN
    description: str | None = None
    provider_id: str | None = None
    billed_on: date | None = None
    source_document_id: str | None = None

    @field_validator("amount")
    @classmethod
    def _exact_money(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else to_money(v)

    @field_validator("status")
    @classmethod
    def _pending_has_no_amount(cls, v: BillStatus, info) -> BillStatus:
        amount = info.data.get("amount")
        if v == BillStatus.PENDING and amount is not None:
            raise ValueError("a PENDING bill must not carry an amount; use KNOWN or ESTIMATED")
        return v


class BillOut(ApiModel):
    id: str
    provider_name: str
    description: str | None
    amount: Decimal | None
    status: BillStatus
    billed_on: date | None
    provider_id: str | None
    source_document_id: str | None


class FutureTreatmentCreate(BaseModel):
    description: str
    provider_name: str | None = None
    quantity: int = 1
    cost_low: Decimal | None = None
    cost_high: Decimal | None = None
    recommended_on: date | None = None
    source_document_id: str | None = None

    @field_validator("cost_low", "cost_high")
    @classmethod
    def _exact_money(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else to_money(v)


class FutureTreatmentOut(ApiModel):
    id: str
    description: str
    provider_name: str | None
    quantity: int
    cost_low: Decimal | None
    cost_high: Decimal | None
    recommended_on: date | None
    source_document_id: str | None


class DamageClaimCreate(BaseModel):
    category: DamageCategory
    description: str
    amount: Decimal | None = None

    @field_validator("amount")
    @classmethod
    def _exact_money(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else to_money(v)


class DamageClaimOut(ApiModel):
    id: str
    category: DamageCategory
    description: str
    amount: Decimal | None


class SettlementTermsUpsert(BaseModel):
    expires_at: datetime
    demand_type: str = "policy_limits"
    demand_amount: Decimal | None = None
    demand_is_policy_limits: bool = True
    delivery_method: str = "email"
    conditions: list[str] = Field(default_factory=list)

    @field_validator("demand_amount")
    @classmethod
    def _exact_money(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else to_money(v)


class SettlementTermsOut(ApiModel):
    id: str
    demand_type: str
    demand_amount: Decimal | None
    demand_is_policy_limits: bool
    expires_at: datetime
    delivery_method: str
    conditions: list[str]


# --------------------------------------------------------------------------- documents


class DocumentOut(ApiModel):
    id: str
    case_id: str
    document_type: DocumentType
    provider_name: str | None
    document_date: date | None
    original_filename: str
    mime_type: str
    size_bytes: int
    page_count: int
    sha256: str
    storage_key: str
    status: DocumentStatus
    extraction_note: str | None
    uploaded_by: str
    created_at: datetime


class DocumentPageOut(ApiModel):
    """A page as the evidence viewer needs it — without the word array.

    ``has_geometry`` says whether asking for ``/geometry`` is worth a round
    trip; the words themselves are large and are never included in a case-level
    or document-level response.
    """

    page_number: int
    text: str
    width: float | None = None
    height: float | None = None
    extraction_method: str = "text"
    word_count: int = 0
    has_geometry: bool = False


class BoundingBoxOut(BaseModel):
    """A rectangle on the rendered page, normalized to ``[0, 1]``."""

    x: float
    y: float
    width: float
    height: float


class WordGeometryOut(BaseModel):
    text: str
    start: int
    end: int
    bbox: BoundingBoxOut


class PageGeometryOut(BaseModel):
    """Word rectangles for exactly one page. Fetched lazily, never in bulk."""

    document_id: str
    page_number: int
    width: float | None
    height: float | None
    extraction_method: str
    words: list[WordGeometryOut] = Field(default_factory=list)


class DocumentDetailOut(DocumentOut):
    pages: list[DocumentPageOut] = Field(default_factory=list)


class UploadLimitsOut(BaseModel):
    """What the server will actually accept.

    The upload UI reads this rather than hardcoding a format list, so it cannot
    offer the attorney a file type the scanner is going to reject. These are
    advisory for the client and authoritative on the server: every value here
    is re-checked during ingestion regardless of what the browser did.
    """

    max_upload_bytes: int
    allowed_mime_types: list[str]
    allowed_extensions: list[str]
    max_template_bytes: int
    template_mime_types: list[str]
    template_extensions: list[str]


# --------------------------------------------------------------------------- facts


class FactSourceIn(BaseModel):
    document_id: str
    page_number: int | None = None
    excerpt: str | None = None


class FactCreate(BaseModel):
    fact_type: FactType
    value: dict[str, Any]
    summary: str
    sources: list[FactSourceIn] = Field(default_factory=list)
    confidence: float | None = None


class FactOutWithMetadata(BaseModel):
    """Extraction provenance, present only on machine-proposed facts."""

    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    document_id: str | None = None
    page_number: int | None = None
    match_kind: str | None = None
    low_confidence: bool = False


class ExtractionRunIn(BaseModel):
    document_ids: list[str] | None = None


class ExtractionReportOut(BaseModel):
    document_id: str
    provider: str
    model: str | None = None
    prompt_version: str
    chunks: int
    candidates: int
    proposed: int
    proposed_fact_ids: list[str] = Field(default_factory=list)
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    suspected_injection_chunks: list[int] = Field(default_factory=list)


class FactSupersede(FactCreate):
    reason: str


class FactRejection(BaseModel):
    reason: str


class FactSourceOut(ApiModel):
    """A citation: document → page → span → region, with its own honesty label.

    ``citation_status`` is what the UI branches on. Only ``EXACT`` may be drawn
    as an authoritative highlight, and only when ``bounding_boxes`` is non-empty
    may that highlight be geometric.
    """

    id: str
    fact_id: str
    document_id: str
    page_number: int | None
    excerpt: str | None
    start_offset: int | None = None
    end_offset: int | None = None
    quoted_text_sha256: str | None = None
    #: "exact"/"normalized" mean the offsets are authoritative; "approximate"
    #: means the UI must present the highlight as a best guess.
    match_kind: str | None = None
    citation_status: CitationStatus = CitationStatus.UNRESOLVED
    bounding_boxes: list[BoundingBoxOut] | None = None
    confidence: float | None = None
    created_at: datetime | None = None


class CitationSelectionIn(BaseModel):
    """A reviewer pointing at the passage they mean, by page-local offsets.

    Used to settle an ``AMBIGUOUS`` citation, or to pin a page-level citation to
    a span. The offsets are checked against the stored page text, and against
    the passage the citation already claims, so this can sharpen provenance but
    never redirect it at different words.
    """

    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)


class FactOut(ApiModel):
    id: str
    case_id: str
    fact_type: FactType
    value: dict[str, Any]
    summary: str
    status: FactStatus
    confidence: float | None
    created_at: datetime
    revision: int
    supersedes_id: str | None
    superseded_by_id: str | None
    proposed_by: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    extraction_metadata: dict[str, Any] | None = None
    sources: list[FactSourceOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- timeline / damages


class TimelineEntryOut(BaseModel):
    entry_date: date
    kind: str
    title: str
    provider: str | None = None
    detail: str | None = None
    diagnoses: list[str] = Field(default_factory=list)
    cost: Decimal | None = None
    source_document_ids: list[str] = Field(default_factory=list)


class PendingBillOut(BaseModel):
    bill_id: str
    provider_name: str
    description: str | None = None


class DamagesOut(BaseModel):
    current_medical_expenses: Decimal
    pending_bills: list[PendingBillOut]
    estimated_bill_total: Decimal
    future_medical_low: Decimal
    future_medical_high: Decimal
    general_damages: Decimal
    other_damages: Decimal
    known_claimed_damages_low: Decimal
    known_claimed_damages_high: Decimal
    line_items: list[dict[str, Any]]


# --------------------------------------------------------------------------- demands


class DemandCreate(BaseModel):
    letter_date: date | None = None


class DemandGenerate(BaseModel):
    regenerate_sections: list[str] | None = None


class SectionEdit(BaseModel):
    body: str


class DemandSectionOut(ApiModel):
    id: str
    key: str
    title: str
    position: int
    body: str
    source: SectionSource
    used_fact_ids: list[str]
    edited_by: str | None


class ValidationIssueOut(ApiModel):
    code: str
    severity: Severity
    message: str
    section_key: str | None
    details: dict[str, Any]


class DemandOut(ApiModel):
    id: str
    case_id: str
    version: int
    status: DemandStatus
    letter_date: date
    template_version: str | None
    provider_name: str | None
    model_name: str | None
    prompt_version: str | None
    generated_at: datetime | None
    docx_sha256: str | None
    pdf_sha256: str | None
    approved_by: str | None
    approved_at: datetime | None
    locked: bool
    created_by: str
    template_id: str | None = None
    template_sha256: str | None = None
    fidelity_report: dict[str, Any] | None = None
    claim_report: dict[str, Any] | None = None
    #: Safe AI-boundary metadata: which boundary drafting crossed, the upstream
    #: provider/model, gateway request ids, token usage, and the privacy summary
    #: of counts. Contains no credential and no detected value, which is what
    #: makes it safe to hand to a browser.
    generation_metadata: dict[str, Any] | None = None
    sections: list[DemandSectionOut] = Field(default_factory=list)
    issues: list[ValidationIssueOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- templates


class TemplateSlotOut(BaseModel):
    name: str
    kind: str
    block_index: int
    section_key: str | None = None
    fields: list[str] = Field(default_factory=list)
    resolvable: bool = True


class TemplateSectionOut(BaseModel):
    key: str
    title: str
    start_index: int
    end_index: int


class TemplateOut(ApiModel):
    id: str
    case_id: str | None
    name: str
    original_filename: str
    sha256: str
    structure_sha256: str
    size_bytes: int
    block_count: int
    slot_names: list[str]
    uploaded_by: str
    created_at: datetime


class TemplateDetailOut(TemplateOut):
    slots: list[TemplateSlotOut] = Field(default_factory=list)
    sections: list[TemplateSectionOut] = Field(default_factory=list)
    header_parts: list[str] = Field(default_factory=list)
    footer_parts: list[str] = Field(default_factory=list)
    page_setup: dict[str, Any] = Field(default_factory=dict)
    unknown_slots: list[str] = Field(default_factory=list)


class TemplateBindIn(BaseModel):
    template_id: str


class FidelityReportOut(BaseModel):
    template_hash: str
    required_blocks: dict[str, int]
    styles_changed: int
    headers_changed: int
    footers_changed: int
    numbering_changed: int
    page_setup_changed: bool
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------------------- revisions


class RevisionConstraintIn(BaseModel):
    preserve_facts: bool = True
    preserve_amounts: bool = True
    preserve_dates: bool = True
    allow_new_facts: bool = False
    preserve_literals: list[str] = Field(default_factory=list)


class RevisionRequestIn(BaseModel):
    section_key: str
    instruction: str = Field(min_length=3, max_length=2000)
    constraints: RevisionConstraintIn = Field(default_factory=RevisionConstraintIn)


class RevisionDecisionIn(BaseModel):
    note: str | None = None


class RevisionOperationOut(ApiModel):
    op: str
    paragraph_id: str
    position: int
    before_hash: str
    after_text: str
    fact_ids: list[str] = Field(default_factory=list)


class RevisionProposalOut(ApiModel):
    id: str
    demand_id: str
    section_key: str
    instruction: str
    constraints: dict[str, Any]
    status: str
    provider_name: str | None
    model_name: str | None
    prompt_version: str | None
    validation: dict[str, Any]
    requested_by: str
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime
    operations: list[RevisionOperationOut] = Field(default_factory=list)


class RevisionProposalDetailOut(BaseModel):
    """The proposal plus everything a reviewer needs to decide on it."""

    proposal: RevisionProposalOut
    before: str
    after: str
    unified_diff: str
    violations: list[dict[str, Any]] = Field(default_factory=list)
    valid: bool


# --------------------------------------------------------------------------- jobs


class JobRequestIn(BaseModel):
    demand_id: str | None = None
    template_id: str | None = None
    letter_date: date | None = None
    extract: bool = False
    document_ids: list[str] | None = None
    regenerate_sections: list[str] | None = None


class GenerationJobOut(ApiModel):
    id: str
    case_id: str
    demand_id: str | None
    kind: str
    status: str
    stages: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    requested_by: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ApprovalIn(BaseModel):
    acknowledgement: str = Field(
        description="Attorney must type the case reference to confirm review.",
    )


class ValidationCountsOut(BaseModel):
    """Counts from the most recent validation run, or ``None`` if never run."""

    blocking: int
    warning: int
    info: int
    last_validated_at: datetime | None = None


class DemandSummaryOut(ApiModel):
    id: str
    version: int
    status: DemandStatus
    letter_date: date
    locked: bool
    approved_at: datetime | None
    updated_at: datetime


class CaseSummaryOut(BaseModel):
    """One row of the case list: enough to triage without opening the case."""

    id: str
    reference: str
    client_display_name: str
    status: CaseStatus
    claim_number: str | None = None
    date_of_loss: date | None = None
    carrier_name: str | None = None
    demand: DemandSummaryOut | None = None
    validation: ValidationCountsOut | None = None
    updated_at: datetime


class AuditEventOut(ApiModel):
    id: str
    created_at: datetime
    event: str
    actor: str
    actor_role: str | None
    case_id: str | None
    demand_id: str | None
    subject_id: str | None
    payload: dict[str, Any]
