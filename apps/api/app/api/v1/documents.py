"""Source document ingestion and retrieval."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db import get_db
from ...domain.enums import DocumentType
from ...domain.models import Case, DocumentPage, SourceDocument
from ...domain.schemas import (
    DocumentDetailOut,
    DocumentOut,
    DocumentPageOut,
    PageGeometryOut,
    UploadLimitsOut,
    WordGeometryOut,
)
from ...ingestion import scanner
from ...ingestion.scanner import UnsafeFileError
from ...ingestion.service import (
    DocumentInUseError,
    DuplicateDocumentError,
    ingest_document,
    remove_document,
)
from ...ingestion.storage import get_object_store
from ...security.auth import CurrentUser, can_edit_case, can_read
from ..deps import get_case, get_document
from .templates import MAX_TEMPLATE_BYTES

router = APIRouter(tags=["documents"])


@router.post(
    "/cases/{case_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED
)
async def upload_document(
    file: UploadFile = File(...),
    document_type: DocumentType | None = Form(default=None),
    provider_name: str | None = Form(default=None),
    document_date: date | None = Form(default=None),
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> SourceDocument:
    data = await file.read()
    try:
        return ingest_document(
            db,
            case_id=case.id,
            filename=file.filename or "upload",
            data=data,
            actor=user,
            declared_mime=file.content_type,
            document_type=document_type,
            provider_name=provider_name,
            document_date=document_date,
        )
    except UnsafeFileError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "existing_document_id": exc.existing.id},
        ) from exc


@router.get("/upload-limits", response_model=UploadLimitsOut)
def get_upload_limits(user: CurrentUser = Depends(can_read)) -> UploadLimitsOut:
    """The size and type limits the ingestion path enforces.

    Exposed so the uploader can validate and label itself from one source of
    truth. Client-side checks here are a courtesy that saves a doomed upload;
    the server re-validates every byte either way.
    """
    settings = get_settings()
    return UploadLimitsOut(
        max_upload_bytes=settings.max_upload_bytes,
        allowed_mime_types=scanner.allowed_mime_types(),
        allowed_extensions=scanner.allowed_extensions(),
        max_template_bytes=MAX_TEMPLATE_BYTES,
        template_mime_types=[scanner.DOCX_MIME],
        template_extensions=[".docx"],
    )


@router.get("/cases/{case_id}/documents", response_model=list[DocumentOut])
def list_documents(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[SourceDocument]:
    return list(
        db.scalars(
            select(SourceDocument)
            .where(SourceDocument.case_id == case.id)
            .order_by(SourceDocument.created_at.desc())
        )
    )


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def get_document_detail(
    document: SourceDocument = Depends(get_document),
    user: CurrentUser = Depends(can_read),
) -> SourceDocument:
    return document


@router.get("/documents/{document_id}/pages/{page_number}", response_model=DocumentPageOut)
def get_document_page(
    page_number: int,
    document: SourceDocument = Depends(get_document),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> DocumentPageOut:
    """One page of canonical text — the string every citation offset indexes.

    Deliberately excludes the word array: the evidence viewer asks for geometry
    separately, and only for the page it is actually showing.
    """
    return _page_out(_require_page(db, document, page_number))


@router.get(
    "/documents/{document_id}/pages/{page_number}/geometry", response_model=PageGeometryOut
)
def get_document_page_geometry(
    page_number: int,
    document: SourceDocument = Depends(get_document),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> PageGeometryOut:
    """Word rectangles for one page, normalized to the rendered page.

    Loaded lazily by the evidence viewer. A page with no text layer returns an
    empty ``words`` list rather than an error: "this page has no geometry" is a
    real answer, and the viewer says so instead of drawing something.
    """
    page = _require_page(db, document, page_number)
    return PageGeometryOut(
        document_id=document.id,
        page_number=page.page_number,
        width=page.width,
        height=page.height,
        extraction_method=page.extraction_method,
        words=[WordGeometryOut.model_validate(word) for word in (page.words or [])],
    )


def _require_page(db: Session, document: SourceDocument, page_number: int) -> DocumentPage:
    page = db.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document.id,
            DocumentPage.page_number == page_number,
        )
    )
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"document {document.id} has no page {page_number}",
        )
    return page


def _page_out(page: DocumentPage) -> DocumentPageOut:
    return DocumentPageOut(
        page_number=page.page_number,
        text=page.text,
        width=page.width,
        height=page.height,
        extraction_method=page.extraction_method,
        word_count=page.word_count,
        has_geometry=page.has_geometry,
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document: SourceDocument = Depends(get_document),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> Response:
    """Remove an uploaded file, unless a fact cites it."""
    try:
        remove_document(db, document=document, actor=user)
    except DocumentInUseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "fact_ids": exc.fact_ids},
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{document_id}/content")
def download_document(
    document: SourceDocument = Depends(get_document),
    user: CurrentUser = Depends(can_read),
) -> Response:
    data = get_object_store().get(document.storage_key)
    return Response(
        content=data,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.original_filename}"',
            "X-Content-SHA256": document.sha256,
        },
    )
