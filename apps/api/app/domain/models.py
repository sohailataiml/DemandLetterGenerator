"""SQLAlchemy mappings for the case fact store.

Design notes that matter for correctness:

* ``insured`` and ``driver`` are roles on a party, never the same field — a
  single person may hold several roles, and two different people commonly hold
  these two.
* Money columns use the exact-decimal :class:`Money` type; a ``NULL`` amount
  means *unknown*, which is a different thing from zero.
* Source documents are immutable after ingestion: there is no update path, and
  the stored SHA-256 lets any later reader prove the bytes never changed.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import ids
from ..db import Base
from .enums import (
    BillStatus,
    CaseStatus,
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
    UserRole,
)
from .money import Money


def _pk(prefix: str) -> Mapped[str]:
    return mapped_column(String(40), primary_key=True, default=ids.id_factory(prefix))


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = _pk(ids.USER)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Case(Base, TimestampMixin):
    __tablename__ = "cases"

    id: Mapped[str] = _pk(ids.CASE)
    reference: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    client_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[CaseStatus] = mapped_column(String(32), default=CaseStatus.INTAKE, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    parties: Mapped[list["Party"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    claim: Mapped["Claim | None"] = relationship(
        back_populates="case", uselist=False, cascade="all, delete-orphan"
    )
    accident: Mapped["Accident | None"] = relationship(
        back_populates="case", uselist=False, cascade="all, delete-orphan"
    )
    vehicles: Mapped[list["Vehicle"]] = relationship(cascade="all, delete-orphan")
    providers: Mapped[list["MedicalProvider"]] = relationship(cascade="all, delete-orphan")
    treatment_events: Mapped[list["TreatmentEvent"]] = relationship(cascade="all, delete-orphan")
    diagnoses: Mapped[list["Diagnosis"]] = relationship(cascade="all, delete-orphan")
    imaging_findings: Mapped[list["ImagingFinding"]] = relationship(cascade="all, delete-orphan")
    bills: Mapped[list["MedicalBill"]] = relationship(cascade="all, delete-orphan")
    future_treatments: Mapped[list["FutureTreatment"]] = relationship(cascade="all, delete-orphan")
    damage_claims: Mapped[list["DamageClaim"]] = relationship(cascade="all, delete-orphan")
    settlement_terms: Mapped["SettlementTerms | None"] = relationship(
        back_populates="case", uselist=False, cascade="all, delete-orphan"
    )
    documents: Mapped[list["SourceDocument"]] = relationship(cascade="all, delete-orphan")
    facts: Mapped[list["Fact"]] = relationship(cascade="all, delete-orphan")
    demands: Mapped[list["Demand"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class Party(Base, TimestampMixin):
    __tablename__ = "parties"

    id: Mapped[str] = _pk(ids.PARTY)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(320))
    address: Mapped[str | None] = mapped_column(Text)
    organization: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    case: Mapped[Case] = relationship(back_populates="parties")
    role_assignments: Mapped[list["PartyRoleAssignment"]] = relationship(
        back_populates="party", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def roles(self) -> list[PartyRole]:
        return [PartyRole(a.role) for a in self.role_assignments]

    def has_role(self, role: PartyRole) -> bool:
        return any(a.role == role.value for a in self.role_assignments)


class PartyRoleAssignment(Base, TimestampMixin):
    __tablename__ = "party_role_assignments"
    __table_args__ = (UniqueConstraint("party_id", "role", name="uq_party_role"),)

    id: Mapped[str] = _pk(ids.ROLE)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), index=True)
    role: Mapped[PartyRole] = mapped_column(String(32), nullable=False)
    relationship_note: Mapped[str | None] = mapped_column(Text)

    party: Mapped[Party] = relationship(back_populates="role_assignments")


class Carrier(Base, TimestampMixin):
    __tablename__ = "carriers"

    id: Mapped[str] = _pk(ids.CARRIER)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    adjuster_name: Mapped[str | None] = mapped_column(String(200))
    adjuster_email: Mapped[str | None] = mapped_column(String(320))
    adjuster_phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)


class Claim(Base, TimestampMixin):
    __tablename__ = "claims"

    id: Mapped[str] = _pk(ids.CLAIM)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), unique=True, index=True
    )
    claim_number: Mapped[str] = mapped_column(String(64), nullable=False)
    date_of_loss: Mapped[date] = mapped_column(Date, nullable=False)
    carrier_id: Mapped[str | None] = mapped_column(ForeignKey("carriers.id", ondelete="SET NULL"))
    policy_number: Mapped[str | None] = mapped_column(String(64))
    policy_limit: Mapped[Decimal | None] = mapped_column(Money)
    policy_limit_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    case: Mapped[Case] = relationship(back_populates="claim")
    carrier: Mapped[Carrier | None] = relationship(lazy="selectin")


class Accident(Base, TimestampMixin):
    __tablename__ = "accidents"

    id: Mapped[str] = _pk(ids.ACCIDENT)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), unique=True, index=True
    )
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_time: Mapped[str | None] = mapped_column(String(16))
    location: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    police_report_number: Mapped[str | None] = mapped_column(String(64))
    impact_type: Mapped[str | None] = mapped_column(String(64))

    case: Mapped[Case] = relationship(back_populates="accident")


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"

    id: Mapped[str] = _pk(ids.VEHICLE)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    year: Mapped[int | None] = mapped_column(Integer)
    make: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(64))
    plate: Mapped[str | None] = mapped_column(String(32))
    owner_party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    driver_party_id: Mapped[str | None] = mapped_column(
        ForeignKey("parties.id", ondelete="SET NULL")
    )
    is_client_vehicle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MedicalProvider(Base, TimestampMixin):
    __tablename__ = "medical_providers"

    id: Mapped[str] = _pk(ids.PROVIDER)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_type: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))


class TreatmentEvent(Base, TimestampMixin):
    __tablename__ = "treatment_events"

    id: Mapped[str] = _pk(ids.TREATMENT)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[str | None] = mapped_column(
        ForeignKey("medical_providers.id", ondelete="SET NULL")
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[TreatmentEventType] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    body_regions: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL")
    )

    provider: Mapped[MedicalProvider | None] = relationship(lazy="selectin")


class Diagnosis(Base, TimestampMixin):
    __tablename__ = "diagnoses"

    id: Mapped[str] = _pk(ids.DIAGNOSIS)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    treatment_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("treatment_events.id", ondelete="SET NULL")
    )
    code: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosed_on: Mapped[date | None] = mapped_column(Date)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL")
    )


class ImagingFinding(Base, TimestampMixin):
    __tablename__ = "imaging_findings"

    id: Mapped[str] = _pk(ids.IMAGING)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[str | None] = mapped_column(
        ForeignKey("medical_providers.id", ondelete="SET NULL")
    )
    study_date: Mapped[date] = mapped_column(Date, nullable=False)
    modality: Mapped[str] = mapped_column(String(32), nullable=False, default="MRI")
    body_region: Mapped[str | None] = mapped_column(String(64))
    level: Mapped[str | None] = mapped_column(String(32))
    finding: Mapped[str] = mapped_column(Text, nullable=False)
    measurement: Mapped[str | None] = mapped_column(String(64))
    impression: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL")
    )

    provider: Mapped[MedicalProvider | None] = relationship(lazy="selectin")


class MedicalBill(Base, TimestampMixin):
    __tablename__ = "medical_bills"

    id: Mapped[str] = _pk(ids.BILL)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[str | None] = mapped_column(
        ForeignKey("medical_providers.id", ondelete="SET NULL")
    )
    provider_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Money)
    status: Mapped[BillStatus] = mapped_column(String(16), default=BillStatus.KNOWN, nullable=False)
    billed_on: Mapped[date | None] = mapped_column(Date)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL")
    )
    fact_id: Mapped[str | None] = mapped_column(ForeignKey("facts.id", ondelete="SET NULL"))


class FutureTreatment(Base, TimestampMixin):
    __tablename__ = "future_treatments"

    id: Mapped[str] = _pk(ids.FUTURE)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cost_low: Mapped[Decimal | None] = mapped_column(Money)
    cost_high: Mapped[Decimal | None] = mapped_column(Money)
    recommended_on: Mapped[date | None] = mapped_column(Date)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL")
    )


class DamageClaim(Base, TimestampMixin):
    __tablename__ = "damage_claims"

    id: Mapped[str] = _pk(ids.DAMAGE)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    category: Mapped[DamageCategory] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Money)


class SettlementTerms(Base, TimestampMixin):
    __tablename__ = "settlement_terms"

    id: Mapped[str] = _pk(ids.SETTLEMENT)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), unique=True, index=True
    )
    demand_type: Mapped[str] = mapped_column(String(64), default="policy_limits", nullable=False)
    demand_amount: Mapped[Decimal | None] = mapped_column(Money)
    demand_is_policy_limits: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivery_method: Mapped[str] = mapped_column(String(64), default="email", nullable=False)
    conditions: Mapped[list[str]] = mapped_column(JSON, default=list)

    case: Mapped[Case] = relationship(back_populates="settlement_terms")


class SourceDocument(Base, TimestampMixin):
    """Immutable record of an ingested file. Never updated after creation."""

    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("case_id", "sha256", name="uq_case_document_sha"),)

    id: Mapped[str] = _pk(ids.DOCUMENT)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    document_type: Mapped[DocumentType] = mapped_column(String(32), nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(200))
    document_date: Mapped[date | None] = mapped_column(Date)
    original_filename: Mapped[str] = mapped_column(String(400), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(String(32), nullable=False)
    extraction_note: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[str] = mapped_column(String(40), nullable=False)

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_number"
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_document_page"),)

    id: Mapped[str] = _pk(ids.PAGE)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)

    document: Mapped[SourceDocument] = relationship(back_populates="pages")


class Fact(Base, TimestampMixin):
    """A single reviewable assertion about the case, with provenance.

    AI extraction may only create ``PROPOSED`` facts. A ``VERIFIED`` fact is
    immutable: correcting it creates a new revision that supersedes it, so the
    audit trail never loses what an attorney actually approved.
    """

    __tablename__ = "facts"

    id: Mapped[str] = _pk(ids.FACT)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    fact_type: Mapped[FactType] = mapped_column(String(40), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[FactStatus] = mapped_column(
        String(16), default=FactStatus.PROPOSED, nullable=False, index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("facts.id", ondelete="SET NULL"))
    superseded_by_id: Mapped[str | None] = mapped_column(ForeignKey("facts.id", ondelete="SET NULL"))
    proposed_by: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    sources: Mapped[list["FactSource"]] = relationship(
        back_populates="fact", cascade="all, delete-orphan", lazy="selectin"
    )


class FactSource(Base, TimestampMixin):
    __tablename__ = "fact_sources"

    id: Mapped[str] = _pk(ids.FACT_SOURCE)
    fact_id: Mapped[str] = mapped_column(ForeignKey("facts.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    excerpt: Mapped[str | None] = mapped_column(Text)

    fact: Mapped[Fact] = relationship(back_populates="sources")


class Demand(Base, TimestampMixin):
    __tablename__ = "demands"
    __table_args__ = (UniqueConstraint("case_id", "version", name="uq_case_demand_version"),)

    id: Mapped[str] = _pk(ids.DEMAND)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DemandStatus] = mapped_column(
        String(16), default=DemandStatus.DRAFT, nullable=False
    )
    letter_date: Mapped[date] = mapped_column(Date, nullable=False)
    template_version: Mapped[str | None] = mapped_column(String(64))
    provider_name: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    docx_key: Mapped[str | None] = mapped_column(String(400))
    docx_sha256: Mapped[str | None] = mapped_column(String(64))
    pdf_key: Mapped[str | None] = mapped_column(String(400))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    damages_snapshot: Mapped[dict | None] = mapped_column(JSON)

    case: Mapped[Case] = relationship(back_populates="demands")
    sections: Mapped[list["DemandSection"]] = relationship(
        back_populates="demand",
        cascade="all, delete-orphan",
        order_by="DemandSection.position",
        lazy="selectin",
    )
    issues: Mapped[list["ValidationIssueRecord"]] = relationship(
        back_populates="demand", cascade="all, delete-orphan", lazy="selectin"
    )


class DemandSection(Base, TimestampMixin):
    __tablename__ = "demand_sections"
    __table_args__ = (UniqueConstraint("demand_id", "key", name="uq_demand_section_key"),)

    id: Mapped[str] = _pk(ids.SECTION)
    demand_id: Mapped[str] = mapped_column(ForeignKey("demands.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source: Mapped[SectionSource] = mapped_column(String(16), nullable=False)
    used_fact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    edited_by: Mapped[str | None] = mapped_column(String(64))

    demand: Mapped[Demand] = relationship(back_populates="sections")


class ValidationIssueRecord(Base, TimestampMixin):
    __tablename__ = "validation_issues"

    id: Mapped[str] = _pk(ids.ISSUE)
    demand_id: Mapped[str] = mapped_column(ForeignKey("demands.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[Severity] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    section_key: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    demand: Mapped[Demand] = relationship(back_populates="issues")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = _pk(ids.AUDIT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    case_id: Mapped[str | None] = mapped_column(String(40), index=True)
    demand_id: Mapped[str | None] = mapped_column(String(40), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
