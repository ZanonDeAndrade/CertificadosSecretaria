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

import pytest

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

    def delete(self, cert_row) -> None:
        file_id = (cert_row.get("drive_file_id") or "").strip()
        self.files.pop(file_id, None)  # idempotent


class FakeGenerator:
    """Generator stub that returns fixed bytes (no Pillow/templates needed)."""

    def render_pdf_bytes_default(self, record, template_path=None, qr_url=None) -> bytes:
        return PDF_BYTES

    def render_pdf_bytes_visual(
        self, record, layout, *, qr_url=None, background_bytes=None
    ) -> bytes:
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


def _local(tmp_path) -> LocalStorage:
    return LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)


def test_local_storage_never_overwrites_and_numbers_a_repeated_name(tmp_path):
    storage = _local(tmp_path)
    first = storage.save(b"%PDF-1.4 first", filename="Ana Lima_Evento_2026.pdf")
    second = storage.save(b"%PDF-1.4 second", filename="Ana Lima_Evento_2026.pdf")
    third = storage.save(b"%PDF-1.4 third", filename="Ana Lima_Evento_2026.pdf")

    assert first.pdf_path == "pdfs/Ana Lima_Evento_2026.pdf"
    assert second.pdf_path == "pdfs/Ana Lima_Evento_2026_2.pdf"
    assert third.pdf_path == "pdfs/Ana Lima_Evento_2026_3.pdf"
    assert second.original_filename == "Ana Lima_Evento_2026_2.pdf"
    # The first file, and therefore its recorded hash, is untouched.
    assert (tmp_path / first.pdf_path).read_bytes() == b"%PDF-1.4 first"
    assert first.checksum_sha256 == sha256_hex(b"%PDF-1.4 first")
    assert (tmp_path / second.pdf_path).read_bytes() == b"%PDF-1.4 second"
    assert (tmp_path / third.pdf_path).read_bytes() == b"%PDF-1.4 third"


def test_local_storage_steps_over_a_file_it_did_not_write(tmp_path):
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "pdfs" / "Ana_Evento_2026.pdf").write_bytes(b"%PDF-1.4 legacy")
    stored = _local(tmp_path).save(b"%PDF-1.4 new", filename="Ana_Evento_2026.pdf")
    assert stored.pdf_path == "pdfs/Ana_Evento_2026_2.pdf"
    assert (tmp_path / "pdfs" / "Ana_Evento_2026.pdf").read_bytes() == b"%PDF-1.4 legacy"


