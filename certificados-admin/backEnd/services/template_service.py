"""Certificate models and their revisions.

A model (``certificate_templates``) is what the secretariat sees as one item:
a name, a certificate type, a course and a layout. Its layout history lives in
``template_versions``; the newest row is the current revision and the one the
editor opens. The rules that keep issued certificates faithful:

  - Every certificate records ``template_version_id`` + a ``template_snapshot``
    of the layout, and the reissue reads the background from that version.
  - A revision a certificate points at, or that has ever been active, is never
    changed: saving such a model adds a new revision. A model nothing points
    at and that was never active is changed in place.
  - At most one version is active per type (``active_type_key``), and it is
    always its model's current revision. Saving the active model applies the
    new revision to the next emissions, so it needs an explicit confirmation.
  - A model with certificates is archived, never deleted. The active model
    and the only model cannot be deleted or archived.
  - The course only files the model in the list; emission picks the active
    model by type, never by course.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from certificados_backend.services import per_work

from database import db
from database.certificate_types import (
    certificate_type_label,
    is_per_work_type,
    parse_certificate_type,
)
from database.courses import MAX_COURSE_NAME_LENGTH, normalize_course_key
from database.repositories import GENERIC_TEMPLATE_KEY

MAX_BACKGROUND_BYTES = 10 * 1024 * 1024  # 10 MB
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPG_MAGIC = b"\xff\xd8\xff"
_SERVING_RE = re.compile(r"^/templates/versions/(\d+)/background$")
MAX_TEMPLATE_NAME_LENGTH = 255
DEFAULT_TEMPLATE_NAME = "Modelo padrão"


class TemplateError(Exception):
    """Invalid template payload (bad/missing background, etc.)."""


class TemplateNotFoundError(TemplateError):
    """No model (or version) with that id."""


class TemplateConflictError(TemplateError):
    """A requested mutation would break active or issued template history."""


class TemplateStaleError(TemplateConflictError):
    """The model changed since the editor opened it."""


class TemplateApplyRequiredError(TemplateConflictError):
    """Saving the active model's layout needs the explicit "apply" confirmation."""


# Upload/abuse limits.
MAX_IMAGE_PIXELS = 40_000_000  # 40 MP — guards against decompression bombs
MAX_IMAGE_DIMENSION = 12_000  # max width/height in px
MAX_LAYOUT_ELEMENTS = 200
MAX_TOTAL_DATA_URL_BYTES = 15 * 1024 * 1024


# ── Image helpers ───────────────────────────────────────────────────────────────


