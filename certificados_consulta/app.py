"""Site público para alunos consultarem e baixarem
os seus certificados.

Sem login, sem autenticação. Três formas de busca:
  - por nome (parcial, case-insensitive)
  - por e-mail exato, comparado somente por HMAC (titular ou qualquer autor)
  - por código único (ex: CERT-2026-AB1234)

O download após uma busca exige confirmar o e-mail cadastrado na emissão; o
Registro Acadêmico (RA) só confirma certificados emitidos antes de o e-mail
ser registrado. Nem o e-mail nem o RA aparecem em página, resposta ou log.

Lê o mesmo PostgreSQL configurado para o painel administrativo e entrega os
PDFs pelo backend a partir do storage privado configurado.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Mapping, TypeGuard

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

import observability
from database import db
from database.certificate_types import certificate_type_label, is_per_work_type
from database.privacy import (
    MAX_EMAIL_LENGTH,
    active_document_key_id,
    document_hash,
    email_hash,
    email_hash_candidates,
    is_valid_email,
    matching_document_key_id,
    matching_email_key_id,
    normalize_document,
    normalize_name,
    pseudonymous_rate_limit_key,
    public_result_reference,
    validate_production_privacy_config,
)
from database.repositories import authors_from_json
from storage_service import (
    StorageError,
    StorageIntegrityError,
    download_certificate,
)
from storage_service.filenames import certificate_filename, content_disposition

LOGGER = logging.getLogger("certificados.consulta")

PUBLIC_PAGE_SIZE = 10
PUBLIC_CERTIFICATE_STATUSES = {"ativo", "revogado"}


def _int_setting(name: str, default: int, minimum: int = 1, maximum: int = 100_000) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


PUBLIC_NAME_MIN_LENGTH = _int_setting("PUBLIC_NAME_SEARCH_MIN_LENGTH", 3, 2, 20)
PUBLIC_MAX_PAGE = _int_setting("PUBLIC_MAX_PAGE", 100, 1, 10_000)
PUBLIC_RATE_LIMIT_REQUESTS = _int_setting("PUBLIC_RATE_LIMIT_REQUESTS", 60)
PUBLIC_RATE_LIMIT_WINDOW_SECONDS = _int_setting("PUBLIC_RATE_LIMIT_WINDOW_SECONDS", 60)
PUBLIC_NAME_RATE_LIMIT_REQUESTS = _int_setting("PUBLIC_NAME_RATE_LIMIT_REQUESTS", 30)
PUBLIC_CONFIRM_RATE_LIMIT_REQUESTS = _int_setting("PUBLIC_CONFIRM_RATE_LIMIT_REQUESTS", 8)
PUBLIC_CONFIRM_RATE_LIMIT_WINDOW_SECONDS = _int_setting(
    "PUBLIC_CONFIRM_RATE_LIMIT_WINDOW_SECONDS", 900
)
PUBLIC_NAME_MAX_LENGTH = 160
PUBLIC_DOCUMENT_MAX_LENGTH = 96
PUBLIC_RESULT_REFERENCE_LENGTH = 64


def _valid_name_term(value: str) -> bool:
    return (
        len(value) <= PUBLIC_NAME_MAX_LENGTH
        and sum(ch.isalnum() for ch in normalize_name(value)) >= PUBLIC_NAME_MIN_LENGTH
    )


def _valid_academic_record(value: str) -> bool:
    normalized = normalize_document(value)
    return len(value) <= PUBLIC_DOCUMENT_MAX_LENGTH and len(normalized) >= 3


def _valid_email(value: str) -> bool:
    return len(value) <= MAX_EMAIL_LENGTH and is_valid_email(value)


class PublicNameSearchRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=PUBLIC_NAME_MAX_LENGTH)
    page: int = Field(default=1, ge=1, le=PUBLIC_MAX_PAGE)

    @field_validator("nome")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class PublicEmailSearchRequest(BaseModel):
    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)

    @field_validator("email")
    @classmethod
    def strip_email(cls, value: str) -> str:
        value = value.strip()
        if not _valid_email(value):
            raise ValueError("E-mail inválido.")
        return value


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
}


_MONTHS_PT = (
    "",
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def _format_issue_date(value: object) -> str:
    """Present a stored ISO (YYYY-MM-DD) date 'por extenso'.

    Dates are stored ISO for correct chronological ordering; the public area
    only formats them for display. Unparseable values pass through unchanged.
    """
    if not value:
        return ""
    text = str(value).strip()
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            d = datetime.strptime(text, fmt).date()
            return f"{d.day} de {_MONTHS_PT[d.month]} de {d.year}"
        except ValueError:
            continue
    return text


def _public_view(cert: dict) -> dict:
    """Sanitised public projection — no email, document, internal id, or Drive id."""
    return {
        "unique_code": cert["unique_code"],
        "participant_name": cert["participant_name"],
        "course_name": cert.get("course_name"),
        "event_name": cert.get("event_name"),
        "certificate_type": cert.get("certificate_type"),
        "certificate_type_label": certificate_type_label(cert.get("certificate_type")),
        "workload_hours": cert.get("workload_hours"),
        "issue_date": _format_issue_date(cert.get("issue_date")),
        "status": cert.get("status") or "ativo",
        # A per-work certificate belongs to every author, as printed on it.
        "per_work": is_per_work_type(cert.get("certificate_type")),
        "authors": authors_from_json(cert.get("authors_json")),
        "work_title": cert.get("work_title"),
        "team_name": cert.get("team_name"),
    }


def _public_name_view(cert: dict) -> dict:
    """Minimal name-search projection with a non-authorizing result selector."""
    per_work = is_per_work_type(cert.get("certificate_type"))
    return {
        "participant_name": _mask_name(cert["participant_name"]),
        "course_name": cert.get("course_name"),
        "event_name": cert.get("event_name"),
        "certificate_type": cert.get("certificate_type"),
        "certificate_type_label": certificate_type_label(cert.get("certificate_type")),
        "workload_hours": cert.get("workload_hours"),
        "issue_date": _format_issue_date(cert.get("issue_date")),
        "status": cert.get("status") or "ativo",
        "result_ref": public_result_reference(cert["unique_code"]),
        "per_work": per_work,
        "authors": [_mask_name(name) for name in authors_from_json(cert.get("authors_json"))],
        # A per-work result is named by its work; the authors stay masked.
        "work_title": cert.get("work_title") if per_work else None,
    }


def _mask_name(value: str) -> str:
    words = [word for word in value.split() if word]
    return " ".join(f"{word[0]}•••" for word in words)


def _is_public_certificate(cert: dict | None) -> TypeGuard[dict]:
    """Hide pending/failed/internal lifecycle states from anonymous users."""
    return bool(cert and (cert.get("status") or "ativo") in PUBLIC_CERTIFICATE_STATUSES)


def _trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    networks = []
    for raw in os.getenv("TRUSTED_PROXY_CIDRS", "").split(","):
        if raw.strip():
            network = ipaddress.ip_network(raw.strip(), strict=False)
            if network.prefixlen == 0:
                raise ValueError("TRUSTED_PROXY_CIDRS não aceita uma rede irrestrita.")
            networks.append(network)
    return tuple(networks)


def resolve_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "0.0.0.0"
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    trusted = _trusted_proxy_networks()
    if not any(peer_ip in network for network in trusted):
        return str(peer_ip)
    forwarded = request.headers.get("x-forwarded-for", "")
    try:
        chain = [
            ipaddress.ip_address(item.strip()) for item in forwarded.split(",") if item.strip()
        ]
    except ValueError:
        return str(peer_ip)
    for candidate in reversed(chain):
        if not any(candidate in network for network in trusted):
            return str(candidate)
    return str(chain[0]) if chain else str(peer_ip)


def _bucket_key(scope: str, value: str) -> str:
    return pseudonymous_rate_limit_key(scope, value)


def _consume_rate_limit(bucket_key: str, *, limit: int, window_seconds: int) -> None:
    allowed, retry_after = db.consume_public_rate_limit(
        bucket_key,
        now=datetime.now(timezone.utc),
        window_seconds=window_seconds,
        limit=limit,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Muitas requisições. Tente novamente em instantes.",
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(request: Request) -> None:
    _consume_rate_limit(
        _bucket_key("ip", resolve_client_ip(request)),
        window_seconds=PUBLIC_RATE_LIMIT_WINDOW_SECONDS,
        limit=PUBLIC_RATE_LIMIT_REQUESTS,
    )


def rate_limit_identity(scope: str, value: str, *, confirmation: bool = False) -> None:
    _consume_rate_limit(
        _bucket_key(scope, value),
        limit=(
            PUBLIC_CONFIRM_RATE_LIMIT_REQUESTS if confirmation else PUBLIC_NAME_RATE_LIMIT_REQUESTS
        ),
        window_seconds=(
            PUBLIC_CONFIRM_RATE_LIMIT_WINDOW_SECONDS
            if confirmation
            else PUBLIC_RATE_LIMIT_WINDOW_SECONDS
        ),
    )


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8001  # admin roda na 8000; consulta na 8001 para subirem juntos
APP_NAME = "Certificados Faculdade AMF"


def _public_site_base_path() -> str:
    """External prefix used when the public site shares port 80 with the SPA."""
    raw = (os.getenv("PUBLIC_SITE_BASE_PATH") or "").strip()
    if raw:
        value = raw.rstrip("/")
    elif (os.getenv("APP_ENV") or "").strip().lower() in {"local_server", "local-server", "lan"}:
        value = "/consulta"
    else:
        value = ""
    if value and (not value.startswith("/") or ".." in value or "//" in value):
        raise RuntimeError("PUBLIC_SITE_BASE_PATH inválido.")
    return value


PUBLIC_SITE_BASE_PATH = _public_site_base_path()

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["app_name"] = APP_NAME
templates.env.globals["public_base_path"] = PUBLIC_SITE_BASE_PATH

observability.configure_logging()

_PRODUCTION = (os.getenv("APP_ENV") or "").strip().lower() in {
    "prod",
    "production",
    "local_server",
    "local-server",
    "lan",
}
app = FastAPI(
    title=f"{APP_NAME} — Consulta",
    version="1.0.0",
    description="Site público para alunos consultarem e baixarem seus certificados.",
    docs_url=None if _PRODUCTION else "/docs",
    redoc_url=None if _PRODUCTION else "/redoc",
    openapi_url=None if _PRODUCTION else "/openapi.json",
)
app.add_middleware(observability.CorrelationIdMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if (
        request.method == "POST"
        or request.url.path.startswith(
            ("/validar/", "/public/search", "/public/verify/", "/public/certificates")
        )
        or any(key in request.query_params for key in ("nome", "codigo"))
    ):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    from storage_service import config as storage_config

    if storage_config.is_production():
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


def validate_startup_config() -> None:
    """Fail-closed checks for production (no-op in development/test).

    The public app shares the SAME PostgreSQL and the SAME private Drive files
    as the admin, but it never receives admin Drive credentials nor exposes a
    public file URL: downloads are always proxied by this backend using
    ``drive_file_id``. In production it refuses to start without DATABASE_URL and
    a fully configured (read) Google Drive backend.
    """
    from database import config as db_config
    from storage_service import config as storage_config

    db_config.require_production_database()
    db_config.validate_forwarded_allow_ips()
    if db_config.is_local_server():
        storage_config.validate_local_server_storage()
    else:
        storage_config.validate_production_storage(required_access="read_only")
        storage_config.validate_production_public_validation_url()
    validate_production_privacy_config()
    try:
        _trusted_proxy_networks()
    except ValueError as exc:
        raise db_config.ConfigError(f"TRUSTED_PROXY_CIDRS inválido: {exc}") from exc


validate_startup_config()

# Garante que a tabela exista em dev (no-op em produção: schema é do Alembic).
db.init_db()
db.cleanup_public_rate_limits(
    datetime.now(timezone.utc)
    - timedelta(seconds=max(PUBLIC_RATE_LIMIT_WINDOW_SECONDS * 2, 86_400))
)


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


def _index_context() -> dict:
    return {
        "results": None,
        "search_type": None,
        "query": "",
        "error": None,
        "total": 0,
        "page": 1,
        "total_pages": 0,
    }


def _institution_context() -> dict:
    settings = db.get_institutional_settings() or {}
    return {
        "institution_name": settings.get("institution_name")
        or os.getenv("INSTITUTION_NAME")
        or "Instituição de ensino",
    }


def _render_index(
    request: Request,
    context: dict,
    *,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_institution_context(), **context},
        status_code=status_code,
        headers=headers,
    )


def _name_search(term: str, page: int) -> dict:
    if not _valid_name_term(term):
        raise HTTPException(400, f"Informe ao menos {PUBLIC_NAME_MIN_LENGTH} caracteres válidos.")
    rate_limit_identity("search-name", term)
    page = max(1, min(int(page), PUBLIC_MAX_PAGE))
    offset = (page - 1) * PUBLIC_PAGE_SIZE
    items, total = db.list_certificates(
        name=term,
        statuses=("ativo", "revogado"),
        limit=PUBLIC_PAGE_SIZE,
        offset=offset,
        order_by="issue_date",
    )
    return {
        "items": [_public_name_view(c) for c in items],
        "total": total,
        "page": page,
        "page_size": PUBLIC_PAGE_SIZE,
    }


def _email_search(email: str) -> dict:
    if not _valid_email(email):
        raise HTTPException(400, "Informe um e-mail válido.")
    # The e-mail is both a lookup identifier and a download confirmation
    # factor: the stricter confirmation throttle applies, keyed by a pseudonym.
    rate_limit_identity("search-email", email, confirmation=True)
    items = db.list_certificates_by_email_hashes(
        email_hash_candidates(email),
        statuses=("ativo", "revogado"),
    )
    return {
        "items": [_public_name_view(c) for c in items],
        "total": len(items),
        "page": 1,
        "page_size": len(items),
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, codigo: str | None = None) -> HTMLResponse:
    """Render the landing page; sensitive name searches are POST-only."""
    try:
        rate_limit(request)
    except HTTPException as exc:
        context = _index_context()
        context["error"] = exc.detail
        return _render_index(
            request,
            context,
            status_code=exc.status_code,
            headers=exc.headers,
        )
    context = _index_context()
    if codigo is not None:
        query = codigo.strip()[:128]
        context["search_type"] = "codigo"
        context["query"] = query
        if query:
            cert = db.get_by_code(query)
            results = [_public_view(cert)] if _is_public_certificate(cert) else []
            context["results"] = results
            context["total"] = len(results)
        else:
            context["error"] = "Digite um código para buscar."
    return _render_index(request, context)


@app.post("/", response_class=HTMLResponse)
async def search_page(request: Request) -> HTMLResponse:
    """HTML name/e-mail search. Sensitive terms remain POST-only and no-store."""

    search_type = "nome"
    try:
        rate_limit(request)
        form = await request.form()
        term = str(form.get("nome") or "").strip()
        email = str(form.get("email") or "").strip()
        if bool(term) == bool(email):
            raise HTTPException(400, "Informe o nome ou o e-mail.")
        if email:
            # The e-mail is never echoed back, not even as the query shown.
            search_type = "email"
            result = _email_search(email)
            term = ""
        else:
            search_type = "nome"
            raw_page = str(form.get("page") or "1")
            if len(term) > PUBLIC_NAME_MAX_LENGTH or len(raw_page) > 6:
                raise HTTPException(400, "Consulta inválida.")
            try:
                page = int(raw_page)
            except ValueError as exc:
                raise HTTPException(400, "Consulta inválida.") from exc
            result = _name_search(term, page)
    except HTTPException as exc:
        context = _index_context()
        context["search_type"] = search_type
        context["error"] = exc.detail
        return _render_index(
            request,
            context,
            status_code=exc.status_code,
            headers=exc.headers,
        )

    total_pages = (
        (result["total"] + PUBLIC_PAGE_SIZE - 1) // PUBLIC_PAGE_SIZE if result["total"] else 0
    )
    return _render_index(
        request,
        {
            "results": result["items"],
            "search_type": search_type,
            "query": term,
            "error": None,
            "total": result["total"],
            "page": result["page"],
            "total_pages": total_pages,
        },
    )


def _validation_response(
    request: Request,
    *,
    state: str,
    status_code: int,
    certificate: dict | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="validar.html",
        context={
            **_institution_context(),
            "state": state,
            "certificate": certificate,
            "download_url": (
                f"{PUBLIC_SITE_BASE_PATH}/public/certificates/{certificate['unique_code']}/download"
                if state == "valid" and certificate
                else None
            ),
        },
        status_code=status_code,
    )


@app.get("/validar/{code}", response_class=HTMLResponse, name="validate_page")
async def validate_page(request: Request, code: str) -> HTMLResponse:
    """Canonical public HTML validation page used by every certificate QR."""
    try:
        rate_limit(request)
    except HTTPException as exc:
        return _validation_response(request, state="rate_limited", status_code=exc.status_code)

    clean_code = code.strip()
    if not clean_code or len(clean_code) > 128:
        return _validation_response(request, state="not_found", status_code=404)

    try:
        cert = db.get_by_code(clean_code)
    except Exception:  # pragma: no cover - depends on an unavailable database
        LOGGER.exception("Falha ao validar certificado público")
        return _validation_response(request, state="error", status_code=503)

    if not _is_public_certificate(cert):
        return _validation_response(request, state="not_found", status_code=404)

    public_certificate = _public_view(cert)
    state = "revoked" if public_certificate["status"] == "revogado" else "valid"
    return _validation_response(
        request,
        state=state,
        status_code=200,
        certificate=public_certificate,
    )


# ── API pública (JSON) ──────────────────────────────────────────────────────────


@app.get("/public/verify/{code}")
async def public_verify(code: str, _: None = Depends(rate_limit)) -> dict:
    """Validate a certificate by code. Returns sanitised data; flags revoked."""
    cert = db.get_by_code(code.strip())
    if not _is_public_certificate(cert):
        return {"valid": False}
    status = cert.get("status") or "ativo"
    return {
        "valid": True,
        "status": status,
        "revoked": status == "revogado",
        "certificate": _public_view(cert),
    }


@app.post("/public/search")
async def public_search(
    payload: PublicNameSearchRequest,
    _: None = Depends(rate_limit),
) -> dict:
    """POST-only name search; returns no verifier code or download capability."""

    return _name_search(payload.nome, payload.page)


@app.post("/public/search/email")
async def public_email_search(
    payload: PublicEmailSearchRequest,
    _: None = Depends(rate_limit),
) -> dict:
    """Every public certificate of an exact e-mail (holder or author), never exposing it."""

    return _email_search(payload.email)


@app.get("/public/certificates/{code}/download")
async def public_download(code: str, _: None = Depends(rate_limit)) -> StreamingResponse:
    return _stream_public_certificate(code)


@app.post("/public/certificates/download-by-name")
@app.post("/public/certificates/download-by-search")
async def public_download_by_name(
    request: Request, _: None = Depends(rate_limit)
) -> StreamingResponse:
    """Download after an independent confirmation of the person's identity.

    After a name search the person confirms the e-mail recorded at emission;
    a certificate issued before e-mails were recorded accepts its Registro
    Acadêmico (RA) instead. After an e-mail search the e-mail is typed again
    and the full name, as printed, is the second factor. ``result_ref`` only
    selects one row of the search result: it is not an authorization
    capability, the stored, versioned HMAC must also match in constant time.
    The removed ``challenge`` field is deliberately ignored, so replaying a
    legacy response cannot authorize a download.
    """

    form = await request.form()
    name = str(form.get("nome") or "").strip()
    # One field confirms: an e-mail, or the RA of a certificate without one.
    # ``registro_academico``/``documento`` stay accepted for pages already open.
    confirmation = str(
        form.get("confirmacao")
        or form.get("email")
        or form.get("registro_academico")
        or form.get("documento")
        or ""
    ).strip()
    email = confirmation if _valid_email(confirmation) else ""
    academic_record = "" if email else confirmation
    search_type = "email" if str(form.get("search_type") or "").strip() == "email" else "nome"
    result_ref = str(form.get("result_ref") or "").strip()
    raw_page = str(form.get("page") or "1")
    selected = None
    proof: _Proof | None = None
    try:
        selected_page = int(raw_page) if len(raw_page) <= 6 else 0
    except ValueError:
        selected_page = 0
    input_is_bounded = (
        len(result_ref) == PUBLIC_RESULT_REFERENCE_LENGTH
        and _valid_name_term(name)
        and (
            (search_type == "email" and bool(email))
            or (
                search_type == "nome"
                and (bool(email) or _valid_academic_record(academic_record))
                and 1 <= selected_page <= PUBLIC_MAX_PAGE
            )
        )
    )
    if input_is_bounded:
        if email:
            rate_limit_identity("confirm-email", email, confirmation=True)
        else:
            rate_limit_identity("confirm-document", academic_record, confirmation=True)
        if search_type == "email":
            candidates = db.list_certificates_by_email_hashes(
                email_hash_candidates(email),
                statuses=("ativo",),
            )
        else:
            rate_limit_identity("confirm-name", name, confirmation=True)
            candidates, _total = db.list_certificates(
                name=name,
                statuses=("ativo",),
                limit=PUBLIC_PAGE_SIZE,
                offset=(selected_page - 1) * PUBLIC_PAGE_SIZE,
                order_by="issue_date",
            )
        # Do not return early: every candidate gets the same digest checks.
        for cert in candidates:
            reference_matches = hmac.compare_digest(
                public_result_reference(cert["unique_code"]), result_ref
            )
            candidate = _confirmation_proof(
                cert,
                email=email,
                academic_record=academic_record,
                name=name if search_type == "email" else "",
            )
            if reference_matches and candidate is not None and selected is None:
                selected = cert
                proof = candidate
    if selected is None or proof is None:
        raise HTTPException(
            404,
            "Não foi possível confirmar o e-mail cadastrado (ou o RA, em certificados "
            "antigos). Verifique os dados ou procure a secretaria.",
        )

    _rotate_confirmation_hash(selected, proof, email=email, academic_record=academic_record)
    return _stream_public_certificate(selected["unique_code"])


class _Proof:
    """Which stored hash confirmed the person, and under which key version."""

    __slots__ = ("kind", "row_id", "expected_hash", "key_id")

    def __init__(self, kind: str, row_id: int | None, expected_hash: str, key_id: str) -> None:
        self.kind = kind
        self.row_id = row_id
        self.expected_hash = expected_hash
        self.key_id = key_id


def _name_matches(cert: dict, name: str) -> bool:
    """The full name as printed: the holder's or, on a per-work certificate, any author's."""
    wanted = normalize_name(name)
    if not wanted:
        return False
    printed = [str(cert.get("participant_name_normalized") or "")]
    printed.extend(normalize_name(author) for author in authors_from_json(cert.get("authors_json")))
    matched = False
    for candidate in printed:
        if hmac.compare_digest(candidate.encode("utf-8"), wanted.encode("utf-8")):
            matched = True
    return matched


def _confirmation_proof(
    cert: dict, *, email: str, academic_record: str, name: str
) -> _Proof | None:
    """Constant-time check of the confirmation against the certificate's hashes.

    An e-mail is checked against every e-mail hash of the certificate (any
    author). The academic record is accepted only when the certificate has no
    e-mail hash at all, that is, it was issued before e-mails were recorded.
    When a name is given it must match too.
    """
    email_rows = db.certificate_email_hashes(int(cert["id"]))
    proof: _Proof | None = None
    if email:
        for row in email_rows:
            key_id = matching_email_key_id(
                row.get("email_hash"), email, key_id=row.get("hash_key_id")
            )
            if key_id and proof is None:
                proof = _Proof("email", int(row["id"]), str(row["email_hash"]), key_id)
    elif academic_record and not email_rows:
        key_id = matching_document_key_id(
            cert.get("participant_document_hash"),
            academic_record,
            key_id=cert.get("participant_document_hash_key_id"),
        )
        if key_id:
            proof = _Proof(
                "document", None, str(cert.get("participant_document_hash") or ""), key_id
            )
    if proof is not None and name and not _name_matches(cert, name):
        return None
    return proof


def _rotate_confirmation_hash(
    cert: dict, proof: _Proof, *, email: str, academic_record: str
) -> None:
    """Move the hash that just confirmed to the active key, as the RA always did."""
    active_key_id = active_document_key_id()
    if proof.key_id == active_key_id:
        return
    try:
        if proof.kind == "email" and proof.row_id is not None:
            rotated = email_hash(email, key_id=active_key_id)
            if rotated:
                db.rotate_certificate_email_hash(
                    proof.row_id,
                    expected_hash=proof.expected_hash,
                    new_hash=rotated,
                    new_key_id=active_key_id,
                )
        elif proof.kind == "document":
            rotated = document_hash(academic_record, key_id=active_key_id)
            if rotated:
                db.rotate_certificate_document_hash(
                    cert["unique_code"],
                    expected_hash=proof.expected_hash,
                    new_hash=rotated,
                    new_key_id=active_key_id,
                )
    except Exception:  # pragma: no cover - download remains available
        LOGGER.warning("Falha ao atualizar versão do HMAC de confirmação")


@app.get("/certificado/{unique_code}/download")
async def legacy_download_route(
    request: Request, unique_code: str, _: None = Depends(rate_limit)
) -> RedirectResponse:
    """Compatibility-only redirect; policy enforcement remains canonical."""
    return RedirectResponse(
        f"{PUBLIC_SITE_BASE_PATH}/public/certificates/{unique_code}/download", status_code=308
    )


def _stream_public_certificate(unique_code: str) -> StreamingResponse:
    """Stream a certificate by code. Never exposes a Drive link; blocks revoked."""
    cert = db.get_by_code(unique_code.strip())
    if not cert:
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    if (cert.get("status") or "ativo") != "ativo":
        raise HTTPException(status_code=410, detail="Certificado revogado.")
    if cert.get("integrity_blocked"):
        raise HTTPException(status_code=409, detail="Certificado indisponível.")

    try:
        retrieved = download_certificate(cert, verify=True)
    except StorageIntegrityError as exc:
        # Tampered/corrupt file: block it, log the incident, do NOT serve content.
        observability.metrics.increment(observability.INTEGRITY_INCIDENTS)
        db.block_certificate_integrity(cert["unique_code"])
        db.insert_audit_log(
            action="integrity_incident",
            target_type="certificate",
            target_id=cert["unique_code"],
            details="arquivo armazenado falhou na verificação de integridade",
        )
        LOGGER.error("Incidente de integridade em certificado público")
        raise HTTPException(status_code=409, detail="Certificado indisponível.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado.") from exc
    except StorageError as exc:
        LOGGER.error("Falha de storage em download público: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Falha ao obter o arquivo.") from exc

    observability.metrics.increment(observability.CERT_DOWNLOADS)
    return StreamingResponse(
        BytesIO(retrieved.content),
        media_type=retrieved.mime_type,
        headers={"Content-Disposition": content_disposition(certificate_filename(cert))},
    )


def _resolve_port() -> int:
    raw = os.getenv("PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def run() -> None:
    host = os.getenv("HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    # The public app emits path-only structured logs. Uvicorn access logs are
    # disabled because legacy clients may still send PII in a query string.
    uvicorn.run(app, host=host, port=_resolve_port(), access_log=False)


if __name__ == "__main__":
    run()
