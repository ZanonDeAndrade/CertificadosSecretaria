"""Institutional fields on templates: the city and the signatory title reach the
PDF, the editor preview resolves the same values, a batch cannot be confirmed
while the active template prints an empty setting, and blank row fields only
warn. Also the body text normalisation that keeps typed spacing."""

from __future__ import annotations

import base64
import io
from io import BytesIO
from itertools import count
from pathlib import Path

import pandas as pd
from certificados_backend import auth
from certificados_backend.models import ParticipantRegistryRecord
from certificados_backend.services import template_service
from certificados_backend.services.certificate_text import (
    normalize_body_text,
    render_certificate_body,
    validate_body_template,
)
from certificados_backend.services.generator import (
    CertificateGenerator,
    CertificateGeneratorConfig,
    measuring_draw,
)
from certificados_backend.services.template_service import _default_layout
from certificados_backend.utils.text_utils import wrap_hard_breaks
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from database import db

_BACKEND_DIR = Path(__file__).resolve().parent.parent
IMAGE_W, IMAGE_H = 1414, 1000
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BODY = "participou da atividade, com carga horária de {{carga_horaria}} horas."
_KEYS = count(1)

COMPLETE_SETTINGS = {
    "institution_name": "Faculdade Exemplo",
    "issue_location": "Restinga Seca",
    "signatory_name": "Helena Martins",
    "signatory_title": "Secretária Acadêmica",
    "public_url": "https://certificados.example.test",
    "retention_days": 0,
    "max_batch_rows": 100,
    "max_upload_mb": 5,
    "secretaria_can_revoke": True,
    "secretaria_can_reissue": True,
}


def _png_bytes(w: int = IMAGE_W, h: int = IMAGE_H) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (w, h), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _record_text_calls(monkeypatch) -> list[str]:
    texts: list[str] = []
    original = ImageDraw.ImageDraw.text

    def recording(self, xy, text, fill=None, font=None, *args, **kwargs):
        texts.append(text)
        return original(self, xy, text, fill, font, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording)
    return texts


def _xlsx(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return buffer.getvalue()


def _files(rows: list[dict]) -> dict:
    return {"file": ("participantes.xlsx", _xlsx(rows), XLSX_MIME)}


def _row(nome: str, **extra) -> dict:
    row = {
        "nome": nome,
        "curso": "Direito",
        "evento": "Semana Jurídica",
        "carga_horaria": 40,
        "data_emissao": "10/06/2026",
    }
    row.update(extra)
    return row


def _put_settings(client, **overrides) -> None:
    response = client.put("/admin/settings", json={**COMPLETE_SETTINGS, **overrides})
    assert response.status_code == 200, response.text


def _preview(client, rows: list[dict]) -> dict:
    response = client.post(
        "/certificates/validate-spreadsheet",
        files=_files(rows),
        data={"texto_padrao": BODY, "certificate_type": "listener"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _start(client, rows: list[dict]):
    return client.post(
        "/emission-batches",
        files=_files(rows),
        data={"texto_padrao": BODY, "certificate_type": "listener", "drive_folders_json": "{}"},
        headers={"Idempotency-Key": f"template-fields-test-{next(_KEYS):06d}"},
    )


def _secretaria(client) -> TestClient:
    db.create_admin_user("secretaria.teste", auth.hash_password("Senha-Forte-2026!"), "secretaria")
    other = TestClient(
        client.app, base_url="https://admin-api.test", headers={"Origin": "http://localhost:5173"}
    )
    login = other.post(
        "/auth/login", json={"username": "secretaria.teste", "password": "Senha-Forte-2026!"}
    )
    assert login.status_code == 200, login.text
    return other


# ── Rendering ─────────────────────────────────────────────────────────────────


def test_city_and_signatory_title_from_settings_reach_the_pdf(tmp_path, monkeypatch):
    generator = CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=tmp_path / "pdfs",
            institution_name="Faculdade Exemplo",
            issue_location="Restinga Seca",
            signatory_name="Helena Martins",
            signatory_title="Secretária Acadêmica",
        )
    )
    record = ParticipantRegistryRecord(
        nome="Ana Souza",
        email="",
        curso="Direito",
        livro=0,
        folha=0,
        linha=0,
        evento="Semana Jurídica",
        validation_code="CERT-2026-TF0001",
        texto_certificado="participou da atividade, com carga horária de 40 horas.",
        certificate_text="participou da atividade, com carga horária de 40 horas.",
        data_emissao="10 de junho de 2026",
    )
    texts = _record_text_calls(monkeypatch)

    generator._compose_visual_image(
        record, _default_layout(IMAGE_W, IMAGE_H), background_bytes=_png_bytes()
    )

    assert "Restinga Seca, 10 de junho de 2026." in texts
    assert "Helena Martins" in texts
    assert "Secretária Acadêmica" in texts


def test_body_text_keeps_typed_spacing_and_drops_invisible_characters(tmp_path):
    typed = "ocorrido nos dias 25 e 26 de agosto de 2026, com {{carga_horaria}} horas."
    assert validate_body_template(typed) == typed
    rendered = render_certificate_body(typed, {"carga_horaria": "16"})
    assert "dias 25 e 26" in rendered and "16 horas" in rendered

    generator = CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=tmp_path / "pdfs",
        )
    )
    font = generator._resolve_visual_font("Times New Roman", 24, False)
    lines = wrap_hard_breaks(measuring_draw(), rendered, font, 2000)
    assert lines == [rendered], "a wide box keeps the sentence intact, spaces included"

    # Characters that print as nothing, or as odd gaps, are normalised away.
    assert normalize_body_text("dias 25 e 26") == "dias 25 e 26"
    assert normalize_body_text("dias​25﻿ e ­26") == "dias25 e 26"
    assert validate_body_template("﻿  texto {{nome}}  ​") == "texto {{nome}}"


