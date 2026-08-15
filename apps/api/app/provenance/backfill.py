"""Adding geometry to documents and precision to citations already on file.

Everything here is metadata enrichment, and the distinction matters legally, not
just architecturally:

* **Documents are not re-extracted.** The stored page text is left exactly as it
  is, because citation offsets already point into it. Words recovered from the
  original file are *aligned* onto that text, and a page whose words cannot be
  walked through it in order is simply left without geometry.
* **Facts are not touched.** No value, summary, status, reviewer or timestamp is
  read or written here. A VERIFIED fact still asserts precisely what the
  attorney approved; all that changes is how well the system can show where that
  assertion came from.
* **Precision is never invented.** A citation recorded as an approximate match
  stays ``TEXT_ONLY`` and gets no rectangles, even though its stored excerpt was
  copied out of the page and would trivially "match" if re-resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from ..domain.enums import CitationStatus
from ..domain.models import DocumentPage, FactSource, SourceDocument
from ..ingestion import pdf_geometry
from ..ingestion.storage import ObjectStore, get_object_store
from . import citations, geometry
from . import service as provenance

PDF_MIME = "application/pdf"


@dataclass
class BackfillReport:
    """What a run did, in the terms the operator needs to check it."""

    documents_examined: int = 0
    documents_with_geometry: int = 0
    pages_with_geometry: int = 0
    pages_unalignable: int = 0
    citations_examined: int = 0
    #: Outcome distribution over every citation examined, changed or not.
    exact: int = 0
    ambiguous: int = 0
    text_only: int = 0
    unresolved: int = 0
    #: Movements: citations that became EXACT, and ones that gained rectangles.
    exact_upgraded: int = 0
    boxes_added: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "documents_examined": self.documents_examined,
            "documents_with_geometry": self.documents_with_geometry,
            "pages_with_geometry": self.pages_with_geometry,
            "pages_unalignable": self.pages_unalignable,
            "citations_examined": self.citations_examined,
            "exact": self.exact,
            "ambiguous": self.ambiguous,
            "text_only": self.text_only,
            "unresolved": self.unresolved,
            "exact_upgraded": self.exact_upgraded,
            "boxes_added": self.boxes_added,
            "notes": list(self.notes),
        }


def run(
    session: Session, *, store: ObjectStore | None = None, case_id: str | None = None
) -> BackfillReport:
    report = BackfillReport()
    store = store or get_object_store()

    documents = select(SourceDocument)
    if case_id:
        documents = documents.where(SourceDocument.case_id == case_id)
    for document in session.scalars(documents):
        report.documents_examined += 1
        _backfill_document_geometry(session, document, store, report)

    sources = select(FactSource)
    if case_id:
        sources = sources.join(SourceDocument, FactSource.document_id == SourceDocument.id).where(
            SourceDocument.case_id == case_id
        )
    for citation in session.scalars(sources):
        report.citations_examined += 1
        _backfill_citation(session, citation, report)

    session.flush()
    return report


def _backfill_document_geometry(
    session: Session,
    document: SourceDocument,
    store: ObjectStore,
    report: BackfillReport,
) -> None:
    if document.mime_type != PDF_MIME:
        return
    pages = list(
        session.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .options(undefer(DocumentPage.words))
            .order_by(DocumentPage.page_number)
        )
    )
    if not pages or all(page.word_count for page in pages):
        if pages and all(page.word_count for page in pages):
            report.documents_with_geometry += 1
        return

    try:
        data = store.get(document.storage_key)
    except OSError as exc:
        report.notes.append(f"{document.id}: original bytes unreadable ({exc})")
        return

    extracted = pdf_geometry.extract(data)
    if extracted is None:
        report.notes.append(
            f"{document.id}: no PDF geometry backend available (pip install pymupdf)"
        )
        return

    added = 0
    for page in pages:
        source = next(
            (item for item in extracted if item.geometry.page_number == page.page_number), None
        )
        if source is None or not source.geometry.words:
            continue
        # The stored text is authoritative; the words come to it, never the
        # other way round.
        aligned = geometry.align_words_to_text(page.text, source.geometry.words)
        if aligned is None:
            report.pages_unalignable += 1
            report.notes.append(
                f"{document.id} page {page.page_number}: words do not align with the stored "
                "page text; left without geometry"
            )
            continue
        page.width = source.geometry.width
        page.height = source.geometry.height
        page.extraction_method = source.geometry.extraction_method
        page.word_count = len(aligned)
        page.words = [word.to_dict() for word in aligned]
        added += 1

    report.pages_with_geometry += added
    if added:
        report.documents_with_geometry += 1


def _backfill_citation(session: Session, citation: FactSource, report: BackfillReport) -> None:
    page = _page(session, citation)
    page_text = page.text if page else ""
    words = geometry.words_from_json(page.words) if page else ()

    if not citation.excerpt or not page_text:
        _apply(citation, provenance.unresolved(citation.excerpt), report)
        return

    if citation.match_kind == citations.MatchKind.APPROXIMATE.value:
        # The excerpt on file is a window of page text that a paraphrase was
        # aligned to. Re-resolving it would "find" it verbatim and dress a fuzzy
        # match up as an exact one.
        citation.citation_status = CitationStatus.TEXT_ONLY
        citation.bounding_boxes = None
        report.text_only += 1
        return

    if (
        citation.start_offset is not None
        and citation.end_offset is not None
        and citation.quoted_text_sha256
        and citations.verify_offsets(
            page_text, citation.start_offset, citation.end_offset, citation.quoted_text_sha256
        )
    ):
        # The recorded offsets still quote what they were recorded against, so
        # they stand as they are and only the geometry is new.
        boxes = provenance.geometry_for_span(
            page_text, words, citation.start_offset, citation.end_offset
        )
        _set_exact(citation, boxes, report, page_has_words=bool(words))
        return

    _apply(
        citation,
        provenance.build_citation(page_text=page_text, quote=citation.excerpt, words=words),
        report,
    )


def _set_exact(
    citation: FactSource,
    boxes: Sequence[geometry.BoundingBox],
    report: BackfillReport,
    *,
    page_has_words: bool,
) -> None:
    """Keep the offsets, replace the geometry with whatever the page now says.

    When the page carries words, this derivation is authoritative in both
    directions: boxes that can no longer be derived are cleared rather than left
    behind pointing at a region nothing verifies.
    """
    was_exact = citation.citation_status == CitationStatus.EXACT
    had_boxes = bool(citation.bounding_boxes)
    citation.citation_status = CitationStatus.EXACT
    citation.confidence = citation.confidence if citation.confidence is not None else 1.0
    if page_has_words:
        citation.bounding_boxes = geometry.boxes_to_json(boxes) if boxes else None
        if boxes and not had_boxes:
            report.boxes_added += 1
    report.exact += 1
    if not was_exact:
        report.exact_upgraded += 1


def _apply(citation: FactSource, provenance_fields, report: BackfillReport) -> None:
    was_exact = citation.citation_status == CitationStatus.EXACT
    had_boxes = bool(citation.bounding_boxes)
    for column, value in provenance_fields.as_kwargs().items():
        setattr(citation, column, value)

    status = provenance_fields.citation_status
    if status == CitationStatus.EXACT:
        report.exact += 1
        if not was_exact:
            report.exact_upgraded += 1
        if provenance_fields.bounding_boxes and not had_boxes:
            report.boxes_added += 1
    elif status == CitationStatus.AMBIGUOUS:
        report.ambiguous += 1
    elif status == CitationStatus.TEXT_ONLY:
        report.text_only += 1
    else:
        report.unresolved += 1


def _page(session: Session, citation: FactSource) -> DocumentPage | None:
    if citation.page_number is None:
        return None
    return session.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == citation.document_id,
            DocumentPage.page_number == citation.page_number,
        )
    )