def test_simultaneous_saves_of_the_same_name_all_succeed_under_distinct_names(tmp_path):
    """Exclusive creation, not "check then write": racing emissions never share a file."""
    import threading

    storage = _local(tmp_path)
    workers = 8
    barrier = threading.Barrier(workers)
    results: list[StoredFile | BaseException | None] = [None] * workers

    def run(index: int) -> None:
        content = f"%PDF-1.4 copy {index}".encode()
        try:
            barrier.wait()
            results[index] = storage.save(content, filename="Mesmo Nome_Evento_2026.pdf")
        except BaseException as exc:  # noqa: BLE001 - reported by the assertion below
            results[index] = exc

    threads = [threading.Thread(target=run, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(isinstance(result, StoredFile) for result in results), results
    stored = [result for result in results if isinstance(result, StoredFile)]
    assert sorted(item.pdf_path for item in stored) == sorted(
        ["pdfs/Mesmo Nome_Evento_2026.pdf"]
        + [f"pdfs/Mesmo Nome_Evento_2026_{number}.pdf" for number in range(2, workers + 1)]
    )
    for index, item in enumerate(stored):
        content = f"%PDF-1.4 copy {index}".encode()
        assert (tmp_path / item.pdf_path).read_bytes() == content
        assert item.checksum_sha256 == sha256_hex(content)
    assert len(list((tmp_path / "pdfs").iterdir())) == workers


@pytest.mark.parametrize("filename", ["../fora.pdf", "sub/arquivo.pdf", "..", ".", "", "  "])
def test_local_storage_refuses_a_name_that_is_not_a_single_component(tmp_path, filename):
    from storage_service import StorageError

    with pytest.raises(StorageError):
        _local(tmp_path).save(b"%PDF-1.4", filename=filename)
    assert not (tmp_path / "fora.pdf").exists()


def test_replace_rewrites_only_the_file_the_certificate_points_at(tmp_path):
    storage = _local(tmp_path)
    mine = storage.save(b"%PDF-1.4 mine", filename="Ana_Evento_2026.pdf")
    sibling = storage.save(b"%PDF-1.4 sibling", filename="Ana_Evento_2026.pdf")

    replaced = storage.replace(
        b"%PDF-1.4 reissued", cert_row={"pdf_path": mine.pdf_path}, filename="Outro Nome.pdf"
    )

    assert replaced.pdf_path == mine.pdf_path
    assert replaced.original_filename == "Ana_Evento_2026.pdf"
    assert replaced.checksum_sha256 == sha256_hex(b"%PDF-1.4 reissued")
    assert (tmp_path / mine.pdf_path).read_bytes() == b"%PDF-1.4 reissued"
    assert (tmp_path / sibling.pdf_path).read_bytes() == b"%PDF-1.4 sibling"
    # Neither the requested name nor a temporary file is left behind.
    assert sorted(path.name for path in (tmp_path / "pdfs").iterdir()) == [
        "Ana_Evento_2026.pdf",
        "Ana_Evento_2026_2.pdf",
    ]


def test_replace_without_a_local_file_creates_a_new_exclusive_one(tmp_path):
    storage = _local(tmp_path)
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "pdfs" / "Novo_2026.pdf").write_bytes(b"%PDF-1.4 someone else's")
    stored = storage.replace(b"%PDF-1.4 new", cert_row={"pdf_path": ""}, filename="Novo_2026.pdf")
    assert stored.pdf_path == "pdfs/Novo_2026_2.pdf"
    assert (tmp_path / "pdfs" / "Novo_2026.pdf").read_bytes() == b"%PDF-1.4 someone else's"


def test_replace_refuses_a_path_outside_the_storage(tmp_path):
    from storage_service import StorageError

    for pdf_path in ("../fora.pdf", str((tmp_path.parent / "fora.pdf").resolve())):
        with pytest.raises(StorageError):
            _local(tmp_path).replace(b"%PDF-1.4", cert_row={"pdf_path": pdf_path}, filename="a.pdf")
    assert not (tmp_path.parent / "fora.pdf").exists()


# ── Google Drive: a repeated name gets _2, _3 ────────────────────────────────


class _DriveCall:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeDriveService:
    """``files().list`` / ``files().create`` over a set of names in one folder."""

    def __init__(self, names):
        self.names = set(names)
        self.created: list[str] = []
        self.queries: list[str] = []

    def files(self):
        return self

    def list(self, *, q, fields, pageSize, supportsAllDrives, includeItemsFromAllDrives):
        import re

        self.queries.append(q)
        match = re.match(r"name = '((?:[^'\\]|\\.)*)' and '(.+)' in parents and trashed = false", q)
        assert match, q
        name = match.group(1).replace("\\'", "'").replace("\\\\", "\\")
        return _DriveCall({"files": [{"id": "taken"}] if name in self.names else []})

    def create(self, *, body, media_body, fields, supportsAllDrives):
        self.created.append(body["name"])
        self.names.add(body["name"])
        return _DriveCall({"id": f"drive-{len(self.created)}"})


def test_drive_upload_takes_the_first_free_numbered_name(monkeypatch):
    from storage_service.google_drive import GoogleDriveStorage

    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_MODE", "read_write")
    service = _FakeDriveService({"Ana Lima_Evento_2026.pdf", "Ana Lima_Evento_2026_2.pdf"})
    storage = GoogleDriveStorage(folder_id="folder-id", service=service)

    stored = storage.save(PDF_BYTES, filename="Ana Lima_Evento_2026.pdf")

    assert stored.original_filename == "Ana Lima_Evento_2026_3.pdf"
    assert service.created == ["Ana Lima_Evento_2026_3.pdf"]
    assert stored.drive_file_id == "drive-1"
    assert len(service.queries) == 3
    assert all("'folder-id' in parents" in query for query in service.queries)


def test_drive_upload_escapes_quotes_in_the_name_lookup(monkeypatch):
    from storage_service.google_drive import GoogleDriveStorage

    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_MODE", "read_write")
    service = _FakeDriveService({"Ana D'Ávila_Evento_2026.pdf"})
    storage = GoogleDriveStorage(folder_id="folder-id", service=service)

    stored = storage.save(PDF_BYTES, filename="Ana D'Ávila_Evento_2026.pdf")

    assert stored.original_filename == "Ana D'Ávila_Evento_2026_2.pdf"
    assert service.queries[0].startswith("name = 'Ana D\\'Ávila_Evento_2026.pdf' and")


def test_drive_reissue_uploads_under_the_certificates_own_name_without_numbering(monkeypatch):
    from storage_service.google_drive import GoogleDriveStorage

    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_MODE", "read_write")
    # The certificate's old file still carries the name when the new one goes up.
    service = _FakeDriveService({"Ana Lima_Evento_2026.pdf"})
    storage = GoogleDriveStorage(folder_id="folder-id", service=service)

    stored = storage.replace(
        PDF_BYTES,
        cert_row={"drive_file_id": "old-file", "original_filename": "Ana Lima_Evento_2026.pdf"},
        filename="Ana Lima_Evento_2026.pdf",
    )

    assert stored.original_filename == "Ana Lima_Evento_2026.pdf"
    assert service.created == ["Ana Lima_Evento_2026.pdf"]
    assert stored.drive_file_id == "drive-1"
    assert service.queries == []


def test_drive_reissue_of_a_certificate_without_a_file_creates_a_numbered_new_one(monkeypatch):
    from storage_service.google_drive import GoogleDriveStorage

    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_MODE", "read_write")
    service = _FakeDriveService({"Ana Lima_Evento_2026.pdf"})
    storage = GoogleDriveStorage(folder_id="folder-id", service=service)

    stored = storage.replace(
        PDF_BYTES, cert_row={"drive_file_id": ""}, filename="Ana Lima_Evento_2026.pdf"
    )

    assert stored.original_filename == "Ana Lima_Evento_2026_2.pdf"
    assert service.created == ["Ana Lima_Evento_2026_2.pdf"]


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
    folders = []

    def drive_for_folder(*_args, **kwargs):
        folders.append(kwargs.get("folder_id"))
        return fake

    monkeypatch.setattr(storage_service, "GoogleDriveStorage", drive_for_folder)

    retrieved = download_certificate(
        {
            "storage_provider": "google_drive",
            "drive_file_id": stored.drive_file_id,
            "drive_folder_id": "folder-event-2026",
            "original_filename": "d.pdf",
        }
    )
    assert isinstance(retrieved, RetrievedFile)
    assert retrieved.content == b"DRIVE-BYTES"
    assert retrieved.filename == "d.pdf"
    assert folders == ["folder-event-2026"]


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


def test_dispatcher_never_reads_local_fallback_in_production(monkeypatch, tmp_path):
    from database import db

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    (tmp_path / "pdfs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pdfs" / "legacy.pdf").write_bytes(b"LEGACY-LOCAL")

    with pytest.raises(storage_service.StorageConfigError):
        download_certificate(
            {
                "storage_provider": "local",
                "pdf_path": "pdfs/legacy.pdf",
                "unique_code": "CERT-X",
            }
        )


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


# NOTE: the legacy /generate-certificates flow (generate_from_excel) was
# removed; structured generation is covered by test_saga / test_admin_certificates.
