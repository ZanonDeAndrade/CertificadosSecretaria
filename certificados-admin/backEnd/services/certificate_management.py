"""History, lifecycle and audited download operations."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from certificados_backend.services import audit_service
from certificados_backend.utils.dates import extenso_from_iso
from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

import observability
from database import db
from database.certificate_types import certificate_type_label
from database.repositories import authors_from_json
from storage_service import (
    RetrievedFile,
    StorageError,
    StorageIntegrityError,
    download_certificate,
)
from storage_service.filenames import certificate_filename, content_disposition

LOGGER = logging.getLogger("certificados.certificates")


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


def _download_limit(actor: dict, *, bulk: bool) -> None:
    scope = "bulk" if bulk else "single"
    window = 3600 if bulk else 60
    limit = (
        _int_env("BULK_DOWNLOAD_REQUESTS_PER_HOUR", 12, 1, 1000)
        if bulk
        else _int_env("DOWNLOAD_REQUESTS_PER_MINUTE", 60, 1, 1000)
    )
    actor_key = hashlib.sha256(
        f"admin-download:{scope}:{actor.get('id')}".encode("utf-8")
    ).hexdigest()
    allowed, retry_after = db.consume_public_rate_limit(
        actor_key,
        now=datetime.now(timezone.utc),
        window_seconds=window,
        limit=limit,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Limite de downloads atingido. Tente novamente mais tarde.",
            headers={"Retry-After": str(retry_after)},
        )


def _responsible(user_id: int | None) -> dict | None:
    if not user_id:
        return None
    user = db.get_admin_user_by_id(int(user_id))
    return {
        "id": int(user_id),
        "name": (user or {}).get("name"),
        "username": (user or {}).get("username"),
    }


def serialize(
    cert: dict, *, actor: dict, full: bool = False, resolve_responsible: bool = True
) -> dict:
    has_file = bool(cert.get("drive_file_id") or cert.get("pdf_path"))
    blocked = bool(cert.get("integrity_blocked"))
    status = cert.get("status") or "ativo"
    integrity_status = (
        "blocked" if blocked else "verified" if cert.get("checksum_sha256") else "unverified"
    )
    response = {
        "unique_code": cert["unique_code"],
        "participant_name": cert["participant_name"],
        "course_name": cert.get("course_name"),
        "event_name": cert.get("event_name"),
        "certificate_type": cert.get("certificate_type"),
        "certificate_type_label": certificate_type_label(cert.get("certificate_type")),
        "workload_hours": cert.get("workload_hours"),
        "authors": authors_from_json(cert.get("authors_json")),
        "team_name": cert.get("team_name"),
        "work_title": cert.get("work_title"),
        "issue_date": extenso_from_iso(cert.get("issue_date")),
        "issue_date_iso": cert.get("issue_date"),
        "status": status,
        "download_available": has_file and status == "ativo" and not blocked,
        "integrity_status": integrity_status,
        "integrity_blocked": blocked,
        "storage_provider": cert.get("storage_provider"),
        "template_used": cert.get("template_used"),
        "template_version_id": cert.get("template_version_id"),
        "issued_by": _responsible(cert.get("issued_by")) if resolve_responsible else None,
        "batch_id": cert.get("batch_id"),
        "created_at": cert.get("created_at"),
        "updated_at": cert.get("updated_at"),
        "reissue_count": int(cert.get("reissue_count") or 0),
        "reissued_at": cert.get("reissued_at"),
        "reissued_by": _responsible(cert.get("reissued_by")) if resolve_responsible else None,
    }
    if full:
        may_view_business_detail = actor.get("role") in {"admin", "secretaria"}
        response.update(
            {
                "participant_email": (
                    cert.get("participant_email") if may_view_business_detail else None
                ),
                "start_date": extenso_from_iso(cert.get("start_date")),
                "end_date": extenso_from_iso(cert.get("end_date")),
                "file_size": cert.get("file_size"),
                "certificate_text": (
                    cert.get("certificate_text") if may_view_business_detail else None
                ),
                "revoked_at": cert.get("revoked_at"),
                "revoke_reason": cert.get("revoke_reason"),
            }
        )
    return response


def revoke(code: str, reason: str, *, actor: dict) -> dict:
    cert = db.get_by_code(code.strip())
    if not cert:
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    if (cert.get("status") or "ativo") == "revogado":
        raise HTTPException(status_code=409, detail="Certificado já está revogado.")
    if (cert.get("status") or "ativo") != "ativo":
        raise HTTPException(
            status_code=409, detail="Apenas certificados ativos podem ser revogados."
        )
    clean_reason = " ".join(reason.strip().split())
    if len(clean_reason) < 5:
        raise HTTPException(
            status_code=400, detail="Informe um motivo com pelo menos 5 caracteres."
        )
    changed = db.update_certificate_status(
        code.strip(),
        status="revogado",
        revoked_by=actor["id"],
        revoke_reason=clean_reason,
        expected_status="ativo",
    )
    if not changed:
        raise HTTPException(
            status_code=409, detail="O certificado foi alterado por outra operação."
        )
    audit_service.record(
        "certificate_revoked",
        actor=actor,
        target_type="certificate",
        target_id=cert["unique_code"],
        # The reason remains on the certificate lifecycle record where it is
        # needed by the secretariat. Do not duplicate arbitrary free text in
        # the audit trail: an operator could inadvertently type personal data.
        details={"reason": "provided", "status": "revogado"},
    )
    return serialize(db.get_by_code(code.strip()) or cert, actor=actor, full=True)


def reissue(code: str, *, actor: dict, certificate_service) -> dict:
    cert = db.get_by_code(code.strip())
    if not cert:
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    if (cert.get("status") or "ativo") != "ativo":
        raise HTTPException(
            status_code=409, detail="Apenas certificados ativos podem ser reemitidos."
        )
    try:
        certificate_service.reissue_certificate(cert, reissued_by=actor["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        LOGGER.error("event=reissue_storage_failed error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Falha ao reemitir o certificado.") from exc
    audit_service.record(
        "certificate_reissued",
        actor=actor,
        target_type="certificate",
        target_id=cert["unique_code"],
        details={"count": int(cert.get("reissue_count") or 0) + 1},
    )
    return serialize(db.get_by_code(code.strip()) or cert, actor=actor, full=True)


def _quarantine(cert: dict, _reason: str) -> None:
    observability.metrics.increment(observability.INTEGRITY_INCIDENTS)
    db.block_certificate_integrity(cert["unique_code"])
    audit_service.record(
        "integrity_incident",
        target_type="certificate",
        target_id=cert["unique_code"],
        details={"reason": "stored_file_mismatch", "integrity_status": "blocked"},
    )
    LOGGER.error("event=certificate_integrity_incident reason_class=storage_mismatch")


def retrieve(code: str) -> tuple[dict, RetrievedFile]:
    cert = db.get_by_code(code.strip())
    if not cert:
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    if (cert.get("status") or "ativo") != "ativo":
        raise HTTPException(status_code=410, detail="Certificado revogado.")
    if cert.get("integrity_blocked"):
        raise HTTPException(
            status_code=409, detail="Certificado bloqueado por falha de integridade."
        )
    try:
        return cert, download_certificate(cert, verify=True)
    except StorageIntegrityError as exc:
        _quarantine(cert, str(exc))
        raise HTTPException(
            status_code=409, detail="Falha de integridade: o arquivo foi bloqueado."
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Arquivo do certificado não encontrado."
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=502, detail="Falha ao obter o arquivo do armazenamento."
        ) from exc


def stream(code: str, *, actor: dict, disposition: str = "attachment") -> StreamingResponse:
    _download_limit(actor, bulk=False)
    cert, retrieved = retrieve(code)
    observability.metrics.increment(observability.CERT_DOWNLOADS)
    audit_service.record(
        "certificate_downloaded",
        actor=actor,
        target_type="certificate",
        target_id=cert["unique_code"],
        details={"count": 1},
    )
    return StreamingResponse(
        BytesIO(retrieved.content),
        media_type=retrieved.mime_type,
        headers={
            "Content-Disposition": content_disposition(certificate_filename(cert), disposition)
        },
    )


def _unique_name(filename: str, used: set[str]) -> str:
    # The code inside each name already keeps entries apart; this only guards
    # against a repeated name on case-insensitive file systems.
    stem, extension = os.path.splitext(filename)
    candidate = filename
    counter = 2
    while candidate.casefold() in used:
        candidate = f"{stem} ({counter}){extension}"
        counter += 1
    used.add(candidate.casefold())
    return candidate


def _remove_temp_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("event=temporary_zip_cleanup_failed")


def download_zip(codes: list[str], *, actor: dict) -> FileResponse:
    unique_codes = list(dict.fromkeys(code.strip() for code in codes if code.strip()))
    if not unique_codes:
        raise HTTPException(status_code=400, detail="Nenhum código informado.")
    max_certificates = _int_env("MAX_ZIP_CERTIFICATES", 100, 1, 200)
    if len(unique_codes) > max_certificates:
        raise HTTPException(
            status_code=413,
            detail=f"O ZIP aceita no máximo {max_certificates} certificados.",
        )
    _download_limit(actor, bulk=True)
    max_total_bytes = _int_env(
        "MAX_ZIP_TOTAL_BYTES", 200 * 1024 * 1024, 1024 * 1024, 1024 * 1024 * 1024
    )
    reserve_bytes = _int_env(
        "MIN_TEMP_FREE_BYTES", 32 * 1024 * 1024, 1024 * 1024, 1024 * 1024 * 1024
    )
    temp_root = Path(os.getenv("DOWNLOAD_TEMP_DIR") or tempfile.gettempdir()).resolve()
    if not temp_root.is_dir():
        raise HTTPException(status_code=503, detail="Diretório temporário indisponível.")
    free_bytes = shutil.disk_usage(temp_root).free
    if free_bytes < max_total_bytes + reserve_bytes:
        raise HTTPException(
            status_code=503,
            detail="Espaço temporário insuficiente para montar o ZIP com segurança.",
        )

    temporary = tempfile.NamedTemporaryFile(
        prefix="certificados-", suffix=".zip", dir=temp_root, delete=False
    )
    temp_path = Path(temporary.name)
    temporary.close()
    skipped: list[str] = []
    used: set[str] = set()
    included = 0
    total_uncompressed = 0
    try:
        with ZipFile(temp_path, "w", ZIP_DEFLATED, allowZip64=True) as archive:
            for code in unique_codes:
                try:
                    cert, retrieved = retrieve(code)
                except HTTPException:
                    skipped.append(code)
                    continue
                content_size = len(retrieved.content)
                if total_uncompressed + content_size > max_total_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="O conteúdo total dos certificados excede o limite do ZIP.",
                    )
                archive.writestr(_unique_name(certificate_filename(cert), used), retrieved.content)
                total_uncompressed += content_size
                included += 1
                # Drop the only per-PDF byte reference before retrieving the next file.
                del retrieved
            if skipped:
                archive.writestr(
                    "_erros-download.txt",
                    "Não encontrados, revogados ou indisponíveis:\n" + "\n".join(skipped),
                )
        if included == 0:
            raise HTTPException(
                status_code=404, detail="Nenhum certificado disponível para download."
            )
        if temp_path.stat().st_size > max_total_bytes:
            raise HTTPException(
                status_code=413, detail="O arquivo ZIP excede o limite configurado."
            )
    except Exception:
        _remove_temp_file(str(temp_path))
        raise

    observability.metrics.increment(observability.CERT_DOWNLOADS, included)
    audit_service.record(
        "certificates_downloaded",
        actor=actor,
        target_type="certificate_batch_download",
        details={
            "count": included,
            "failed": len(skipped),
            "bytes": total_uncompressed,
        },
    )
    headers = {"Content-Disposition": 'attachment; filename="certificados.zip"'}
    if skipped:
        headers["X-Skipped-Certificates"] = quote(",".join(skipped), safe=",")[:2048]
    return FileResponse(
        path=temp_path,
        media_type="application/zip",
        filename="certificados.zip",
        headers=headers,
        background=BackgroundTask(_remove_temp_file, str(temp_path)),
    )
