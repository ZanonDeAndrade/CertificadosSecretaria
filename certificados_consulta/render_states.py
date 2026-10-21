"""Renderiza os templates públicos em HTML estático, um arquivo por estado.

Serve para conferência visual e para os testes de acessibilidade/responsividade
da área pública, sem precisar subir o app inteiro (que exige banco, segredos e
configuração de armazenamento).

Uso:
    python -m certificados_consulta.render_states <diretorio-de-saida>
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = BASE_DIR / "templates"
STATIC = BASE_DIR / "static"


def _url_for(endpoint: str, **values: str) -> str:
    """Stand-in for Starlette's url_for, enough for the static stylesheet."""
    if endpoint == "static":
        return f".{values.get('path', '')}"
    return "#"


def _cert(**overrides: object) -> dict:
    base = {
        "participant_name": "Ana Carolina Souza",
        "event_name": "Semana de Inovação",
        "course_name": "Direito",
        "workload_hours": 12,
        "issue_date": "10 de junho de 2026",
        "unique_code": "CERT-2026-AB1234",
        "status": "ativo",
        "result_ref": "abc123",
    }
    base.update(overrides)
    return base


def _index_ctx(**overrides: object) -> dict:
    ctx: dict[str, object] = {
        "results": None,
        "error": None,
        "query": "",
        "search_type": None,
        "total": 0,
        "page": 1,
        "total_pages": 1,
    }
    ctx.update(overrides)
    return ctx


STATES: dict[str, tuple[str, dict]] = {
    "busca-inicial": ("index.html", _index_ctx()),
    "busca-por-codigo": (
        "index.html",
        _index_ctx(
            search_type="codigo",
            query="CERT-2026-AB1234",
            results=[_cert()],
            total=1,
        ),
    ),
    "busca-por-nome": (
        "index.html",
        _index_ctx(
            search_type="nome",
            query="Ana Carolina",
            results=[
                _cert(),
                _cert(
                    participant_name="Ana Carolina Souza",
                    event_name="Jornada Jurídica",
                    unique_code="CERT-2025-ZZ9999",
                    status="revogado",
                    result_ref="def456",
                ),
            ],
            total=2,
            page=1,
            total_pages=3,
        ),
    ),
    "sem-resultados": (
        "index.html",
        _index_ctx(search_type="nome", query="Fulano de Tal", results=[], total=0),
    ),
    "erro": (
        "index.html",
        _index_ctx(
            error="Muitas consultas em pouco tempo. Aguarde alguns instantes.",
            search_type="nome",
            query="Ana",
        ),
    ),
    "valido": (
        "validar.html",
        {"state": "valid", "certificate": _cert(), "download_url": "#"},
    ),
    "revogado": (
        "validar.html",
        {
            "state": "revoked",
            "certificate": _cert(status="revogado"),
            "download_url": None,
        },
    ),
    "inexistente": (
        "validar.html",
        {"state": "not_found", "certificate": None, "download_url": None},
    ),
    "bloqueado": (
        "validar.html",
        {"state": "rate_limited", "certificate": None, "download_url": None},
    ),
    "indisponivel": (
        "validar.html",
        {"state": "error", "certificate": None, "download_url": None},
    ),
}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(STATIC / "styles.css", out / "styles.css")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["url_for"] = _url_for
    env.globals["institution_name"] = "Instituição Acadêmica de Demonstração"

    for name, (template_name, context) in STATES.items():
        html = env.get_template(template_name).render(**context)
        (out / f"{name}.html").write_text(html, encoding="utf-8")
        print(f"{name:<20} -> {template_name}")

    print(f"\n{len(STATES)} estados escritos em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
