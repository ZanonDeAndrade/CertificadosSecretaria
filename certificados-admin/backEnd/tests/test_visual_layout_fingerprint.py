"""Golden fingerprint of the visual-template renderer for legacy layouts.

Text boxes gained optional ``width``/``height`` fields. A layout that predates
them (every template saved before that change) must keep producing exactly the
same certificate. Rather than hashing pixels, which depends on the rasterizer
of each platform, this records every draw call the generator issues — text,
position, font file, size and colour, plus the position and size of each
composited image — and compares it with the fixture below. Only fonts shipped
in ``fonts/`` are used, so the result is the same on every machine and in CI.

Regenerate the fixture ONLY when a rendering change is intended:

    CERT_FINGERPRINT_WRITE=1 uv run pytest certificados-admin/backEnd/tests/test_visual_layout_fingerprint.py
"""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO
from pathlib import Path

import pytest
from certificados_backend.models import ParticipantRegistryRecord
from certificados_backend.services.generator import (
    CertificateGenerator,
    CertificateGeneratorConfig,
)
from certificados_backend.services.template_service import _default_layout
from PIL import Image, ImageDraw

_BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "visual_layout_fingerprint.json"

# Captured once at import time so that recording one layout never chains into
# the recorder installed for a previous layout within the same test.
_ORIGINAL_TEXT = ImageDraw.ImageDraw.text
_ORIGINAL_COMPOSITE = Image.Image.alpha_composite

IMAGE_W, IMAGE_H = 1414, 1000
QR_URL = "https://cert.example.edu/validar/CERT-2026-FP0001"

BODY = (
    "participou da Semana Acadêmica de Tecnologia, promovida pelo Curso de "
    "Sistemas de Informação, realizada de 10 a 12 de junho de 2026, com carga "
    "horária total de 12 horas.\n"
    "A atividade contou com palestras, oficinas práticas e mesa-redonda sobre "
    "inteligência artificial aplicada à educação."
)

PARTICIPANT = ParticipantRegistryRecord(
    nome="Maria Aparecida da Conceição dos Santos Oliveira",
    email="",
    curso="Sistemas de Informação",
    livro=0,
    folha=0,
    linha=0,
    evento="Semana Acadêmica de Tecnologia",
    validation_code="CERT-2026-FP0001",
    texto_certificado=BODY,
    certificate_text=BODY,
    data_emissao="27 de abril de 2026",
    certificate_type="Ouvinte",
)


def _png_bytes(w: int, h: int, color: str = "white") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (w, h), color).save(buffer, "PNG")
    return buffer.getvalue()


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _text(key: str, **overrides) -> dict:
    element = {
        "type": "text",
        "key": key,
        "x": IMAGE_W // 2,
        "y": 100,
        "fontSize": 32,
        "fontFamily": "Times New Roman",
        "color": "#000000",
        "align": "center",
        "bold": False,
        "italic": False,
    }
    element.update(overrides)
    return element


def legacy_layouts() -> dict[str, dict]:
    """Layouts without text-box sizes, as every pre-existing template has."""
    mixed = {
        "image_width": IMAGE_W,
        "image_height": IMAGE_H,
        "elements": [
            _text("static", y=80, fontSize=48, bold=True, staticText="CERTIFICADO"),
            _text("static", y=170, x=90, align="left", staticText="Linha um\nLinha dois"),
            # Long name, large font: exercises the shrink-to-fit + wrap path.
            _text("name", y=260, fontSize=72, bold=True),
            _text("name", y=380, x=1300, fontSize=40, align="right"),
            # Body with the legacy maxWidth hint still honoured by the renderer.
            _text("texto_certificado", y=450, x=90, fontSize=26, align="left", maxWidth=700),
            _text("certificate_text", y=450, x=1324, fontSize=22, align="right"),
            _text("event", y=760, x=90, fontSize=28, align="left"),
            _text("course", y=800, x=1324, fontSize=28, align="right"),
            _text("issue_line", y=850, fontSize=24),
            _text("signatory_name", y=890, fontSize=22),
            _text("signatory_title", y=915, fontSize=20),
            _text("validation_code", y=960, fontSize=18, color="#444444"),
            _text("certificate_type", y=40, x=1324, fontSize=20, align="right"),
            _text("unknown_key", y=40, x=90, fontSize=20, align="left"),
            {
                "type": "image",
                "key": "image",
                "x": 1200,
                "y": 60,
                "width": 120,
                "height": 90,
                "opacity": 0.5,
                "src": _data_url(_png_bytes(40, 30, "blue")),
            },
            {"type": "qr", "key": "qr", "x": 1200, "y": 820, "width": 140, "height": 140},
            # QR saved by the editor round-trip: type text + key qr, no size.
            {"type": "text", "key": "qr", "x": 60, "y": 820},
        ],
    }
    return {"default": _default_layout(IMAGE_W, IMAGE_H), "mixed": mixed}


def record_draw_calls(monkeypatch, layout: dict, output_dir: Path) -> dict:
    """Compose a certificate and return every draw call it issued, in order."""
    calls: list[dict] = []

    def recording_text(self, xy, text, fill=None, font=None, *args, **kwargs):
        calls.append(
            {
                "op": "text",
                "xy": [int(round(v)) for v in xy],
                "text": text,
                "font": Path(font.path).name,
                "size": font.size,
                "fill": fill,
            }
        )
        return _ORIGINAL_TEXT(self, xy, text, fill, font, *args, **kwargs)

    def recording_composite(self, im, dest=(0, 0), source=(0, 0)):
        calls.append({"op": "composite", "dest": list(dest), "size": list(im.size)})
        return _ORIGINAL_COMPOSITE(self, im, dest, source)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording_text)
    monkeypatch.setattr(Image.Image, "alpha_composite", recording_composite)

    generator = CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=output_dir,
            institution_name="Faculdade Exemplo",
            issue_location="São Paulo",
            signatory_name="Helena Martins",
            signatory_title="Secretária Acadêmica",
        )
    )
    image = generator._compose_visual_image(
        PARTICIPANT,
        layout,
        qr_url=QR_URL,
        background_bytes=_png_bytes(IMAGE_W, IMAGE_H),
    )
    return {"image_size": list(image.size), "calls": calls}


def test_legacy_layouts_render_exactly_as_before(monkeypatch, tmp_path):
    actual = {
        name: record_draw_calls(monkeypatch, layout, tmp_path)
        for name, layout in legacy_layouts().items()
    }

    if os.environ.get("CERT_FINGERPRINT_WRITE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(
            json.dumps(actual, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        pytest.skip("fixture regenerated")

    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for name in expected:
        assert actual[name]["image_size"] == expected[name]["image_size"], name
        assert actual[name]["calls"] == expected[name]["calls"], (
            f"layout '{name}' no longer renders as before; every legacy template "
            "must produce the same PDF. Regenerate only if the change is intended."
        )
    assert set(actual) == set(expected)


def test_fingerprint_covers_every_text_element():
    """Sanity: the fixture is not trivially empty."""
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for name, layout in legacy_layouts().items():
        text_elements = [el for el in layout["elements"] if el.get("type", "text") == "text"]
        text_calls = [c for c in expected[name]["calls"] if c["op"] == "text"]
        # Body, static and name elements draw one call per line, so there are at
        # least as many calls as elements (the QR-as-text element draws none).
        assert len(text_calls) >= len(text_elements) - 1, name
