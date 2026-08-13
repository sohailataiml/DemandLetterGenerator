"""Attorney template upload, inspection, and binding to a demand."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ...db import get_db
from ...domain.models import Case, Demand, LetterTemplate
from ...domain.schemas import (
    FidelityReportOut,
    TemplateBindIn,
    TemplateDetailOut,
    TemplateOut,
    TemplateSectionOut,
    TemplateSlotOut,
)
from ...security.auth import CurrentUser, can_edit_case, can_read
from ...templates import service as template_service
from ...templates import slots as slot_catalog
from ...templates.analyzer import TemplateAnalysisError
from ..deps import get_case, get_demand

router = APIRouter(tags=["templates"])

MAX_TEMPLATE_BYTES = 20 * 1024 * 1024


def _get_template(
    template_id: str, db: Session = Depends(get_db)
) -> LetterTemplate:
    template = db.get(LetterTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"template {template_id} not found"
        )
    return template


def _detail(template: LetterTemplate) -> TemplateDetailOut:
    manifest = template_service.load_manifest(template)
    known = set(slot_catalog.known_slot_names())
    unknown = [
        slot.name
        for slot in manifest.slots
        if slot.name.split("[].", 1)[0] not in known
        and not slot.name.startswith(slot_catalog.SECTION_PREFIX)
    ]
    return TemplateDetailOut(
        id=template.id,
        case_id=template.case_id,
        name=template.name,
        original_filename=template.original_filename,
        sha256=template.sha256,
        structure_sha256=template.structure_sha256,
        size_bytes=template.size_bytes,
        block_count=template.block_count,
        slot_names=list(template.slot_names or []),
        uploaded_by=template.uploaded_by,
        created_at=template.created_at,
        slots=[
            TemplateSlotOut(
                name=slot.name,
                kind=slot.kind.value,
                block_index=slot.block_index,
                section_key=slot.section_key,
                fields=list(slot.fields),
                resolvable=slot.name not in unknown,
            )
            for slot in manifest.slots
        ],
        sections=[
            TemplateSectionOut(
                key=section.key,
                title=section.title,
                start_index=section.start_index,
                end_index=section.end_index,
            )
            for section in manifest.sections
        ],
        header_parts=[part.name for part in manifest.headers],
        footer_parts=[part.name for part in manifest.footers],
        page_setup=manifest.page_setup.to_dict(),
        unknown_slots=sorted(set(unknown)),
    )


@router.post(
    "/cases/{case_id}/templates", response_model=TemplateDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_template(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> TemplateDetailOut:
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded template is empty"
        )
    if len(data) > MAX_TEMPLATE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"template exceeds {MAX_TEMPLATE_BYTES} bytes",
        )
    try:
        template = template_service.store_template(
            db,
            case_id=case.id,
            name=name or (file.filename or "template"),
            filename=file.filename or "template.docx",
            data=data,
            actor=user,
        )
    except TemplateAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except template_service.DuplicateTemplateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "existing_template_id": exc.existing.id},
        ) from exc
    return _detail(template)


@router.get("/cases/{case_id}/templates", response_model=list[TemplateOut])
def list_templates(
    case: Case = Depends(get_case),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_read),
) -> list[LetterTemplate]:
    return template_service.list_templates(db, case.id)


@router.get("/templates/{template_id}", response_model=TemplateDetailOut)
def get_template(
    template: LetterTemplate = Depends(_get_template),
    user: CurrentUser = Depends(can_read),
) -> TemplateDetailOut:
    return _detail(template)


@router.post("/demands/{demand_id}/template", response_model=TemplateDetailOut)
def bind_template(
    payload: TemplateBindIn,
    demand: Demand = Depends(get_demand),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(can_edit_case),
) -> TemplateDetailOut:
    template = db.get(LetterTemplate, payload.template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"template {payload.template_id} not found",
        )
    try:
        template_service.bind_template_to_demand(db, demand, template, actor=user)
    except template_service.TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _detail(template)


@router.get("/demands/{demand_id}/fidelity", response_model=FidelityReportOut)
def get_fidelity(
    demand: Demand = Depends(get_demand),
    user: CurrentUser = Depends(can_read),
) -> FidelityReportOut:
    if not demand.template_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this demand has no template bound; there is no fidelity report",
        )
    if not demand.fidelity_report:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the demand has not been validated since a template was bound",
        )
    return FidelityReportOut(**demand.fidelity_report)


@router.get("/template-slots", response_model=list[str], tags=["templates"])
def list_known_slots(user: CurrentUser = Depends(can_read)) -> list[str]:
    """The slot names a template may use. Anything else is an authoring error."""
    return list(slot_catalog.known_slot_names())
