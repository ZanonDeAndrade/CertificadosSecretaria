"""Tests for the single global template: versioning, activation, event×course,
faithful reissue, reissue rollback, and absence of Drive orphans."""
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
)
from services.spreadsheet import SpreadsheetRow  # noqa: E402
from storage_service.base import CertificateStorage, StoredFile, sha256_hex, utc_now_iso  # noqa: E402

PDF_BYTES = b"%PDF-1.4\ntpl\n%%EOF"


def _png_bytes(w: int = 400, h: int = 300) -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _layout(elements: list[dict], w: int = 400, h: int = 300) -> dict:
    return {
        "background": _data_url(_png_bytes(w, h)),
        "image_width": w,
        "image_height": h,
        "elements": elements,
    }


def _point_db(monkeypatch, tmp_path):
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "c.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    db.init_db()
    return db


class RecordingGenerator:
    """Captures the layout/background each render was asked to use."""

    def __init__(self):
        self.calls: list[dict] = []

    def render_pdf_bytes_default(self, record, template_path=None, qr_url=None):
        return PDF_BYTES

    def render_pdf_bytes_visual(self, record, layout, *, qr_url=None, background_bytes=None):
        self.calls.append({"layout": layout, "background": background_bytes, "record": record})
        return PDF_BYTES


class RecordingDriveStorage(CertificateStorage):
    provider = "google_drive"

    def __init__(self):
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


def _service(tmp_path, storage=None, generator=None):
    config = CertificateBatchConfig(
        template_path=tmp_path / "t.png",
        regular_font_path=tmp_path / "r.ttf",
        bold_font_path=tmp_path / "b.ttf",
        output_dir=tmp_path / "pdfs",
    )
    return CertificateBatchService(
        config, storage=storage, generator=generator or RecordingGenerator()
    )


def _row():
    return SpreadsheetRow(
        row_number=2,
        nome="Ana Souza",
        curso="Direito",
        evento="Semana Jurídica",
        carga_horaria=40,
        data_emissao="10 de junho de 2026",
        email="ana@x.com",
        documento="123",
    )


# ── Versioning + activation ────────────────────────────────────────────────────


def test_create_version_increments_and_is_immutable(monkeypatch, tmp_path):
    _point_db(monkeypatch, tmp_path)
    v1 = template_service.create_version(name="A", layout=_layout([{"type": "text", "key": "name", "x": 1, "y": 1}]))
    v2 = template_service.create_version(name="B", layout=_layout([{"type": "text", "key": "date", "x": 2, "y": 2}]))

    assert v1["version_number"] == 1
    assert v2["version_number"] == 2
    assert v1["is_active"] is False and v2["is_active"] is False  # not auto-activated

    # v1 is immutable: re-reading returns the original elements.
    again = template_service.get_version(v1["id"])
    assert again["layout"]["elements"][0]["key"] == "name"


