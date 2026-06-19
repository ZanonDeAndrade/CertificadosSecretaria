"""Tests for the storage abstraction (storage_service) and its integration
with certificate generation and persistence.

Covers:
  - LocalStorage save/download + metadata (size, checksum, provider).
  - A fake GoogleDriveStorage exercising the same interface.
  - download_certificate dispatcher: Drive when drive_file_id is present,
    local fallback for legacy certificates.
  - The public download never exposes a Drive link/id.
  - get_storage() factory honours STORAGE_PROVIDER.
  - SQLite migration adds the new columns without losing data.
  - End-to-end generation via LocalStorage persists storage metadata.
"""
from __future__ import annotations

import dataclasses
import sqlite3
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

# Ensure both backEnd/ and the repo root are importable.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import storage_service
from storage_service import RetrievedFile, download_certificate, get_storage
from storage_service.base import CertificateStorage, StoredFile, sha256_hex
from storage_service.local import LocalStorage

PDF_BYTES = b"%PDF-1.4\nfake-certificate-content\n%%EOF"


# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeDriveStorage(CertificateStorage):
    """In-memory stand-in for GoogleDriveStorage (no network/credentials)."""

    provider = "google_drive"
    _FOLDER = "fake-folder-id"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self._counter = 0

    def save(self, content, *, filename, mime_type="application/pdf") -> StoredFile:
        self._counter += 1
        file_id = f"drive-{self._counter}"
        self.files[file_id] = content
        return StoredFile(
            storage_provider=self.provider,
            original_filename=filename,
            mime_type=mime_type,
            file_size=len(content),
            checksum_sha256=sha256_hex(content),
            created_at="2026-01-01T00:00:00+00:00",
            drive_file_id=file_id,
            drive_folder_id=self._FOLDER,
            pdf_path="",
        )

    def download(self, cert_row) -> bytes:
        file_id = cert_row.get("drive_file_id")
        if file_id not in self.files:
            raise FileNotFoundError(file_id)
        return self.files[file_id]


class FakeGenerator:
    """Generator stub that returns fixed bytes (no Pillow/templates needed)."""

    def render_pdf_bytes_default(self, record, template_path=None) -> bytes:
        return PDF_BYTES

    def render_pdf_bytes_visual(self, record, layout) -> bytes:
        return PDF_BYTES


# ── LocalStorage ────────────────────────────────────────────────────────────


def test_local_storage_save_writes_file_and_metadata(tmp_path):
    storage = LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)
    stored = storage.save(PDF_BYTES, filename="Joao_CERT-2026-AB1234.pdf")

    assert stored.storage_provider == "local"
    assert stored.pdf_path == "pdfs/Joao_CERT-2026-AB1234.pdf"
    assert stored.drive_file_id is None
    assert stored.file_size == len(PDF_BYTES)
    assert stored.checksum_sha256 == sha256_hex(PDF_BYTES)
    assert (tmp_path / "pdfs" / "Joao_CERT-2026-AB1234.pdf").read_bytes() == PDF_BYTES


def test_local_storage_download_roundtrip(tmp_path):
    storage = LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)
    stored = storage.save(PDF_BYTES, filename="x.pdf")
    assert storage.download({"pdf_path": stored.pdf_path}) == PDF_BYTES


def test_local_storage_download_missing_raises(tmp_path):
    storage = LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        storage.download({"pdf_path": "pdfs/nope.pdf"})


# ── Fake Drive via the shared interface ───────────────────────────────────────


def test_fake_drive_roundtrip_and_metadata():
    storage = FakeDriveStorage()
    stored = storage.save(PDF_BYTES, filename="cert.pdf")
    assert stored.storage_provider == "google_drive"
    assert stored.drive_file_id
    assert stored.pdf_path == ""
    assert storage.download({"drive_file_id": stored.drive_file_id}) == PDF_BYTES


# ── download_certificate dispatcher ───────────────────────────────────────────


def test_dispatcher_uses_drive_when_file_id_present(monkeypatch):
    fake = FakeDriveStorage()
    stored = fake.save(b"DRIVE-BYTES", filename="d.pdf")
    # Patch the symbol the dispatcher resolves at call time.
    monkeypatch.setattr(storage_service, "GoogleDriveStorage", lambda *a, **k: fake)

    retrieved = download_certificate(
        {
            "storage_provider": "google_drive",
            "drive_file_id": stored.drive_file_id,
            "original_filename": "d.pdf",
        }
    )
    assert isinstance(retrieved, RetrievedFile)
    assert retrieved.content == b"DRIVE-BYTES"
    assert retrieved.filename == "d.pdf"


def test_dispatcher_falls_back_to_local_when_no_drive_id(monkeypatch, tmp_path):
    # Point the shared local paths at a temp dir and drop a legacy file there.
    from database import db

    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    (tmp_path / "pdfs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pdfs" / "old.pdf").write_bytes(b"LEGACY-LOCAL")

    retrieved = download_certificate(
        {"storage_provider": "local", "pdf_path": "pdfs/old.pdf", "unique_code": "CERT-X"}
    )
    assert retrieved.content == b"LEGACY-LOCAL"
    assert retrieved.filename == "CERT-X.pdf"  # falls back to code-based name


def test_retrieved_file_never_exposes_drive_link():
    field_names = {f.name for f in dataclasses.fields(RetrievedFile)}
    assert field_names == {"content", "filename", "mime_type"}
    # No attribute could carry a provider URL/id.
    assert not any("url" in n or "drive" in n or "id" in n for n in field_names)


