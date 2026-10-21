"""Text boxes on template text elements: optional ``width`` (wrap limit) and
``height`` (box area), the preview endpoint and the batch pre-check."""

from __future__ import annotations

import base64
import io
from io import BytesIO
from pathlib import Path

import pandas as pd
from certificados_backend import auth
from certificados_backend.models import ParticipantRegistryRecord
from certificados_backend.services import generator as generator_module
from certificados_backend.services import template_service
from certificados_backend.services.generator import (
    CertificateGenerator,
    CertificateGeneratorConfig,
    measuring_draw,
)
from certificados_backend.utils.text_utils import get_text_size
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from database import db

_BACKEND_DIR = Path(__file__).resolve().parent.parent
IMAGE_W, IMAGE_H = 1414, 1000
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BODY = "participou da atividade, com carga horária de {{carga_horaria}} horas."
LONG_NAME = "Maria Aparecida da Conceição dos Santos Oliveira"


def _generator(tmp_path: Path) -> CertificateGenerator:
    return CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=tmp_path / "pdfs",
        )
    )


def _element(key: str, **overrides) -> dict:
    element = {
        "type": "text",
        "key": key,
        "x": IMAGE_W // 2,
        "y": 300,
        "fontSize": 32,
        "fontFamily": "Times New Roman",
        "color": "#000000",
        "align": "center",
        "bold": False,
        "italic": False,
    }
    element.update(overrides)
    return element


def _png_bytes(w: int = IMAGE_W, h: int = IMAGE_H) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (w, h), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _record(
    nome: str = "Ana Souza",
    body: str = "participou da atividade, com carga horária de 40 horas.",
) -> ParticipantRegistryRecord:
    return ParticipantRegistryRecord(
        nome=nome,
        email="",
        curso="Direito",
        livro=0,
        folha=0,
        linha=0,
        evento="Semana Jurídica",
        validation_code="CERT-2026-TB0001",
        texto_certificado=body,
        certificate_text=body,
        data_emissao="10 de junho de 2026",
    )


