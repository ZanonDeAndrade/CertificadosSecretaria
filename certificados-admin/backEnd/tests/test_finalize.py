"""Tests for the finalization pass: date utils, signatory config, migration."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.dates import format_extenso, normalize_date, normalize_date_text


# ── Dates (pt-BR, accented months) ────────────────────────────────────────────


def test_format_extenso_uses_accented_month():
    assert format_extenso(date(2026, 3, 24)) == "24 de março de 2026"


def test_normalize_date_numeric_formats():
    assert normalize_date("24/03/2026") == "24 de março de 2026"
    assert normalize_date("24-03-2026") == "24 de março de 2026"
    assert normalize_date("2026-03-24") == "24 de março de 2026"


def test_normalize_date_interval():
    assert normalize_date("20 a 25/10/2025") == "20 a 25 de outubro de 2025"


def test_normalize_date_passthrough_extenso():
    assert normalize_date("24 de março de 2026") == "24 de março de 2026"


def test_normalize_date_invalid_returns_none():
    assert normalize_date("32/13/2026") is None
    assert normalize_date("") is None
    assert normalize_date("não é data") is None


def test_normalize_date_text_is_lenient():
    assert normalize_date_text("24/03/2026") == "24 de março de 2026"
    assert normalize_date_text("texto livre") == "texto livre"  # not rejected


# ── Signatory/location come from config (no hardcoding) ───────────────────────


def _generator(tmp_path, **signature):
    from services.generator import CertificateGenerator, CertificateGeneratorConfig

    return CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=tmp_path / "pdfs",
            **signature,
        )
    )


def _record(code="CERT-2026-CFG001"):
    from models import ParticipantRegistryRecord

    return ParticipantRegistryRecord(
        nome="Ana Souza",
        email="",
        curso="Direito",
        livro=0,
        folha=0,
        linha=0,
        validation_code=code,
        texto_certificado="participou do evento de teste.",
        certificate_text="participou do evento de teste.",
        data_emissao="10 de junho de 2026",
    )


def test_generator_renders_with_configured_signatory(tmp_path):
    gen = _generator(
        tmp_path,
        issue_location="Cidade Exemplo",
        signatory_name="Fulana de Tal",
        signatory_title="Secretária Acadêmica",
    )
    pdf = gen.render_pdf_bytes_default(_record())
    assert pdf[:4] == b"%PDF"


def test_generator_renders_without_signatory(tmp_path):
    # Empty config (no hardcoded fallback) must still produce a valid PDF.
    gen = _generator(tmp_path)
    pdf = gen.render_pdf_bytes_default(_record())
    assert pdf[:4] == b"%PDF"


# ── Migration to Drive (dry-run) ──────────────────────────────────────────────


def _point_db(monkeypatch, tmp_path):
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "c.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    db.init_db()
    return db


def _seed(db, code, pdf_path, *, drive_file_id=None):
    db.insert_certificates(
        [
            {
                "unique_code": code,
                "participant_name": "P " + code,
                "event_name": "Evento",
                "course_name": "Direito",
                "issue_date": "10 de junho de 2026",
                "pdf_path": pdf_path,
                "storage_provider": "google_drive" if drive_file_id else "local",
                "drive_file_id": drive_file_id,
            }
        ]
    )


def test_migration_dry_run_reports_without_changing_db(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir(parents=True, exist_ok=True)
    (pdfs / "a.pdf").write_bytes(b"%PDF-1.4 a")

    _seed(db, "CERT-2026-LOC001", "pdfs/a.pdf")          # exists → would migrate
    _seed(db, "CERT-2026-LOC002", "pdfs/missing.pdf")    # missing → not_found
    _seed(db, "CERT-2026-DRV001", "pdfs/c.pdf", drive_file_id="already")  # excluded

    import migrate_to_drive

    report = migrate_to_drive.run_migration(dry_run=True)

    assert report["total"] == 2  # the drive one is not pending
    assert report["migrated"] == 1
    assert report["not_found"] == 1
    assert report["failed"] == 0

    # Dry-run must not have written drive metadata.
    assert (db.get_by_code("CERT-2026-LOC001").get("drive_file_id") or "") == ""
    # The already-migrated one is untouched.
    assert db.get_by_code("CERT-2026-DRV001")["drive_file_id"] == "already"
