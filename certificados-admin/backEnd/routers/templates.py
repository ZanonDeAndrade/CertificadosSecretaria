"""Certificate models (templates) and the registered course list.

The list screen manages models; every mutation is audited. Version-level
routes remain read-only: the editor loads a revision's layout and the browser
loads its background image.
"""

from __future__ import annotations

from io import BytesIO

from certificados_backend.policies import Permission, require_permission
from certificados_backend.schemas.templates import (
    CourseCreateRequest,
    CourseResponse,
    CourseUpdateRequest,
    TemplateCreateRequest,
    TemplateDuplicateRequest,
    TemplateSampleDataResponse,
    TemplateSaveRequest,
    TextLayoutRequest,
    TextLayoutResponse,
)
from certificados_backend.services import audit_service, template_fields, template_service
from certificados_backend.services.generator import measuring_draw
from certificados_backend.services.runtime import build_layout_generator
from certificados_backend.services.template_service import (
    TemplateConflictError,
    TemplateError,
    TemplateNotFoundError,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/templates", tags=["templates"])
courses_router = APIRouter(tags=["courses"])


def _raise_for(exc: TemplateError) -> None:
    if isinstance(exc, TemplateNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, TemplateConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _audit(action: str, current: dict, template: dict, **details: object) -> None:
    audit_service.record(
        action,
        actor=current,
        target_type="certificate_template",
        target_id=template["id"],
        details={
            "template_id": template["id"],
            "version_id": template.get("current_version_id"),
            "version_number": template.get("version_number"),
            "certificate_type": template.get("certificate_type"),
            "course_id": template.get("course_id"),
            **details,
        },
    )


# ── Read side kept from the version era ───────────────────────────────────────


@router.get("/active")
def template_active(
    certificate_type: str | None = None,
    _: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
) -> dict:
    """Active version for a type (its own, else the generic one; per-work types
    have no fallback)."""
    version = template_service.get_active_version(certificate_type or None)
    if not version:
        raise HTTPException(status_code=404, detail="Nenhum template ativo.")
    return version


@router.get("/versions/{version_id:int}")
def template_version_detail(
    version_id: int,
    _: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
) -> dict:
    version = template_service.get_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versão não encontrada.")
    return version


@router.get("/versions/{version_id:int}/background")
def template_version_background(version_id: int) -> StreamingResponse:
    # Public: a template background image is not sensitive data, and the
    # editor loads it cross-origin where a SameSite=Lax cookie isn't sent.
    try:
        content, mime = template_service.get_background_bytes(version_id)
    except TemplateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(BytesIO(content), media_type=mime)


@router.get("/sample-data", response_model=TemplateSampleDataResponse)
def template_sample_data(
    current: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
) -> dict:
    """Sample values for the editor, resolved exactly as the PDF resolves them.

    Institutional values come from the current settings, so the preview
    never shows a city or a signatory the certificate will not have.
    """
    return template_fields.sample_data(actor=current)


@router.post("/text-layout", response_model=TextLayoutResponse)
def template_text_layout(
    payload: TextLayoutRequest,
    _: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
) -> dict:
    """Line breaks and heights the PDF will use, for the editor preview.

    Measured with the same fonts and wrapping as the renderer, so the
    editor shows the operator exactly what the certificate will contain.
    """
    generator = build_layout_generator()
    draw = measuring_draw()
    items: list[dict] = []
    for item in payload.items:
        if not item.text.strip():
            items.append(
                {
                    "id": item.id,
                    "lines": [],
                    "font_size": item.fontSize,
                    "line_height": 0,
                    "text_height": 0,
                    "wrap_width": None,
                    "overflow": False,
                    "top_offset": 0,
                }
            )
            continue
        box = generator.layout_text_box(draw, payload.image_width, item.text, item.as_element())
        items.append(
            {
                "id": item.id,
                "lines": box.lines,
                "font_size": box.font_size,
                "line_height": box.line_height,
                "text_height": box.text_height,
                "wrap_width": box.wrap_width,
                "overflow": box.overflow,
                "top_offset": box.top_offset,
            }
        )
    return {"items": items}


# ── Models ────────────────────────────────────────────────────────────────────


@router.get("")
def list_templates(
    course_id: int | None = Query(default=None, ge=1),
    without_course: bool = False,
    certificate_type: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=255),
    include_archived: bool = False,
    _: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
) -> list[dict]:
    """Models for the list: active first. ``certificate_type`` accepts a type
    or ``__generic__``; ``without_course`` lists the models for all courses."""
    try:
        return template_service.list_templates(
            course_id=course_id,
            without_course=without_course,
            certificate_type=certificate_type,
            query=q,
            include_archived=include_archived,
        )
    except TemplateError as exc:
        _raise_for(exc)
        raise  # pragma: no cover - _raise_for always raises


@router.post("")
def create_template(
    payload: TemplateCreateRequest,
    current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
) -> dict:
    try:
        template = template_service.create_template(
            name=payload.name,
            layout=payload.layout,
            certificate_type=payload.certificate_type,
            course_id=payload.course_id,
            actor_id=current["id"],
        )
    except TemplateError as exc:
        _raise_for(exc)
        raise  # pragma: no cover
    _audit("template_created", current, template)
    return template


@router.get("/{template_id:int}")
def template_detail(
    template_id: int,
    _: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
) -> dict:
    template = template_service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")
    return template


@router.get("/{template_id:int}/history")
def template_history(
    template_id: int,
    _: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
) -> list[dict]:
    history = template_service.template_history(template_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")
    return history


@router.put("/{template_id:int}")
def save_template(
    template_id: int,
    payload: TemplateSaveRequest,
    current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
) -> dict:
    """Save the model. The response carries ``outcome``: ``unchanged``,
    ``updated`` (in place), ``revised`` (new revision) or ``applied`` (new
    revision now used by emissions)."""
    try:
        template, outcome = template_service.save_template(
            template_id,
            name=payload.name,
            certificate_type=payload.certificate_type,
            type_provided="certificate_type" in payload.model_fields_set,
            course_id=payload.course_id,
            course_provided="course_id" in payload.model_fields_set,
            layout=payload.layout,
            expected_revision=payload.revision,
            apply=payload.apply,
            actor_id=current["id"],
        )
    except TemplateError as exc:
        _raise_for(exc)
        raise  # pragma: no cover
    _audit("template_saved", current, template, outcome=outcome)
    return {**template, "outcome": outcome}


@router.post("/{template_id:int}/duplicate")
def duplicate_template(
    template_id: int,
    payload: TemplateDuplicateRequest | None = None,
    current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
) -> dict:
    body = payload or TemplateDuplicateRequest()
    try:
        template = template_service.duplicate_template(
            template_id,
            name=body.name,
            version_id=body.version_id,
            actor_id=current["id"],
        )
    except TemplateError as exc:
        _raise_for(exc)
        raise  # pragma: no cover
    _audit(
        "template_duplicated",
        current,
        template,
        source_template_id=template_id,
        source_version_id=body.version_id,
    )
    return template


@router.post("/{template_id:int}/activate")
def activate_template(
    template_id: int,
    current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
) -> dict:
    try:
        template = template_service.activate_template(template_id, current["id"])
    except TemplateError as exc:
        _raise_for(exc)
        raise  # pragma: no cover
    _audit("template_activated", current, template)
    return template


@router.delete("/{template_id:int}")
def delete_template(
    template_id: int,
    current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
) -> dict:
    """Delete a model nothing points at; archive one that issued certificates."""
    try:
        outcome, template = template_service.delete_template(template_id, current["id"])
    except TemplateError as exc:
        _raise_for(exc)
        raise  # pragma: no cover
    _audit(
        "template_deleted" if outcome == "deleted" else "template_archived",
        current,
        template,
        reference_count=template.get("reference_count"),
    )
    return {"outcome": outcome, "template_id": template_id}


@router.post("/{template_id:int}/restore")
def restore_template(
    template_id: int,
    current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
) -> dict:
    try:
        template = template_service.restore_template(template_id, current["id"])
    except TemplateError as exc:
        _raise_for(exc)
        raise  # pragma: no cover
    _audit("template_restored", current, template)
    return template


# ── Courses ───────────────────────────────────────────────────────────────────


@courses_router.get("/courses", response_model=list[CourseResponse])
def list_courses(
    include_inactive: bool = True,
    _: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
) -> list[dict]:
    """Registered courses, for filing templates and for the settings screen."""
    return template_service.list_courses(include_inactive=include_inactive)


@courses_router.post("/courses", response_model=CourseResponse)
def create_course(
    payload: CourseCreateRequest,
    current: dict = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> dict:
    try:
        course = template_service.create_course(payload.name)
    except TemplateError as exc:
        _raise_for(exc)
        raise  # pragma: no cover
    audit_service.record(
        "course_created",
        actor=current,
        target_type="course",
        target_id=course["id"],
        details={"course_id": course["id"]},
    )
    return course


@courses_router.patch("/courses/{course_id:int}", response_model=CourseResponse)
def update_course(
    course_id: int,
    payload: CourseUpdateRequest,
    current: dict = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> dict:
    try:
        course = template_service.update_course(
            course_id, name=payload.name, is_active=payload.is_active
        )
    except TemplateError as exc:
        _raise_for(exc)
        raise  # pragma: no cover
    audit_service.record(
        "course_updated",
        actor=current,
        target_type="course",
        target_id=course_id,
        details={
            "course_id": course_id,
            "fields": sorted(payload.model_fields_set),
        },
    )
    return course