def _record_text_calls(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    original = ImageDraw.ImageDraw.text

    def recording(self, xy, text, fill=None, font=None, *args, **kwargs):
        calls.append({"xy": xy, "text": text, "size": font.size})
        return original(self, xy, text, fill, font, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording)
    return calls


# ── Layout rules ──────────────────────────────────────────────────────────────


def test_width_wraps_a_short_field_and_every_line_fits(tmp_path):
    generator = _generator(tmp_path)
    draw = measuring_draw()
    text = "Semana Acadêmica de Tecnologia e Inovação Pedagógica"

    legacy = generator.layout_text_box(draw, IMAGE_W, text, _element("event"))
    assert legacy.wrap_width is None
    assert legacy.lines == [text]
    assert legacy.height is None and legacy.overflow is False

    boxed = generator.layout_text_box(draw, IMAGE_W, text, _element("event", width=220))
    assert boxed.wrap_width == 220
    assert len(boxed.lines) > 1
    assert " ".join(boxed.lines) == text
    assert all(get_text_size(draw, line, boxed.font)[0] <= 220 for line in boxed.lines)
    assert (
        boxed.text_height
        == (len(boxed.lines) - 1) * boxed.line_height + (get_text_size(draw, "Ag", boxed.font)[1])
    )


def test_width_never_exceeds_the_page_bound_the_pdf_enforces(tmp_path):
    generator = _generator(tmp_path)
    draw = measuring_draw()
    margin = int(IMAGE_W * 0.04)

    left = generator.layout_text_box(
        draw, IMAGE_W, "texto", _element("event", width=5000, align="left", x=90)
    )
    assert left.wrap_width == IMAGE_W - 90 - margin

    center = generator.layout_text_box(draw, IMAGE_W, "texto", _element("event", width=5000))
    assert center.wrap_width == 2 * (IMAGE_W // 2 - margin)

    right = generator.layout_text_box(
        draw, IMAGE_W, "texto", _element("event", width=5000, align="right", x=1324)
    )
    assert right.wrap_width == 1324 - margin


def test_legacy_element_without_box_is_drawn_in_one_call(tmp_path, monkeypatch):
    """A template saved before boxes existed must render exactly as before:
    typed line breaks go to Pillow in a single call, nothing is wrapped."""
    generator = _generator(tmp_path)
    calls = _record_text_calls(monkeypatch)
    text = "Linha um\nLinha dois"
    layout = {
        "image_width": IMAGE_W,
        "image_height": IMAGE_H,
        "elements": [_element("static", staticText=text, align="left", x=90)],
    }

    generator._compose_visual_image(_record(), layout, background_bytes=_png_bytes())

    assert calls == [{"xy": (90, 300), "text": text, "size": 32}]


def test_boxed_static_text_wraps_and_draws_one_call_per_line(tmp_path, monkeypatch):
    generator = _generator(tmp_path)
    calls = _record_text_calls(monkeypatch)
    text = "Linha um bem mais comprida do que a caixa permite\nLinha dois"
    layout = {
        "image_width": IMAGE_W,
        "image_height": IMAGE_H,
        "elements": [_element("static", staticText=text, align="left", x=90, width=200)],
    }

    generator._compose_visual_image(_record(), layout, background_bytes=_png_bytes())

    assert len(calls) > 2
    assert [call["text"] for call in calls][-1] == "Linha dois"
    assert all(call["xy"][0] == 90 for call in calls)
    ys = [call["xy"][1] for call in calls]
    assert ys == sorted(ys) and len(set(ys)) == len(ys)


def test_height_flags_overflow_logs_it_and_never_clips(tmp_path, monkeypatch):
    generator = _generator(tmp_path)
    draw = measuring_draw()
    text = " ".join(["palavra"] * 60)
    element = _element("texto_certificado", align="left", x=90, width=400, height=30)

    box = generator.layout_text_box(draw, IMAGE_W, text, element)
    assert box.overflow is True
    assert box.height == 30 and box.text_height > 30
    assert len(box.lines) > 3

    roomy = generator.layout_text_box(draw, IMAGE_W, text, {**element, "height": box.text_height})
    assert roomy.overflow is False

    calls = _record_text_calls(monkeypatch)
    layout = {"image_width": IMAGE_W, "image_height": IMAGE_H, "elements": [element]}
    # The app's logging setup, installed by earlier tests, routes records away
    # from pytest's capture; record the warning at its source instead.
    warnings: list[str] = []
    monkeypatch.setattr(
        generator_module,
        "LOGGER",
        type("Recorder", (), {"warning": lambda self, msg, *args: warnings.append(msg % args)})(),
    )
    generator._compose_visual_image(_record(body=text), layout, background_bytes=_png_bytes())

    # Every wrapped line is drawn: the PDF is complete even though it overflows.
    assert [call["text"] for call in calls] == box.lines
    assert len(warnings) == 1 and "excede a caixa" in warnings[0]
    assert "30 px" in warnings[0]
    assert "palavra" not in warnings[0], "the participant's text never reaches the log"


def test_name_box_grows_downward_only_when_width_is_set(tmp_path):
    generator = _generator(tmp_path)
    draw = measuring_draw()

    legacy = generator.layout_text_box(draw, IMAGE_W, LONG_NAME, _element("name", fontSize=48))
    assert len(legacy.lines) == 2
    assert legacy.top_offset == legacy.line_height // 2

    boxed = generator.layout_text_box(
        draw, IMAGE_W, LONG_NAME, _element("name", fontSize=48, width=300)
    )
    assert boxed.top_offset == 0
    assert boxed.wrap_width == 300
    assert boxed.font_size < 48, "the name still shrinks to fit its box"
    assert all(get_text_size(draw, line, boxed.font)[0] <= 300 for line in boxed.lines)


def test_pdf_for_legacy_and_boxed_layouts_both_render(tmp_path):
    generator = _generator(tmp_path)
    elements = [
        _element("name", y=200, fontSize=40, width=500, height=120),
        _element("texto_certificado", y=400, align="left", x=90, width=600, height=200),
        _element("event", y=700, width=300),
    ]
    layout = {"image_width": IMAGE_W, "image_height": IMAGE_H, "elements": elements}
    pdf = generator.render_pdf_bytes_visual(_record(), layout, background_bytes=_png_bytes())
    assert pdf[:4] == b"%PDF"


# ── Preview endpoint ──────────────────────────────────────────────────────────


def _item(id_: str = "a", **overrides) -> dict:
    item = {
        "id": id_,
        "key": "event",
        "text": "Semana Acadêmica de Tecnologia e Inovação Pedagógica",
        "x": IMAGE_W // 2,
        "fontSize": 32,
        "fontFamily": "Times New Roman",
        "bold": False,
        "align": "center",
    }
    item.update(overrides)
    return item


def test_text_layout_endpoint_requires_login(client):
    response = client.post(
        "/templates/text-layout", json={"image_width": IMAGE_W, "items": [_item()]}
    )
    assert response.status_code == 401


def test_text_layout_endpoint_denies_roles_without_template_management(client, auth_headers):
    db.create_admin_user("auditor", auth.hash_password("audit-password"), "auditor")
    auditor = TestClient(
        client.app, base_url="https://admin-api.test", headers={"Origin": "http://localhost:5173"}
    )
    login = auditor.post("/auth/login", json={"username": "auditor", "password": "audit-password"})
    assert login.status_code == 200, login.text

    response = auditor.post(
        "/templates/text-layout", json={"image_width": IMAGE_W, "items": [_item()]}
    )
    assert response.status_code == 403


def test_text_layout_endpoint_returns_the_pdf_breaks(client, auth_headers):
    response = client.post(
        "/templates/text-layout",
        json={
            "image_width": IMAGE_W,
            "items": [
                _item("legacy"),
                _item("boxed", width=220, height=40),
                _item("name", key="name", text=LONG_NAME, fontSize=48, bold=True),
                _item("empty", key="static", text="   "),
            ],
        },
    )
    assert response.status_code == 200, response.text
    items = {item["id"]: item for item in response.json()["items"]}

    assert items["legacy"]["lines"] == [_item()["text"]]
    assert items["legacy"]["wrap_width"] is None
    assert items["legacy"]["overflow"] is False

    boxed = items["boxed"]
    assert boxed["wrap_width"] == 220
    assert len(boxed["lines"]) > 1
    assert boxed["overflow"] is True
    assert boxed["text_height"] > 40
    assert boxed["line_height"] > 0

    name = items["name"]
    assert len(name["lines"]) == 2
    assert name["top_offset"] == name["line_height"] // 2
    assert name["font_size"] <= 48

    assert items["empty"]["lines"] == [] and items["empty"]["text_height"] == 0


def test_text_layout_endpoint_limits_text_font_and_item_count(client, auth_headers):
    too_long = client.post(
        "/templates/text-layout",
        json={"image_width": IMAGE_W, "items": [_item(text="x" * 4001)]},
    )
    assert too_long.status_code == 422

    tiny_font = client.post(
        "/templates/text-layout", json={"image_width": IMAGE_W, "items": [_item(fontSize=5)]}
    )
    assert tiny_font.status_code == 422

    huge_font = client.post(
        "/templates/text-layout", json={"image_width": IMAGE_W, "items": [_item(fontSize=601)]}
    )
    assert huge_font.status_code == 422

    too_many = client.post(
        "/templates/text-layout",
        json={"image_width": IMAGE_W, "items": [_item(str(i)) for i in range(101)]},
    )
    assert too_many.status_code == 422

    bad_width = client.post("/templates/text-layout", json={"image_width": 0, "items": [_item()]})
    assert bad_width.status_code == 422


# ── Batch pre-check ───────────────────────────────────────────────────────────


def _xlsx(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return buffer.getvalue()


def _files(rows: list[dict]) -> dict:
    return {"file": ("participantes.xlsx", _xlsx(rows), XLSX_MIME)}


def _row(nome: str, row_extra: dict | None = None) -> dict:
    row = {
        "nome": nome,
        "curso": "Direito",
        "evento": "Semana Jurídica",
        "carga_horaria": 40,
        "data_emissao": "10/06/2026",
    }
    row.update(row_extra or {})
    return row


def _activate_layout(client, elements: list[dict]) -> None:
    layout = {
        "background": "data:image/png;base64," + base64.b64encode(_png_bytes()).decode("ascii"),
        "image_width": IMAGE_W,
        "image_height": IMAGE_H,
        "elements": elements,
    }
    version = template_service.create_version(name="Com caixas", layout=layout)
    activated = client.post(f"/templates/versions/{version['id']}/activate")
    assert activated.status_code == 200, activated.text


def test_preview_lists_participants_whose_text_overflows_a_sized_box(client, auth_headers):
    _activate_layout(
        client,
        [
            # Every name overflows a 10 px box; the body has plenty of room.
            _element("name", y=200, width=500, height=10, label="Nome do participante"),
            _element("texto_certificado", y=400, align="left", x=90, width=900, height=900),
            # A fixed text that cannot fit: it affects every certificate.
            _element("static", staticText="Texto fixo", y=800, width=300, height=1),
            # No height: never reported, regardless of length.
            _element("event", y=900, width=100),
        ],
    )

    response = client.post(
        "/certificates/validate-spreadsheet",
        files=_files(
            [_row("Ana Souza"), _row("Bruno", {"carga_horaria": "abc"}), _row("Carla Dias")]
        ),
        data={"texto_padrao": BODY},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    warnings = {item["key"]: item for item in response.json()["layout_warnings"]}
    assert set(warnings) == {"name", "static"}

    name = warnings["name"]
    assert name["label"] == "Nome do participante"
    assert name["height"] == 10
    assert name["row_count"] == 2
    assert name["rows"] == [
        {"row_number": 2, "nome": "Ana Souza"},
        {"row_number": 4, "nome": "Carla Dias"},
    ]
    assert name["applies_to_all"] is False
    assert name["checked_rows"] == 2
    assert name["truncated"] is False

    static = warnings["static"]
    assert static["applies_to_all"] is True
    assert static["row_count"] == 0 and static["rows"] == []


def test_preview_has_no_warnings_without_sized_boxes(client, auth_headers):
    response = client.post(
        "/certificates/validate-spreadsheet",
        files=_files([_row("Ana Souza")]),
        data={"texto_padrao": BODY},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["layout_warnings"] == []
