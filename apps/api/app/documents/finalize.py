"""Artifact generation, attorney approval, and locking.

The approval path is deliberately narrow: re-validate against current data,
refuse while any BLOCKING issue stands, then produce the exact bytes that were
approved and hash them. After that the demand is locked — regeneration and
section edits both fail.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..audit import service as audit
from ..domain.enums import DemandStatus, Severity
from ..domain.models import Demand
from ..generation.composer import validate_demand
from ..generation.context import build_context
from ..ingestion.storage import ObjectStore, artifact_key, get_object_store, sha256_hex
from ..security.auth import CurrentUser
from .docx_renderer import render_docx


class ApprovalBlockedError(RuntimeError):
    """Approval was refused because blocking issues remain or review is incomplete."""

    def __init__(self, message: str, issues: list | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


class PdfUnavailableError(RuntimeError):
    """No PDF converter is available in this environment."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_docx(
    session: Session,
    demand: Demand,
    *,
    actor: CurrentUser,
    store: ObjectStore | None = None,
    final: bool = False,
) -> tuple[bytes, str, str]:
    """Render, store, and hash the DOCX. Returns ``(data, key, sha256)``."""
    store = store or get_object_store()
    context = build_context(session, demand)
    data = render_docx(demand, context, store=store, watermark_draft=not final)
    digest = sha256_hex(data)
    filename = "final.docx" if final else f"draft-v{demand.version}.docx"
    key = artifact_key(demand.case_id, demand.id, filename)
    store.put(key, data, immutable=final)

    demand.docx_key = key
    demand.docx_sha256 = digest
    audit.record(
        session,
        event="DEMAND_DOCX_GENERATED",
        actor=actor,
        case_id=demand.case_id,
        demand_id=demand.id,
        payload={"key": key, "sha256": digest, "final": final},
    )
    session.flush()
    return data, key, digest


def build_pdf(
    session: Session,
    demand: Demand,
    *,
    actor: CurrentUser,
    store: ObjectStore | None = None,
    final: bool = False,
    docx_data: bytes | None = None,
) -> tuple[bytes, str, str]:
    """Convert the DOCX to PDF via LibreOffice.

    There is no pure-Python fallback that preserves the letterhead faithfully, so
    if no converter is installed this raises rather than shipping a lookalike.

    ``docx_data`` lets a caller that already rendered the document hand those
    exact bytes over. Re-rendering would produce a different file — python-docx
    stamps each render with the current time — which for a final artifact means
    a PDF that does not correspond to the approved DOCX.
    """
    store = store or get_object_store()
    if docx_data is None:
        docx_data, _, _ = build_docx(session, demand, actor=actor, store=store, final=final)

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        raise PdfUnavailableError(
            "PDF generation requires LibreOffice ('soffice') on PATH. "
            "The DOCX is available and unaffected."
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "demand.docx"
        source.write_bytes(docx_data)
        result = subprocess.run(  # noqa: S603 - fixed binary, no shell
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(source)],
            capture_output=True,
            timeout=180,
        )
        produced = tmp_path / "demand.pdf"
        if result.returncode != 0 or not produced.exists():
            raise PdfUnavailableError(
                f"LibreOffice conversion failed: {result.stderr.decode(errors='replace')[:500]}"
            )
        pdf_data = produced.read_bytes()

    digest = sha256_hex(pdf_data)
    filename = "final.pdf" if final else f"draft-v{demand.version}.pdf"
    key = artifact_key(demand.case_id, demand.id, filename)
    store.put(key, pdf_data, immutable=final)

    demand.pdf_key = key
    demand.pdf_sha256 = digest
    audit.record(
        session,
        event="DEMAND_PDF_GENERATED",
        actor=actor,
        case_id=demand.case_id,
        demand_id=demand.id,
        payload={"key": key, "sha256": digest, "final": final},
    )
    session.flush()
    return pdf_data, key, digest


