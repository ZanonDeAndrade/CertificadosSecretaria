"""Saga + compensation tests (F1/F2).

Covers: reservation idempotency, code collision retry, simultaneous business_key,
upload failure, finalize failure, compensation, reconciliation, real-thread
concurrency, and that the API summary reflects exactly what was persisted.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path


_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import func, select  # noqa: E402

from services import certificate_store  # noqa: E402
from services.certificate_service import (  # noqa: E402
    CertificateBatchConfig,
    CertificateBatchService,
)
from services.spreadsheet import SpreadsheetRow, compute_business_key  # noqa: E402
from storage_service import StorageError  # noqa: E402
from storage_service.base import CertificateStorage, StoredFile, sha256_hex, utc_now_iso  # noqa: E402
from storage_service.local import LocalStorage  # noqa: E402

PDF_BYTES = b"%PDF-1.4\nsaga\n%%EOF"


# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeGenerator:
    def render_pdf_bytes_default(self, record, template_path=None, qr_url=None):
        return PDF_BYTES

    def render_pdf_bytes_visual(self, record, layout, *, qr_url=None, background_bytes=None):
        return PDF_BYTES


class FailingStorage(CertificateStorage):
    """Upload always fails — exercises the upload-failure compensation path."""

    provider = "google_drive"

    def save(self, content, *, filename, mime_type="application/pdf") -> StoredFile:
        raise StorageError("upload boom")

    def download(self, cert_row) -> bytes:  # pragma: no cover
        raise FileNotFoundError

    def delete(self, cert_row) -> None:  # pragma: no cover
        pass


class RecordingDriveStorage(CertificateStorage):
    """In-memory Drive-like backend that records deletions (compensation proof)."""

    provider = "google_drive"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.deleted: list[str] = []
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
        file_id = (cert_row.get("drive_file_id") or "").strip()
        self.deleted.append(file_id)
        self.files.pop(file_id, None)


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
    storage = storage or LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)
    return CertificateBatchService(
        config, storage=storage, generator=generator or FakeGenerator()
    )


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


def _count_audit(db, action: str) -> int:
    from database import engine as db_engine
    from database.models import AuditLog

    url = db._current_database_url()
    with db_engine.session_scope(url) as s:
        return int(
            s.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.action == action)
            ).scalar_one()
        )


# ── Happy path: API reflects exactly what was persisted ────────────────────────


def test_summary_reflects_persisted(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path)
    issuer_id = db.create_admin_user("secretaria", "hash")  # FK target for issued_by

    summary = service.generate_certificates([_row()], issued_by=issuer_id)
    assert len(summary.generated) == 1
    assert summary.failed == []
    assert summary.duplicates == []

    code = summary.generated[0]["code"]
    row = db.get_by_code(code)
    assert row["status"] == "ativo"  # finalized
    assert row["drive_file_id"] is None and row["pdf_path"]  # local file pointer
    # Exactly one persisted, and it is active.
    _items, total = db.list_certificates()
    assert total == 1
    assert db.list_certificates(status="ativo")[1] == 1


# ── Idempotency / simultaneous business_key ────────────────────────────────────


def test_duplicate_business_key_reported(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path)

    first = service.generate_certificates([_row()])
    second = service.generate_certificates([_row()])
    assert len(second.generated) == 0
    assert len(second.duplicates) == 1
    assert second.duplicates[0]["existing_code"] == first.generated[0]["code"]
    assert second.duplicates[0]["status"] == "ativo"
    assert db.list_certificates()[1] == 1


def test_simultaneous_business_key_race_resolves_to_duplicate(monkeypatch, tmp_path):
    """Force the fast-path lookup to miss once, so the UNIQUE insert conflicts and
    the saga must resolve the race via a fresh read → duplicate."""
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path)
    row = _row()
    bk = compute_business_key(row)

    # A row already holds this business_key (the "winner" of the race).
    db.insert_certificates(
        [
            {
                "unique_code": "CERT-2026-SEED01",
                "participant_name": row.nome,
                "event_name": row.evento,
                "course_name": row.curso,
                "issue_date": row.data_emissao,
                "status": "ativo",
                "business_key": bk,
            }
        ]
    )

    real = db.get_by_business_key
    calls = {"n": 0}

    def flaky(key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(key)  # miss once (simulate race)

    monkeypatch.setattr(db, "get_by_business_key", flaky)

    summary = service.generate_certificates([row])
    assert len(summary.generated) == 0
    assert len(summary.duplicates) == 1
    assert summary.duplicates[0]["existing_code"] == "CERT-2026-SEED01"
    assert db.list_certificates()[1] == 1  # no new row created


# ── Code collision retry ───────────────────────────────────────────────────────


def test_code_collision_retries_until_unique(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path)

    taken = "CERT-2026-TAKEN0"
    db.insert_certificates(
        [
            {
                "unique_code": taken,
                "participant_name": "Outro",
                "event_name": "X",
                "issue_date": "1 de janeiro de 2026",
                "status": "ativo",
                "business_key": "seed-bk",
            }
        ]
    )

    # generate_code yields the taken code twice (collisions), then a free one.
    seq = iter([taken, taken, "CERT-2026-FREE00"])
    monkeypatch.setattr(certificate_store, "generate_code", lambda year=None: next(seq))

    summary = service.generate_certificates([_row(nome="Novo", evento="Outro Evento")])
    assert len(summary.generated) == 1
    assert summary.generated[0]["code"] == "CERT-2026-FREE00"
    assert db.get_by_code("CERT-2026-FREE00")["status"] == "ativo"


# ── Upload failure → compensation ──────────────────────────────────────────────


def test_upload_failure_marks_failed_without_file(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path, storage=FailingStorage())

    summary = service.generate_certificates([_row()])
    assert summary.generated == []
    assert len(summary.failed) == 1
    assert summary.failed[0]["name"] == "Ana Souza"

    # Exactly one row, marked failed, with no file pointer and not servable.
    items, total = db.list_certificates(status="failed")
    assert total == 1
    cert = items[0]
    assert cert["status"] == "failed"
    assert (cert["drive_file_id"] or "") == ""
    assert (cert["pdf_path"] or "") == ""
    assert db.list_certificates(status="ativo")[1] == 0
    # Failure was audited.
    assert _count_audit(db, "generation_failed") == 1


# ── Finalize failure → compensation deletes the uploaded file ──────────────────


def test_finalize_failure_compensates_uploaded_file(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    storage = RecordingDriveStorage()
    service = _service(tmp_path, storage=storage)

    # The upload succeeds, but finalization reports 0 rows affected.
    monkeypatch.setattr(db, "finalize_certificate", lambda *a, **k: False)

    summary = service.generate_certificates([_row()])
    assert summary.generated == []
    assert len(summary.failed) == 1

    # The uploaded Drive file was deleted (compensation), leaving no orphan.
    assert storage.deleted == ["drive-1"]
    assert storage.files == {}

    items, total = db.list_certificates(status="failed")
    assert total == 1
    cert = items[0]
    assert cert["status"] == "failed"
    assert (cert["drive_file_id"] or "") == ""  # pointer cleared after delete
    assert _count_audit(db, "generation_failed") == 1


# ── Reconciliation ─────────────────────────────────────────────────────────────


def test_reconcile_marks_stale_pending_failed(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    from services.reconciliation import run_reconciliation

    code, existing = db.reserve_certificate(
        business_key=None,
        fields={
            "participant_name": "Pendente",
            "event_name": "Evento",
            "issue_date": "1 de janeiro de 2026",
        },
        code_factory=lambda: "CERT-2026-PEND00",
    )
    assert code == "CERT-2026-PEND00" and existing is None
    assert db.get_by_code(code)["status"] == "pending"

    report = run_reconciliation(pending_max_age_minutes=0)
    assert report["pending_failed"] == 1
    assert db.get_by_code(code)["status"] == "failed"


def test_reconcile_marks_active_without_file_failed(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    from services.reconciliation import run_reconciliation

    db.insert_certificates(
        [
            {
                "unique_code": "CERT-2026-NOFILE",
                "participant_name": "Sem Arquivo",
                "event_name": "Evento",
                "issue_date": "1 de janeiro de 2026",
                "status": "ativo",
                "drive_file_id": None,
                "pdf_path": "",
            }
        ]
    )

    report = run_reconciliation()
    assert report["active_without_file_failed"] == 1
    assert db.get_by_code("CERT-2026-NOFILE")["status"] == "failed"


def test_reconcile_compensates_failed_orphan_file(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    from services.reconciliation import run_reconciliation

    # A real local file that a 'failed' row still points at (orphan).
    storage = LocalStorage(pdfs_dir=tmp_path / "pdfs", storage_dir=tmp_path)
    stored = storage.save(PDF_BYTES, filename="orphan.pdf")
    assert (tmp_path / "pdfs" / "orphan.pdf").exists()

    db.insert_certificates(
        [
            {
                "unique_code": "CERT-2026-ORPH00",
                "participant_name": "Órfão",
                "event_name": "Evento",
                "issue_date": "1 de janeiro de 2026",
                "status": "failed",
                "storage_provider": "local",
                "pdf_path": stored.pdf_path,
            }
        ]
    )

    report = run_reconciliation()
    assert report["compensated"] == 1
    assert not (tmp_path / "pdfs" / "orphan.pdf").exists()  # file removed
    assert (db.get_by_code("CERT-2026-ORPH00")["pdf_path"] or "") == ""  # pointer cleared


# ── Real-thread concurrency ────────────────────────────────────────────────────


def test_concurrent_generation_same_business_key(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path)
    # Seed the global template once up front (production seeds at startup), so the
    # threads race only on the certificate business_key, not on template seeding.
    from services import template_service

    template_service.ensure_default_version(tmp_path / "missing.png")
    row = _row()

    results: list = []
    errors: list = []

    def worker():
        try:
            results.append(service.generate_certificates([row]))
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"saga raised under concurrency: {errors}"
    total_generated = sum(len(r.generated) for r in results)
    total_duplicate = sum(len(r.duplicates) for r in results)
    assert total_generated == 1  # exactly one winner
    assert total_duplicate == len(threads) - 1  # the rest see the duplicate
    # And the database holds exactly one active certificate.
    assert db.list_certificates()[1] == 1
    assert db.list_certificates(status="ativo")[1] == 1
