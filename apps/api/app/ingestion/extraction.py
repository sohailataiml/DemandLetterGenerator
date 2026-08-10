"""Text extraction, split by page.

Page granularity is the point: a verified fact cites a document *and a page*, so
"where did this figure come from" is answerable down to the page a reviewer can
open. Formats we cannot read are marked NEEDS_OCR rather than silently stored as
empty text.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from ..domain.enums import DocumentStatus


@dataclass(frozen=True)
class ExtractionResult:
    pages: list[str]
    status: DocumentStatus
    note: str | None = None

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def full_text(self) -> str:
        return "\n\n".join(self.pages)


def extract(data: bytes, mime_type: str, filename: str) -> ExtractionResult:
    if mime_type in ("text/plain", "text/markdown"):
        return _extract_text(data)
    if mime_type == "application/pdf":
        return _extract_pdf(data)
    if mime_type.startswith("application/vnd.openxmlformats-officedocument.wordprocessingml"):
        return _extract_docx(data)
    if mime_type.startswith("image/"):
        return ExtractionResult(
            pages=[""],
            status=DocumentStatus.NEEDS_OCR,
            note="image upload; OCR not configured, no text indexed",
        )
    return ExtractionResult(
        pages=[""],
        status=DocumentStatus.EXTRACTION_FAILED,
        note=f"no extractor for {mime_type}",
    )


def _extract_text(data: bytes) -> ExtractionResult:
    text = data.decode("utf-8", errors="replace")
    # Honour explicit form feeds; otherwise the whole file is one page.
    pages = text.split("\f") if "\f" in text else [text]
    return ExtractionResult(pages=[p.strip() for p in pages], status=DocumentStatus.EXTRACTED)


def _extract_pdf(data: bytes) -> ExtractionResult:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return ExtractionResult(
            pages=[""],
            status=DocumentStatus.NEEDS_OCR,
            note="pypdf is not installed; PDF stored without text extraction",
        )
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:  # pragma: no cover - depends on the file
        return ExtractionResult(
            pages=[""], status=DocumentStatus.EXTRACTION_FAILED, note=f"pypdf error: {exc}"
        )
    if not any(pages):
        return ExtractionResult(
            pages=pages or [""],
            status=DocumentStatus.NEEDS_OCR,
            note="PDF contains no extractable text layer (likely a scan)",
        )
    return ExtractionResult(pages=pages, status=DocumentStatus.EXTRACTED)


def _extract_docx(data: bytes) -> ExtractionResult:
    try:
        import docx  # type: ignore
    except ImportError:  # pragma: no cover - dependency is declared
        return ExtractionResult(
            pages=[""], status=DocumentStatus.EXTRACTION_FAILED, note="python-docx not installed"
        )
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # pragma: no cover - depends on the file
        return ExtractionResult(
            pages=[""], status=DocumentStatus.EXTRACTION_FAILED, note=f"python-docx error: {exc}"
        )
    blocks = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    text = "\n".join(blocks)
    return ExtractionResult(
        pages=[text] if text else [""],
        status=DocumentStatus.EXTRACTED if text else DocumentStatus.NEEDS_OCR,
        note=None if text else "DOCX contained no text",
    )
