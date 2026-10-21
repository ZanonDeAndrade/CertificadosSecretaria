from __future__ import annotations

import json
from io import BytesIO

from certificados_backend.policies import Permission, require_permission
from certificados_backend.schemas.batches import (
    EmissionBatchPageResponse,
    EmissionBatchResponse,
    SpreadsheetPreviewResponse,
)
from certificados_backend.services import batch_service, job_dispatch
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from database import db

router = APIRouter(tags=["emission-batches"])


@router.get(
    "/certificates/spreadsheet-template",
    operation_id="download_spreadsheet_template",
    responses={
        200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}
    },
)
def spreadsheet_template(
    _: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> StreamingResponse:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "certificados"
    columns = [
        "nome",
        "carga_horaria",
        "curso",
        "evento",
        "data_emissao",
        "data_inicio",
        "data_fim",
        "email",
        "documento",
    ]
    sheet.append(columns)
    sheet.append(
        [
            "Nome completo",
            8,
            "Curso (opcional)",
            "Evento (opcional)",
            "10/06/2026",
            "",
            "",
            "",
            "",
        ]
    )
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for index, width in enumerate((32, 18, 28, 32, 18, 18, 18, 32, 20), start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A2"
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="modelo-certificados.xlsx"'},
    )


@router.post(
    "/certificates/validate-spreadsheet",
    response_model=SpreadsheetPreviewResponse,
    operation_id="validate_certificate_spreadsheet",
)
async def validate_spreadsheet(
    file: UploadFile = File(...),
    data_emissao: str | None = Form(None),
    texto_padrao: str | None = Form(None),
    certificate_type: str | None = Form(None),
    _: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    return await batch_service.preview(
        file,
        data_emissao=data_emissao,
        texto_padrao=texto_padrao,
        certificate_type=certificate_type,
    )


@router.post(
    "/emission-batches",
    response_model=EmissionBatchResponse,
    status_code=202,
    operation_id="start_emission_batch",
)
async def start_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    data_emissao: str | None = Form(None),
    texto_padrao: str | None = Form(None),
    certificate_type: str = Form(...),
    drive_folders_json: str = Form("{}"),
    idempotency_key: str = Header(alias="Idempotency-Key"),
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    try:
        raw_folders = json.loads(drive_folders_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Destinos do Google Drive inválidos.") from exc
    if not isinstance(raw_folders, dict) or any(
        not isinstance(key, str)
        or not isinstance(folder_id, str)
        or len(key) > 255
        or not (1 <= len(folder_id.strip()) <= 255)
        for key, folder_id in raw_folders.items()
    ):
        raise HTTPException(status_code=422, detail="Destinos do Google Drive inválidos.")
    batch, created = await batch_service.prepare_batch(
        file,
        data_emissao=data_emissao,
        texto_padrao=texto_padrao,
        idempotency_key=idempotency_key,
        drive_folders={key: value.strip() for key, value in raw_folders.items()},
        certificate_type=certificate_type,
        actor=current,
    )
    if created:
        if not int(batch.get("valid_count") or 0):
            batch_service.complete_empty_batch(batch["id"], actor=current)
        elif batch_service.worker_mode() == "inline":
            # Development/test convenience only. The background task receives
            # the durable id, never request-memory rows; a crash leaves a
            # claimable queued/stale job for the external worker.
            background_tasks.add_task(
                batch_service.run_one_job,
                request.app.state.certificate_service,
                batch_id=batch["id"],
            )
        elif job_dispatch.mode() == "cloud_run_job":
            # Queue state was committed before this best-effort wake-up. A
            # periodic fallback execution recovers a failed control-plane call.
            background_tasks.add_task(job_dispatch.dispatch)
    return batch_service.get_batch(batch["id"]) or batch_service.serialize_batch(batch)


def _visible_batch(batch_id: str, current: dict) -> dict:
    batch = batch_service.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Lote não encontrado.")
    return batch


def _mutable_batch(batch_id: str, current: dict) -> dict:
    batch = _visible_batch(batch_id, current)
    if current.get("role") != "admin" and int(batch.get("created_by") or 0) != int(current["id"]):
        raise HTTPException(status_code=403, detail="Operação não permitida.")
    return batch


@router.get(
    "/emission-batches/{batch_id}",
    response_model=EmissionBatchResponse,
    operation_id="get_emission_batch",
)
def get_batch(
    batch_id: str,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_READ)),
) -> dict:
    return _visible_batch(batch_id, current)


@router.post(
    "/emission-batches/{batch_id}/cancel",
    response_model=EmissionBatchResponse,
    operation_id="cancel_emission_batch",
)
def cancel_batch(
    batch_id: str,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    _mutable_batch(batch_id, current)
    return batch_service.cancel_batch(batch_id, actor=current)


@router.post(
    "/emission-batches/{batch_id}/retry",
    response_model=EmissionBatchResponse,
    operation_id="retry_emission_batch",
)
def retry_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    batch_id: str,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    _mutable_batch(batch_id, current)
    retried = batch_service.retry_batch(batch_id, actor=current)
    if batch_service.worker_mode() == "inline":
        background_tasks.add_task(
            batch_service.run_one_job,
            request.app.state.certificate_service,
            batch_id=batch_id,
        )
    elif job_dispatch.mode() == "cloud_run_job":
        background_tasks.add_task(job_dispatch.dispatch)
    return retried


@router.get(
    "/emission-batches/by-idempotency-key/{idempotency_key}",
    response_model=EmissionBatchResponse,
    operation_id="resume_emission_batch",
)
def by_idempotency_key(
    idempotency_key: str,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    key = batch_service.validate_idempotency_key(idempotency_key)
    row = db.get_emission_batch_by_idempotency_key(key)
    if not row or (
        current.get("role") != "admin" and int(row.get("created_by") or 0) != int(current["id"])
    ):
        raise HTTPException(status_code=404, detail="Lote não encontrado.")
    return batch_service.serialize_batch(row)


@router.get(
    "/emission-batches",
    response_model=EmissionBatchPageResponse,
    operation_id="list_emission_batches",
)
def list_batches(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current: dict = Depends(require_permission(Permission.CERTIFICATES_READ)),
) -> dict:
    rows, total = db.list_emission_batches(limit=limit, offset=offset)
    return {
        "items": [batch_service.serialize_batch(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