def _validate_image(content: bytes) -> None:
    """Validate a template image: format, size, real decodability, and pixel/
    dimension limits (rejecting decompression bombs)."""
    from PIL import Image  # local import keeps module light

    if not content:
        raise TemplateError("Imagem de fundo vazia.")
    if len(content) > MAX_BACKGROUND_BYTES:
        raise TemplateError("Imagem de fundo excede o limite de 10 MB.")
    if content[:8] != _PNG_MAGIC and content[:3] != _JPG_MAGIC:
        raise TemplateError("Imagem de fundo inválida (apenas PNG ou JPG).")

    # Cap pixels so PIL refuses huge/bomb images instead of exhausting memory.
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        # verify() detects truncated/corrupt files (consumes the image object).
        with Image.open(BytesIO(content)) as probe:
            probe.verify()
        with Image.open(BytesIO(content)) as img:
            width, height = img.size
    except TemplateError:
        raise
    except Exception as exc:  # PIL DecompressionBombError / UnidentifiedImageError / ...
        raise TemplateError("Imagem de fundo inválida ou perigosa.") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    if width <= 0 or height <= 0:
        raise TemplateError("Imagem de fundo com dimensões inválidas.")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise TemplateError(
            f"Imagem de fundo grande demais (máx. {MAX_IMAGE_DIMENSION}px por lado)."
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise TemplateError("Imagem de fundo excede o limite de pixels.")


def _enforce_layout_limits(layout: dict) -> None:
    """Cap element count and the total size of embedded data URLs in a layout."""
    elements = layout.get("elements") or []
    if not isinstance(elements, list):
        raise TemplateError("Lista de elementos do template inválida.")
    if len(elements) > MAX_LAYOUT_ELEMENTS:
        raise TemplateError(f"Template excede o limite de {MAX_LAYOUT_ELEMENTS} elementos.")
    total_data_url = 0
    for field_value in [layout.get("background")] + [
        el.get("src") for el in elements if isinstance(el, dict)
    ]:
        if isinstance(field_value, str) and field_value.startswith("data:image"):
            total_data_url += len(field_value)
    if total_data_url > MAX_TOTAL_DATA_URL_BYTES:
        raise TemplateError("Template excede o tamanho total permitido de imagens embutidas.")


def _mime_for(content: bytes) -> str:
    return "image/png" if content[:8] == _PNG_MAGIC else "image/jpeg"


def _decode_data_url(data_url: str) -> bytes:
    _, _, encoded = data_url.partition(",")
    if not encoded:
        raise TemplateError("Data URL de imagem sem conteúdo.")
    try:
        return base64.b64decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise TemplateError("Data URL de imagem inválida.") from exc


def _read_image_size(content: bytes) -> tuple[int, int]:
    from PIL import Image  # local import keeps module light

    with Image.open(BytesIO(content)) as img:
        return int(img.width), int(img.height)


def background_serving_path(version_id: int) -> str:
    return f"/templates/versions/{version_id}/background"


def _resolve_background(bg_field: str) -> tuple[bytes, str]:
    """Return ``(bytes, mime)`` from a data URL or an existing version's image."""
    bg_field = (bg_field or "").strip()
    if bg_field.startswith("data:image"):
        content = _decode_data_url(bg_field)
        _validate_image(content)
        return content, _mime_for(content)
    match = _SERVING_RE.match(bg_field)
    if match:
        existing = db.get_template_background(int(match.group(1)))
        if existing and existing[0]:
            return existing[0], existing[1]
    raise TemplateError("Imagem de fundo do template ausente ou inválida.")


@dataclass(frozen=True)
class PreparedLayout:
    """A layout validated and frozen: what a revision stores."""

    layout: dict
    layout_json: str
    width: int
    height: int
    background: bytes
    mime: str

    def digest(self) -> str:
        return hashlib.sha256(self.layout_json.encode("utf-8") + self.background).hexdigest()


def _prepare_layout(layout: Any) -> PreparedLayout:
    if not isinstance(layout, dict):
        raise TemplateError("Layout inválido.")
    _enforce_layout_limits(layout)
    content, mime = _resolve_background(str(layout.get("background") or ""))
    width = int(layout.get("image_width") or 0)
    height = int(layout.get("image_height") or 0)
    if width <= 0 or height <= 0:
        width, height = _read_image_size(content)
    clean_layout = {
        "image_width": width,
        "image_height": height,
        "elements": layout.get("elements") or [],
    }
    return PreparedLayout(
        layout=clean_layout,
        layout_json=json.dumps(clean_layout, ensure_ascii=False),
        width=width,
        height=height,
        background=content,
        mime=mime,
    )


def _version_digest(version: dict, background: bytes | None) -> str:
    return hashlib.sha256(
        str(version["layout_json"]).encode("utf-8") + (background or b"")
    ).hexdigest()


# ── Serialization ───────────────────────────────────────────────────────────────


def _layout_with_background(version: dict) -> dict:
    layout = json.loads(version["layout_json"])
    layout["background"] = background_serving_path(version["id"])
    layout["image_width"] = version["image_width"]
    layout["image_height"] = version["image_height"]
    return layout


def serialize_version(version: dict, *, include_layout: bool = True) -> dict:
    data = {
        "id": version["id"],
        "template_id": version.get("template_id"),
        "version_number": version["version_number"],
        "name": version["name"],
        "is_active": bool(version["is_active"]),
        "certificate_type": version.get("certificate_type"),
        "image_width": version["image_width"],
        "image_height": version["image_height"],
        "background_url": background_serving_path(version["id"]),
        "created_at": version.get("created_at"),
        "created_by": version.get("created_by"),
        "activated_at": version.get("activated_at"),
    }
    if include_layout:
        data["layout"] = _layout_with_background(version)
    return data


def serialize_template(overview: dict, *, layout_version: dict | None = None) -> dict:
    """One model as the list and the editor see it."""
    reference_count = int(overview.get("reference_count") or 0)
    ever_activated = int(overview.get("activation_count") or 0) > 0
    current_version_id = overview.get("current_version_id")
    data = {
        "id": overview["id"],
        "name": overview["name"],
        "certificate_type": overview.get("certificate_type"),
        "certificate_type_label": (
            certificate_type_label(overview["certificate_type"])
            if overview.get("certificate_type")
            else None
        ),
        "course_id": overview.get("course_id"),
        "course_name": overview.get("course_name"),
        "is_active": bool(overview.get("is_active")),
        "is_archived": overview.get("archived_at") is not None,
        "archived_at": overview.get("archived_at"),
        "revision": int(overview.get("revision") or 1),
        "current_version_id": current_version_id,
        "version_number": overview.get("version_number"),
        "image_width": overview.get("image_width"),
        "image_height": overview.get("image_height"),
        "background_url": (
            background_serving_path(int(current_version_id)) if current_version_id else None
        ),
        "certificate_count": int(overview.get("certificate_count") or 0),
        "reference_count": reference_count,
        "ever_activated": ever_activated,
        # Changing the type would re-aim a layout certificates were issued
        # with, or one a worker may be issuing with: duplicate instead.
        "type_locked": reference_count > 0 or ever_activated,
        # In-place edits stay possible only while nothing depends on the layout.
        "edits_in_place": reference_count == 0 and not ever_activated,
        "created_at": overview.get("created_at"),
        "updated_at": overview.get("updated_at"),
        "activated_at": overview.get("activated_at"),
    }
    if layout_version is not None:
        data["layout"] = _layout_with_background(layout_version)
    return data


# ── Read side ───────────────────────────────────────────────────────────────────


def list_versions() -> list[dict]:
    return [serialize_version(v, include_layout=False) for v in db.list_template_versions()]


def get_version(version_id: int) -> dict | None:
    version = db.get_template_version(version_id)
    return serialize_version(version) if version else None


def get_active_version(certificate_type: str | None = None) -> dict | None:
    """The active version for a batch type, falling back to the generic one.

    Per-work types never fall back: the generic template highlights a
    participant name, which a certificate shared by every author must not do.
    """
    version = db.get_active_template_version(certificate_type) if certificate_type else None
    if not version and not is_per_work_type(certificate_type):
        # No version dedicated to this type: the generic one applies.
        version = db.get_active_template_version(None)
    return serialize_version(version) if version else None


def get_background_bytes(version_id: int) -> tuple[bytes, str]:
    result = db.get_template_background(version_id)
    if not result or not result[0]:
        raise TemplateError("Imagem de fundo do template não encontrada.")
    return result[0], result[1]


def list_templates(
    *,
    course_id: int | None = None,
    without_course: bool = False,
    certificate_type: str | None = None,
    query: str | None = None,
    include_archived: bool = False,
) -> list[dict]:
    """Models for the list screen: the active ones first.

    ``certificate_type`` may be a type value or ``GENERIC_TEMPLATE_KEY`` for
    the generic models only.
    """
    generic_only = certificate_type == GENERIC_TEMPLATE_KEY
    if certificate_type and not generic_only:
        try:
            parsed = parse_certificate_type(certificate_type, required=True)
        except ValueError as exc:
            raise TemplateError(str(exc)) from exc
        certificate_type = parsed.value if parsed else None
    else:
        certificate_type = None
    rows = db.list_template_overviews(
        course_id=course_id,
        without_course=without_course,
        certificate_type=certificate_type,
        generic_only=generic_only,
        query=(query or "").strip() or None,
        include_archived=include_archived,
    )
    return [serialize_template(row) for row in rows]


def get_template(template_id: int) -> dict | None:
    overview = db.get_template_overview(template_id)
    if not overview or not overview.get("current_version_id"):
        return None
    version = db.get_template_version(int(overview["current_version_id"]))
    return serialize_template(overview, layout_version=version)


def template_history(template_id: int) -> list[dict] | None:
    overview = db.get_template_overview(template_id)
    if not overview:
        return None
    current_id = overview.get("current_version_id")
    return [
        {
            **serialize_version(version, include_layout=False),
            "is_current": version["id"] == current_id,
        }
        for version in db.list_template_versions_of(template_id)
    ]


# ── Validation helpers ──────────────────────────────────────────────────────────


def _clean_name(name: str | None, *, fallback: str) -> str:
    clean = (name or "").strip()
    if not clean:
        clean = fallback
    if len(clean) > MAX_TEMPLATE_NAME_LENGTH:
        raise TemplateError(
            f"O nome do modelo deve ter no máximo {MAX_TEMPLATE_NAME_LENGTH} caracteres."
        )
    return clean


def _parse_type(value: str | None) -> str | None:
    try:
        parsed = parse_certificate_type(value, required=False)
    except ValueError as exc:
        raise TemplateError(str(exc)) from exc
    return parsed.value if parsed else None


def _check_course(uow: db.TemplateUnitOfWork, course_id: int | None) -> None:
    if course_id is None:
        return
    if uow.courses.get(course_id) is None:
        raise TemplateError(
            "Curso não encontrado. Escolha um curso cadastrado ou “Todos os cursos”."
        )


def _per_work_problems(layout: dict, certificate_type: str | None) -> str | None:
    """Why a per-work model cannot be applied to emissions right now."""
    if not is_per_work_type(certificate_type):
        return None
    problems = per_work.layout_problems(layout)
    if not problems:
        return None
    label = certificate_type_label(certificate_type)
    return (
        f"O modelo ativo do tipo {label} bloquearia a emissão: "
        + per_work.describe_problems(problems)
        + ". Corrija o layout antes de aplicar às próximas emissões."
    )


def _overview_or_raise(uow: db.TemplateUnitOfWork, template_id: int) -> dict:
    overview = uow.templates.overview(template_id)
    if overview is None or overview.get("current_version_id") is None:
        raise TemplateNotFoundError("Modelo não encontrado.")
    return overview


# ── Mutations ───────────────────────────────────────────────────────────────────


def create_template(
    *,
    name: str | None,
    layout: dict,
    certificate_type: str | None = None,
    course_id: int | None = None,
    actor_id: int | None = None,
) -> dict:
    """A new, inactive model with its first revision."""
    clean_name = _clean_name(name, fallback="Novo modelo")
    parsed_type = _parse_type(certificate_type)
    prepared = _prepare_layout(layout)
    with db.template_unit_of_work() as uow:
        uow.versions.lock_sequence()
        _check_course(uow, course_id)
        template_id = uow.templates.create(
            name=clean_name,
            certificate_type=parsed_type,
            course_id=course_id,
            created_by=actor_id,
        )
        uow.versions.create(
            template_id=template_id,
            name=clean_name,
            layout_json=prepared.layout_json,
            image_width=prepared.width,
            image_height=prepared.height,
            background_image=prepared.background,
            background_mime_type=prepared.mime,
            created_by=actor_id,
            certificate_type=parsed_type,
        )
    created = get_template(template_id)
    if created is None:  # pragma: no cover - the row was just written
        raise TemplateError("O modelo criado não pôde ser relido.")
    return created


def save_template(
    template_id: int,
    *,
    name: str | None = None,
    certificate_type: str | None = None,
    type_provided: bool = False,
    course_id: int | None = None,
    course_provided: bool = False,
    layout: dict | None = None,
    expected_revision: int | None = None,
    apply: bool = False,
    actor_id: int | None = None,
) -> tuple[dict, str]:
    """Save a model. Returns the model and what happened to its layout:

    ``"unchanged"`` (only name/type/course), ``"updated"`` (the current revision
    changed in place), ``"revised"`` (a new revision, model not active) or
    ``"applied"`` (a new revision that the next emissions use).
    """
    prepared = _prepare_layout(layout) if layout is not None else None
    with db.template_unit_of_work() as uow:
        uow.versions.lock_sequence()
        template = uow.templates.get(template_id, for_update=True)
        if template is None:
            raise TemplateNotFoundError("Modelo não encontrado.")
        if template.get("archived_at") is not None:
            raise TemplateConflictError("Este modelo está arquivado. Restaure-o antes de editar.")
        if expected_revision is not None and int(template["revision"]) != int(expected_revision):
            raise TemplateStaleError(
                "Este modelo foi alterado por outra pessoa desde que você o abriu. "
                "Recarregue o modelo para ver a versão atual antes de salvar."
            )
        current = uow.versions.current_for_template(template_id)
        if current is None:
            raise TemplateNotFoundError("Modelo sem revisão atual.")
        is_active = bool(current["is_active"])
        reference_count, _issued = uow.templates.reference_counts(template_id)
        ever_activated = uow.templates.ever_activated(template_id)
        frozen = reference_count > 0 or ever_activated

        new_name = _clean_name(name, fallback=str(template["name"])) if name is not None else None
        new_type = _parse_type(certificate_type) if type_provided else template["certificate_type"]
        if new_type != template["certificate_type"] and frozen:
            raise TemplateConflictError(
                "O tipo de um modelo que já emitiu certificados ou já esteve ativo não pode "
                "mudar. Duplique o modelo e escolha o tipo na cópia."
            )
        if course_provided:
            _check_course(uow, course_id)

        outcome = "unchanged"
        if prepared is not None:
            current_background = uow.versions.get_background(int(current["id"]))
            unchanged = prepared.digest() == _version_digest(
                current, current_background[0] if current_background else None
            )
            if not unchanged:
                if is_active:
                    if not apply:
                        raise TemplateApplyRequiredError(
                            "Este modelo está ativo: salvar muda os próximos certificados "
                            "emitidos, inclusive de lotes já na fila. Confirme com "
                            "“Salvar e aplicar às próximas emissões”."
                        )
                    problem = _per_work_problems(prepared.layout, new_type)
                    if problem:
                        raise TemplateError(problem)
                if frozen:
                    created = uow.versions.create(
                        template_id=template_id,
                        name=new_name or str(template["name"]),
                        layout_json=prepared.layout_json,
                        image_width=prepared.width,
                        image_height=prepared.height,
                        background_image=prepared.background,
                        background_mime_type=prepared.mime,
                        created_by=actor_id,
                        certificate_type=new_type,
                    )
                    if is_active:
                        uow.versions.activate(int(created["id"]), actor_id)
                        outcome = "applied"
                    else:
                        outcome = "revised"
                else:
                    uow.versions.update_layout(
                        int(current["id"]),
                        layout_json=prepared.layout_json,
                        image_width=prepared.width,
                        image_height=prepared.height,
                        background_image=prepared.background,
                        background_mime_type=prepared.mime,
                    )
                    outcome = "updated"

        values: dict[str, Any] = {}
        if new_name is not None:
            values["name"] = new_name
        if type_provided and new_type != template["certificate_type"]:
            values["certificate_type"] = new_type
            uow.versions.set_certificate_type(template_id, new_type)
        if course_provided:
            values["course_id"] = course_id
        uow.templates.update(template_id, values, actor=actor_id, bump=True)
    saved = get_template(template_id)
    if saved is None:  # pragma: no cover - the row was just written
        raise TemplateError("O modelo salvo não pôde ser relido.")
    return saved, outcome


def duplicate_template(
    template_id: int,
    *,
    name: str | None = None,
    version_id: int | None = None,
    actor_id: int | None = None,
) -> dict:
    """A new inactive model copied from a model's current (or chosen) revision."""
    with db.template_unit_of_work() as uow:
        uow.versions.lock_sequence()
        template = uow.templates.get(template_id)
        if template is None:
            raise TemplateNotFoundError("Modelo não encontrado.")
        source = (
            uow.versions.get(version_id)
            if version_id is not None
            else uow.versions.current_for_template(template_id)
        )
        if source is None or int(source["template_id"]) != template_id:
            raise TemplateNotFoundError("Revisão não encontrada neste modelo.")
        background = uow.versions.get_background(int(source["id"]))
        if not background or not background[0]:
            raise TemplateError("Imagem de fundo do modelo não encontrada.")
        clean_name = _clean_name(name, fallback=f"Cópia de {template['name']}")
        new_id = uow.templates.create(
            name=clean_name,
            certificate_type=template["certificate_type"],
            course_id=template["course_id"],
            created_by=actor_id,
        )
        uow.versions.create(
            template_id=new_id,
            name=clean_name,
            layout_json=str(source["layout_json"]),
            image_width=int(source["image_width"]),
            image_height=int(source["image_height"]),
            background_image=background[0],
            background_mime_type=background[1],
            created_by=actor_id,
            certificate_type=template["certificate_type"],
        )
    created = get_template(new_id)
    if created is None:  # pragma: no cover - the row was just written
        raise TemplateError("O modelo duplicado não pôde ser relido.")
    return created


def activate_template(template_id: int, actor_id: int | None = None) -> dict:
    """Make the model's current revision the active one for its type."""
    with db.template_unit_of_work() as uow:
        uow.versions.lock_sequence()
        template = uow.templates.get(template_id, for_update=True)
        if template is None:
            raise TemplateNotFoundError("Modelo não encontrado.")
        if template.get("archived_at") is not None:
            raise TemplateConflictError(
                "Um modelo arquivado não pode ser ativado. Restaure-o antes."
            )
        current = uow.versions.current_for_template(template_id)
        if current is None:
            raise TemplateNotFoundError("Modelo sem revisão atual.")
        if not bool(current["is_active"]):
            problem = _per_work_problems(
                json.loads(current["layout_json"]), template["certificate_type"]
            )
            if problem:
                raise TemplateError(problem)
            uow.versions.activate(int(current["id"]), actor_id)
            uow.templates.update(template_id, {}, actor=actor_id, bump=False)
    activated = get_template(template_id)
    if activated is None:  # pragma: no cover - the row was just written
        raise TemplateError("O modelo ativado não pôde ser relido.")
    return activated


def delete_template(template_id: int, actor_id: int | None = None) -> tuple[str, dict]:
    """Delete a model nothing points at; archive one that issued certificates.

    Returns ``("deleted", model)`` or ``("archived", model)``.
    """
    with db.template_unit_of_work() as uow:
        uow.versions.lock_sequence()
        template = uow.templates.get(template_id, for_update=True)
        if template is None:
            raise TemplateNotFoundError("Modelo não encontrado.")
        overview = _overview_or_raise(uow, template_id)
        if bool(overview.get("is_active")):
            raise TemplateConflictError(
                "O modelo ativo não pode ser excluído nem arquivado. Ative outro modelo primeiro."
            )
        if uow.templates.count() <= 1:
            raise TemplateConflictError(
                "O único modelo existente não pode ser excluído: sem ele, a próxima emissão "
                "criaria e ativaria um modelo padrão sem aviso."
            )
        reference_count, _issued = uow.templates.reference_counts(template_id)
        if reference_count > 0:
            if template.get("archived_at") is None:
                uow.templates.set_archived(template_id, archived=True, actor=actor_id)
            snapshot = serialize_template(_overview_or_raise(uow, template_id))
            return "archived", snapshot
        if uow.templates.ever_activated(template_id) and uow.batches.count_in_progress() > 0:
            raise TemplateConflictError(
                "Este modelo já esteve ativo e há um lote em andamento que pode estar usando "
                "o layout dele. Aguarde o lote terminar antes de excluir."
            )
        snapshot = serialize_template(overview)
        uow.templates.delete(template_id)
        return "deleted", snapshot


def restore_template(template_id: int, actor_id: int | None = None) -> dict:
    with db.template_unit_of_work() as uow:
        uow.versions.lock_sequence()
        template = uow.templates.get(template_id, for_update=True)
        if template is None:
            raise TemplateNotFoundError("Modelo não encontrado.")
        if template.get("archived_at") is not None:
            uow.templates.set_archived(template_id, archived=False, actor=actor_id)
    restored = get_template(template_id)
    if restored is None:  # pragma: no cover - the row was just written
        raise TemplateError("O modelo restaurado não pôde ser relido.")
    return restored


# ── Compatibility helpers (tests and seeding) ───────────────────────────────────


def create_version(
    *,
    name: str | None,
    layout: dict,
    created_by: int | None = None,
    certificate_type: str | None = None,
) -> dict:
    """A new inactive model named ``name`` with this layout; returns its version.

    Kept for the test-suite fixtures and scripts that think in versions.
    """
    template = create_template(
        name=name,
        layout=layout,
        certificate_type=certificate_type,
        actor_id=created_by,
    )
    version = db.get_template_version(int(template["current_version_id"]))
    if version is None:  # pragma: no cover - the row was just written
        raise TemplateError("A versão criada não pôde ser relida.")
    return serialize_version(version)


def activate_version(version_id: int, actor: int | None = None) -> bool:
    """Activate the model whose current revision is ``version_id``."""
    version = db.get_template_version(version_id)
    if version is None:
        return False
    template_id = int(version["template_id"])
    current = db.get_template_overview(template_id)
    if not current or int(current.get("current_version_id") or 0) != version_id:
        raise TemplateConflictError(
            "Só a revisão atual de um modelo pode ser ativada. Duplique a revisão antiga "
            "pelo histórico e ative a cópia."
        )
    activate_template(template_id, actor)
    return True


# ── Courses ─────────────────────────────────────────────────────────────────────


def serialize_course(course: dict) -> dict:
    return {
        "id": course["id"],
        "name": course["name"],
        "is_active": bool(course["is_active"]),
    }


def list_courses(*, include_inactive: bool = True) -> list[dict]:
    return [
        serialize_course(course) for course in db.list_courses(include_inactive=include_inactive)
    ]


def _clean_course_name(name: str | None) -> tuple[str, str]:
    clean = " ".join((name or "").split())
    if not clean:
        raise TemplateError("Informe o nome do curso.")
    if len(clean) > MAX_COURSE_NAME_LENGTH:
        raise TemplateError(
            f"O nome do curso deve ter no máximo {MAX_COURSE_NAME_LENGTH} caracteres."
        )
    key = normalize_course_key(clean)
    if not key:
        raise TemplateError("Informe o nome do curso.")
    return clean, key


def create_course(name: str | None) -> dict:
    clean, key = _clean_course_name(name)
    existing = db.get_course_by_key(key)
    if existing:
        raise TemplateConflictError(f"Já existe o curso “{existing['name']}” com esse nome.")
    return serialize_course(db.create_course(name=clean, normalized_key=key))


def update_course(
    course_id: int, *, name: str | None = None, is_active: bool | None = None
) -> dict:
    values: dict[str, Any] = {}
    if name is not None:
        clean, key = _clean_course_name(name)
        existing = db.get_course_by_key(key)
        if existing and int(existing["id"]) != course_id:
            raise TemplateConflictError(f"Já existe o curso “{existing['name']}” com esse nome.")
        values["name"] = clean
        values["normalized_key"] = key
    if is_active is not None:
        values["is_active"] = 1 if is_active else 0
    if not values:
        current = db.get_course(course_id)
        if current is None:
            raise TemplateNotFoundError("Curso não encontrado.")
        return serialize_course(current)
    updated = db.update_course(course_id, values)
    if updated is None:
        raise TemplateNotFoundError("Curso não encontrado.")
    return serialize_course(updated)


# ── Default seeding ─────────────────────────────────────────────────────────────


def _placeholder_png() -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (1414, 1000), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _load_default_background(default_png_path: Path) -> bytes:
    try:
        if default_png_path and Path(default_png_path).is_file():
            content = Path(default_png_path).read_bytes()
            if content:
                return content
    except OSError:
        pass
    return _placeholder_png()


def _default_layout(width: int, height: int) -> dict:
    cx = width // 2
    margin = int(width * 0.05)

    def t(key, y_ratio, size_ratio, *, static=None, bold=False, align="center", x=None):
        el = {
            "type": "text",
            "key": "static" if static is not None else key,
            "x": cx if x is None else x,
            "y": int(height * y_ratio),
            "fontSize": max(int(height * size_ratio), 8),
            "fontFamily": "Times New Roman",
            "color": "#000000",
            "align": align,
            "bold": bold,
            "italic": False,
        }
        if static is not None:
            el["staticText"] = static
        return el

    elements = [
        t("static", 0.12, 0.050, static="CERTIFICADO", bold=True),
        t("static", 0.30, 0.022, static="Certificamos, para os devidos fins, que"),
        t("name", 0.355, 0.045, bold=True),
        # Corpo do certificado: o texto padrão escrito pela secretaria é
        # interpolado por linha e renderizado aqui (quebra automática + quebras
        # digitadas). Curso, evento, carga horária e datas entram via variáveis.
        t("texto_certificado", 0.46, 0.024, align="left", x=margin),
        # These values come from the institutional settings snapshot. They stay
        # editable as layout elements without freezing business data in a
        # template version.
        t("issue_line", 0.72, 0.022),
        t("signatory_name", 0.79, 0.018),
        t("signatory_title", 0.825, 0.016),
        t("validation_code", 0.92, 0.014),
        {
            "type": "qr",
            "key": "qr",
            "x": margin,
            "y": int(height * 0.82),
            "width": int(height * 0.12),
            "height": int(height * 0.12),
        },
    ]
    return {"image_width": width, "image_height": height, "elements": elements}


def ensure_default_version(default_png_path: Path, created_by: int | None = None) -> None:
    """Seed + activate a default generic model when no version exists yet."""
    if db.count_template_versions() > 0:
        return
    content = _load_default_background(default_png_path)
    try:
        width, height = _read_image_size(content)
    except Exception:  # pragma: no cover - corrupt default
        width, height = 1414, 1000
    layout = _default_layout(width, height)
    with db.template_unit_of_work() as uow:
        uow.versions.lock_sequence()
        if uow.versions.count() > 0:
            return
        template_id = uow.templates.create(
            name=DEFAULT_TEMPLATE_NAME,
            certificate_type=None,
            course_id=None,
            created_by=created_by,
        )
        created = uow.versions.create(
            template_id=template_id,
            name=DEFAULT_TEMPLATE_NAME,
            layout_json=json.dumps(layout, ensure_ascii=False),
            image_width=width,
            image_height=height,
            background_image=content,
            background_mime_type=_mime_for(content),
            created_by=created_by,
        )
        uow.versions.activate(int(created["id"]), created_by)
