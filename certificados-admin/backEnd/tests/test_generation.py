"""Tests for structured generation: idempotency, metadata, and QR code."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from services.certificate_service import CertificateBatchConfig, CertificateBatchService
from services.spreadsheet import SpreadsheetRow
from storage_service.local import LocalStorage

PDF_BYTES = b"%PDF-1.4\nfake\n%%EOF"


class FakeGenerator:
    def __init__(self):
        self.qr_urls: list[str] = []

    def render_pdf_bytes_default(self, record, template_path=None, qr_url=None):
        self.qr_urls.append(qr_url)
        return PDF_BYTES

    def render_pdf_bytes_visual(self, record, layout, qr_url=None):
        self.qr_urls.append(qr_url)
        return PDF_BYTES


def _service(tmp_path, generator=None):
    config = CertificateBatchConfig(
        template_path=tmp_path / "t.png",
        regular_font_path=tmp_path / "r.ttf",
        bold_font_path=tmp_path / "b.ttf",
        output_dir=tmp_path / "pdfs",
    )
    storage = LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)
    return CertificateBatchService(config, storage=storage, generator=generator or FakeGenerator())


def _point_db(monkeypatch, tmp_path):
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "c.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    db.init_db()
    return db


def _row(nome="Ana Souza", evento="Semana Jurídica"):
    return SpreadsheetRow(
        row_number=2,
        nome=nome,
        curso="Direito",
        evento=evento,
        carga_horaria=40,
        data_emissao="10 de junho de 2026",
        email="ana@x.com",
        documento="123",
    )


def test_generation_persists_structured_metadata(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path)

    summary = service.generate_certificates([_row()], issued_by=7)
    assert len(summary.generated) == 1
    code = summary.generated[0]["code"]

    row = db.get_by_code(code)
    assert row["course_name"] == "Direito"
    assert row["event_name"] == "Semana Jurídica"  # evento, NOT the course
    assert row["workload_hours"] == 40
    assert row["participant_email"] == "ana@x.com"
    assert row["participant_document"] == "123"
    assert row["issued_by"] == 7
    assert row["business_key"]
    assert row["storage_provider"] == "local"


def test_generation_is_idempotent(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path)

    first = service.generate_certificates([_row()])
    assert len(first.generated) == 1
    assert len(first.duplicates) == 0
    code = first.generated[0]["code"]

    # Re-submitting the same row generates nothing new and reports the duplicate.
    second = service.generate_certificates([_row()])
    assert len(second.generated) == 0
    assert len(second.duplicates) == 1
    assert second.duplicates[0]["existing_code"] == code

    # Only one row in the DB.
    _, total = db.list_certificates()
    assert total == 1


def test_qr_url_passed_to_generator(monkeypatch, tmp_path):
    _point_db(monkeypatch, tmp_path)
    monkeypatch.setenv("PUBLIC_VALIDATION_BASE_URL", "https://cert.example.edu")
    gen = FakeGenerator()
    service = _service(tmp_path, generator=gen)

    summary = service.generate_certificates([_row()])
    code = summary.generated[0]["code"]
    assert gen.qr_urls == [f"https://cert.example.edu/validar/{code}"]


def test_make_qr_image_is_not_blank():
    from services.generator import make_qr_image

    img = make_qr_image("https://cert.example.edu/validar/CERT-2026-AB1234", 200)
    assert img.size == (200, 200)
    colors = {px[:3] for px in img.getdata()}
    # Must contain both dark and light modules.
    assert any(sum(c) < 200 for c in colors)  # dark present
    assert any(sum(c) > 600 for c in colors)  # light present


def test_real_generator_embeds_qr(tmp_path, monkeypatch):
    """Integration: the real generator produces a valid PDF with a QR url."""
    _point_db(monkeypatch, tmp_path)
    from services.generator import CertificateGenerator, CertificateGeneratorConfig

    be = _BACKEND_DIR
    gen = CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=be / "templates" / "certificado_base.png",
            regular_font_path=be / "fonts" / "times.ttf",
            bold_font_path=be / "fonts" / "timesbd.ttf",
            output_dir=tmp_path / "pdfs",
        )
    )
    record = _row()
    from services.certificate_service import _row_to_record

    rec = _row_to_record(record, "CERT-2026-QR0001")
    with_qr = gen.render_pdf_bytes_default(
        rec, qr_url="https://cert.example.edu/validar/CERT-2026-QR0001"
    )
    without_qr = gen.render_pdf_bytes_default(rec, qr_url=None)
    assert with_qr[:4] == b"%PDF"
    # The QR adds visible content → the PDF is larger than without it.
    assert len(with_qr) > len(without_qr)
