"""certificados-consulta — site público para alunos consultarem e baixarem
os seus certificados.

Sem login, sem autenticação. Duas formas de busca:
  - por nome (parcial, case-insensitive)
  - por código único (ex: CERT-2026-AB1234)

Lê do MESMO banco SQLite gravado por certificados-admin (database/db.py) e
serve os PDFs a partir do MESMO storage (storage/pdfs).
"""
from __future__ import annotations

import re
import sys
import unicodedata
import hashlib
import hmac
import ipaddress
from pathlib import Path

# Make the shared `database` package importable by walking up to the repo root
# that contains database/db.py.
for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

import logging  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from io import BytesIO  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from database import db  # noqa: E402
from database.privacy import (  # noqa: E402
    certificate_challenge,
    hash_matches_document,
    normalize_name,
    validate_production_privacy_config,
)
from storage_service import (  # noqa: E402
    StorageError,
    StorageIntegrityError,
    download_certificate,
)

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
PUBLIC_DOCUMENT_ATTEMPTS = _int_setting("PUBLIC_DOCUMENT_ATTEMPTS_PER_WINDOW", 5)


def _valid_name_term(value: str) -> bool:
    return sum(ch.isalnum() for ch in normalize_name(value)) >= PUBLIC_NAME_MIN_LENGTH

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
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
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
        "workload_hours": cert.get("workload_hours"),
        "issue_date": _format_issue_date(cert.get("issue_date")),
        "status": cert.get("status") or "ativo",
    }


def _public_name_view(cert: dict) -> dict:
    """Minimal name-search projection: no verifier code and no direct URL."""
    return {
        "participant_name": cert["participant_name"],
        "course_name": cert.get("course_name"),
        "event_name": cert.get("event_name"),
        "workload_hours": cert.get("workload_hours"),
        "issue_date": _format_issue_date(cert.get("issue_date")),
        "status": cert.get("status") or "ativo",
        "download_challenge": certificate_challenge(cert["unique_code"]),
    }


def _is_public_certificate(cert: dict | None) -> bool:
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
        chain = [ipaddress.ip_address(item.strip()) for item in forwarded.split(",") if item.strip()]
    except ValueError:
        return str(peer_ip)
    for candidate in reversed(chain):
        if not any(candidate in network for network in trusted):
            return str(candidate)
    return str(chain[0]) if chain else str(peer_ip)


def _bucket_key(scope: str, value: str) -> str:
    return hashlib.sha256(f"public:{scope}:{value}".encode()).hexdigest()


def rate_limit(request: Request) -> None:
    allowed, retry_after = db.consume_public_rate_limit(
        _bucket_key("ip", resolve_client_ip(request)),
        now=datetime.now(timezone.utc),
        window_seconds=PUBLIC_RATE_LIMIT_WINDOW_SECONDS,
        limit=PUBLIC_RATE_LIMIT_REQUESTS,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Muitas requisições. Tente novamente em instantes.",
            headers={"Retry-After": str(retry_after)},
        )


def _limit_document_attempt(request: Request, challenge: str) -> None:
    identity = f"{resolve_client_ip(request)}:{challenge}"
    allowed, retry_after = db.consume_public_rate_limit(
        _bucket_key("document", identity),
        now=datetime.now(timezone.utc),
        window_seconds=PUBLIC_RATE_LIMIT_WINDOW_SECONDS,
        limit=PUBLIC_DOCUMENT_ATTEMPTS,
    )
    if not allowed:
        raise HTTPException(429, "Muitas tentativas. Tente novamente em instantes.", headers={"Retry-After": str(retry_after)})

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8001  # admin roda na 8000; consulta na 8001 para subirem juntos

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

import observability  # noqa: E402

observability.configure_logging()

