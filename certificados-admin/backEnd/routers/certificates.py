from __future__ import annotations

from datetime import date

from certificados_backend.policies import Permission, require_permission
from certificados_backend.schemas.certificates import (
    CertificatePageResponse,
    CertificateResponse,
    DownloadCertificatesRequest,
    RevokeCertificateRequest,
)
from certificados_backend.services import certificate_management
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from database import db
from database.certificate_types import certificate_type_label, parse_certificate_type

router = APIRouter(tags=["certificates"])
_STATUSES = frozenset({"pending", "ativo", "revogado", "failed"})


@router.get(
    "/certificates",
    response_model=CertificatePageResponse,
    operation_id="list_certificates",
)
def list_certificates(
    name: str | None = Query(default=None, max_length=255),
    code: str | None = Query(default=None, max_length=128),
    course: str | None = Query(default=None, max_length=255),
    event: str | None = Query(default=None, max_length=255),
    certificate_type: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=32),
    date_from: date | None = None,
    date_to: date | None = None,
    batch_id: str | None = Query(default=None, max_length=36),
    order_by: str = Query(default="created_at", pattern="^(created_at|issue_date)$"),
    descending: bool = True,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100000),
    current: dict = Depends(require_permission(Permission.CERTIFICATES_READ)),
) -> dict:
    if status and status not in _STATUSES:
        raise HTTPException(status_code=422, detail="Situação de certificado inválida.")
    try:
        parsed_type = parse_certificate_type(certificate_type, required=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="Período inválido.")
    rows, total = db.list_certificates(
        name=name,
        code=code,
        course=course,
        event=event,
        certificate_type=parsed_type.value if parsed_type else None,
        status=status,
        issue_date_from=date_from.isoformat() if date_from else None,
        issue_date_to=date_to.isoformat() if date_to else None,
        batch_id=batch_id,
        order_by=order_by,
        descending=descending,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [
            certificate_management.serialize(row, actor=current, resolve_responsible=False)
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/certificates/{code}",
    response_model=CertificateResponse,
    operation_id="get_certificate",
)
def get_certificate(
    code: str,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_READ)),
) -> dict:
    cert = db.get_by_code(code.strip())
    if not cert:
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    return certificate_management.serialize(cert, actor=current, full=True)


@router.post(
    "/certificates/{code}/revoke",
    response_model=CertificateResponse,
    operation_id="revoke_certificate",
)
def revoke_certificate(
    code: str,
    payload: RevokeCertificateRequest,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_REVOKE)),
) -> dict:
    return certificate_management.revoke(code, payload.reason, actor=current)


@router.post(
    "/certificates/{code}/reissue",
    response_model=CertificateResponse,
    operation_id="reissue_certificate",
)
def reissue_certificate(
    code: str,
    request: Request,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_REISSUE)),
) -> dict:
    return certificate_management.reissue(
        code, actor=current, certificate_service=request.app.state.certificate_service
    )


@router.get(
    "/certificate-file/{code}",
    operation_id="download_certificate",
    response_class=StreamingResponse,
)
def download_certificate_file(
    code: str,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_DOWNLOAD)),
) -> StreamingResponse:
    return certificate_management.stream(code, actor=current)


@router.post(
    "/certificates/download-zip",
    operation_id="download_certificates_zip",
    response_class=FileResponse,
)
def download_zip(
    payload: DownloadCertificatesRequest,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_DOWNLOAD)),
) -> FileResponse:
    return certificate_management.download_zip(payload.codes, actor=current)


@router.get(
    "/admin/certificates/{code}/metadata",
    operation_id="get_certificate_storage_metadata",
)
def certificate_metadata(
    code: str,
    _: dict = Depends(require_permission(Permission.SETTINGS_READ)),
) -> dict:
    cert = db.get_by_code(code.strip())
    if not cert:
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    # Operational metadata only; no provider URL, local path or participant
    # document is exposed even to an administrator.
    return {
        "unique_code": cert["unique_code"],
        "certificate_type": cert.get("certificate_type"),
        "certificate_type_label": certificate_type_label(cert.get("certificate_type")),
        "storage_provider": cert.get("storage_provider"),
        "original_filename": cert.get("original_filename"),
        "mime_type": cert.get("mime_type"),
        "file_size": cert.get("file_size"),
        "checksum_sha256": cert.get("checksum_sha256"),
        "integrity_blocked": bool(cert.get("integrity_blocked")),
        "created_at": cert.get("created_at"),
        "updated_at": cert.get("updated_at"),
    }
