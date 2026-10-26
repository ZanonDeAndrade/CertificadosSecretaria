"""PostgreSQL contract for per-work certificates (the Mostra).

On the production database a per-work type must not fall back to the generic
template, and a certificate issued with its own template stores every author
and the automatic body. Skipped unless ``TEST_DATABASE_URL`` points at a
disposable PostgreSQL database.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest
from certificados_backend.services import template_service
from certificados_backend.services.runtime import build_certificate_service
from certificados_backend.services.spreadsheet import SpreadsheetRow
from PIL import Image

from database import db
from database.repositories import authors_from_json

pytestmark = pytest.mark.postgres

_BACKEND_DIR = Path(__file__).resolve().parent.parent
MOSTRA = "scientific_initiation"
AUTHORS = ("Pessoa Exemplo Alfa", "Pessoa Exemplo Beta", "Pessoa Exemplo Gama")
EVENT = "Mostra de Iniciação Científica 2026"
TITLE = "Horta vertical automatizada"
SNAPSHOT = {
    "institution_name": "Instituição",
    "issue_location": "Cidade",
    "signatory_name": "Assinante",
    "signatory_title": "Cargo",
    "public_url": "https://certificados.example.test",
}


def _mostra_layout() -> dict:
    buffer = BytesIO()
    Image.new("RGB", (1414, 1000), "white").save(buffer, "PNG")

    def text(key: str, **extra) -> dict:
        return {"type": "text", "key": key, "x": 70, "fontSize": 24, "align": "left", **extra}

    return {
        "background": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
        "image_width": 1414,
        "image_height": 1000,
        "elements": [
            text("texto_certificado", y=300, width=1000),
            text("authors", y=800, anchorY="bottom"),
            {"type": "qr", "key": "qr", "x": 70, "y": 820, "width": 120, "height": 120},
        ],
    }


def test_mostra_on_postgres_never_falls_back_and_stores_every_author(
    postgres_engine, monkeypatch, tmp_path
):
    import storage_service

    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    storage_service.reset_storage_cache()
    try:
        template_service.ensure_default_version(_BACKEND_DIR / "templates" / "certificado_base.png")
        generic = template_service.get_active_version(None)
        assert generic is not None
        assert template_service.get_active_version(MOSTRA) is None
        assert template_service.get_active_version("listener")["id"] == generic["id"]

        service = build_certificate_service()
        rows = [
            SpreadsheetRow(
                row_number=2,
                nome=AUTHORS[0],
                carga_horaria=60,
                evento=EVENT,
                titulo_trabalho=TITLE,
                autores=AUTHORS,
            )
        ]
        with pytest.raises(ValueError, match="Não há template ativo do tipo"):
            service.generate_certificates(
                rows, body_template="", certificate_type=MOSTRA, institutional_snapshot=SNAPSHOT
            )
        assert db.list_certificates(limit=10, offset=0)[1] == 0

        version = template_service.create_version(
            name="Mostra", layout=_mostra_layout(), certificate_type=MOSTRA
        )
        assert template_service.activate_version(version["id"])
        assert template_service.get_active_version(MOSTRA)["id"] == version["id"]
        # The generic version stays active for every other type.
        assert template_service.get_active_version("listener")["id"] == generic["id"]

        summary = service.generate_certificates(
            rows, body_template="", certificate_type=MOSTRA, institutional_snapshot=SNAPSHOT
        )
        assert len(summary.generated) == 1
        stored = db.get_by_code(summary.generated[0]["code"])
        assert stored is not None
        assert stored["template_version_id"] == version["id"]
        assert authors_from_json(stored["authors_json"]) == list(AUTHORS)
        assert stored["work_title"] == TITLE
        assert stored["certificate_text"] == (
            f'Certificamos que o trabalho "{TITLE}" foi apresentado no evento {EVENT}, '
            "com carga horária de 60 horas."
        )
        # Any author finds the certificate.
        found, total = db.list_certificates(name=AUTHORS[2], limit=10, offset=0)
        assert total == 1 and found[0]["unique_code"] == stored["unique_code"]
    finally:
        storage_service.reset_storage_cache()
