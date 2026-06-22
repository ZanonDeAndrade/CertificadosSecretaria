"""Tests for F8 (ISO dates/ordering), F12 (Drive integrity), F15 (malicious
uploads), F16 (CHECK/FK constraints) and F21 (local path traversal)."""
from __future__ import annotations

import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import delete, select

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from database import engine as db_engine  # noqa: E402
from database.models import AdminUser, AuditLog, Base, Certificate  # noqa: E402
from database.repositories import (  # noqa: E402
    AdminUserRepository,
    AuditLogRepository,
    CertificateRepository,
)

PDF_BYTES = b"%PDF-1.4\nhello world\n%%EOF"


@pytest.fixture
def session(tmp_path):
    url = f"sqlite:///{(tmp_path / 't.db').as_posix()}"
    eng = db_engine.get_engine(url)
    Base.metadata.create_all(eng)
    factory = db_engine.get_session_factory(url)
    s = factory()
    try:
        yield s
    finally:
        s.close()
        db_engine.reset_engines()


def _cert(code, **over):
    base = {
        "unique_code": code,
        "participant_name": "Ana Souza",
        "event_name": "Evento",
        "issue_date": "2026-06-10",
        "status": "ativo",
    }
    base.update(over)
    return base


# ── F8: ISO dates + chronological ordering ─────────────────────────────────────


def test_dates_iso_helpers():
    from utils.dates import extenso_from_iso, parse_date, to_iso

    assert to_iso("10/06/2026") == "2026-06-10"
    assert to_iso("10 de junho de 2026") == "2026-06-10"
    assert to_iso("2026-06-10") == "2026-06-10"
    assert to_iso("não é data") is None
    assert parse_date("2026-06-10").isoformat() == "2026-06-10"
    assert extenso_from_iso("2026-06-10") == "10 de junho de 2026"
    assert extenso_from_iso("") == ""


def test_ordering_by_issue_date_is_chronological(session):
    repo = CertificateRepository(session)
    repo.insert_many(
        [
            _cert("CERT-2026-DEC", issue_date="2025-12-05"),
            _cert("CERT-2026-JAN", issue_date="2026-01-05"),
            _cert("CERT-2026-APR", issue_date="2026-04-05"),
        ]
    )
    session.commit()

    rows, _ = repo.list(order_by="issue_date", descending=True)
    order = [r["unique_code"] for r in rows]
    # Chronological DESC (real date), NOT alphabetical 'por extenso'.
    assert order == ["CERT-2026-APR", "CERT-2026-JAN", "CERT-2026-DEC"]


# ── F16: CHECK constraints + FK ON DELETE SET NULL ─────────────────────────────


def test_check_constraint_rejects_bad_status(session):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        CertificateRepository(session).insert_many([_cert("CERT-2026-BAD", status="bogus")])
    session.rollback()


def test_check_constraint_rejects_bad_storage_provider(session):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        CertificateRepository(session).insert_many(
            [_cert("CERT-2026-BADP", storage_provider="dropbox")]
        )
    session.rollback()