# ── Preview sample data ───────────────────────────────────────────────────────


def test_sample_data_resolves_values_like_the_pdf(client, auth_headers):
    assert (
        TestClient(client.app, base_url="https://admin-api.test")
        .get("/templates/sample-data")
        .status_code
        == 401
    )

    _put_settings(client, signatory_title="")
    response = client.get("/templates/sample-data")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["values"]["issue_line"] == "Restinga Seca, 27 de abril de 2026."
    assert body["values"]["issue_location"] == "Restinga Seca"
    assert body["values"]["signatory_name"] == "Helena Martins"
    assert body["values"]["signatory_title"] == ""
    assert body["values"]["institution_name"] == "Faculdade Exemplo"
    assert body["values"]["name"] == "Joao Silva"
    assert body["empty_settings"] == [{"setting": "signatory_title", "label": "Cargo do assinante"}]
    assert body["can_manage_settings"] is True


# ── Batch review ──────────────────────────────────────────────────────────────


def test_empty_setting_used_by_the_template_blocks_confirmation(client, auth_headers):
    # The seeded default template prints issue_line, signatory_name and
    # signatory_title; leave the city and the title empty.
    _put_settings(client, issue_location="", signatory_title="")

    preview = _preview(client, [_row("Ana Souza")])
    missing = {item["setting"]: item for item in preview["missing_settings"]}
    assert set(missing) == {"issue_location", "signatory_title"}
    assert missing["issue_location"]["label"] == "Cidade (local de emissão)"
    assert missing["issue_location"]["keys"] == ["issue_line"]
    assert missing["signatory_title"]["keys"] == ["signatory_title"]
    assert preview["can_manage_settings"] is True
    assert "Preencha em Configurações" in preview["missing_settings_message"]
    assert "administrador" not in preview["missing_settings_message"]

    blocked = _start(client, [_row("Ana Souza")])
    assert blocked.status_code == 422, blocked.text
    assert "Cidade (local de emissão)" in blocked.json()["detail"]
    assert "Cargo do assinante" in blocked.json()["detail"]
    assert "Configurações" in blocked.json()["detail"]
    assert client.get("/certificates").json()["total"] == 0

    _put_settings(client)
    assert _preview(client, [_row("Ana Souza")])["missing_settings"] == []
    accepted = _start(client, [_row("Ana Souza")])
    assert accepted.status_code == 202, accepted.text


def test_secretaria_is_told_to_ask_an_administrator(client, auth_headers):
    _put_settings(client, issue_location="")
    secretaria = _secretaria(client)

    preview = _preview(secretaria, [_row("Ana Souza")])
    assert preview["can_manage_settings"] is False
    assert "administrador" in preview["missing_settings_message"]

    blocked = _start(secretaria, [_row("Ana Souza")])
    assert blocked.status_code == 422, blocked.text
    assert "administrador" in blocked.json()["detail"]