def test_only_one_active_and_activation_is_explicit(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    v1 = template_service.create_version(name="A", layout=_layout([{"type": "text", "key": "name", "x": 1, "y": 1}]))
    v2 = template_service.create_version(name="B", layout=_layout([{"type": "text", "key": "name", "x": 1, "y": 1}]))

    assert template_service.get_active_version() is None  # nothing active until asked

    assert template_service.activate_version(v1["id"]) is True
    assert template_service.get_active_version()["id"] == v1["id"]

    assert template_service.activate_version(v2["id"]) is True
    active = template_service.get_active_version()
    assert active["id"] == v2["id"]
    # Exactly one active.
    assert sum(1 for v in db.list_template_versions() if v["is_active"]) == 1


def test_activate_unknown_version_returns_false(monkeypatch, tmp_path):
    _point_db(monkeypatch, tmp_path)
    assert template_service.activate_version(999) is False


# ── event × course ─────────────────────────────────────────────────────────────


def test_event_and_course_are_distinct():
    from services.generator import CertificateGenerator, CertificateGeneratorConfig

    gen = CertificateGenerator(
        CertificateGeneratorConfig(
            template_path=_BACKEND_DIR / "templates" / "certificado_base.png",
            regular_font_path=_BACKEND_DIR / "fonts" / "times.ttf",
            bold_font_path=_BACKEND_DIR / "fonts" / "timesbd.ttf",
            output_dir=_BACKEND_DIR / "output",
        )
    )
    record = ParticipantRegistryRecord(
        nome="Ana", email="", curso="Direito", evento="Semana Jurídica",
        livro=0, folha=0, linha=0, validation_code="CERT-2026-AAAAAA",
    )
    data = gen._participant_data(record)
    assert data["event"] == "Semana Jurídica"  # NOT the course
    assert data["course"] == "Direito"


def test_generation_persists_distinct_event_and_course(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    template_service.create_version(name="A", layout=_layout([{"type": "text", "key": "event", "x": 1, "y": 1}]))
    template_service.activate_version(1)
    service = _service(tmp_path, storage=RecordingDriveStorage())

    summary = service.generate_certificates([_row()])
    cert = db.get_by_code(summary.generated[0]["code"])
    assert cert["event_name"] == "Semana Jurídica"
    assert cert["course_name"] == "Direito"
    assert cert["template_version_id"] == 1
    assert cert["template_snapshot"]


# ── Faithful reissue ───────────────────────────────────────────────────────────


def _generate_one(db, service):
    template_service.create_version(name="v1", layout=_layout([{"type": "text", "key": "name", "x": 10, "y": 10}]))
    template_service.activate_version(1)
    summary = service.generate_certificates([_row()])
    return db.get_by_code(summary.generated[0]["code"])


def test_reissue_uses_original_version_not_active(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    gen = RecordingGenerator()
    service = _service(tmp_path, storage=RecordingDriveStorage(), generator=gen)

    cert = _generate_one(db, service)
    assert cert["template_version_id"] == 1

    # A NEW active version with a clearly different layout.
    v2 = template_service.create_version(
        name="v2", layout=_layout([{"type": "text", "key": "date", "x": 9, "y": 9}, {"type": "text", "key": "name", "x": 1, "y": 1}])
    )
    template_service.activate_version(v2["id"])
    assert template_service.get_active_version()["id"] == v2["id"]

    gen.calls.clear()
    service.reissue_certificate(db.get_by_code(cert["unique_code"]))

    # Reissue rendered with the ORIGINAL (v1) snapshot, not the active v2.
    used = gen.calls[-1]["layout"]
    assert len(used["elements"]) == 1
    assert used["elements"][0]["key"] == "name"
    assert db.get_by_code(cert["unique_code"])["template_version_id"] == 1


def test_reissue_requires_version_and_snapshot(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    service = _service(tmp_path, storage=RecordingDriveStorage())
    db.insert_certificates(
        [
            {
                "unique_code": "CERT-2026-LEGACY",
                "participant_name": "Antigo",
                "event_name": "Direito",
                "issue_date": "1 de janeiro de 2020",
                "status": "ativo",
            }
        ]
    )
    with pytest.raises(ValueError):
        service.reissue_certificate(db.get_by_code("CERT-2026-LEGACY"))


# ── Drive-safe swap: no orphans / rollback ─────────────────────────────────────


def test_reissue_deletes_old_drive_file_after_finalizing_new(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    storage = RecordingDriveStorage()
    service = _service(tmp_path, storage=storage)

    cert = _generate_one(db, service)
    old_id = cert["drive_file_id"]
    assert old_id in storage.files

    service.reissue_certificate(db.get_by_code(cert["unique_code"]))

    updated = db.get_by_code(cert["unique_code"])
    new_id = updated["drive_file_id"]
    assert new_id != old_id
    # New finalized, old deleted → no orphan.
    assert list(storage.files.keys()) == [new_id]
    assert old_id in storage.deleted


def test_reissue_rollback_preserves_old_file_when_db_update_fails(monkeypatch, tmp_path):
    db = _point_db(monkeypatch, tmp_path)
    storage = RecordingDriveStorage()
    service = _service(tmp_path, storage=storage)

    cert = _generate_one(db, service)
    old_id = cert["drive_file_id"]

    # The DB finalize of the new file fails → must delete the NEW file and keep old.
    monkeypatch.setattr(db, "update_certificate_file", lambda *a, **k: False)

    with pytest.raises(Exception):
        service.reissue_certificate(db.get_by_code(cert["unique_code"]))

    # Old file preserved, the just-uploaded new file removed → no orphan, no loss.
    assert old_id in storage.files
    assert len(storage.files) == 1
    # DB still points at the original file.
    assert db.get_by_code(cert["unique_code"])["drive_file_id"] == old_id
