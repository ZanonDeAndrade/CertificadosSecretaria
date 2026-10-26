"""Durable, encrypted and idempotent emission-job workflow."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

from certificados_backend.policies import Permission, is_allowed
from certificados_backend.services import (
    audit_service,
    job_crypto,
    per_work,
    settings_service,
    spreadsheet,
    template_fields,
    template_service,
)
from certificados_backend.services.certificate_service import (
    CertificateBatchService,
    _row_to_record,
    build_row_variables,
    resolve_batch_body,
)
from certificados_backend.services.certificate_text import (
    BODY_VARIABLE_LABELS,
    CertificateTextError,
    body_template_variables,
    normalize_body_text,
    validate_body_template,
)
from certificados_backend.services.generator import (
    CertificateGenerator,
    box_size,
    measuring_draw,
)
from certificados_backend.services.runtime import build_certificate_service
from certificados_backend.services.spreadsheet import (
    SpreadsheetError,
    SpreadsheetRow,
    compute_business_key,
)
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError

import observability
from database import config as db_config
from database import db
from database.certificate_types import (
    certificate_type_label,
    is_per_work_type,
    parse_certificate_type,
)

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
# Pre-check of the active template's sized text boxes. Measuring every row of
# a large batch would slow the preview down, so only the first rows are
# checked and the response says when the check stopped early.
MAX_LAYOUT_CHECK_ROWS = 300
MAX_LAYOUT_WARNING_ROWS = 50
_TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled"}
_MISSING_DESTINATION_MESSAGE = (
    "Selecione uma pasta do Google Drive para todos os eventos antes de emitir os certificados."
)
LOGGER = logging.getLogger("certificados.emission_jobs")


def event_key(value: str | None) -> str:
    """Canonical destination key; the empty string is the explicit no-event group."""
    return (value or "").strip()


def event_groups(rows: list[SpreadsheetRow]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        key = event_key(row.evento)
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "key": key,
            "label": key or "Certificados sem evento",
            "count": counts[key],
        }
        for key in sorted(counts, key=lambda item: (item == "", item.casefold()))
    ]


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


def worker_mode() -> str:
    value = (os.getenv("BATCH_WORKER_MODE") or "").strip().lower()
    if not value:
        return "external" if db_config.is_production() else "inline"
    if value not in {"inline", "external"}:
        raise RuntimeError("BATCH_WORKER_MODE deve ser inline ou external.")
    if db_config.is_production() and value == "inline":
        raise RuntimeError("BATCH_WORKER_MODE=inline não é permitido em produção.")
    return value


def validate_runtime_configuration() -> None:
    worker_mode()
    job_crypto.validate_configuration()
    from certificados_backend.services import job_dispatch

    job_dispatch.validate_configuration()


def validate_idempotency_key(value: str) -> str:
    clean = value.strip()
    if not _IDEMPOTENCY_RE.fullmatch(clean):
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key deve ter de 16 a 128 caracteres seguros.",
        )
    return clean


async def read_upload(file: UploadFile) -> bytes:
    settings = settings_service.get()
    filename = (file.filename or "").strip()
    if not filename or not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Envie uma planilha .xlsx válida.")
    content = await file.read()
    await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    max_bytes = int(settings["max_upload_mb"]) * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"O arquivo excede o limite institucional de {settings['max_upload_mb']} MB.",
        )
    if content[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="O conteúdo não é um .xlsx válido.")
    return content


def _parse(
    content: bytes, *, data_emissao: str | None, certificate_type: str | None = None
) -> spreadsheet.ValidationReport:
    try:
        return spreadsheet.read_and_validate(
            BytesIO(content),
            default_data_emissao=data_emissao,
            max_rows=int(settings_service.get()["max_batch_rows"]),
            certificate_type=certificate_type,
        )
    except SpreadsheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # malformed workbook internals stay server-side
        raise HTTPException(status_code=400, detail="Não foi possível ler a planilha.") from exc


def _body(value: str | None, certificate_type: str | None) -> str:
    """The batch's body text, validated for its type.

    A per-work type may leave it blank (``""``): its automatic body applies.
    """
    if is_per_work_type(certificate_type) and not normalize_body_text(value).strip():
        return ""
    try:
        text = validate_body_template(value)
        per_work.check_body_variables(text, certificate_type)
    except CertificateTextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return text


def _template_problem(
    version: dict | None, certificate_type: str | None, *, actor: dict | None
) -> str | None:
    """Why a per-work batch cannot use the active template (``None`` if it can)."""
    return per_work.template_problem(
        version,
        certificate_type,
        can_manage=bool(actor and is_allowed(actor, Permission.TEMPLATES_MANAGE)),
    )


@dataclass
class _ReviewContext:
    """The active template and the values each row resolves to, computed once."""

    layout: dict[str, Any]
    image_width: int
    generator: CertificateGenerator
    rows: list[tuple[SpreadsheetRow, dict[str, str]]]
    truncated: bool
    certificate_type: str | None
    #: ``{{variáveis}}`` the body text uses.
    body_variables: frozenset[str]


def _review_context(
    report: spreadsheet.ValidationReport,
    *,
    body_template: str | None,
    certificate_type: str | None,
) -> _ReviewContext | None:
    """Resolve every row the way the renderer will, against the active template."""
    if not report.valid:
        return None
    version = template_service.get_active_version(certificate_type)
    if not version:
        return None
    layout = version.get("layout") or {}
    # Built from the current settings, so institutional values match the PDF.
    generator = build_certificate_service().generator
    # The real code only exists after emission; any code has this shape.
    placeholder_code = f"CERT-{datetime.now().year}-XXXXXX"
    checked = report.valid[:MAX_LAYOUT_CHECK_ROWS]
    rows: list[tuple[SpreadsheetRow, dict[str, str]]] = []
    for row in checked:
        body = (
            resolve_batch_body(row, body_template, certificate_type)
            if body_template is not None
            else None
        )
        record = _row_to_record(row, placeholder_code, body=body, certificate_type=certificate_type)
        rows.append((row, generator.participant_data(record)))
    return _ReviewContext(
        layout=layout,
        image_width=int(layout.get("image_width") or version.get("image_width") or 0),
        generator=generator,
        rows=rows,
        truncated=len(report.valid) > len(checked),
        certificate_type=certificate_type,
        body_variables=frozenset(body_template_variables(body_template or "")),
    )


def layout_warnings(context: _ReviewContext) -> list[dict[str, Any]]:
    """Participants whose text would not fit a sized box of the active template.

    Uses the very measurement the PDF uses, before anything is emitted, so the
    secretaria can enlarge the box or shorten the text first. The certificate
    is never clipped either way.
    """
    sized = [
        element
        for element in context.layout.get("elements") or []
        if isinstance(element, dict)
        and element.get("type", "text") == "text"
        and element.get("key") not in (None, "", "qr")
        and box_size(element, "height")
    ]
    if not sized:
        return []

    generator = context.generator
    draw = measuring_draw()
    warnings: list[dict[str, Any]] = []
    for element in sized:
        key = str(element.get("key"))
        rows: list[dict[str, Any]] = []
        applies_to_all = False
        if key == "static":
            text = str(element.get("staticText") or "")
            applies_to_all = bool(text) and (
                generator.layout_text_box(draw, context.image_width, text, element).overflow
            )
        else:
            for row, data in context.rows:
                text = data.get(key, f"[{key}]")
                if (
                    text
                    and generator.layout_text_box(draw, context.image_width, text, element).overflow
                ):
                    rows.append({"row_number": row.row_number, "nome": row.nome})
        if not rows and not applies_to_all:
            continue
        warnings.append(
            {
                "key": key,
                "label": str(element.get("label") or key),
                "height": box_size(element, "height") or 0,
                "row_count": len(rows),
                "rows": rows[:MAX_LAYOUT_WARNING_ROWS],
                "applies_to_all": applies_to_all,
                "checked_rows": len(context.rows),
                "truncated": context.truncated,
            }
        )
    return warnings


def empty_fields(context: _ReviewContext) -> list[dict[str, Any]]:
    """Rows for which a template field resolves to nothing: the PDF omits it.

    Institutional fields are handled by :func:`template_fields.missing_settings`
    and the name is required by the spreadsheet, so only row-level fields are
    listed here. A warning, never a block.
    """
    results: list[dict[str, Any]] = []

    def report_blank(key: str, label: str, rows: list[dict[str, Any]]) -> None:
        # One entry per field: the "Evento" element and {{evento}} in the body
        # read the same column, so the secretaria sees the rows only once.
        if rows and not any(item["label"] == label for item in results):
            results.append(
                {
                    "key": key,
                    "label": label,
                    "row_count": len(rows),
                    "rows": rows[:MAX_LAYOUT_WARNING_ROWS],
                    "checked_rows": len(context.rows),
                    "truncated": context.truncated,
                }
            )

    for element in template_fields.text_elements(context.layout):
        key = str(element.get("key"))
        label = template_fields.ROW_FIELD_LABELS.get(key)
        if label is None:
            continue
        report_blank(
            key,
            label,
            [
                {"row_number": row.row_number, "nome": row.nome}
                for row, data in context.rows
                if not str(data.get(key) or "").strip()
            ],
        )

    # Variables the body text interpolates, such as an optional workload or team.
    for variable in sorted(context.body_variables):
        label = BODY_VARIABLE_LABELS.get(variable)
        if label is None:
            continue
        report_blank(
            variable,
            label,
            [
                {"row_number": row.row_number, "nome": row.nome}
                for row, _data in context.rows
                if not build_row_variables(row, context.certificate_type).get(variable)
            ],
        )
    return results


def serialize_report(
    report: spreadsheet.ValidationReport,
    *,
    body_template: str | None = None,
    certificate_type: str | None = None,
    layout_warnings: list[dict[str, Any]] | None = None,
    missing_settings: list[dict[str, Any]] | None = None,
    missing_settings_message: str | None = None,
    empty_fields: list[dict[str, Any]] | None = None,
    can_manage_settings: bool = False,
    template_problem: str | None = None,
    can_manage_templates: bool = False,
) -> dict:
    """Preview projection without document/e-mail or unnecessary row content."""
    return {
        "template_problem": template_problem,
        "can_manage_templates": can_manage_templates,
        "layout_warnings": layout_warnings or [],
        "missing_settings": missing_settings or [],
        "missing_settings_message": missing_settings_message,
        "empty_fields": empty_fields or [],
        "can_manage_settings": can_manage_settings,
        "warnings": list(report.warnings),
        "total": report.total,
        "valid_count": report.valid_count,
        "invalid_count": report.invalid_count,
        "valid": [
            {
                "row_number": row.row_number,
                "nome": row.nome,
                "curso": row.curso,
                "evento": row.evento,
                "carga_horaria": row.carga_horaria,
                "data_emissao": row.data_emissao,
                "data_inicio": row.data_inicio,
                "data_fim": row.data_fim,
                "autores": list(row.autores),
                "equipe": row.equipe,
                "titulo_trabalho": row.titulo_trabalho,
            }
            for row in report.valid
        ],
        "invalid": [
            {"row_number": row.row_number, "errors": row.errors, "data": None}
            for row in report.invalid
        ],
        "events": event_groups(report.valid),
        "resolved_text_preview": (
            resolve_batch_body(report.valid[0], body_template, certificate_type)
            if body_template is not None and report.valid
            else None
        ),
    }


async def preview(
    file: UploadFile,
    *,
    data_emissao: str | None,
    texto_padrao: str | None,
    certificate_type: str | None = None,
    actor: dict | None = None,
) -> dict:
    content = await read_upload(file)
    try:
        parsed_type = parse_certificate_type(certificate_type, required=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    frozen_type = parsed_type.value if parsed_type else None
    body_template = _body(texto_padrao, frozen_type)
    report = _parse(content, data_emissao=data_emissao, certificate_type=frozen_type)
    context = _review_context(report, body_template=body_template, certificate_type=frozen_type)
    active = template_service.get_active_version(frozen_type)
    missing = template_fields.missing_settings((active or {}).get("layout") or {})
    return serialize_report(
        report,
        body_template=body_template,
        certificate_type=frozen_type,
        layout_warnings=layout_warnings(context) if context else [],
        empty_fields=empty_fields(context) if context else [],
        missing_settings=missing,
        missing_settings_message=(
            template_fields.missing_settings_message(missing, actor=actor) if missing else None
        ),
        can_manage_settings=bool(actor and is_allowed(actor, Permission.SETTINGS_MANAGE)),
        template_problem=_template_problem(active, frozen_type, actor=actor),
        can_manage_templates=bool(actor and is_allowed(actor, Permission.TEMPLATES_MANAGE)),
    )


def _request_hash(
    report: spreadsheet.ValidationReport,
    data_emissao: str | None,
    body: str,
    drive_folders: dict[str, str] | None,
    certificate_type: str,
) -> str:
    """Hash semantic input, not volatile XLSX ZIP metadata/timestamps."""
    value = {
        "default_issue_date": data_emissao or "",
        "body": body,
        "drive_folders": drive_folders,
        "certificate_type": certificate_type,
        "valid": [asdict(row) for row in report.valid],
        "invalid": [
            {
                "row_number": row.row_number,
                "data": row.data,
                "errors": row.errors,
            }
            for row in report.invalid
        ],
    }
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(canonical).hexdigest()


def _invalid_report(report: spreadsheet.ValidationReport) -> list[dict]:
    return [
        {"row_number": row.row_number, "errors": row.errors, "data": None} for row in report.invalid
    ]


def _context_aad(batch_id: str) -> str:
    return f"emission-batch:{batch_id}:context:v1"


def _row_aad(batch_id: str, row_number: int, business_key: str) -> str:
    return f"emission-batch:{batch_id}:row:{row_number}:{business_key}:v1"


async def prepare_batch(
    file: UploadFile,
    *,
    data_emissao: str | None,
    texto_padrao: str | None,
    idempotency_key: str,
    drive_folders: dict[str, str],
    certificate_type: str,
    actor: dict,
) -> tuple[dict, bool]:
    """Validate once, encrypt durable work items, and commit the job atomically."""
    key = validate_idempotency_key(idempotency_key)
    try:
        parsed_type = parse_certificate_type(certificate_type, required=True)
        assert parsed_type is not None
        frozen_type = parsed_type.value
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    content = await read_upload(file)
    body_template = _body(texto_padrao, frozen_type)
    report = _parse(content, data_emissao=data_emissao, certificate_type=frozen_type)
    # A per-work type never falls back to the generic template, and its own
    # must fit it; the review screen says the same, this guards the API.
    active = template_service.get_active_version(frozen_type)
    template_problem = _template_problem(active, frozen_type, actor=actor)
    if template_problem:
        raise HTTPException(status_code=422, detail=template_problem)
    # A template that prints an empty setting would issue incomplete
    # certificates; the review screen says the same, this guards the API.
    missing = template_fields.missing_settings((active or {}).get("layout") or {})
    if missing:
        raise HTTPException(
            status_code=422,
            detail=template_fields.missing_settings_message(missing, actor=actor),
        )
    from storage_service import config as storage_config

    if storage_config.get_storage_provider() == "local":
        validated_folders: dict[str, str] | None = None
    else:
        expected_events = {event_key(row.evento) for row in report.valid}
        supplied_events = set(drive_folders)
        if expected_events != supplied_events or any(
            not folder.strip() for folder in drive_folders.values()
        ):
            raise HTTPException(status_code=422, detail=_MISSING_DESTINATION_MESSAGE)
        from certificados_backend.services import drive_integration

        validated_folders = drive_integration.validate_batch_destinations(
            actor=actor,
            destinations={event_key(key): value.strip() for key, value in drive_folders.items()},
        )
    request_hash = _request_hash(
        report,
        data_emissao,
        body_template,
        validated_folders,
        frozen_type,
    )
    existing = db.get_emission_batch_by_idempotency_key(key)
    if existing:
        if existing.get("request_sha256") != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Esta chave de idempotência já foi usada para outro lote.",
            )
        if int(existing.get("created_by") or 0) != int(actor["id"]):
            raise HTTPException(status_code=409, detail="Chave de idempotência indisponível.")
        return existing, False

    batch_id = str(uuid.uuid4())
    snapshot = settings_service.certificate_snapshot()
    try:
        context = job_crypto.encrypt_json(
            {
                "schema_version": 3,
                "body_template": body_template,
                "snapshot": snapshot,
                "drive_folders": validated_folders,
                "certificate_type": frozen_type,
            },
            aad=_context_aad(batch_id),
        )
        items: list[dict[str, Any]] = []
        for row in report.valid:
            resolved_body = resolve_batch_body(row, body_template, frozen_type)
            business_key = compute_business_key(row, resolved_body, frozen_type)
            payload = job_crypto.encrypt_json(
                asdict(row),
                aad=_row_aad(batch_id, row.row_number, business_key),
            )
            items.append(
                {
                    "batch_id": batch_id,
                    "row_number": row.row_number,
                    "status": "queued",
                    "business_key": business_key,
                    "payload_ciphertext": payload.ciphertext,
                    "payload_nonce": payload.nonce,
                    "payload_key_id": payload.key_id,
                    "attempt_count": 0,
                }
            )
    except job_crypto.PayloadCryptoError as exc:
        raise HTTPException(
            status_code=503,
            detail="A fila de emissão não está configurada corretamente.",
        ) from exc

    invalid = _invalid_report(report)
    values = {
        "id": batch_id,
        "idempotency_key": key,
        "request_sha256": request_hash,
        "status": "queued",
        "total_rows": report.total,
        "valid_count": report.valid_count,
        "invalid_count": report.invalid_count,
        "processed_count": 0,
        "generated_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
        "certificate_type": frozen_type,
        "invalid_report_json": json.dumps(invalid, ensure_ascii=False),
        "context_ciphertext": context.ciphertext,
        "context_nonce": context.nonce,
        "payload_key_id": context.key_id,
        "max_attempts": _int_env("BATCH_MAX_ATTEMPTS", 3, 1, 10),
        "created_by": actor["id"],
    }
    try:
        batch = db.create_emission_batch(values, items)
    except IntegrityError:
        # A double click/racing request can win after the initial read.
        existing = db.get_emission_batch_by_idempotency_key(key)
        if not existing or existing.get("request_sha256") != request_hash:
            raise HTTPException(status_code=409, detail="Chave de idempotência já utilizada.")
        return existing, False
    audit_service.record(
        "batch_created",
        actor=actor,
        target_type="emission_batch",
        target_id=batch_id,
        details={
            "batch_id": batch_id,
            "total_rows": report.total,
            "invalid": report.invalid_count,
            "destination_count": len(validated_folders or {}),
            "certificate_type": frozen_type,
        },
    )
    return batch, True


def configured_service(
    base_service: CertificateBatchService, snapshot: dict
) -> CertificateBatchService:
    config = replace(
        base_service.config,
        issue_location=str(snapshot.get("issue_location") or ""),
        signatory_name=str(snapshot.get("signatory_name") or ""),
        signatory_title=str(snapshot.get("signatory_title") or ""),
        institution_name=str(snapshot.get("institution_name") or ""),
        public_validation_base_url=str(snapshot.get("public_url") or ""),
    )
    generator = base_service.generator
    return CertificateBatchService(
        config,
        storage=base_service._storage,
        generator=None if isinstance(generator, CertificateGenerator) else generator,
        cache_active_template=True,
    )


def _worker_id() -> str:
    host = re.sub(r"[^A-Za-z0-9_.-]", "-", socket.gethostname())[:48]
    return f"{host}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _lease_deadline(now: datetime) -> datetime:
    seconds = _int_env("BATCH_LEASE_SECONDS", 600, 60, 3600)
    return now + timedelta(seconds=seconds)


def _actor(batch: dict) -> dict:
    user_id = int(batch.get("created_by") or 0)
    user = db.get_admin_user_by_id(user_id) if user_id else None
    return {
        "id": user_id or None,
        "username": (user or {}).get("username") or "system-job",
        "role": (user or {}).get("role") or "system",
    }


def _decrypt_context(
    batch: dict,
) -> tuple[str, dict, dict[str, str] | None, str | None]:
    if not all(
        (
            batch.get("context_ciphertext"),
            batch.get("context_nonce"),
            batch.get("payload_key_id"),
        )
    ):
        raise job_crypto.PayloadCryptoError("Contexto do job está ausente.")
    value = job_crypto.decrypt_json(
        batch["context_ciphertext"],
        batch["context_nonce"],
        str(batch["payload_key_id"]),
        aad=_context_aad(str(batch["id"])),
    )
    body = value.get("body_template")
    snapshot = value.get("snapshot")
    if not isinstance(body, str) or not isinstance(snapshot, dict):
        raise job_crypto.PayloadCryptoError("Contexto do job possui formato inválido.")
    raw_folders = value.get("drive_folders")
    try:
        parsed_type = parse_certificate_type(value.get("certificate_type"), required=False)
    except ValueError as exc:
        raise job_crypto.PayloadCryptoError("Tipo do certificado do lote é inválido.") from exc
    frozen_type = parsed_type.value if parsed_type else None
    if raw_folders is None:
        # Compatibility with jobs created before per-event destinations. Those
        # jobs retain the explicit legacy/global behavior they were born with.
        return body, snapshot, None, frozen_type
    if not isinstance(raw_folders, dict) or any(
        not isinstance(key, str) or not isinstance(folder, str) or not folder.strip()
        for key, folder in raw_folders.items()
    ):
        raise job_crypto.PayloadCryptoError("Destinos do lote possuem formato inválido.")
    return (
        body,
        snapshot,
        {event_key(key): folder.strip() for key, folder in raw_folders.items()},
        frozen_type,
    )


def _decrypt_row(batch_id: str, item: dict) -> SpreadsheetRow:
    ciphertext = item.get("payload_ciphertext")
    nonce = item.get("payload_nonce")
    key_id = item.get("payload_key_id")
    if not isinstance(ciphertext, bytes) or not isinstance(nonce, bytes) or not key_id:
        raise job_crypto.PayloadCryptoError("Item do job está sem payload.")
    value = job_crypto.decrypt_json(
        ciphertext,
        nonce,
        str(key_id),
        aad=_row_aad(
            batch_id,
            int(item["row_number"]),
            str(item["business_key"]),
        ),
    )
    try:
        workload = value.get("carga_horaria")
        return SpreadsheetRow(
            row_number=int(value["row_number"]),
            nome=str(value["nome"]),
            carga_horaria=None if workload is None else int(workload),
            curso=str(value.get("curso") or ""),
            evento=str(value.get("evento") or ""),
            data_emissao=str(value.get("data_emissao") or ""),
            email=str(value.get("email") or ""),
            documento=str(value.get("documento") or ""),
            data_inicio=str(value.get("data_inicio") or ""),
            data_fim=str(value.get("data_fim") or ""),
            # Jobs queued before per-work certificates carry none of these.
            autores=tuple(str(name) for name in (value.get("autores") or []) if str(name)),
            equipe=str(value.get("equipe") or ""),
            titulo_trabalho=str(value.get("titulo_trabalho") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise job_crypto.PayloadCryptoError("Linha do job possui formato inválido.") from exc


def _result(batch: dict) -> dict[str, Any]:
    try:
        result = json.loads(batch.get("result_json") or "null")
    except (TypeError, ValueError):
        result = None
    if not isinstance(result, dict):
        result = {}
    result.setdefault("batch_id", batch["id"])
    result.setdefault("generated", [])
    result.setdefault("duplicates", [])
    result.setdefault("failed", [])
    return result


def _record_result(
    result: dict[str, Any], category: str, row_number: int, value: dict[str, Any]
) -> None:
    values = result.setdefault(category, [])
    if not isinstance(values, list):
        values = []
        result[category] = values
    values[:] = [entry for entry in values if entry.get("row_number") != row_number]
    values.append({"row_number": row_number, **value})


def _persist_progress(batch_id: str, result: dict[str, Any]) -> None:
    counts = db.emission_batch_item_counts(batch_id)
    processed = sum(
        counts.get(status, 0) for status in ("generated", "duplicate", "failed", "cancelled")
    )
    db.update_emission_batch(
        batch_id,
        {
            "processed_count": processed,
            "generated_count": counts.get("generated", 0),
            "duplicate_count": counts.get("duplicate", 0),
            "failed_count": counts.get("failed", 0),
            "result_json": json.dumps(result, ensure_ascii=False),
        },
    )


def _is_cancel_requested(batch_id: str) -> bool:
    current = db.get_emission_batch(batch_id) or {}
    return current.get("cancel_requested_at") is not None


def _finish_batch(batch_id: str, *, actor: dict, result: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    batch = db.get_emission_batch(batch_id) or {}
    counts = db.emission_batch_item_counts(batch_id)
    generated = counts.get("generated", 0)
    duplicate = counts.get("duplicate", 0)
    failed = counts.get("failed", 0)
    cancelled = counts.get("cancelled", 0)
    processed = generated + duplicate + failed + cancelled
    if cancelled:
        status = "cancelled"
    elif failed and (generated or duplicate):
        status = "partial"
    elif failed:
        status = "failed"
    else:
        status = "completed"

    try:
        invalid = json.loads(batch.get("invalid_report_json") or "[]")
    except (TypeError, ValueError):
        invalid = []
    result.update(
        generated_count=generated,
        duplicate_count=duplicate,
        failed_count=failed,
        invalid=invalid,
        invalid_count=int(batch.get("invalid_count") or 0),
        total_rows=int(batch.get("total_rows") or 0),
    )
    values: dict[str, Any] = {
        "status": status,
        "processed_count": processed,
        "generated_count": generated,
        "duplicate_count": duplicate,
        "failed_count": failed,
        "result_json": json.dumps(result, ensure_ascii=False),
        "completed_at": now,
        "lease_owner": None,
        "lease_expires_at": None,
        "next_attempt_at": None,
    }
    if status in {"completed", "cancelled"}:
        values.update(
            context_ciphertext=None,
            context_nonce=None,
            payload_key_id=None,
        )
    db.update_emission_batch(batch_id, values)
    action = "emission_cancelled" if status == "cancelled" else "emission_completed"
    audit_service.record(
        action,
        actor=actor,
        target_type="emission_batch",
        target_id=batch_id,
        details={
            "batch_id": batch_id,
            "status": status,
            "generated": generated,
            "duplicates": duplicate,
            "failed": failed,
            "invalid": int(batch.get("invalid_count") or 0),
            "total_rows": int(batch.get("total_rows") or 0),
        },
    )
    if duplicate:
        audit_service.record(
            "certificate_duplicate",
            actor=actor,
            target_type="emission_batch",
            target_id=batch_id,
            details={"batch_id": batch_id, "count": duplicate},
        )
    return status


def run_one_job(
    base_service: CertificateBatchService,
    *,
    batch_id: str | None = None,
    worker_id: str | None = None,
) -> bool:
    """Claim and process one durable job; return whether a job was claimed."""
    worker = worker_id or _worker_id()
    now = datetime.now(timezone.utc)
    batch = db.claim_emission_batch(
        worker_id=worker,
        now=now,
        lease_expires_at=_lease_deadline(now),
        batch_id=batch_id,
    )
    if batch is None:
        return False
    correlation_token = observability.correlation_id_var.set(f"job-{str(batch['id'])[:36]}")
    started_monotonic = time.monotonic()
    actor = _actor(batch)
    result = _result(batch)
    try:
        body_template, snapshot, drive_folders, certificate_type = _decrypt_context(batch)
        service = configured_service(base_service, snapshot)
        items = db.get_emission_batch_items(batch["id"], statuses=("queued",))
        for item in items:
            heartbeat_at = datetime.now(timezone.utc)
            if not db.heartbeat_emission_batch(
                batch["id"],
                worker_id=worker,
                now=heartbeat_at,
                lease_expires_at=_lease_deadline(heartbeat_at),
            ):
                LOGGER.warning("event=batch_lease_lost batch_id=%s", batch["id"])
                return True
            if _is_cancel_requested(batch["id"]):
                db.cancel_remaining_emission_batch_items(batch["id"], now=heartbeat_at)
                break
            if not db.mark_emission_batch_item_processing(int(item["id"]), now=heartbeat_at):
                continue
            if _is_cancel_requested(batch["id"]):
                db.mark_emission_batch_item(int(item["id"]), status="cancelled", clear_payload=True)
                db.cancel_remaining_emission_batch_items(batch["id"], now=heartbeat_at)
                break

            row = _decrypt_row(str(batch["id"]), item)
            destination = (
                None if drive_folders is None else drive_folders.get(event_key(row.evento))
            )
            if drive_folders is not None and not destination:
                raise job_crypto.PayloadCryptoError(
                    "O lote não possui destino para um dos eventos."
                )
            existing = db.get_by_business_key(str(item["business_key"]))
            if (
                existing is not None
                and str(existing.get("batch_id") or "") == str(batch["id"])
                and existing.get("status") == "failed"
                and not existing.get("drive_file_id")
                and not existing.get("pdf_path")
            ):
                # A prior upload was compensated. Let the saga atomically
                # reopen that reservation and retry with the frozen folder.
                existing = None
            if existing is not None:
                code = str(existing["unique_code"])
                if (
                    str(existing.get("batch_id") or "") == str(batch["id"])
                    and existing.get("status") == "ativo"
                    and (existing.get("drive_file_id") or existing.get("pdf_path"))
                ):
                    status = "generated"
                    _record_result(
                        result,
                        "generated",
                        row.row_number,
                        {"name": row.nome, "code": code, "resumed": True},
                    )
                elif str(existing.get("batch_id") or "") != str(batch["id"]):
                    status = "duplicate"
                    _record_result(
                        result,
                        "duplicates",
                        row.row_number,
                        {
                            "name": row.nome,
                            "existing_code": code,
                            "status": existing.get("status") or "ativo",
                        },
                    )
                else:
                    raise job_crypto.PayloadCryptoError(
                        "Reserva existente do lote possui estado inconsistente."
                    )
                db.mark_emission_batch_item(
                    int(item["id"]),
                    status=status,
                    certificate_code=code,
                    clear_payload=True,
                )
            else:
                summary = service.generate_certificates(
                    [row],
                    issued_by=actor["id"],
                    body_template=body_template,
                    batch_id=str(batch["id"]),
                    institutional_snapshot=snapshot,
                    drive_folder_id=destination,
                    certificate_type=certificate_type,
                )
                if summary.generated:
                    entry = summary.generated[0]
                    code = str(entry["code"])
                    db.mark_emission_batch_item(
                        int(item["id"]),
                        status="generated",
                        certificate_code=code,
                        clear_payload=True,
                    )
                    _record_result(
                        result,
                        "generated",
                        row.row_number,
                        {"name": row.nome, "code": code},
                    )
                elif summary.duplicates:
                    entry = summary.duplicates[0]
                    code = str(entry["existing_code"])
                    db.mark_emission_batch_item(
                        int(item["id"]),
                        status="duplicate",
                        certificate_code=code,
                        clear_payload=True,
                    )
                    _record_result(
                        result,
                        "duplicates",
                        row.row_number,
                        {
                            "name": row.nome,
                            "existing_code": code,
                            "status": entry.get("status") or "ativo",
                        },
                    )
                else:
                    db.mark_emission_batch_item(
                        int(item["id"]),
                        status="failed",
                        error_code="certificate_generation_failed",
                        error_message="Não foi possível gerar esta linha.",
                    )
                    _record_result(
                        result,
                        "failed",
                        row.row_number,
                        {
                            "name": row.nome,
                            "error": "Não foi possível gerar esta linha.",
                        },
                    )
            _persist_progress(str(batch["id"]), result)

        status = _finish_batch(str(batch["id"]), actor=actor, result=result)
        observability.metrics.increment(observability.EMISSION_JOBS_COMPLETED)
        if status in {"partial", "failed"}:
            observability.metrics.increment(observability.EMISSION_JOBS_FAILED)
        return True
    except job_crypto.PayloadCryptoError:
        failed_at = datetime.now(timezone.utc)
        db.release_emission_batch(
            str(batch["id"]),
            worker_id=worker,
            retry_at=None,
            error_code="job_payload_integrity",
            error_message="Payload do lote indisponível ou inválido.",
            now=failed_at,
        )
        audit_service.record(
            "integrity_incident",
            actor=actor,
            target_type="emission_batch",
            target_id=str(batch["id"]),
            details={"batch_id": batch["id"], "kind": "job_payload"},
        )
        LOGGER.exception("Falha de integridade no payload do lote %s", batch["id"])
        observability.metrics.increment(observability.EMISSION_JOBS_FAILED)
        return True
    except Exception as exc:  # noqa: BLE001 - durable worker boundary
        failed_at = datetime.now(timezone.utc)
        attempts = int(batch.get("attempt_count") or 0)
        max_attempts = int(batch.get("max_attempts") or 3)
        retry_at = None
        if attempts < max_attempts:
            delay = min(300, 15 * (2 ** max(0, attempts - 1)))
            retry_at = failed_at + timedelta(seconds=delay)
        db.release_emission_batch(
            str(batch["id"]),
            worker_id=worker,
            retry_at=retry_at,
            error_code="worker_failure",
            error_message=(
                "Falha transitória; o lote será retomado."
                if retry_at
                else "A emissão falhou apó esgotar as tentativas."
            ),
            now=failed_at,
        )
        audit_service.record(
            "generation_failed",
            actor=actor,
            target_type="emission_batch",
            target_id=str(batch["id"]),
            details={
                "batch_id": batch["id"],
                "retry_scheduled": retry_at is not None,
                "error_class": type(exc).__name__,
            },
        )
        LOGGER.exception("Falha no worker do lote %s", batch["id"])
        observability.metrics.increment(observability.EMISSION_JOBS_FAILED)
        return True
    finally:
        observability.metrics.observe(
            observability.EMISSION_JOB_DURATION_MS,
            (time.monotonic() - started_monotonic) * 1000,
        )
        observability.correlation_id_var.reset(correlation_token)


def complete_empty_batch(batch_id: str, *, actor: dict) -> None:
    """Finish an all-invalid spreadsheet without scheduling a worker."""
    current = db.get_emission_batch(batch_id) or {}
    result = _result(current)
    _finish_batch(batch_id, actor=actor, result=result)


def cancel_batch(batch_id: str, *, actor: dict) -> dict:
    status = db.request_emission_batch_cancel(batch_id, now=datetime.now(timezone.utc))
    if status is None:
        raise HTTPException(status_code=404, detail="Lote não encontrado.")
    audit_service.record(
        "emission_cancel_requested",
        actor=actor,
        target_type="emission_batch",
        target_id=batch_id,
        details={"batch_id": batch_id, "status": status},
    )
    return get_batch(batch_id) or {}


def retry_batch(batch_id: str, *, actor: dict) -> dict:
    if not db.retry_emission_batch(batch_id, now=datetime.now(timezone.utc)):
        raise HTTPException(
            status_code=409,
            detail="Este lote não pode ser retomado ou esgotou as tentativas.",
        )
    audit_service.record(
        "emission_retry_requested",
        actor=actor,
        target_type="emission_batch",
        target_id=batch_id,
        details={"batch_id": batch_id},
    )
    return get_batch(batch_id) or {}


def serialize_batch(batch: dict) -> dict:
    valid = int(batch.get("valid_count") or 0)
    processed = int(batch.get("processed_count") or 0)
    status = batch.get("status") or "queued"
    percent = (
        100
        if status in _TERMINAL_STATUSES
        else (min(99, round(processed * 100 / valid)) if valid else 0)
    )
    try:
        result = json.loads(batch.get("result_json") or "null")
    except (TypeError, ValueError):
        result = None
    try:
        invalid = json.loads(batch.get("invalid_report_json") or "[]")
    except (TypeError, ValueError):
        invalid = []
    return {
        "id": batch["id"],
        "status": status,
        "total_rows": int(batch.get("total_rows") or 0),
        "valid_count": valid,
        "invalid_count": int(batch.get("invalid_count") or 0),
        "processed_count": processed,
        "generated_count": int(batch.get("generated_count") or 0),
        "duplicate_count": int(batch.get("duplicate_count") or 0),
        "failed_count": int(batch.get("failed_count") or 0),
        "certificate_type": batch.get("certificate_type"),
        "certificate_type_label": certificate_type_label(batch.get("certificate_type")),
        "progress_percent": percent,
        "attempt_count": int(batch.get("attempt_count") or 0),
        "max_attempts": int(batch.get("max_attempts") or 3),
        "result": result,
        "invalid_report": invalid,
        "error_message": batch.get("error_message"),
        "created_by": batch.get("created_by"),
        "created_at": batch.get("created_at"),
        "started_at": batch.get("started_at"),
        "completed_at": batch.get("completed_at"),
        "updated_at": batch.get("updated_at"),
    }


def get_batch(batch_id: str) -> dict | None:
    row = db.get_emission_batch(batch_id)
    return serialize_batch(row) if row else None
