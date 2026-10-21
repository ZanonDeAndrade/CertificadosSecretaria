from __future__ import annotations

import logging
import os
import socket
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import uvicorn
from certificados_backend import auth
from certificados_backend.policies import Permission, require_permission
from certificados_backend.schemas.templates import (
    TemplateSampleDataResponse,
    TextLayoutRequest,
    TextLayoutResponse,
)
from certificados_backend.services import (
    audit_service,
    batch_service,
    template_fields,
    template_service,
)
from certificados_backend.services.generator import measuring_draw
from certificados_backend.services.runtime import (
    build_certificate_service,
    build_layout_generator,
)
from certificados_backend.services.template_service import TemplateConflictError, TemplateError
from certificados_backend.utils.courses import COURSES
from certificados_backend.utils.file_utils import ensure_directory
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from database import db
from database.db import PDFS_DIR, init_db

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
            raise RuntimeError("Em produção, configure ADMIN_FRONTEND_URL ou CORS_ALLOWED_ORIGINS.")
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


class CreateTemplateVersionRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    # {background: <data URL or serving URL>, image_width, image_height, elements}
    layout: dict
    # Dedicates the version to one certificate type; omitted = generic.
    certificate_type: str | None = Field(default=None, max_length=32)


class RenameTemplateVersionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


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
    db_config.validate_forwarded_allow_ips()
    auth.require_production_auth_config()
    resolve_allowed_origins()
    if db_config.is_local_server():
        storage_config.validate_local_server_storage()
    else:
        storage_config.validate_production_storage(required_access="read_write")
    validate_production_privacy_config()
    batch_service.validate_runtime_configuration()
    if not db_config.is_local_server():
        from certificados_backend.services import drive_integration

        drive_integration.validate_configuration()


