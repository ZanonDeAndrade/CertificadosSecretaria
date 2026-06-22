from __future__ import annotations

import sys
from pathlib import Path as _Path

# Ensure the backEnd directory is always on sys.path so that bare imports
# like "from models import ..." resolve correctly regardless of the working
# directory the process was started from (e.g. repo root, packaged exe, etc.).
_BACKEND_DIR = str(_Path(__file__).resolve().parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Make the shared `database` package importable by walking up to the repo root
# that contains database/db.py (works regardless of how deep this app lives).
for _ancestor in _Path(__file__).resolve().parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

import json
import logging
import os
import socket
from zipfile import ZIP_DEFLATED, ZipFile
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from storage_service import (
    RetrievedFile,
    StorageError,
    StorageIntegrityError,
    download_certificate,
)

import auth
from database import db
from services import template_service
from services.template_service import TemplateError
from services.certificate_service import (
    CertificateBatchConfig,
    CertificateBatchService,
    build_row_variables,
)
from services.certificate_text import (
    CertificateTextError,
    render_certificate_body,
    validate_body_template,
)
from services import spreadsheet
from services.spreadsheet import SpreadsheetError
from utils.courses import COURSES
from utils.dates import extenso_from_iso
from utils.file_utils import ensure_directory, sanitize_filename
from database.db import PDFS_DIR, get_by_code, init_db

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
FONTS_DIR = BASE_DIR / "fonts"
# Generated PDFs live in the SHARED storage (storage/pdfs) so that
# certificados-consulta can serve them from the same place.
OUTPUT_DIR = PDFS_DIR

TEMPLATE_PATH = TEMPLATES_DIR / "certificado_base.png"
REGULAR_FONT_PATH = FONTS_DIR / "times.ttf"
BOLD_FONT_PATH = FONTS_DIR / "timesbd.ttf"

LOGGER = logging.getLogger("certificados.api")
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
HEALTHCHECK_HOST = "127.0.0.1"
# Dev fallback origins (used only when the admin frontend origin is unset).
_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]


def _env(*names: str, default: str = "") -> str:
    """Return the first non-empty env var among ``names`` (backwards-compat)."""
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return default


def resolve_allowed_origins() -> list[str]:
    """Resolve and strictly validate the admin frontend CORS allowlist."""
    raw_list = _env("CORS_ALLOWED_ORIGINS")
    if raw_list:
        origins = [o.strip().rstrip("/") for o in raw_list.split(",") if o.strip()]
    else:
        admin = _env("ADMIN_FRONTEND_URL", "FRONTEND_ADMIN_URL").rstrip("/")
        origins = [admin] if admin else []

    if not origins:
        if auth.is_production():
            raise RuntimeError(
                "Em produção, configure ADMIN_FRONTEND_URL ou CORS_ALLOWED_ORIGINS."
            )
        LOGGER.warning("CORS não configurado; usando origens locais de desenvolvimento.")
        return _DEV_ORIGINS

    normalized: list[str] = []
    for origin in origins:
        if origin == "*":
            raise RuntimeError("CORS_ALLOWED_ORIGINS não pode conter '*'.")
        try:
            parsed = urlsplit(origin)
            parsed.port
        except ValueError as exc:
            raise RuntimeError(f"Origem CORS inválida: {origin}") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError(f"Origem CORS inválida: {origin}")
        if auth.is_production() and parsed.scheme != "https":
            raise RuntimeError(f"Origem CORS deve usar HTTPS em produção: {origin}")
        normalized.append(f"{parsed.scheme}://{parsed.netloc}".rstrip("/"))
    return list(dict.fromkeys(normalized))


class CertificateDownloadItem(BaseModel):
    name: str
    validation_code: str


class DownloadCertificatesRequest(BaseModel):
    certificates: list[CertificateDownloadItem]


class LoginRequest(BaseModel):
    username: str
    password: str


class RevokeRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class DownloadZipRequest(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=200)


class CreateTemplateVersionRequest(BaseModel):
    name: str | None = None
    # {background: <data URL or serving URL>, image_width, image_height, elements}
    layout: dict


def max_spreadsheet_bytes() -> int:
    raw = _env("MAX_SPREADSHEET_SIZE_MB", "MAX_SPREADSHEET_FILE_SIZE_MB")
    try:
        mb = float(raw) if raw else 10.0
    except ValueError:
        mb = 10.0
    return int(mb * 1024 * 1024)


