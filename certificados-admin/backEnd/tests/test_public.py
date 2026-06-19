"""Tests for the public area (certificados-consulta): verify, search, download.

Loads the consulta FastAPI app against a temporary database and asserts the
public projection never leaks sensitive fields or Drive links.
"""
from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient

CODE = "CERT-2026-PUB001"


def _seed_certificate(db, tmp_path, *, status="ativo", name="João Público", code=CODE):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir(parents=True, exist_ok=True)
    (pdfs / "j.pdf").write_bytes(b"%PDF-1.4 test certificate")
    db.insert_certificates(
        [
            {
                "unique_code": code,
                "participant_name": name,
                "event_name": "Semana Acadêmica",
                "course_name": "Direito",
                "workload_hours": 40,
                "issue_date": "10 de junho de 2026",
                "pdf_path": "pdfs/j.pdf",
                "participant_email": "segredo@exemplo.com",
                "participant_document": "99999999999",
                "storage_provider": "local",
                "status": status,
            }
        ]
    )


@pytest.fixture
def public(tmp_path, monkeypatch):
    import storage_service
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "certificates.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    storage_service.reset_storage_cache()
    db.init_db()

    path = _REPO_ROOT / "certificados-consulta" / "app.py"
    spec = importlib.util.spec_from_file_location(f"consulta_{uuid.uuid4().hex}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    client = TestClient(module.app)
    yield client, db, tmp_path
    storage_service.reset_storage_cache()


def test_verify_valid_certificate_is_sanitized(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)

    resp = client.get(f"/public/verify/{CODE}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["revoked"] is False
    cert = body["certificate"]
    assert cert["participant_name"] == "João Público"
    assert cert["event_name"] == "Semana Acadêmica"
    # No sensitive/internal fields leak.
    for forbidden in ("participant_email", "participant_document", "drive_file_id", "pdf_path", "id"):
        assert forbidden not in cert


def test_verify_unknown_code(public):
    client, _, _ = public
    assert client.get("/public/verify/CERT-2026-NOPE").json() == {"valid": False}


def test_verify_revoked_is_flagged(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, status="revogado")
    body = client.get(f"/public/verify/{CODE}").json()
    assert body["valid"] is True
    assert body["revoked"] is True
    assert body["status"] == "revogado"


def test_public_search_is_paginated_and_sanitized(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)

    body = client.get("/public/search", params={"nome": "João"}).json()
    assert body["total"] == 1
    assert body["page"] == 1
    item = body["items"][0]
    assert item["unique_code"] == CODE
    assert "participant_email" not in item
    assert "participant_document" not in item


def test_public_search_empty_term(public):
    client, _, _ = public
    body = client.get("/public/search", params={"nome": ""}).json()
    assert body["items"] == []
    assert body["total"] == 0


def test_public_download_requires_code_and_streams_pdf(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    resp = client.get(f"/public/certificates/{CODE}/download")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    assert resp.headers["content-type"] == "application/pdf"


def test_public_download_revoked_returns_410(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, status="revogado")
    assert client.get(f"/public/certificates/{CODE}/download").status_code == 410


def test_public_download_unknown_returns_404(public):
    client, _, _ = public
    assert client.get("/public/certificates/CERT-2026-NOPE/download").status_code == 404