def create_app() -> FastAPI:
    configure_logging()
    validate_startup_config()
    from storage_service import config as storage_config

    if not storage_config.is_production():
        # Local PDF directory only matters for the development storage backend.
        ensure_directory(OUTPUT_DIR)
    init_db()  # create the shared tables (dev) / verify connectivity (prod)
    from certificados_backend.services import settings_service

    institutional_settings = settings_service.ensure_settings()
    settings_service.validate_runtime_settings(institutional_settings)
    auth.seed_admin_from_env()  # create the initial admin user if configured
    auth.cleanup_auth_state()
    # Seed + activate a default global template version if none exists yet.
    template_service.ensure_default_version(TEMPLATE_PATH)

    production = auth.is_hardened_environment()
    app = FastAPI(
        title="Certificados Faculdade AMF API",
        version="2.1.0",
        description=(
            "API administrativa para usuários, RBAC, auditoria, configurações, "
            "emissão idempotente e ciclo de vida de certificados."
        ),
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )

    import observability

    app.add_middleware(observability.CorrelationIdMiddleware)

    allowed_origins = resolve_allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,  # required for the HttpOnly auth cookie
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Idempotency-Key",
            "X-Request-ID",
        ],
        expose_headers=[
            "Content-Disposition",
            "X-Skipped-Certificates",
            "X-Request-ID",
            "Retry-After",
        ],
    )

    @app.middleware("http")
    async def enforce_cookie_origin(request: Request, call_next):
        try:
            auth.validate_mutating_request_origin(request, allowed_origins)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    @app.middleware("http")
    async def add_api_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), geolocation=(), microphone=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        if request.url.path.startswith(("/auth", "/certificates", "/admin", "/integrations")):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
        if auth.is_production():
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    # NB: não montamos StaticFiles em "/certificates" — isso colidiria com as
    # rotas /certificates/* da API. Os PDFs são servidos por /certificate-file/{code}.
    app.state.certificate_service = build_certificate_service()

    # Functional areas are routers; main.py remains the composition root.
    from certificados_backend.routers import audit as audit_routes
    from certificados_backend.routers import auth as auth_routes
    from certificados_backend.routers import batches as batch_routes
    from certificados_backend.routers import certificates as certificate_routes
    from certificados_backend.routers import drive as drive_routes
    from certificados_backend.routers import settings as settings_routes
    from certificados_backend.routers import users as user_routes

    app.include_router(auth_routes.router)
    app.include_router(user_routes.router)
    app.include_router(user_routes.legacy_router)
    app.include_router(audit_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(batch_routes.router)
    app.include_router(certificate_routes.router)
    app.include_router(drive_routes.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness() -> dict[str, str]:
        try:
            db.check_connection()
        except Exception as exc:  # noqa: BLE001 - never expose database details
            LOGGER.error("Readiness do banco falhou: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Banco indisponível.") from exc
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics_endpoint(
        _: dict = Depends(require_permission(Permission.SETTINGS_READ)),
    ) -> dict:
        """In-process counters (no PII): generation, failures, compensations,
        downloads and integrity incidents."""
        return observability.metrics.snapshot()

    # ── Template global (versionado) ────────────────────────────────────────────

    @app.get("/templates/active")
    def template_active(
        certificate_type: str | None = None,
        _: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
    ) -> dict:
        """Active version for a type (its own, else the generic one)."""
        version = template_service.get_active_version(certificate_type or None)
        if not version:
            raise HTTPException(status_code=404, detail="Nenhum template ativo.")
        return version

    @app.get("/templates/versions")
    def template_versions(
        _: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
    ) -> list[dict]:
        return template_service.list_versions()

    @app.get("/templates/versions/{version_id}")
    def template_version_detail(
        version_id: int,
        _: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
    ) -> dict:
        version = template_service.get_version(version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Versão não encontrada.")
        return version

    @app.get("/templates/versions/{version_id}/background")
    def template_version_background(version_id: int) -> StreamingResponse:
        # Public: a template background image is not sensitive data, and the
        # editor loads it cross-origin where a SameSite=Lax cookie isn't sent.
        try:
            content, mime = template_service.get_background_bytes(version_id)
        except TemplateError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(BytesIO(content), media_type=mime)

    @app.get("/templates/sample-data", response_model=TemplateSampleDataResponse)
    def template_sample_data(
        current: dict = Depends(require_permission(Permission.TEMPLATES_READ)),
    ) -> dict:
        """Sample values for the editor, resolved exactly as the PDF resolves them.

        Institutional values come from the current settings, so the preview
        never shows a city or a signatory the certificate will not have.
        """
        return template_fields.sample_data(actor=current)

    @app.post("/templates/text-layout", response_model=TextLayoutResponse)
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

    @app.post("/templates/versions")
    def create_template_version(
        payload: CreateTemplateVersionRequest,
        current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
    ) -> dict:
        try:
            version = template_service.create_version(
                name=payload.name,
                layout=payload.layout,
                created_by=current["id"],
                certificate_type=payload.certificate_type,
            )
        except TemplateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_service.record(
            "template_version_created",
            actor=current,
            target_type="template_version",
            target_id=version["id"],
            details={
                "version_id": version["id"],
                "version_number": version["version_number"],
            },
        )
        return version

    @app.post("/templates/versions/{version_id}/activate")
    def activate_template_version(
        version_id: int,
        current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
    ) -> dict:
        if not template_service.activate_version(version_id, current["id"]):
            raise HTTPException(status_code=404, detail="Versão não encontrada.")
        audit_service.record(
            "template_version_activated",
            actor=current,
            target_type="template_version",
            target_id=version_id,
            details={"version_id": version_id},
        )
        return template_service.get_version(version_id)

    @app.patch("/templates/versions/{version_id}")
    def rename_template_version(
        version_id: int,
        payload: RenameTemplateVersionRequest,
        current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
    ) -> dict:
        try:
            version = template_service.rename_version(version_id, payload.name)
        except TemplateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if version is None:
            raise HTTPException(status_code=404, detail="Versão não encontrada.")
        audit_service.record(
            "template_version_renamed",
            actor=current,
            target_type="template_version",
            target_id=version_id,
            details={
                "version_id": version_id,
                "version_number": version["version_number"],
                "fields": ["name"],
            },
        )
        return version

    @app.delete("/templates/versions/{version_id}")
    def delete_template_version(
        version_id: int,
        current: dict = Depends(require_permission(Permission.TEMPLATES_MANAGE)),
    ) -> dict:
        try:
            version = template_service.delete_version(version_id)
        except TemplateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if version is None:
            raise HTTPException(status_code=404, detail="Versão não encontrada.")
        audit_service.record(
            "template_version_deleted",
            actor=current,
            target_type="template_version",
            target_id=version_id,
            details={
                "version_id": version_id,
                "version_number": version["version_number"],
            },
        )
        return {"deleted": True, "version_id": version_id}

    @app.get("/courses")
    def list_courses(
        _: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
    ) -> list[str]:
        """Return the canonical list of valid courses (participant field)."""
        return COURSES

    # ── Modelo estruturado: pré-validação + geração confirmada ──────────────────

    @app.post(
        "/certificates/generate",
        deprecated=True,
        summary="Endpoint legado removido; use lotes duráveis",
    )
    async def removed_synchronous_generation(
        _: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
    ) -> None:
        """Fail explicitly instead of starting an untracked long request."""
        raise HTTPException(
            status_code=410,
            detail="Fluxo removido. Inicie a emissão em POST /emission-batches.",
        )

    # ── Painel, usuários e auditoria ────────────────────────────────────────────
    #
    # Read-only aggregations over data the system already records. Business
    # lifecycle, user management and audit queries live in dedicated modules.

    @app.get("/admin/stats")
    def admin_stats(
        recent_days: int = 30,
        _: dict = Depends(require_permission(Permission.DASHBOARD_READ)),
    ) -> dict:
        days = max(1, min(int(recent_days), 365))
        return db.certificate_dashboard_stats(recent_days=days)

    @app.get("/admin/recent-certificates")
    def admin_recent_certificates(
        limit: int = 8,
        current: dict = Depends(require_permission(Permission.DASHBOARD_READ)),
    ) -> list[dict]:
        from certificados_backend.services import certificate_management

        rows = db.recent_certificates(limit=max(1, min(int(limit), 50)))
        return [
            certificate_management.serialize(row, actor=current, resolve_responsible=False)
            for row in rows
        ]

    return app


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
        LOGGER.error("event=invalid_runtime_address error_type=%s", type(exc).__name__)
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

    # Access logs include the raw request target. Keep application/correlation
    # logs, but never persist legacy query strings that may contain PII.
    uvicorn.run(app, host=host, port=port, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