def max_spreadsheet_rows() -> int:
    raw = (os.getenv("MAX_SPREADSHEET_ROWS") or "").strip()
    try:
        return int(raw) if raw else 2000
    except ValueError:
        return 2000


async def read_spreadsheet_upload(file: UploadFile) -> bytes:
    """Validate an uploaded .xlsx (extension, content, size) and return bytes."""
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Nenhum arquivo foi enviado.")
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400, detail="Envie um arquivo Excel válido com extensão .xlsx."
        )
    content = await file.read()
    await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    if len(content) > max_spreadsheet_bytes():
        raise HTTPException(
            status_code=400,
            detail=f"O arquivo excede o limite de {max_spreadsheet_bytes() // (1024 * 1024)} MB.",
        )
    # .xlsx is a ZIP container — reject renamed files.
    if content[:4] != b"PK\x03\x04":
        raise HTTPException(
            status_code=400, detail="O conteúdo do arquivo não é um .xlsx válido."
        )
    return content


def configure_logging() -> None:
    import observability

    observability.configure_logging()


def validate_startup_config() -> None:
    """Fail-closed checks for production (no-op in development/test).

    In ``APP_ENV=production`` the app refuses to start unless DATABASE_URL,
    a strong JWT_SECRET, an HTTPS CORS allowlist and a fully configured Google
    Drive backend are present. This prevents permissive/ephemeral fallbacks.
    """
    from database import config as db_config
    from database.privacy import validate_production_privacy_config
    from storage_service import config as storage_config

    db_config.require_production_database()
    auth.require_production_auth_config()
    resolve_allowed_origins()
    storage_config.validate_production_storage()
    storage_config.validate_production_public_validation_url()
    validate_production_privacy_config()


