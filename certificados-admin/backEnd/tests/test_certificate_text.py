"""Tests for the secretaria-authored certificate body text.

Covers: validation (required/length/unknown/malformed), interpolation of every
allowed variable, persistence of the RESOLVED body, faithful reissue,
idempotency that considers the text, the block when the active template has no
body element, and long-text wrapping that never leaves the certificate.
"""
from __future__ import annotations

import base64
import sys
from io import BytesIO
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from models import ParticipantRegistryRecord  # noqa: E402
from services import template_service  # noqa: E402
from services.certificate_service import (  # noqa: E402
    CertificateBatchConfig,
    CertificateBatchService,
    build_row_variables,
)
from services.certificate_text import (  # noqa: E402
    CertificateTextError,
    render_certificate_body,
    validate_body_template,
)
from services.spreadsheet import SpreadsheetRow  # noqa: E402
from storage_service.base import (  # noqa: E402
    CertificateStorage,
    StoredFile,
    sha256_hex,
    utc_now_iso,
)

PDF_BYTES = b"%PDF-1.4\nbody\n%%EOF"


# ── Fakes ─────────────────────────────────────────────────────────────────────


class RecordingGenerator:
    def __init__(self) -> None:
        self.records: list[ParticipantRegistryRecord] = []

    def render_pdf_bytes_default(self, record, template_path=None, qr_url=None):
        return PDF_BYTES

    def render_pdf_bytes_visual(self, record, layout, *, qr_url=None, background_bytes=None):
        self.records.append(record)
        return PDF_BYTES


class MemoryStorage(CertificateStorage):
    provider = "google_drive"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self._n = 0

    def save(self, content, *, filename, mime_type="application/pdf") -> StoredFile:
        self._n += 1
        file_id = f"drive-{self._n}"
        self.files[file_id] = content
        return StoredFile(
            storage_provider=self.provider,
            original_filename=filename,
            mime_type=mime_type,
            file_size=len(content),
            checksum_sha256=sha256_hex(content),
            created_at=utc_now_iso(),
            drive_file_id=file_id,
            drive_folder_id="folder",
            pdf_path="",
        )

    def download(self, cert_row) -> bytes:  # pragma: no cover
        return self.files[cert_row["drive_file_id"]]

    def delete(self, cert_row) -> None:
        self.files.pop((cert_row.get("drive_file_id") or "").strip(), None)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _point_db(monkeypatch, tmp_path):
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "c.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    db.init_db()
    return db


def _service(tmp_path, storage=None, generator=None):
    config = CertificateBatchConfig(
        template_path=tmp_path / "t.png",
        regular_font_path=tmp_path / "r.ttf",
        bold_font_path=tmp_path / "b.ttf",
        output_dir=tmp_path / "pdfs",
    )
    return CertificateBatchService(
        config, storage=storage or MemoryStorage(), generator=generator or RecordingGenerator()
    )


def _seed_default_template() -> None:
    # The default seeded template now includes a texto_certificado element.
    template_service.ensure_default_version(Path("missing-on-purpose.png"))


def _row(nome="Ana Souza"):
    return SpreadsheetRow(
        row_number=2,
        nome=nome,
        curso="Direito",
        evento="Semana Jurídica",
        carga_horaria=40,
        data_emissao="10 de junho de 2026",
        email="ana@x.com",
        documento="123",
        data_inicio="1 de junho de 2026",
        data_fim="3 de junho de 2026",
    )


# ── Validation ─────────────────────────────────────────────────────────────────


def test_body_text_is_required():
    for empty in ("", "   ", "  \n  "):
        with pytest.raises(CertificateTextError):
            validate_body_template(empty)


def test_only_outer_whitespace_is_trimmed():
    assert validate_body_template("  olá\nmundo  ") == "olá\nmundo"


def test_body_text_max_length():
    with pytest.raises(CertificateTextError):
        validate_body_template("a" * 3001)
    assert validate_body_template("a" * 3000)  # boundary OK


def test_unknown_variable_is_rejected():
    with pytest.raises(CertificateTextError) as exc:
        validate_body_template("participou de {{palestrante}}.")
    assert "palestrante" in str(exc.value)


def test_malformed_braces_are_rejected():
    for bad in ("{{nome", "{nome}", "olá {{}}", "}}x{{", "{{ 1nome }}"):
        with pytest.raises(CertificateTextError):
            validate_body_template(bad)


def test_allowed_variables_are_interpolated():
    template = "{{nome}} fez {{carga_horaria}} horas"
    validate_body_template(template)  # must pass validation
    out = render_certificate_body(template, build_row_variables(_row()))
    assert "{{" not in out and "}}" not in out
    assert out == "Ana Souza fez 40 horas"


def test_non_spreadsheet_variables_are_rejected():
    # Only name + workload are columns now; the rest is written literally.
    for bad in ("{{curso}}", "{{evento}}", "{{data_inicio}}", "{{data_emissao}}"):
        with pytest.raises(CertificateTextError):
            validate_body_template(f"texto {bad}")


