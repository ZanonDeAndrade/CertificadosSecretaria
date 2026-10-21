"""Seed the single global certificate template (idempotent).

Run once after applying the database migrations (``alembic upgrade head``). If no
template version exists yet, it creates version 1 from the bundled default
background (``templates/certificado_base.png``) and activates it. Existing
versions are left untouched.

Usage:
    python seed_template.py
"""

from __future__ import annotations

from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent

from certificados_backend.services import template_service

from database import db

DEFAULT_TEMPLATE = _BACKEND_DIR / "templates" / "certificado_base.png"


def main() -> int:
    db.init_db()
    before = db.count_template_versions()
    template_service.ensure_default_version(DEFAULT_TEMPLATE)
    after = db.count_template_versions()
    active = db.get_active_template_version()

    if before == 0 and after > 0 and active is not None:
        print(f"Template global padrao criado e ativado (v{active['version_number']}).")
    else:
        label = f"v{active['version_number']}" if active else "nenhuma"
        print(f"Nada a fazer: {after} versao(oes) ja existem (ativa: {label}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