app = FastAPI(
    title="Consulta de Certificados",
    version="1.0.0",
    description="Site público para alunos consultarem e baixarem seus certificados.",
)
app.add_middleware(observability.CorrelationIdMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith("/validar/"):
        response.headers.setdefault("Cache-Control", "no-store")
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
    storage_config.validate_production_storage()
    storage_config.validate_production_public_validation_url()
    validate_production_privacy_config()
    try:
        _trusted_proxy_networks()
    except ValueError as exc:
        raise db_config.ConfigError(f"TRUSTED_PROXY_CIDRS inválido: {exc}") from exc


validate_startup_config()

# Garante que a tabela exista em dev (no-op em produção: schema é do Alembic).
db.init_db()
db.prepare_private_data()
db.cleanup_public_rate_limits(
    datetime.now(timezone.utc)
    - timedelta(seconds=max(PUBLIC_RATE_LIMIT_WINDOW_SECONDS * 2, 86_400))
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    nome: str | None = None,
    codigo: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    try:
        rate_limit(request)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "results": None,
                "search_type": None,
                "query": "",
                "error": exc.detail,
                "total": 0,
                "page": 1,
                "total_pages": 0,
            },
            status_code=exc.status_code,
            headers=exc.headers,
        )
    results: list[dict] | None = None
    search_type: str | None = None
    query = ""
    error: str | None = None
    total = 0
    page = max(1, min(int(page), PUBLIC_MAX_PAGE))
    page_size = PUBLIC_PAGE_SIZE

    if codigo is not None:
        search_type = "codigo"
        query = codigo.strip()
        if query:
            cert = db.get_by_code(query)
            results = [_public_view(cert)] if _is_public_certificate(cert) else []
            total = len(results)
        else:
            error = "Digite um código para buscar."
    elif nome is not None:
        search_type = "nome"
        query = nome.strip()
        if _valid_name_term(query):
            rows, total = db.list_certificates(
                name=query,
                statuses=("ativo", "revogado"),
                limit=page_size,
                offset=(page - 1) * page_size,
                order_by="issue_date",
            )
            results = [_public_name_view(r) for r in rows]
        else:
            error = f"Digite ao menos {PUBLIC_NAME_MIN_LENGTH} caracteres válidos."

    total_pages = (total + page_size - 1) // page_size if total else 0
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "results": results,
            "search_type": search_type,
            "query": query,
            "error": error,
            "total": total,
            "page": page,
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
            "state": state,
            "certificate": certificate,
            "download_url": (
                request.url_for(
                    "public_download", code=certificate["unique_code"]
                )
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
        return _validation_response(
            request, state="rate_limited", status_code=exc.status_code
        )

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


@app.get("/public/search")
async def public_search(
    nome: str = "",
    page: int = 1,
    _: None = Depends(rate_limit),
) -> dict:
    """Paginated search by name. Never returns email/document/internal ids."""
    term = nome.strip()
    if not _valid_name_term(term):
        raise HTTPException(400, f"Informe ao menos {PUBLIC_NAME_MIN_LENGTH} caracteres válidos.")
    page = max(1, min(int(page), PUBLIC_MAX_PAGE))
    offset = (page - 1) * PUBLIC_PAGE_SIZE
    items, total = db.list_certificates(
        name=term, statuses=("ativo", "revogado"), limit=PUBLIC_PAGE_SIZE, offset=offset, order_by="issue_date"
    )
    return {
        "items": [_public_name_view(c) for c in items],
        "total": total,
        "page": page,
        "page_size": PUBLIC_PAGE_SIZE,
    }


@app.get("/public/certificates/{code}/download")
async def public_download(code: str, _: None = Depends(rate_limit)) -> StreamingResponse:
    return _stream_public_certificate(code)


@app.post("/public/certificates/download-by-name")
async def public_download_by_name(request: Request, _: None = Depends(rate_limit)) -> StreamingResponse:
    form = await request.form()
    name = str(form.get("nome") or "")
    document = str(form.get("documento") or "")
    challenge = str(form.get("challenge") or "")
    _limit_document_attempt(request, challenge)
    selected = None
    if _valid_name_term(name) and document and challenge:
        for cert in db.certificates_by_normalized_name(name):
            expected = certificate_challenge(cert["unique_code"])
            if hmac.compare_digest(expected, challenge) and hash_matches_document(
                cert.get("participant_document_hash"), document
            ) and (cert.get("status") or "ativo") == "ativo":
                selected = cert
                break
    if selected is None:
        raise HTTPException(404, "Não foi possível validar os dados informados.")
    return _stream_public_certificate(selected["unique_code"])


@app.get("/certificado/{unique_code}/download")
async def legacy_download_route(
    request: Request, unique_code: str, _: None = Depends(rate_limit)
) -> RedirectResponse:
    """Compatibility-only redirect; policy enforcement remains canonical."""
    return RedirectResponse(
        request.url_for("public_download", code=unique_code), status_code=308
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
            details=str(exc)[:480],
        )
        LOGGER.error("Incidente de integridade em %s: %s", unique_code, exc)
        raise HTTPException(status_code=409, detail="Certificado indisponível.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado.") from exc
    except StorageError as exc:
        LOGGER.error("Falha de storage ao baixar %s: %s", unique_code, exc)
        raise HTTPException(status_code=502, detail="Falha ao obter o arquivo.") from exc

    observability.metrics.increment(observability.CERT_DOWNLOADS)
    filename = _download_filename(cert["participant_name"])
    return StreamingResponse(
        BytesIO(retrieved.content),
        media_type=retrieved.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _download_filename(participant_name: str) -> str:
    base = (
        unicodedata.normalize("NFKD", participant_name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    return f"{base or 'certificado'}.pdf"


def _resolve_port() -> int:
    raw = os.getenv("PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


if __name__ == "__main__":
    host = os.getenv("HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    uvicorn.run(app, host=host, port=_resolve_port())