def test_blank_row_fields_only_warn_with_their_rows(client, auth_headers):
    _put_settings(client)
    layout = {
        "background": "data:image/png;base64," + base64.b64encode(_png_bytes()).decode("ascii"),
        "image_width": IMAGE_W,
        "image_height": IMAGE_H,
        "elements": [
            {"type": "text", "key": "name", "x": 707, "y": 300, "fontSize": 40, "align": "center"},
            {"type": "text", "key": "event", "x": 707, "y": 400, "fontSize": 24, "align": "center"},
            {
                "type": "text",
                "key": "texto_certificado",
                "x": 90,
                "y": 500,
                "fontSize": 24,
                "align": "left",
            },
        ],
    }
    version = template_service.create_version(name="Com evento", layout=layout)
    assert client.post(f"/templates/versions/{version['id']}/activate").status_code == 200

    preview = _preview(client, [_row("Ana Souza"), _row("Carla Dias", evento="")])
    assert preview["missing_settings"] == []
    assert preview["empty_fields"] == [
        {
            "key": "event",
            "label": "Evento",
            "row_count": 1,
            "rows": [{"row_number": 3, "nome": "Carla Dias"}],
            "checked_rows": 2,
            "truncated": False,
        }
    ]

    # A warning, not a block: the batch is accepted.
    accepted = _start(client, [_row("Ana Souza"), _row("Carla Dias", evento="")])
    assert accepted.status_code == 202, accepted.text


def _preview_with(client, rows: list[dict], text: str, certificate_type: str) -> dict:
    response = client.post(
        "/certificates/validate-spreadsheet",
        files=_files(rows),
        data={"texto_padrao": text, "certificate_type": certificate_type},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_blank_team_used_by_the_body_lists_its_rows(client, auth_headers):
    _put_settings(client)
    rows = [
        _row("Ana Souza", equipe="Equipe Azul"),
        _row("Bruno Lima", equipe=""),
        _row("Carla Dias", equipe="Equipe Verde"),
        _row("Davi Rocha"),  # no value in the column at all
    ]
    preview = _preview_with(client, rows, "integrou a {{equipe}}.", "listener")
    assert preview["empty_fields"] == [
        {
            "key": "equipe",
            "label": "Equipe",
            "row_count": 2,
            "rows": [
                {"row_number": 3, "nome": "Bruno Lima"},
                {"row_number": 5, "nome": "Davi Rocha"},
            ],
            "checked_rows": 4,
            "truncated": False,
        }
    ]


def test_blank_team_warning_also_covers_per_work_batches(client, auth_headers):
    _put_settings(client)
    works = [
        {"autor1": "Pessoa Exemplo Alfa", "evento": "Mostra 2026", "equipe": "Equipe Azul"},
        {"autor1": "Pessoa Exemplo Beta", "evento": "Mostra 2026", "equipe": ""},
    ]
    preview = _preview_with(
        client, works, "{{titulo_trabalho}}, da {{equipe}}.", "scientific_initiation"
    )
    by_key = {field["key"]: field for field in preview["empty_fields"]}
    assert by_key["equipe"]["rows"] == [{"row_number": 3, "nome": "Pessoa Exemplo Beta"}]
    # Neither work has a title: both rows are listed under it.
    assert by_key["titulo_trabalho"]["row_count"] == 2


def test_blank_event_is_listed_once_when_template_and_body_both_use_it(client, auth_headers):
    _put_settings(client)
    layout = {
        "background": "data:image/png;base64," + base64.b64encode(_png_bytes()).decode("ascii"),
        "image_width": IMAGE_W,
        "image_height": IMAGE_H,
        "elements": [
            {"type": "text", "key": "name", "x": 707, "y": 300, "fontSize": 40, "align": "center"},
            {"type": "text", "key": "event", "x": 707, "y": 400, "fontSize": 24, "align": "center"},
            {"type": "text", "key": "texto_certificado", "x": 90, "y": 500, "fontSize": 24},
        ],
    }
    version = template_service.create_version(name="Evento duas vezes", layout=layout)
    assert client.post(f"/templates/versions/{version['id']}/activate").status_code == 200

    rows = [_row("Ana Souza"), _row("Carla Dias", evento="")]
    preview = _preview_with(client, rows, "participou de {{evento}}.", "listener")
    assert [field["label"] for field in preview["empty_fields"]] == ["Evento"]
    assert preview["empty_fields"][0]["rows"] == [{"row_number": 3, "nome": "Carla Dias"}]
