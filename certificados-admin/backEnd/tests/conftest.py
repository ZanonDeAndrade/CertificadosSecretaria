"""Shared pytest fixtures: an admin TestClient bound to a temp database."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ADMIN_USER = "secretaria"
ADMIN_PASS = "senha-super-secreta"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import storage_service
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "certificates.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret-32-bytes-long-aaaaaaaaaa")
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)
    monkeypatch.setenv("FRONTEND_ADMIN_URL", "http://localhost:5173")

    storage_service.reset_storage_cache()  # rebuild with the patched paths

    import main

    client = TestClient(main.create_app())
    yield client
    storage_service.reset_storage_cache()


@pytest.fixture
def auth_headers(client) -> dict:
    resp = client.post(
        "/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
