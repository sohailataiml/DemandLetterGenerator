"""Ingestion pipeline: validate → scan → store → extract → paginate → classify."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import service as audit
from ..domain.enums import DocumentType
from ..domain.models import DocumentPage, SourceDocument
from ..security.auth import CurrentUser
from . import classifier
from .extraction import extract
from .scanner import UnsafeFileError, scan  # noqa: F401  (re-exported for the API layer)
from .storage import ObjectStore, document_key, get_object_store, sha256_hex


class DuplicateDocumentError(ValueError):
    """The identical bytes are already on file for this case."""

    def __init__(self, existing: SourceDocument) -> None:
        super().__init__(
            f"document with sha256 {existing.sha256} already ingested as {existing.id}"
        )
        self.existing = existing


def ingest_document(
    session: Session,
    *,
    case_id: str,
    filename: str,
    data: bytes,
    actor: CurrentUser,
    declared_mime: str | None = None,
    document_type: DocumentType | None = None,
    provider_name: str | None = None,
    document_date: date | None = None,
    store: ObjectStore | None = None,
) -> SourceDocument:
    store = store or get_object_store()

    scan_result = scan(filename, data, declared_mime)
    digest = sha256_hex(data)

    existing = session.scalar(
        select(SourceDocument).where(
            SourceDocument.case_id == case_id, SourceDocument.sha256 == digest
        )
    )
    if existing is not None:
        raise DuplicateDocumentError(existing)

    extraction = extract(data, scan_result.mime_type, filename)

    key = document_key(case_id, digest, filename)
    store.put(key, data, immutable=True)

    resolved_type = document_type or classifier.classify(
        filename, extraction.full_text, scan_result.mime_type
    )
    resolved_provider = provider_name or classifier.guess_provider(extraction.full_text)
    resolved_date = document_date or classifier.guess_document_date(extraction.full_text)

    document = SourceDocument(
        case_id=case_id,
        document_type=resolved_type,
        provider_name=resolved_provider,
        document_date=resolved_date,
        original_filename=filename,
        mime_type=scan_result.mime_type,
        size_bytes=scan_result.size_bytes,
        page_count=extraction.page_count,
        sha256=digest,
        storage_key=key,
        status=extraction.status,
        extraction_note=extraction.note,
        uploaded_by=actor.id,
    )
    session.add(document)
    session.flush()

    for index, text in enumerate(extraction.pages, start=1):
        session.add(DocumentPage(document_id=document.id, page_number=index, text=text))

    audit.record(
        session,
        event="DOCUMENT_INGESTED",
        actor=actor,
        case_id=case_id,
        subject_id=document.id,
        payload={
            "sha256": digest,
            "document_type": resolved_type.value,
            "page_count": extraction.page_count,
            "status": extraction.status.value,
            "storage_key": key,
        },
    )
    session.flush()
    return document