# ── Factory ───────────────────────────────────────────────────────────────────


def test_get_storage_defaults_to_local(monkeypatch):
    monkeypatch.delenv("STORAGE_PROVIDER", raising=False)
    storage_service.reset_storage_cache()
    try:
        assert isinstance(get_storage(), LocalStorage)
    finally:
        storage_service.reset_storage_cache()


def test_get_storage_returns_google_drive_when_configured(monkeypatch):
    from storage_service.google_drive import GoogleDriveStorage

    monkeypatch.setenv("STORAGE_PROVIDER", "google_drive")
    monkeypatch.setenv("GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID", "folder-123")
    storage_service.reset_storage_cache()
    try:
        storage = get_storage()
        assert isinstance(storage, GoogleDriveStorage)
        assert storage.provider == "google_drive"
    finally:
        storage_service.reset_storage_cache()


# ── DB migration + metadata persistence ───────────────────────────────────────


def _point_db_at(monkeypatch, tmp_path):
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "certificates.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    return db


def test_migration_adds_columns_without_losing_data(monkeypatch, tmp_path):
    db = _point_db_at(monkeypatch, tmp_path)

    # Create an OLD-style table (pre-storage-metadata) with one row.
    conn = sqlite3.connect(str(tmp_path / "certificates.db"))
    conn.executescript(
        """
        CREATE TABLE certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unique_code TEXT NOT NULL UNIQUE,
            participant_name TEXT NOT NULL,
            event_name TEXT NOT NULL,
            issue_date TEXT NOT NULL,
            pdf_path TEXT NOT NULL,
            certificate_text TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO certificates (unique_code, participant_name, event_name, issue_date, pdf_path)
        VALUES ('CERT-2025-OLD001', 'Maria Antiga', 'Direito', '01 de janeiro de 2025', 'pdfs/maria.pdf');
        """
    )
    conn.commit()
    conn.close()

    db.init_db()  # runs migration

    row = db.get_by_code("CERT-2025-OLD001")
    assert row is not None
    assert row["participant_name"] == "Maria Antiga"  # data preserved
    assert row["storage_provider"] == "local"  # new column, default applied
    assert row["status"] == "ativo"
    assert "drive_file_id" in row.keys()


def test_insert_persists_drive_metadata(monkeypatch, tmp_path):
    db = _point_db_at(monkeypatch, tmp_path)
    db.init_db()

    db.insert_certificates(
        [
            {
                "unique_code": "CERT-2026-DRV001",
                "participant_name": "Ana Drive",
                "event_name": "Pedagogia",
                "issue_date": "10 de junho de 2026",
                "storage_provider": "google_drive",
                "drive_file_id": "drive-xyz",
                "drive_folder_id": "folder-123",
                "original_filename": "Ana_Drive_CERT-2026-DRV001.pdf",
                "mime_type": "application/pdf",
                "file_size": 4242,
                "checksum_sha256": "abc123",
            }
        ]
    )

    row = db.get_by_code("CERT-2026-DRV001")
    assert row["storage_provider"] == "google_drive"
    assert row["drive_file_id"] == "drive-xyz"
    assert row["drive_folder_id"] == "folder-123"
    assert row["file_size"] == 4242
    assert row["checksum_sha256"] == "abc123"
    assert (row["pdf_path"] or "") == ""  # nothing stored locally


# ── End-to-end generation via LocalStorage ────────────────────────────────────


def test_generate_from_excel_saves_via_local_storage(monkeypatch, tmp_path):
    db = _point_db_at(monkeypatch, tmp_path)
    db.init_db()

    from models import CertificateFormData
    from services.certificate_service import (
        CertificateBatchConfig,
        CertificateBatchService,
    )

    # Tiny spreadsheet with the expected columns.
    xlsx = tmp_path / "participantes.xlsx"
    pd.DataFrame(
        {"nome": ["Joao Teste"], "email": ["joao@x.com"], "curso": ["Direito"]}
    ).to_excel(xlsx, index=False)

    storage = LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)
    config = CertificateBatchConfig(
        template_path=tmp_path / "template.png",  # unused (fake generator)
        regular_font_path=tmp_path / "r.ttf",
        bold_font_path=tmp_path / "b.ttf",
        output_dir=tmp_path / "pdfs",
    )
    service = CertificateBatchService(config, storage=storage, generator=FakeGenerator())

    results = service.generate_from_excel(
        xlsx,
        CertificateFormData(texto_certificado="participou do evento.", data_emissao="10/06/2026"),
    )

    assert len(results) == 1
    result = results[0]
    code = result.validation_code
    assert code.startswith("CERT-")
    # Public file URL is code-based and exposes no provider link.
    assert result.file_url == f"/certificate-file/{code}"
    assert "drive" not in result.file_url

    # Metadata persisted.
    row = db.get_by_code(code)
    assert row["storage_provider"] == "local"
    assert row["pdf_path"] == f"pdfs/{result.pdf_path.split('/')[-1]}"
    assert row["checksum_sha256"] == sha256_hex(PDF_BYTES)
    assert row["file_size"] == len(PDF_BYTES)

    # The PDF actually landed in the temp storage and is downloadable.
    retrieved = download_certificate(dict(row))
    assert retrieved.content == PDF_BYTES
