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

import logging
import os
import socket
from zipfile import ZIP_DEFLATED, ZipFile
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from models import CertificateFormData
from services.certificate_store import find_certificate
from storage_service import RetrievedFile, StorageError, download_certificate

import auth
from database import db
from services.visual_template_store import (
    ensure_dirs as _ensure_visual_dirs,
    get_visual_template,
    resolve_background_path,
)
from routers.visual_templates import router as visual_templates_router
from services.certificate_service import (
    CertificateBatchConfig,
    CertificateBatchService,
    GeneratedCertificateResult,
)
from services import spreadsheet
from services.spreadsheet import SpreadsheetError
from utils.courses import COURSES
from utils.file_utils import ensure_directory, sanitize_filename
from utils.template_store import (
    MAX_TEMPLATE_BYTES,
    ensure_app_dirs,
    load_templates,
    normalize_course_name,
    register_template,
)
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
# Dev fallback origins (used only when FRONTEND_ADMIN_URL/PUBLIC_APP_URL are unset).
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
    """CORS allowlist from env — never '*'.

    Precedence: CORS_ALLOWED_ORIGINS (comma-separated) → ADMIN_FRONTEND_URL +
    PUBLIC_APP_URL → localhost dev origins (with a warning).
    Legacy alias FRONTEND_ADMIN_URL is still accepted.
    """
    raw_list = _env("CORS_ALLOWED_ORIGINS")
    if raw_list:
        origins = [o.strip().rstrip("/") for o in raw_list.split(",") if o.strip()]
        if origins:
            return origins

    origins = []
    admin = _env("ADMIN_FRONTEND_URL", "FRONTEND_ADMIN_URL").rstrip("/")
    public = _env("PUBLIC_APP_URL").rstrip("/")
    if admin:
        origins.append(admin)
    if public:
        origins.append(public)
    if origins:
        return origins

    LOGGER.warning(
        "CORS não configurado (ADMIN_FRONTEND_URL/PUBLIC_APP_URL) — usando "
        "origens de desenvolvimento (localhost). Defina-as em produção."
    )
    return _DEV_ORIGINS


class CertificateResponseItem(BaseModel):
    name: str
    file_url: str
    livro: int
    folha: int
    linha: int
    validation_code: str


class GenerateCertificatesResponse(BaseModel):
    certificates: list[CertificateResponseItem]


class CertificateDownloadItem(BaseModel):
    name: str
    validation_code: str


class DownloadCertificatesRequest(BaseModel):
    certificates: list[CertificateDownloadItem]


class LoginRequest(BaseModel):
    username: str
    password: str


class RevokeRequest(BaseModel):
    reason: str | None = None


