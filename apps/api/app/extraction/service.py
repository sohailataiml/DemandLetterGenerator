"""Case materials -> chunks -> candidates -> verified citations -> PROPOSED facts.

The gate in the middle is the whole point. A provider returns candidates with a
quote; this module looks that quote up in the page text the ingestion pipeline
stored, and only a candidate whose quote is actually there becomes a fact. A
model cannot cite a document into saying something it does not say, because the
citation is resolved against the document and not against the model.

Nothing here can verify a fact. Everything it creates is ``PROPOSED``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import service as audit
from ..domain.enums import CitationStatus, FactStatus, FactType
from ..domain.models import DocumentPage, Fact, FactSource, SourceDocument
from ..provenance import geometry
from ..provenance import service as provenance
from ..security.auth import CurrentUser
from . import chunker
from .prompts import PROMPT_VERSION, ExtractionRequest
from .provider import Candidate, ExtractionError, ExtractionProvider, get_extraction_provider

#: A candidate whose confidence is below this is still proposed, but flagged.
LOW_CONFIDENCE = 0.4

_VALID_FACT_TYPES = {member.value for member in FactType}


class ExtractionRejected(str):
    """Why a candidate did not become a fact. Kept as strings for the audit payload."""


NO_CITATION = "quote not found in the stored document text"
UNKNOWN_TYPE = "fact type is not one this system models"
EMPTY_SUMMARY = "candidate had no summary"


@dataclass
class ExtractionReport:
    """What one extraction run did, in full. Recorded to the audit trail."""

    document_id: str
    provider: str
    model: str | None
    prompt_version: str
    chunks: int = 0
    candidates: int = 0
    proposed_fact_ids: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    suspected_injection_chunks: list[int] = field(default_factory=list)

    @property
    def proposed(self) -> int:
        return len(self.proposed_fact_ids)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "chunks": self.chunks,
            "candidates": self.candidates,
            "proposed": self.proposed,
            "proposed_fact_ids": list(self.proposed_fact_ids),
            "rejected": list(self.rejected),
            "suspected_injection_chunks": list(self.suspected_injection_chunks),
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _page(session: Session, document_id: str, page_number: int) -> DocumentPage | None:
    return session.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document_id,
            DocumentPage.page_number == page_number,
        )
    )


def _resolve_citation(
    session: Session, request: ExtractionRequest, candidate: Candidate
) -> provenance.CitationFields | None:
    """Locate the candidate's quote in the stored page, not in the chunk we sent.

    Resolving against the page is deliberate: the offsets recorded on the fact
    have to be openable by a reviewer looking at the page, and a chunk boundary
    is an implementation detail they never see. Where the page has word
    geometry, the same call also fixes the region on the rendered page, so an
    extracted fact arrives with the full document → page → span → box chain.

    ``None`` means the page does not contain the quote at all — no evidence, so
    no fact. An ambiguous quote is *not* nothing: it is returned as a citation
    with ``AMBIGUOUS`` status, and the reviewer chooses the passage.
    """
    page = _page(session, request.document_id, request.page_number)
    if page is None or not page.text:
        return None
    fields = provenance.build_citation(
        page_text=page.text,
        quote=candidate.quote,
        words=geometry.words_from_json(page.words),
    )
    if fields.citation_status == CitationStatus.UNRESOLVED:
        return None
    return fields


def extract_document(
    session: Session,
    document: SourceDocument,
    *,
    actor: CurrentUser,
    provider: ExtractionProvider | None = None,
    max_chunk_chars: int = chunker.DEFAULT_CHUNK_CHARS,
) -> ExtractionReport:
    """Read one document and propose facts from it. Verifies nothing."""
    provider = provider or get_extraction_provider()
    requests = chunker.chunk_document(document, max_chunk_chars)

    report = ExtractionReport(
        document_id=document.id,
        provider=provider.name,
        model=getattr(provider, "model", None),
        prompt_version=PROMPT_VERSION,
        chunks=len(requests),
    )

    for request in requests:
        response = provider.extract(request)
        if response.contains_suspected_injection:
            report.suspected_injection_chunks.append(request.chunk_index)
        report.candidates += len(response.candidates)

        for candidate in response.candidates:
            fact = _propose_candidate(session, document, request, candidate, actor, report)
            if fact is not None:
                report.proposed_fact_ids.append(fact.id)

    audit.record(
        session,
        event="FACTS_EXTRACTED",
        actor=actor,
        case_id=document.case_id,
        subject_id=document.id,
        payload=report.to_dict(),
    )
    session.flush()
    return report


def _propose_candidate(
    session: Session,
    document: SourceDocument,
    request: ExtractionRequest,
    candidate: Candidate,
    actor: CurrentUser,
    report: ExtractionReport,
) -> Fact | None:
    if not candidate.summary.strip():
        report.rejected.append({"summary": candidate.summary, "reason": EMPTY_SUMMARY})
        return None
    if candidate.fact_type not in _VALID_FACT_TYPES:
        report.rejected.append(
            {"summary": candidate.summary[:120], "reason": UNKNOWN_TYPE,
             "fact_type": candidate.fact_type}
        )
        return None

    resolved = _resolve_citation(session, request, candidate)
    if resolved is None:
        # The provider quoted something the document does not contain. There is
        # no evidence here, so there is no fact.
        report.rejected.append(
            {"summary": candidate.summary[:120], "reason": NO_CITATION,
             "quote": candidate.quote[:160]}
        )
        return None

    fact = Fact(
        case_id=document.case_id,
        fact_type=FactType(candidate.fact_type),
        value=dict(candidate.value),
        summary=candidate.summary.strip(),
        # The one status machine extraction may create. Nothing verifies itself.
        status=FactStatus.PROPOSED,
        confidence=candidate.confidence,
        proposed_by=f"{report.provider}:{actor.id}",
        extraction_metadata={
            "provider": report.provider,
            "model": report.model,
            "prompt_version": report.prompt_version,
            "document_id": document.id,
            "page_number": request.page_number,
            "chunk_index": request.chunk_index,
            "match_kind": resolved.match_kind,
            "citation_status": resolved.citation_status.value,
            "similarity": resolved.confidence,
            "low_confidence": candidate.confidence < LOW_CONFIDENCE,
            "extracted_at": _now().isoformat(),
        },
    )
    session.add(fact)
    session.flush()

    session.add(
        FactSource(
            fact_id=fact.id,
            document_id=document.id,
            page_number=request.page_number,
            **resolved.as_kwargs(),
        )
    )
    audit.record(
        session,
        event="FACT_PROPOSED",
        actor=actor,
        case_id=document.case_id,
        subject_id=fact.id,
        payload={
            "fact_type": candidate.fact_type,
            "summary": fact.summary,
            "revision": 1,
            "source": "extraction",
            "provider": report.provider,
            "confidence": candidate.confidence,
            "citation": {
                "document_id": document.id,
                "page": request.page_number,
                "start_offset": resolved.start_offset,
                "end_offset": resolved.end_offset,
                "match_kind": resolved.match_kind,
                "citation_status": resolved.citation_status.value,
                "bounding_boxes": len(resolved.bounding_boxes or []),
            },
        },
    )
    session.flush()
    return fact


def extract_case(
    session: Session,
    case_id: str,
    *,
    actor: CurrentUser,
    provider: ExtractionProvider | None = None,
    document_ids: list[str] | None = None,
) -> list[ExtractionReport]:
    """Run extraction across a case's documents."""
    provider = provider or get_extraction_provider()
    stmt = select(SourceDocument).where(SourceDocument.case_id == case_id)
    if document_ids:
        stmt = stmt.where(SourceDocument.id.in_(document_ids))
    documents = list(session.scalars(stmt.order_by(SourceDocument.created_at)))

    reports: list[ExtractionReport] = []
    for document in documents:
        if not document.pages:
            continue
        reports.append(extract_document(session, document, actor=actor, provider=provider))
    return reports


__all__ = [
    "ExtractionError",
    "ExtractionReport",
    "extract_case",
    "extract_document",
]