def test_carga_horaria_is_number_only():
    out = render_certificate_body("{{carga_horaria}} horas", build_row_variables(_row()))
    assert out == "40 horas"


# ── Persistence + faithful reissue ────────────────────────────────────────────


def test_persisted_body_is_the_resolved_text(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    _seed_default_template()
    service = _service(tmp_path)

    summary = service.generate_certificates(
        [_row()], body_template="corpo de {{nome}} com {{carga_horaria}} horas."
    )
    cert = db.get_by_code(summary.generated[0]["code"])
    assert cert["certificate_text"] == "corpo de Ana Souza com 40 horas."
    assert "{{" not in cert["certificate_text"]


def test_reissue_reproduces_original_body(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    _seed_default_template()
    gen = RecordingGenerator()
    service = _service(tmp_path, generator=gen)

    summary = service.generate_certificates([_row()], body_template="texto fiel de {{nome}}.")
    code = summary.generated[0]["code"]

    gen.records.clear()
    service.reissue_certificate(db.get_by_code(code))
    assert gen.records[-1].texto_certificado == "texto fiel de Ana Souza."


# ── Idempotency considering the text ──────────────────────────────────────────


def test_same_row_same_text_is_duplicate(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    _seed_default_template()
    service = _service(tmp_path)

    first = service.generate_certificates([_row()], body_template="texto {{nome}}")
    second = service.generate_certificates([_row()], body_template="texto {{nome}}")
    assert len(first.generated) == 1
    assert len(second.generated) == 0 and len(second.duplicates) == 1
    assert db.list_certificates()[1] == 1


def test_same_row_different_text_is_new_emission(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    _seed_default_template()
    service = _service(tmp_path)

    first = service.generate_certificates([_row()], body_template="versão A para {{nome}}")
    second = service.generate_certificates([_row()], body_template="versão B para {{nome}}")
    assert len(first.generated) == 1 and len(second.generated) == 1
    assert db.list_certificates()[1] == 2


# ── Block when the active template has no body element ─────────────────────────


def test_generation_blocked_when_template_lacks_body_element(monkeypatch, tmp_path):
    _point_db(monkeypatch, tmp_path)
    buf = BytesIO()
    from PIL import Image

    Image.new("RGB", (400, 300), "white").save(buf, "PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    version = template_service.create_version(
        name="sem-corpo",
        layout={
            "background": data_url,
            "image_width": 400,
            "image_height": 300,
            "elements": [{"type": "text", "key": "name", "x": 1, "y": 1}],
        },
    )
    template_service.activate_version(version["id"])
    service = _service(tmp_path)

    with pytest.raises(ValueError) as exc:
        service.generate_certificates([_row()], body_template="qualquer {{nome}}")
    message = str(exc.value).lower()
    assert "texto_certificado" in message or "corpo" in message


# ── Long text wraps and never leaves the certificate ──────────────────────────


def _draw():
    from PIL import Image, ImageDraw

    return ImageDraw.Draw(Image.new("RGB", (1200, 900), "white"))


def _times(size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(_BACKEND_DIR / "fonts" / "times.ttf"), size)


def test_long_body_wraps_within_width():
    from utils.text_utils import get_text_size, wrap_hard_breaks

    draw = _draw()
    font = _times(28)
    lines = wrap_hard_breaks(draw, "palavra " * 200, font, 600)
    assert len(lines) > 1
    for line in lines:
        assert get_text_size(draw, line, font)[0] <= 600  # never exceeds the width


def test_typed_line_breaks_are_respected():
    from utils.text_utils import wrap_hard_breaks

    lines = wrap_hard_breaks(_draw(), "linha um\nlinha dois", _times(24), 800)
    assert lines == ["linha um", "linha dois"]


def test_visual_generator_renders_long_body(tmp_path):
    from services.generator import CertificateGenerator, CertificateGeneratorConfig

    buf = BytesIO()
    from PIL import Image

    Image.new("RGB", (1200, 900), "white").save(buf, "PNG")

    gen = CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=tmp_path / "pdfs",
        )
    )
    record = ParticipantRegistryRecord(
        nome="Ana Souza",
        email="",
        curso="Direito",
        evento="Semana",
        livro=0,
        folha=0,
        linha=0,
        validation_code="CERT-2026-AAAAAA",
        texto_certificado="palavra muito longa de teste " * 60,
        certificate_text="palavra muito longa de teste " * 60,
    )
    layout = {
        "image_width": 1200,
        "image_height": 900,
        "elements": [
            {
                "type": "text",
                "key": "texto_certificado",
                "x": int(1200 * 0.05),
                "y": 200,
                "fontSize": 28,
                "fontFamily": "Times New Roman",
                "color": "#000000",
                "align": "left",
                "bold": False,
            }
        ],
    }
    pdf = gen.render_pdf_bytes_visual(record, layout, background_bytes=buf.getvalue())
    assert pdf[:4] == b"%PDF"