class DownloadZipRequest(BaseModel):
    codes: list[str]


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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def create_app() -> FastAPI:
    configure_logging()
    ensure_directory(OUTPUT_DIR)
    ensure_app_dirs()
    _ensure_visual_dirs()
    init_db()  # create the shared tables / run migrations
    auth.seed_admin_from_env()  # create the initial admin user if configured

    app = FastAPI(
        title="Certificate Generation API",
        version="1.0.0",
        description="API local para envio de planilhas e geracao de certificados em PDF.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolve_allowed_origins(),
        allow_credentials=True,  # required for the HttpOnly auth cookie
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # NB: não montamos StaticFiles em "/certificates" — isso colidiria com as
    # rotas /certificates/* da API. Os PDFs são servidos por /certificate-file/{code}.
    # Visual-template CRUD is admin-only.
    app.include_router(
        visual_templates_router, dependencies=[Depends(auth.get_current_admin)]
    )
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

    # ── Autenticação (secretaria) ───────────────────────────────────────────────

    @app.post("/auth/login")
    async def login(payload: LoginRequest) -> JSONResponse:
        user = auth.authenticate(payload.username, payload.password)
        if not user:
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")

        token = auth.create_access_token(user)
        db.insert_audit_log(
            action="login",
            actor_id=user["id"],
            actor_username=user["username"],
            target_type="admin_user",
            target_id=str(user["id"]),
        )
        json_response = JSONResponse(
            content={
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "role": user.get("role"),
                },
                "access_token": token,
                "token_type": "bearer",
            }
        )
        json_response.set_cookie(
            key=auth.COOKIE_NAME,
            value=token,
            httponly=True,
            secure=auth.cookie_secure(),
            samesite="lax",
            max_age=auth.token_ttl_minutes() * 60,
            path="/",
        )
        return json_response

    @app.post("/auth/logout")
    async def logout() -> JSONResponse:
        json_response = JSONResponse(content={"ok": True})
        json_response.delete_cookie(key=auth.COOKIE_NAME, path="/")
        return json_response

    @app.get("/auth/me")
    async def whoami(current=Depends(auth.get_current_admin)) -> dict:
        return {
            "id": current["id"],
            "username": current["username"],
            "role": current.get("role"),
        }

    @app.get("/visual-template-backgrounds/{filename}")
    async def serve_visual_background(filename: str) -> FileResponse:
        if "/" in filename or ".." in filename:
            raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")
        path = resolve_background_path(f"/visual-template-backgrounds/{filename}")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Imagem não encontrada.")
        return FileResponse(str(path))

    @app.get("/validate/{code}")
    async def validate_certificate(code: str) -> dict:
        # Codes are stored as CERT-ANO-XXXXXX; matching is case-insensitive in the DB.
        cert = find_certificate(code.strip())
        if not cert:
            return {"valid": False}

        issued_at = cert.get("issued_at") or cert.get("date")
        certificate_text = cert.get("certificate_text") or cert.get("texto_certificado")

        return {
            "valid": True,
            "name": cert["name"],
            "event": cert["event"],
            "issued_at": issued_at,
            "date": issued_at,
            "certificate_text": certificate_text,
        }

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
            "issue_date": cert["issue_date"],
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
        """Return the canonical list of valid courses."""
        return COURSES

    @app.get("/templates")
    async def list_templates() -> dict[str, str]:
        """Return the current course → relative-path mapping."""
        return load_templates()

    @app.post("/upload-template")
    async def upload_template(
        course_name: str = Form(...),
        file: UploadFile = File(...),
        current: dict = Depends(auth.get_current_admin),
    ) -> dict[str, str]:
        """
        Upload a PNG template for a specific course.

        - Accepts only PNG files up to 5 MB.
        - Replaces (and deletes) any existing template for the same course.
        - Course names are normalised, so "Engenharia Civil" and
          "engenharia civil" resolve to the same slot.
        """
        course_name = course_name.strip()
        if not course_name:
            raise HTTPException(status_code=400, detail="O campo course_name nao pode ser vazio.")

        if course_name not in COURSES:
            raise HTTPException(
                status_code=400,
                detail=f"Curso invalido. Valores aceitos: {', '.join(COURSES)}",
            )

        filename = (file.filename or "").strip().lower()
        if not (filename.endswith(".png") or filename.endswith(".jpg") or filename.endswith(".jpeg")):
            raise HTTPException(
                status_code=400,
                detail="Apenas arquivos PNG ou JPG sao aceitos como template.",
            )

        content = await file.read()
        await file.close()

        if not content:
            raise HTTPException(status_code=400, detail="O arquivo enviado esta vazio.")

        if len(content) > MAX_TEMPLATE_BYTES:
            raise HTTPException(
                status_code=400,
                detail="O arquivo excede o tamanho maximo permitido de 5 MB.",
            )

        # Validate file magic bytes to prevent renamed files
        # PNG: \x89PNG\r\n\x1a\n  |  JPG: \xff\xd8\xff
        PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
        JPG_MAGIC = b"\xff\xd8\xff"
        if content[:8] != PNG_MAGIC and content[:3] != JPG_MAGIC:
            raise HTTPException(
                status_code=400,
                detail="O conteudo do arquivo nao e um PNG ou JPG valido.",
            )

        ext = ".jpg" if filename.endswith((".jpg", ".jpeg")) else ".png"
        try:
            register_template(course_name, content, ext)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            LOGGER.exception("Falha ao salvar template: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Nao foi possivel salvar o template no servidor.",
            ) from exc

        key = normalize_course_name(course_name)
        db.insert_audit_log(
            action="upload_template",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="template",
            target_id=key,
            details=course_name,
        )
        return {"message": f"Template para '{course_name}' salvo com sucesso.", "key": key}

    @app.post(
        "/generate-certificates",
        response_model=GenerateCertificatesResponse,
    )
    async def generate_certificates(
        file: UploadFile = File(...),
        texto_certificado: str | None = Form(None),
        data_emissao: str | None = Form(None),
        template_id: str | None = Form(None),
        current: dict = Depends(auth.get_current_admin),
    ) -> GenerateCertificatesResponse:
        validate_uploaded_file(file)
        validated_form_data = validate_form_fields(
            texto_certificado=texto_certificado,
            data_emissao=data_emissao,
            require_texto=not bool(template_id),
        )
        content = await file.read()

        if not content:
            raise HTTPException(status_code=400, detail="O arquivo enviado esta vazio.")

        visual_layout: dict | None = None
        if template_id:
            tmpl = get_visual_template(template_id)
            if not tmpl:
                raise HTTPException(
                    status_code=404,
                    detail=f"Template visual '{template_id}' não encontrado.",
                )
            visual_layout = tmpl["layout"]

        try:
            certificates = app.state.certificate_service.generate_from_excel(
                BytesIO(content),
                validated_form_data,
                visual_template_layout=visual_layout,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            LOGGER.exception("Configuracao do backend incompleta: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Backend sem template ou fontes configuradas corretamente.",
            ) from exc
        except StorageError as exc:
            LOGGER.error("Falha de armazenamento ao gerar certificados: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="Falha ao salvar o certificado no armazenamento configurado.",
            ) from exc
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("Falha inesperada ao gerar certificados: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Falha inesperada ao gerar certificados.",
            ) from exc
        finally:
            await file.close()

        db.insert_audit_log(
            action="generate",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="certificate",
            target_id=",".join(c.validation_code for c in certificates),
            details=f"{len(certificates)} certificado(s)",
        )
        return GenerateCertificatesResponse(
            certificates=[to_response_item(item) for item in certificates]
        )

    # ── Modelo estruturado: pré-validação + geração confirmada ──────────────────

    @app.post("/certificates/validate-spreadsheet")
    async def validate_spreadsheet(
        file: UploadFile = File(...),
        data_emissao: str | None = Form(None),
        _: dict = Depends(auth.get_current_admin),
    ) -> dict:
        """Validate a spreadsheet and return a preview (nothing is persisted)."""
        content = await read_spreadsheet_upload(file)
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
        return _serialize_report(report)

    @app.post("/certificates/generate")
    async def generate_structured(
        file: UploadFile = File(...),
        data_emissao: str | None = Form(None),
        template_id: str | None = Form(None),
        current: dict = Depends(auth.get_current_admin),
    ) -> dict:
        """Validate (again) and generate only the valid, non-duplicate rows."""
        content = await read_spreadsheet_upload(file)
        try:
            report = spreadsheet.read_and_validate(
                BytesIO(content),
                default_data_emissao=data_emissao,
                max_rows=max_spreadsheet_rows(),
            )
        except SpreadsheetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        visual_layout: dict | None = None
        if template_id:
            tmpl = get_visual_template(template_id)
            if not tmpl:
                raise HTTPException(
                    status_code=404, detail=f"Template visual '{template_id}' não encontrado."
                )
            visual_layout = tmpl["layout"]

        try:
            summary = app.state.certificate_service.generate_certificates(
                report.valid,
                issued_by=current["id"],
                visual_template_layout=visual_layout,
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
        current: dict = Depends(auth.get_current_admin),
    ) -> dict:
        cert = get_by_code(code.strip())
        if not cert:
            raise HTTPException(status_code=404, detail="Certificado não encontrado.")
        if (cert.get("status") or "ativo") == "revogado":
            raise HTTPException(status_code=409, detail="Certificado já está revogado.")
        db.update_certificate_status(
            code.strip(),
            status="revogado",
            revoked_by=current["id"],
            revoke_reason=(payload.reason or "").strip() or None,
        )
        db.insert_audit_log(
            action="revoke",
            actor_id=current["id"],
            actor_username=current["username"],
            target_type="certificate",
            target_id=cert["unique_code"],
            details=(payload.reason or "").strip() or None,
        )
        return _serialize_admin_certificate(get_by_code(code.strip()), full=True)

    @app.post("/certificates/{code}/reissue")
    async def reissue_certificate(
        code: str, current: dict = Depends(auth.get_current_admin)
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
        current: dict = Depends(auth.get_current_admin),
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
        if missing:
            raise HTTPException(
                status_code=404, detail="Não encontrados/indisponíveis: " + ", ".join(missing)
            )
        archive_buffer = BytesIO()
        with ZipFile(archive_buffer, mode="w", compression=ZIP_DEFLATED) as archive:
            for content_bytes, archive_name in archive_items:
                archive.writestr(archive_name, content_bytes)
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

    @app.post("/download-certificates")
    async def download_certificates(
        payload: DownloadCertificatesRequest,
        current: dict = Depends(auth.get_current_admin),
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
        "issue_date": cert.get("issue_date"),
        "status": cert.get("status") or "ativo",
        "storage_provider": cert.get("storage_provider"),
        "created_at": cert.get("created_at"),
    }
    if full:
        base.update(
            {
                "participant_email": cert.get("participant_email"),
                "participant_document": cert.get("participant_document"),
                "start_date": cert.get("start_date"),
                "end_date": cert.get("end_date"),
                "drive_file_id": cert.get("drive_file_id"),
                "checksum_sha256": cert.get("checksum_sha256"),
                "file_size": cert.get("file_size"),
                "certificate_text": cert.get("certificate_text"),
                "revoked_at": cert.get("revoked_at"),
                "revoke_reason": cert.get("revoke_reason"),
                "issued_by": cert.get("issued_by"),
                "updated_at": cert.get("updated_at"),
            }
        )
    return base


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

    try:
        retrieved: RetrievedFile = download_certificate(cert)
    except FileNotFoundError as exc:
        LOGGER.warning("Arquivo ausente para %s: %s", code, exc)
        raise HTTPException(status_code=404, detail="Arquivo do certificado não encontrado.") from exc
    except StorageError as exc:
        LOGGER.error("Falha de storage ao servir %s: %s", code, exc)
        raise HTTPException(status_code=502, detail="Falha ao obter o arquivo do storage.") from exc

    safe_name = sanitize_filename(cert.get("participant_name") or code)
    return StreamingResponse(
        BytesIO(retrieved.content),
        media_type=retrieved.mime_type,
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}.pdf"'},
    )


def validate_uploaded_file(file: UploadFile) -> None:
    filename = (file.filename or "").strip()

    if not filename:
        raise HTTPException(status_code=400, detail="Nenhum arquivo foi enviado.")

    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Envie um arquivo Excel valido com extensao .xlsx.",
        )


def validate_form_fields(
    texto_certificado: str | None,
    data_emissao: str | None,
    require_texto: bool = True,
) -> CertificateFormData:
    texto = (texto_certificado or "").strip()
    emissao = (data_emissao or "").strip()

    missing: list[str] = []
    if require_texto and not texto:
        missing.append("texto_certificado")
    if not emissao:
        missing.append("data_emissao")

    if missing:
        raise HTTPException(
            status_code=400,
            detail="Campos obrigatorios ausentes no formulario: " + ", ".join(missing),
        )

    return CertificateFormData(
        texto_certificado=texto,
        data_emissao=emissao,
    )


def to_response_item(item: GeneratedCertificateResult) -> CertificateResponseItem:
    return CertificateResponseItem(
        name=item.name,
        file_url=item.file_url,
        livro=item.livro,
        folha=item.folha,
        linha=item.linha,
        validation_code=item.validation_code,
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