def test_check_constraint_rejects_bad_role(session):
    from sqlalchemy.exc import IntegrityError

    session.add(AdminUser(username="x", password_hash="h", role="superhacker"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_fk_set_null_preserves_certificate_and_audit_on_user_delete(session):
    uid = AdminUserRepository(session).create("secretaria", "hash")
    CertificateRepository(session).insert_many([_cert("CERT-2026-FK01", issued_by=uid)])
    AuditLogRepository(session).insert(action="generate", actor_id=uid, actor_username="secretaria")
    session.commit()

    # Delete the user → FK ON DELETE SET NULL keeps the rows, clears the link.
    session.execute(delete(AdminUser).where(AdminUser.id == uid))
    session.commit()

    cert = session.execute(
        select(Certificate).where(Certificate.unique_code == "CERT-2026-FK01")
    ).scalar_one()
    assert cert is not None and cert.issued_by is None  # history preserved

    audit = session.execute(select(AuditLog)).scalars().all()
    assert len(audit) == 1
    assert audit[0].actor_id is None
    assert audit[0].actor_username == "secretaria"  # textual record kept


# ── F12: Drive/file integrity ──────────────────────────────────────────────────


def _local_storage(tmp_path):
    from storage_service.local import LocalStorage

    return LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)


def _point_storage(monkeypatch, tmp_path):
    """Point the shared local-storage paths at ``tmp_path`` (the download
    dispatcher builds a default LocalStorage())."""
    from database import db

    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")


def test_download_verifies_size_and_checksum(tmp_path, monkeypatch):
    from storage_service import StorageIntegrityError, download_certificate
    from storage_service.base import sha256_hex

    _point_storage(monkeypatch, tmp_path)
    storage = _local_storage(tmp_path)
    stored = storage.save(PDF_BYTES, filename="ok.pdf")
    row = {
        "pdf_path": stored.pdf_path,
        "file_size": len(PDF_BYTES),
        "checksum_sha256": sha256_hex(PDF_BYTES),
        "mime_type": "application/pdf",
    }
    # Healthy file verifies fine.
    assert download_certificate(row, verify=True).content == PDF_BYTES

    # Wrong checksum → blocked.
    with pytest.raises(StorageIntegrityError):
        download_certificate({**row, "checksum_sha256": "deadbeef"}, verify=True)
    # Wrong size → blocked.
    with pytest.raises(StorageIntegrityError):
        download_certificate({**row, "file_size": 999999}, verify=True)


def test_download_rejects_non_pdf_mime(tmp_path, monkeypatch):
    from storage_service import StorageIntegrityError, download_certificate
    from storage_service.base import sha256_hex

    _point_storage(monkeypatch, tmp_path)
    storage = _local_storage(tmp_path)
    junk = b"<html>not a pdf</html>"
    stored = storage.save(junk, filename="x.pdf")
    with pytest.raises(StorageIntegrityError):
        download_certificate(
            {"pdf_path": stored.pdf_path, "file_size": len(junk),
             "checksum_sha256": sha256_hex(junk)},
            verify=True,
        )


def test_periodic_integrity_check_blocks_tampered_file(tmp_path, monkeypatch):
    from database import db
    from services.integrity import run_integrity_check
    from storage_service.base import sha256_hex

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "c.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    db.init_db()

    storage = _local_storage(tmp_path)
    stored = storage.save(PDF_BYTES, filename="Ana_CERT-2026-INT01.pdf")
    db.insert_certificates(
        [
            _cert(
                "CERT-2026-INT01",
                storage_provider="local",
                pdf_path=stored.pdf_path,
                file_size=len(PDF_BYTES),
                checksum_sha256=sha256_hex(PDF_BYTES),
            )
        ]
    )

    # Tamper the stored file on disk.
    (tmp_path / stored.pdf_path).write_bytes(b"%PDF-1.4 tampered")

    report = run_integrity_check()
    assert report["blocked"] == 1
    assert db.get_by_code("CERT-2026-INT01")["integrity_blocked"] == 1


# ── F15: malicious spreadsheet uploads ─────────────────────────────────────────


def _xlsx_bytes(rows: list[dict]) -> bytes:
    import pandas as pd

    buf = BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def test_enforce_xlsx_rejects_non_zip():
    from services.spreadsheet import SpreadsheetError, enforce_xlsx_limits

    with pytest.raises(SpreadsheetError):
        enforce_xlsx_limits(b"definitely not a zip file")


def test_enforce_xlsx_rejects_non_office_zip():
    from services.spreadsheet import SpreadsheetError, enforce_xlsx_limits

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("random.txt", "hello")
    with pytest.raises(SpreadsheetError):
        enforce_xlsx_limits(buf.getvalue())


def test_enforce_xlsx_rejects_decompression_bomb():
    from services.spreadsheet import SpreadsheetError, enforce_xlsx_limits

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<x/>")
        zf.writestr("xl/worksheets/sheet1.xml", "A" * (4 * 1024 * 1024))  # huge ratio
    with pytest.raises(SpreadsheetError):
        enforce_xlsx_limits(buf.getvalue())


def test_enforce_xlsx_row_column_cell_limits():
    from services.spreadsheet import SpreadsheetError, enforce_xlsx_limits

    data = _xlsx_bytes([{"a": 1, "b": 2, "c": 3}, {"a": 4, "b": 5, "c": 6}])
    # Too many columns.
    with pytest.raises(SpreadsheetError):
        enforce_xlsx_limits(data, max_cols=2)
    # Too many rows.
    with pytest.raises(SpreadsheetError):
        enforce_xlsx_limits(data, max_rows=1)
    # Oversized cell.
    big = _xlsx_bytes([{"a": "x" * 50}])
    with pytest.raises(SpreadsheetError):
        enforce_xlsx_limits(big, max_cell_len=10)
    # A small, well-formed file passes.
    enforce_xlsx_limits(data, max_rows=10, max_cols=10, max_cell_len=100)


# ── F15: malicious template images ─────────────────────────────────────────────


def _png_bytes(w: int, h: int) -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


def test_image_validation_rejects_oversized_dimensions():
    from services.template_service import TemplateError, _validate_image

    with pytest.raises(TemplateError):
        _validate_image(_png_bytes(13000, 2))  # exceeds MAX_IMAGE_DIMENSION


def test_image_validation_rejects_pixel_bomb(monkeypatch):
    from services import template_service
    from services.template_service import TemplateError, _validate_image

    monkeypatch.setattr(template_service, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(TemplateError):
        _validate_image(_png_bytes(100, 100))  # 10_000 px > 1000


def test_image_validation_rejects_corrupt_png():
    from services.template_service import TemplateError, _validate_image

    corrupt = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40  # valid magic, broken body
    with pytest.raises(TemplateError):
        _validate_image(corrupt)


def test_layout_limits_reject_too_many_elements_and_data_urls():
    from services.template_service import TemplateError, _enforce_layout_limits

    with pytest.raises(TemplateError):
        _enforce_layout_limits({"elements": [{"type": "text"} for _ in range(201)]})

    huge = "data:image/png;base64," + "A" * (16 * 1024 * 1024)
    with pytest.raises(TemplateError):
        _enforce_layout_limits({"background": huge, "elements": []})


# ── Drive×DB reconciliation index (no PII) + metrics ───────────────────────────


def test_drive_file_index_maps_fileid_to_code_only(session):
    repo = CertificateRepository(session)
    repo.insert_many(
        [
            _cert("CERT-2026-DRV1", drive_file_id="drv-1"),
            _cert("CERT-2026-LOCAL", pdf_path="pdfs/x.pdf"),  # no drive_file_id
        ]
    )
    session.commit()
    index = repo.drive_file_index()
    # Only Drive-backed rows; values are verifier codes (never names/documents).
    assert index == {"drv-1": "CERT-2026-DRV1"}


def test_metrics_counters():
    import observability

    observability.metrics.reset()
    observability.metrics.increment(observability.CERTS_GENERATED, 2)
    observability.metrics.increment(observability.CERT_DOWNLOADS)
    snap = observability.metrics.snapshot()
    assert snap[observability.CERTS_GENERATED] == 2
    assert snap[observability.CERT_DOWNLOADS] == 1


# ── F21: local path traversal ──────────────────────────────────────────────────


def test_local_storage_rejects_absolute_and_traversal(tmp_path):
    from storage_service import StorageError

    storage = _local_storage(tmp_path)
    (tmp_path / "secret.txt").write_text("top secret")

    with pytest.raises(StorageError):
        storage.download({"pdf_path": "../secret.txt"})
    with pytest.raises(StorageError):
        storage.download({"pdf_path": str((tmp_path / "secret.txt").resolve())})
    # delete is equally confined.
    with pytest.raises(StorageError):
        storage.delete({"pdf_path": "../secret.txt"})
    assert (tmp_path / "secret.txt").exists()  # never touched
