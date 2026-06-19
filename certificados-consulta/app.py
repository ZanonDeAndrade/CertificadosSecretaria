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
import time  # noqa: E402
from collections import defaultdict, deque  # noqa: E402
from io import BytesIO  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from database import db  # noqa: E402
from storage_service import StorageError, download_certificate  # noqa: E402

LOGGER = logging.getLogger("certificados.consulta")

PUBLIC_PAGE_SIZE = 10


def _public_view(cert: dict) -> dict:
    """Sanitised public projection — no email, document, internal id, or Drive id."""
    return {
        "unique_code": cert["unique_code"],
        "participant_name": cert["participant_name"],
        "course_name": cert.get("course_name"),
        "event_name": cert.get("event_name"),
        "workload_hours": cert.get("workload_hours"),
        "issue_date": cert.get("issue_date"),
        "status": cert.get("status") or "ativo",
    }


# ── Rate limiting (best-effort, single-process) ─────────────────────────────────

_RATE_BUCKETS: dict[str, deque] = defaultdict(deque)
_RATE_WINDOW_SECONDS = 60
_RATE_MAX_REQUESTS = 60


def rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    bucket = _RATE_BUCKETS[ip]
    while bucket and bucket[0] < now - _RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _RATE_MAX_REQUESTS:
        raise HTTPException(
            status_code=429, detail="Muitas requisições. Tente novamente em instantes."
        )
    bucket.append(now)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8001  # admin roda na 8000; consulta na 8001 para subirem juntos

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(
    title="Consulta de Certificados",
    version="1.0.0",
    description="Site público para alunos consultarem e baixarem seus certificados.",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Garante que a tabela exista (no-op se o admin já criou).
db.init_db()


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
    results: list[dict] | None = None
    search_type: str | None = None
    query = ""
    error: str | None = None
    total = 0
    page = max(1, int(page))
    page_size = PUBLIC_PAGE_SIZE

    if codigo is not None:
        search_type = "codigo"
        query = codigo.strip()
        if query:
            cert = db.get_by_code(query)
            results = [_public_view(cert)] if cert else []
            total = len(results)
        else:
            error = "Digite um código para buscar."
    elif nome is not None:
        search_type = "nome"
        query = nome.strip()
        if query:
            rows, total = db.list_certificates(
                name=query,
                limit=page_size,
                offset=(page - 1) * page_size,
                order_by="issue_date",
            )
            results = [_public_view(r) for r in rows]
        else:
            error = "Digite um nome para buscar."

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


# ── API pública (JSON) ──────────────────────────────────────────────────────────


@app.get("/public/verify/{code}")
async def public_verify(code: str, _: None = Depends(rate_limit)) -> dict:
    """Validate a certificate by code. Returns sanitised data; flags revoked."""
    cert = db.get_by_code(code.strip())
    if not cert:
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
    if not term:
        return {"items": [], "total": 0, "page": 1, "page_size": PUBLIC_PAGE_SIZE}
    page = max(1, int(page))
    offset = (page - 1) * PUBLIC_PAGE_SIZE
    items, total = db.list_certificates(
        name=term, limit=PUBLIC_PAGE_SIZE, offset=offset, order_by="issue_date"
    )
    return {
        "items": [_public_view(c) for c in items],
        "total": total,
        "page": page,
        "page_size": PUBLIC_PAGE_SIZE,
    }


@app.get("/public/certificates/{code}/download")
async def public_download(code: str, _: None = Depends(rate_limit)) -> StreamingResponse:
    return _stream_public_certificate(code)


@app.get("/certificado/{unique_code}/download")
async def legacy_download_route(unique_code: str) -> StreamingResponse:
    """Legacy download route (kept for compatibility)."""
    return _stream_public_certificate(unique_code)


def _stream_public_certificate(unique_code: str) -> StreamingResponse:
    """Stream a certificate by code. Never exposes a Drive link; blocks revoked."""
    cert = db.get_by_code(unique_code.strip())
    if not cert:
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    if (cert.get("status") or "ativo") != "ativo":
        raise HTTPException(status_code=410, detail="Certificado revogado.")

    try:
        retrieved = download_certificate(cert)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado.") from exc
    except StorageError as exc:
        LOGGER.error("Falha de storage ao baixar %s: %s", unique_code, exc)
        raise HTTPException(status_code=502, detail="Falha ao obter o arquivo.") from exc

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