def create_app() -> FastAPI:
    configure_logging()
    validate_startup_config()
    from storage_service import config as storage_config
    if not storage_config.is_production():
        # Local PDF directory only matters for the development storage backend.
        ensure_directory(OUTPUT_DIR)
    init_db()  # create the shared tables (dev) / verify connectivity (prod)
    from database import db as shared_db
    shared_db.prepare_private_data()
    auth.seed_admin_from_env()  # create the initial admin user if configured
    auth.cleanup_auth_state()
    # Seed + activate a default global template version if none exists yet.
    template_service.ensure_default_version(TEMPLATE_PATH)

    app = FastAPI(
        title="Certificate Generation API",
        version="1.0.0",
        description="API local para envio de planilhas e geracao de certificados em PDF.",
    )

    import observability

    app.add_middleware(observability.CorrelationIdMiddleware)

    allowed_origins = resolve_allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,  # required for the HttpOnly auth cookie
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        expose_headers=["Content-Disposition", "X-Skipped-Certificates", "X-Request-ID"],
    )

    @app.middleware("http")
    async def enforce_cookie_origin(request: Request, call_next):
        try:
            auth.validate_mutating_request_origin(request, allowed_origins)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    # NB: não montamos StaticFiles em "/certificates" — isso colidiria com as
    # rotas /certificates/* da API. Os PDFs são servidos por /certificate-file/{code}.
    app.state.certificate_service = CertificateBatchService(
        CertificateBatchConfig(
            template_path=TEMPLATE_PATH,
            regular_font_path=REGULAR_FONT_PATH,
            bold_font_path=BOLD_FONT_PATH,
            output_dir=OUTPUT_DIR,
            issue_location=(os.getenv("ISSUE_LOCATION") or "").strip(),
            signatory_name=(os.getenv("SIGNATORY_NAME") or "").strip(),
            signatory_title=(os.getenv("SIGNATORY_TITLE") or "").strip(),
        )
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics_endpoint(_: dict = Depends(auth.get_current_admin)) -> dict:
        """In-process counters (no PII): generation, failures, compensations,
        downloads and integrity incidents."""
        return observability.metrics.snapshot()

    # ── Autenticação (secretaria) ───────────────────────────────────────────────

    @app.post("/auth/login")
    async def login(request: Request, payload: LoginRequest) -> JSONResponse:
        try:
            user, token = await auth.login_with_throttling(
                payload.username, payload.password, request
            )
        except auth.LoginRejected as exc:
            headers = (
                {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=headers,
            )
        json_response = JSONResponse(
            content={
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "role": user.get("role"),
                }
            }
        )
        json_response.set_cookie(
            key=auth.COOKIE_NAME,
            value=token,
            httponly=True,
            secure=auth.cookie_secure(),
            samesite=auth.cookie_samesite(),
            max_age=auth.token_ttl_minutes() * 60,
            path="/",
        )
        return json_response

    @app.post("/auth/logout")
    async def logout(request: Request) -> JSONResponse:
        auth.revoke_request_session(request, reason="logout")
        json_response = JSONResponse(content={"ok": True})
        json_response.delete_cookie(
            key=auth.COOKIE_NAME,
            path="/",
            secure=auth.cookie_secure(),
            httponly=True,
            samesite=auth.cookie_samesite(),
        )
        return json_response

    @app.get("/auth/me")
    async def whoami(current=Depends(auth.get_current_admin)) -> dict:
        return {
            "id": current["id"],
            "username": current["username"],
            "role": current.get("role"),
        }

    @app.post("/auth/sessions/revoke-all")
    async def revoke_own_sessions(
        current: dict = Depends(auth.get_current_admin),
    ) -> JSONResponse:
        count = db.revoke_all_auth_sessions(current["id"], "self_revoke_all")
        response = JSONResponse(content={"revoked": count})
        response.delete_cookie(
            key=auth.COOKIE_NAME,
            path="/",
            secure=auth.cookie_secure(),
            httponly=True,
            samesite=auth.cookie_samesite(),
        )
        return response

    @app.post("/auth/users/{user_id}/sessions/revoke-all")
    async def revoke_user_sessions(
        user_id: int,
        current: dict = Depends(auth.require_roles("admin")),
    ) -> dict:
        user = db.get_admin_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        count = db.revoke_all_auth_sessions(user_id, "admin_revoke_all")
        db.insert_audit_log(
            action="sessions_revoke_all",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="admin_user",
            target_id=str(user_id),
            details=json.dumps({"revoked": count}),
        )
        return {"revoked": count}

    # ── Template global (versionado) ────────────────────────────────────────────

    @app.get("/templates/active")
    async def template_active(_: dict = Depends(auth.get_current_admin)) -> dict:
        version = template_service.get_active_version()
        if not version:
            raise HTTPException(status_code=404, detail="Nenhum template ativo.")
        return version

    @app.get("/templates/versions")
    async def template_versions(_: dict = Depends(auth.get_current_admin)) -> list[dict]:
        return template_service.list_versions()

    @app.get("/templates/versions/{version_id}")
    async def template_version_detail(
        version_id: int, _: dict = Depends(auth.get_current_admin)
    ) -> dict:
        version = template_service.get_version(version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Versão não encontrada.")
        return version

    @app.get("/templates/versions/{version_id}/background")
    async def template_version_background(version_id: int) -> StreamingResponse:
        # Public: a template background image is not sensitive data, and the
        # editor loads it cross-origin where a SameSite=Lax cookie isn't sent.
        try:
            content, mime = template_service.get_background_bytes(version_id)
        except TemplateError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(BytesIO(content), media_type=mime)

    @app.post("/templates/versions")
    async def create_template_version(
        payload: CreateTemplateVersionRequest,
        current: dict = Depends(auth.require_roles("admin")),
    ) -> dict:
        try:
            version = template_service.create_version(
                name=payload.name, layout=payload.layout, created_by=current["id"]
            )
        except TemplateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.insert_audit_log(
            action="template_version_created",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="template_version",
            target_id=str(version["id"]),
            details=f"v{version['version_number']}",
        )
        return version

    @app.post("/templates/versions/{version_id}/activate")
    async def activate_template_version(
        version_id: int, current: dict = Depends(auth.require_roles("admin"))
    ) -> dict:
        if not template_service.activate_version(version_id, current["id"]):
            raise HTTPException(status_code=404, detail="Versão não encontrada.")
        db.insert_audit_log(
            action="template_version_activated",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="template_version",
            target_id=str(version_id),
        )
        return template_service.get_version(version_id)

    @app.get("/certificate-file/{code}")
    async def serve_certificate_file(
        code: str, _: dict = Depends(auth.get_current_admin)
    ) -> StreamingResponse:
        """Stream a certificate PDF by its verification code (provider-agnostic).

        Admin-only view/download. Works for both local and Drive backends and
        never exposes a provider link.
        """
        return _stream_certificate(code, disposition="inline")

    @app.get("/admin/certificates/{code}/metadata")
    async def admin_certificate_metadata(
        code: str, _: dict = Depends(auth.get_current_admin)
    ) -> dict:
        """Protected: full storage metadata for a certificate (admin only)."""
        cert = get_by_code(code.strip())
        if not cert:
            raise HTTPException(status_code=404, detail="Certificado não encontrado.")
        return {
            "unique_code": cert["unique_code"],
            "participant_name": cert["participant_name"],
            "event_name": cert["event_name"],
            "issue_date": extenso_from_iso(cert["issue_date"]),
            "issue_date_iso": cert["issue_date"],
            "status": cert.get("status") or "ativo",
            "storage_provider": cert.get("storage_provider"),
            "drive_file_id": cert.get("drive_file_id"),
            "drive_folder_id": cert.get("drive_folder_id"),
            "original_filename": cert.get("original_filename"),
            "mime_type": cert.get("mime_type"),
            "file_size": cert.get("file_size"),
            "checksum_sha256": cert.get("checksum_sha256"),
            "pdf_path": cert.get("pdf_path"),
            "created_at": cert.get("created_at"),
        }

    @app.get("/courses")
    async def list_courses() -> list[str]:
        """Return the canonical list of valid courses (participant field)."""
        return COURSES

    # ── Modelo estruturado: pré-validação + geração confirmada ──────────────────

    @app.post("/certificates/validate-spreadsheet")
    async def validate_spreadsheet(
        file: UploadFile = File(...),
        data_emissao: str | None = Form(None),
        texto_padrao: str | None = Form(None),
        _: dict = Depends(auth.require_roles("admin", "secretaria")),
    ) -> dict:
        """Validate a spreadsheet and return a preview (nothing is persisted).

        Also validates the secretaria-authored body text and returns it already
        interpolated for the first valid row, so the result can be reviewed
        before emission. The exact same text must be sent to /generate.
        """
        content = await read_spreadsheet_upload(file)
        # Business validation of the body text (AFTER auth + file checks).
        try:
            body_template = validate_body_template(texto_padrao)
        except CertificateTextError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            report = spreadsheet.read_and_validate(
                BytesIO(content),
                default_data_emissao=data_emissao,
                max_rows=max_spreadsheet_rows(),
            )
        except SpreadsheetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("Falha ao ler planilha: %s", exc)
            raise HTTPException(status_code=400, detail="Não foi possível ler a planilha.") from exc
        serialized = _serialize_report(report)
        serialized["resolved_text_preview"] = (
            render_certificate_body(body_template, build_row_variables(report.valid[0]))
            if report.valid
            else None
        )
        return serialized

    @app.post("/certificates/generate")
    async def generate_structured(
        file: UploadFile = File(...),
        data_emissao: str | None = Form(None),
        texto_padrao: str | None = Form(None),
        current: dict = Depends(auth.require_roles("admin", "secretaria")),
    ) -> dict:
        """Validate (again) and generate only the valid, non-duplicate rows.

        Uses the single active global template version (no per-batch choice) and
        the secretaria-authored body text (the SAME text reviewed in the
        preview), interpolated per row into the certificate body."""
        content = await read_spreadsheet_upload(file)
        try:
            body_template = validate_body_template(texto_padrao)
        except CertificateTextError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            report = spreadsheet.read_and_validate(
                BytesIO(content),
                default_data_emissao=data_emissao,
                max_rows=max_spreadsheet_rows(),
            )
        except SpreadsheetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            summary = app.state.certificate_service.generate_certificates(
                report.valid,
                issued_by=current["id"],
                body_template=body_template,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except StorageError as exc:
            LOGGER.error("Falha de armazenamento ao gerar certificados: %s", exc)
            raise HTTPException(
                status_code=502, detail="Falha ao salvar o certificado no armazenamento."
            ) from exc
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("Falha inesperada ao gerar certificados: %s", exc)
            raise HTTPException(status_code=500, detail="Falha inesperada ao gerar certificados.") from exc

        if summary.generated:
            db.insert_audit_log(
                action="generate",
                actor_id=current["id"],
                actor_username=current["username"],
                target_type="certificate",
                target_id=",".join(g["code"] for g in summary.generated),
                details=f"{len(summary.generated)} gerado(s), {len(summary.duplicates)} duplicado(s)",
            )

        return {
            "generated": summary.generated,
            "generated_count": len(summary.generated),
            "duplicates": summary.duplicates,
            "duplicate_count": len(summary.duplicates),
            # Reservations that were rolled back/compensated (status 'failed').
            "failed": summary.failed,
            "failed_count": len(summary.failed),
            "invalid": [
                {"row_number": r.row_number, "errors": r.errors} for r in report.invalid
            ],
            "invalid_count": report.invalid_count,
            "total_rows": report.total,
        }

    # ── Histórico administrativo ────────────────────────────────────────────────

    @app.get("/certificates")
    async def list_certificates_route(
        name: str | None = None,
        code: str | None = None,
        course: str | None = None,
        event: str | None = None,
        status: str | None = None,
        order_by: str = "created_at",
        descending: bool = True,
        limit: int = 20,
        offset: int = 0,
        _: dict = Depends(auth.get_current_admin),
    ) -> dict:
        items, total = db.list_certificates(
            name=name, code=code, course=course, event=event, status=status,
            order_by=order_by, descending=descending, limit=limit, offset=offset,
        )
        return {
            "items": [_serialize_admin_certificate(c) for c in items],
            "total": total,
            "limit": max(1, min(int(limit), 200)),
            "offset": max(0, int(offset)),
        }

    @app.get("/certificates/{code}")
    async def get_certificate_detail(
        code: str, _: dict = Depends(auth.get_current_admin)
    ) -> dict:
        cert = get_by_code(code.strip())
        if not cert:
            raise HTTPException(status_code=404, detail="Certificado não encontrado.")
        return _serialize_admin_certificate(cert, full=True)

    @app.post("/certificates/{code}/revoke")
    async def revoke_certificate(
        code: str,
        payload: RevokeRequest,
        current: dict = Depends(auth.require_roles("admin", "secretaria")),
    ) -> dict:
        cert = get_by_code(code.strip())
        if not cert:
            raise HTTPException(status_code=404, detail="Certificado não encontrado.")
        if (cert.get("status") or "ativo") == "revogado":
            raise HTTPException(status_code=409, detail="Certificado já está revogado.")
        reason = payload.reason.strip()
        if len(reason) < 5:
            raise HTTPException(
                status_code=400,
                detail="Informe um motivo com pelo menos 5 caracteres.",
            )
        db.update_certificate_status(
            code.strip(),
            status="revogado",
            revoked_by=current["id"],
            revoke_reason=reason,
        )
        db.insert_audit_log(
            action="revoke",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="certificate",
            target_id=cert["unique_code"],
            details=reason,
        )
        return _serialize_admin_certificate(get_by_code(code.strip()), full=True)

    @app.post("/certificates/{code}/reissue")
    async def reissue_certificate(
        code: str, current: dict = Depends(auth.require_roles("admin", "secretaria"))
    ) -> dict:
        cert = get_by_code(code.strip())
        if not cert:
            raise HTTPException(status_code=404, detail="Certificado não encontrado.")
        try:
            app.state.certificate_service.reissue_certificate(cert)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except StorageError as exc:
            LOGGER.error("Falha ao reemitir %s: %s", code, exc)
            raise HTTPException(status_code=502, detail="Falha ao reemitir o certificado.") from exc
        db.insert_audit_log(
            action="reissue",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="certificate",
            target_id=cert["unique_code"],
        )
        return _serialize_admin_certificate(get_by_code(code.strip()), full=True)

    @app.post("/certificates/download-zip")
    async def download_zip(
        payload: DownloadZipRequest,
        current: dict = Depends(auth.require_roles("admin", "secretaria")),
    ) -> StreamingResponse:
        if not payload.codes:
            raise HTTPException(status_code=400, detail="Nenhum código informado.")
        archive_items: list[tuple[bytes, str]] = []
        missing: list[str] = []
        used: set[str] = set()
        for code in payload.codes:
            cert = get_by_code(code.strip())
            if not cert or (cert.get("status") or "ativo") != "ativo":
                missing.append(code)
                continue
            try:
                retrieved = download_certificate(cert)
            except (FileNotFoundError, StorageError):
                missing.append(code)
                continue
            archive_items.append(
                (retrieved.content, build_unique_archive_name(cert["participant_name"], used))
            )
        if not archive_items:
            raise HTTPException(
                status_code=404, detail="Não encontrados/indisponíveis: " + ", ".join(missing)
            )
        archive_buffer = BytesIO()
        with ZipFile(archive_buffer, mode="w", compression=ZIP_DEFLATED) as archive:
            for content_bytes, archive_name in archive_items:
                archive.writestr(archive_name, content_bytes)
            if missing:
                archive.writestr(
                    "_erros-download.txt",
                    "Não encontrados, revogados ou indisponíveis:\n" + "\n".join(missing),
                )
        archive_buffer.seek(0)
        db.insert_audit_log(
            action="download_zip",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="certificate",
            details=f"{len(archive_items)} certificado(s)",
        )
        headers = {"Content-Disposition": 'attachment; filename="certificados.zip"'}
        if missing:
            headers["X-Skipped-Certificates"] = quote(",".join(missing), safe=",")
        return StreamingResponse(
            archive_buffer,
            media_type="application/zip",
            headers=headers,
        )

    @app.post("/download-certificates")
    async def download_certificates(
        payload: DownloadCertificatesRequest,
        current: dict = Depends(auth.require_roles("admin", "secretaria")),
    ) -> StreamingResponse:
        if not payload.certificates:
            raise HTTPException(status_code=400, detail="Nenhum certificado foi informado.")

        archive_items: list[tuple[bytes, str]] = []
        missing_certificates: list[str] = []
        used_archive_names: set[str] = set()

        for certificate in payload.certificates:
            cert = get_by_code(certificate.validation_code.strip())
            if not cert or (cert.get("status") or "ativo") != "ativo":
                missing_certificates.append(certificate.name)
                continue
            try:
                retrieved = download_certificate(cert)
            except (FileNotFoundError, StorageError):
                missing_certificates.append(certificate.name)
                continue
            archive_name = build_unique_archive_name(certificate.name, used_archive_names)
            archive_items.append((retrieved.content, archive_name))

        if missing_certificates:
            raise HTTPException(
                status_code=404,
                detail="Certificados nao encontrados: " + ", ".join(missing_certificates),
            )

        archive_buffer = BytesIO()
        with ZipFile(archive_buffer, mode="w", compression=ZIP_DEFLATED) as archive:
            for content, archive_name in archive_items:
                archive.writestr(archive_name, content)

        archive_buffer.seek(0)
        db.insert_audit_log(
            action="download_zip",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="certificate",
            details=f"{len(archive_items)} certificado(s)",
        )
        return StreamingResponse(
            archive_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="certificados.zip"'},
        )

    return app


def _serialize_report(report: spreadsheet.ValidationReport) -> dict:
    return {
        "total": report.total,
        "valid_count": report.valid_count,
        "invalid_count": report.invalid_count,
        "valid": [
            {
                "row_number": r.row_number,
                "nome": r.nome,
                "curso": r.curso,
                "evento": r.evento,
                "carga_horaria": r.carga_horaria,
                "data_emissao": r.data_emissao,
                "email": r.email,
                "documento": r.documento,
                "data_inicio": r.data_inicio,
                "data_fim": r.data_fim,
            }
            for r in report.valid
        ],
        "invalid": [
            {"row_number": r.row_number, "errors": r.errors, "data": r.data}
            for r in report.invalid
        ],
    }


def _serialize_admin_certificate(cert: dict, full: bool = False) -> dict:
    """Admin view of a certificate row (no Drive links exposed to the public)."""
    base = {
        "unique_code": cert["unique_code"],
        "participant_name": cert["participant_name"],
        "course_name": cert.get("course_name"),
        "event_name": cert.get("event_name"),
        "workload_hours": cert.get("workload_hours"),
        # Stored ISO → presented 'por extenso'.
        "issue_date": extenso_from_iso(cert.get("issue_date")),
        "status": cert.get("status") or "ativo",
        "download_available": bool(
            (cert.get("drive_file_id") or cert.get("pdf_path"))
            and (cert.get("status") or "ativo") == "ativo"
        ),
        "storage_provider": cert.get("storage_provider"),
        "created_at": cert.get("created_at"),
    }
    if full:
        base.update(
            {
                "participant_email": cert.get("participant_email"),
                "participant_document": cert.get("participant_document"),
                "start_date": extenso_from_iso(cert.get("start_date")),
                "end_date": extenso_from_iso(cert.get("end_date")),
                "drive_file_id": cert.get("drive_file_id"),
                "checksum_sha256": cert.get("checksum_sha256"),
                "file_size": cert.get("file_size"),
                "template_used": cert.get("template_used"),
                "certificate_text": cert.get("certificate_text"),
                "revoked_at": cert.get("revoked_at"),
                "revoke_reason": cert.get("revoke_reason"),
                "issued_by": cert.get("issued_by"),
                "updated_at": cert.get("updated_at"),
            }
        )
    return base


def _quarantine_certificate(cert: dict, reason: str) -> None:
    """Block a certificate whose stored file failed integrity + log the incident."""
    import observability

    observability.metrics.increment(observability.INTEGRITY_INCIDENTS)
    code = cert["unique_code"]
    db.block_certificate_integrity(code)
    db.insert_audit_log(
        action="integrity_incident",
        target_type="certificate",
        target_id=code,
        details=reason[:480],
    )
    LOGGER.error("Incidente de integridade em %s: %s", code, reason)


def _stream_certificate(code: str, disposition: str = "inline") -> StreamingResponse:
    """Look up a certificate by code, validate it, and stream its bytes.

    Centralises the error handling required by the spec: not found (404),
    revoked (410), missing file / storage failure (404 / 502). Never leaks a
    provider link or internal id.
    """
    cert = get_by_code(code.strip())
    if not cert:
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    if (cert.get("status") or "ativo") != "ativo":
        raise HTTPException(status_code=410, detail="Certificado revogado.")
    if cert.get("integrity_blocked"):
        raise HTTPException(status_code=409, detail="Certificado bloqueado por falha de integridade.")

    try:
        retrieved: RetrievedFile = download_certificate(cert, verify=True)
    except StorageIntegrityError as exc:
        _quarantine_certificate(cert, str(exc))
        raise HTTPException(
            status_code=409, detail="Falha de integridade: o arquivo foi bloqueado."
        ) from exc
    except FileNotFoundError as exc:
        LOGGER.warning("Arquivo ausente para %s: %s", code, exc)
        raise HTTPException(status_code=404, detail="Arquivo do certificado não encontrado.") from exc
    except StorageError as exc:
        LOGGER.error("Falha de storage ao servir %s: %s", code, exc)
        raise HTTPException(status_code=502, detail="Falha ao obter o arquivo do storage.") from exc

    import observability

    observability.metrics.increment(observability.CERT_DOWNLOADS)
    safe_name = sanitize_filename(cert.get("participant_name") or code)
    return StreamingResponse(
        BytesIO(retrieved.content),
        media_type=retrieved.mime_type,
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}.pdf"'},
    )


def build_unique_archive_name(name: str, used_archive_names: set[str]) -> str:
    base_name = sanitize_filename(name)
    archive_name = f"{base_name}.pdf"
    archive_key = archive_name.lower()
    counter = 2

    while archive_key in used_archive_names:
        archive_name = f"{base_name}_{counter}.pdf"
        archive_key = archive_name.lower()
        counter += 1

    used_archive_names.add(archive_key)
    return archive_name


app = create_app()


def resolve_host() -> str:
    return os.getenv("HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def resolve_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT)).strip()

    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError(f"PORT invalida: {raw_port}") from exc

    if not 1 <= port <= 65535:
        raise ValueError(f"PORT fora do intervalo permitido: {port}")

    return port


def is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def is_certificate_api_running(port: int) -> bool:
    try:
        with urlopen(f"http://{HEALTHCHECK_HOST}:{port}/health", timeout=2) as response:
            return response.status == 200 and response.read().decode("utf-8").strip() == (
                '{"status":"ok"}'
            )
    except URLError:
        return False
    except Exception:  # pragma: no cover
        return False


def run() -> int:
    try:
        host = resolve_host()
        port = resolve_port()
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 1

    if is_port_in_use(HEALTHCHECK_HOST, port):
        if is_certificate_api_running(port):
            LOGGER.info("API ja esta em execucao em http://%s:%s", HEALTHCHECK_HOST, port)
            LOGGER.info("Documentacao disponivel em http://%s:%s/docs", HEALTHCHECK_HOST, port)
            return 0

        LOGGER.error(
            "A porta %s ja esta em uso por outro processo. Defina PORT com outra porta.",
            port,
        )
        return 1

    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
