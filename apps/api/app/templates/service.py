"""Persistence and orchestration for uploaded letter templates.

Uploading stores the exact bytes immutably and records the manifest. Rendering
reads those same bytes back, binds values into a clone, and re-analyzes the
result to prove nothing else moved. The template row is never updated after
creation — a corrected template is a new row, the same way a corrected fact is
a new revision.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import service as audit
from ..domain.models import Demand, LetterTemplate
from ..ingestion.storage import ObjectStore, get_object_store, sha256_hex
from ..security.auth import CurrentUser
from . import analyzer, binder, fidelity, slots
from .manifest import TemplateManifest

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TemplateError(ValueError):
    """The template could not be stored or used."""


class DuplicateTemplateError(TemplateError):
    def __init__(self, existing: LetterTemplate) -> None:
        self.existing = existing
        super().__init__(
            f"an identical template is already on file for this case as {existing.id}"
        )


def template_key(case_id: str | None, sha256: str) -> str:
    scope = f"cases/{case_id}" if case_id else "shared"
    return f"{scope}/templates/{sha256}.docx"


@dataclass(frozen=True)
class RenderedTemplate:
    """The bytes produced by binding, plus everything needed to defend them."""

    data: bytes
    sha256: str
    bind_report: binder.BindReport
    fidelity_report: fidelity.FidelityReport
    unresolved_slots: tuple[str, ...]


# --------------------------------------------------------------------------- upload


def store_template(
    session: Session,
    *,
    case_id: str | None,
    name: str,
    filename: str,
    data: bytes,
    actor: CurrentUser,
    store: ObjectStore | None = None,
) -> LetterTemplate:
    """Analyze and persist an attorney template. Raises on an unreadable file."""
    store = store or get_object_store()
    manifest = analyzer.analyze(data)  # raises TemplateAnalysisError
    digest = manifest.fingerprint.sha256

    existing = session.scalar(
        select(LetterTemplate).where(
            LetterTemplate.case_id == case_id, LetterTemplate.sha256 == digest
        )
    )
    if existing is not None:
        raise DuplicateTemplateError(existing)

    key = template_key(case_id, digest)
    store.put(key, data, immutable=True)

    template = LetterTemplate(
        case_id=case_id,
        name=name,
        original_filename=filename,
        sha256=digest,
        structure_sha256=manifest.fingerprint.structure_sha256,
        size_bytes=len(data),
        storage_key=key,
        manifest=manifest.to_dict(),
        slot_names=list(manifest.slot_names()),
        block_count=len(manifest.blocks),
        uploaded_by=actor.id,
    )
    session.add(template)
    session.flush()

    audit.record(
        session,
        event="TEMPLATE_INGESTED",
        actor=actor,
        case_id=case_id,
        subject_id=template.id,
        payload={
            "sha256": digest,
            "structure_sha256": manifest.fingerprint.structure_sha256,
            "blocks": len(manifest.blocks),
            "slots": list(manifest.slot_names()),
            "sections": [s.key for s in manifest.sections],
            "headers": len(manifest.headers),
            "footers": len(manifest.footers),
        },
    )
    session.flush()
    return template


def load_manifest(template: LetterTemplate) -> TemplateManifest:
    return TemplateManifest.from_dict(template.manifest)


def template_bytes(template: LetterTemplate, store: ObjectStore | None = None) -> bytes:
    store = store or get_object_store()
    data = store.get(template.storage_key)
    actual = sha256_hex(data)
    if actual != template.sha256:  # pragma: no cover - storage corruption
        raise TemplateError(
            f"stored template {template.id} no longer matches its recorded hash "
            f"({actual} != {template.sha256})"
        )
    return data


# --------------------------------------------------------------------------- render


def render_from_template(
    template: LetterTemplate,
    context,
    sections: dict[str, str],
    *,
    store: ObjectStore | None = None,
) -> RenderedTemplate:
    """Bind ``sections`` and deterministic case values into the attorney's file."""
    source = template_bytes(template, store)
    manifest = load_manifest(template)

    # A template the system cannot fill is a template error, surfaced as one.
    # Rendering a partially bound letter would be the worse outcome.
    try:
        values, unresolved = slots.build_values(manifest.slot_names(), context, sections)
        data, bind_report = binder.bind(source, manifest, values)
    except (slots.UnknownSlotError, binder.SlotBindingError) as exc:
        raise TemplateError(str(exc)) from exc

    report = fidelity.compare(manifest, analyzer.analyze(data))
    if unresolved:
        report = fidelity.FidelityReport(
            template_hash=report.template_hash,
            required_blocks_expected=report.required_blocks_expected,
            required_blocks_preserved=report.required_blocks_preserved,
            styles_changed=report.styles_changed,
            headers_changed=report.headers_changed,
            footers_changed=report.footers_changed,
            numbering_changed=report.numbering_changed,
            page_setup_changed=report.page_setup_changed,
            issues=report.issues
            + tuple(
                fidelity.FidelityIssue(
                    code=fidelity.TEMPLATE_UNRESOLVED,
                    severity=fidelity.BLOCKING,
                    message=(
                        f"Template slot '{name}' has no case data behind it; the letter would "
                        "print a placeholder where a value belongs."
                    ),
                    details={"slot": name},
                )
                for name in unresolved
            ),
        )

    leftover = binder.unbound_placeholders(data)
    if leftover:  # pragma: no cover - bind() raises before this is reachable
        raise TemplateError(
            "generated document still contains unbound placeholders: " + ", ".join(leftover)
        )

    return RenderedTemplate(
        data=data,
        sha256=sha256_hex(data),
        bind_report=bind_report,
        fidelity_report=report,
        unresolved_slots=tuple(unresolved),
    )


# --------------------------------------------------------------------------- binding


def bind_template_to_demand(
    session: Session, demand: Demand, template: LetterTemplate, *, actor: CurrentUser
) -> Demand:
    if demand.locked:
        raise TemplateError(f"demand {demand.id} is approved and locked")
    if template.case_id is not None and template.case_id != demand.case_id:
        raise TemplateError("template belongs to a different case")
    demand.template_id = template.id
    demand.template_sha256 = template.sha256
    audit.record(
        session,
        event="DEMAND_TEMPLATE_BOUND",
        actor=actor,
        case_id=demand.case_id,
        demand_id=demand.id,
        subject_id=template.id,
        payload={"template_sha256": template.sha256, "slots": list(template.slot_names or [])},
    )
    session.flush()
    return demand


def render_demand(
    session: Session, demand: Demand, context, *, store: ObjectStore | None = None
) -> RenderedTemplate | None:
    """Bind the demand's sections into its template, or ``None`` if unbound.

    Raises :class:`TemplateError` subclasses on a binding failure — a demand
    that cannot be bound must not fall back to a rebuilt document, because that
    would silently produce a letter in the wrong format.
    """
    if not demand.template_id:
        return None
    template = session.get(LetterTemplate, demand.template_id)
    if template is None:  # pragma: no cover - FK is SET NULL
        raise TemplateError(f"demand {demand.id} references a template that no longer exists")
    sections = {section.key: section.body for section in demand.sections}
    return render_from_template(template, context, sections, store=store)


def record_reports(demand: Demand, rendered: RenderedTemplate) -> None:
    demand.fidelity_report = rendered.fidelity_report.to_dict()
    demand.bind_report = rendered.bind_report.to_dict()


def list_templates(session: Session, case_id: str) -> list[LetterTemplate]:
    return list(
        session.scalars(
            select(LetterTemplate)
            .where(LetterTemplate.case_id == case_id)
            .order_by(LetterTemplate.created_at.desc())
        )
    )