def load_or_build_docx(
    session: Session,
    demand: Demand,
    *,
    actor: CurrentUser,
    store: ObjectStore | None = None,
) -> tuple[bytes, str | None]:
    """Bytes for download.

    An approved demand serves the artifact that was approved and hashed — the
    stored object, byte for byte. Only a draft is rendered on demand.
    """
    store = store or get_object_store()
    if demand.locked and demand.docx_key and store.exists(demand.docx_key):
        return store.get(demand.docx_key), demand.docx_sha256
    data, _, digest = build_docx(session, demand, actor=actor, store=store, final=demand.locked)
    return data, digest


def load_or_build_pdf(
    session: Session,
    demand: Demand,
    *,
    actor: CurrentUser,
    store: ObjectStore | None = None,
) -> tuple[bytes, str | None]:
    """As above for PDF.

    If a demand was approved without a converter available, the PDF is generated
    from the *stored* DOCX rather than from a new render, so it still matches the
    approved document.
    """
    store = store or get_object_store()
    if demand.locked and demand.pdf_key and store.exists(demand.pdf_key):
        return store.get(demand.pdf_key), demand.pdf_sha256

    approved_docx = (
        store.get(demand.docx_key)
        if demand.locked and demand.docx_key and store.exists(demand.docx_key)
        else None
    )
    data, _, digest = build_pdf(
        session,
        demand,
        actor=actor,
        store=store,
        final=demand.locked,
        docx_data=approved_docx,
    )
    return data, digest


def approve_demand(
    session: Session,
    demand: Demand,
    *,
    actor: CurrentUser,
    acknowledgement: str,
    store: ObjectStore | None = None,
    require_pdf: bool = False,
) -> Demand:
    if demand.locked:
        raise ApprovalBlockedError(f"demand {demand.id} is already approved and locked")
    if not demand.sections:
        raise ApprovalBlockedError("demand has not been generated yet")
    if not actor.is_attorney:
        raise ApprovalBlockedError("only an attorney may approve a demand")

    expected = demand.case.reference if demand.case else None
    if expected and acknowledgement.strip() != expected:
        raise ApprovalBlockedError(
            "acknowledgement must be the case reference to confirm the draft was reviewed"
        )

    issues = validate_demand(session, demand, actor=actor)
    blocking = [i for i in issues if i.severity == Severity.BLOCKING]
    if blocking:
        raise ApprovalBlockedError(
            f"{len(blocking)} blocking validation issue(s) must be resolved before approval",
            issues=blocking,
        )

    store = store or get_object_store()
    demand.status = DemandStatus.APPROVED
    demand.approved_by = actor.id
    demand.approved_at = _now()
    demand.locked = True
    session.flush()

    docx_data, docx_key, docx_sha = build_docx(
        session, demand, actor=actor, store=store, final=True
    )

    pdf_sha = None
    pdf_note = None
    try:
        # Convert the exact bytes just approved, never a fresh render of them.
        _, _, pdf_sha = build_pdf(
            session, demand, actor=actor, store=store, final=True, docx_data=docx_data
        )
    except PdfUnavailableError as exc:
        if require_pdf:
            # Roll the approval back rather than record an approval we cannot fulfil.
            session.rollback()
            raise
        pdf_note = str(exc)

    audit.record(
        session,
        event="DEMAND_APPROVED",
        actor=actor,
        case_id=demand.case_id,
        demand_id=demand.id,
        payload={
            "demand_version": demand.version,
            "approved_by": actor.id,
            "timestamp": demand.approved_at.isoformat() if demand.approved_at else None,
            "docx_key": docx_key,
            "docx_sha256": docx_sha,
            "pdf_sha256": pdf_sha,
            "pdf_note": pdf_note,
            "warnings": [i.code for i in issues if i.severity == Severity.WARNING],
        },
    )
    session.flush()
    session.refresh(demand)
    return demand
