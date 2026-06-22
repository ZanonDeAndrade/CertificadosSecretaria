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


@pytest.fixture(autouse=True)
def isolate_database_credentials(monkeypatch):
    """Never let a developer's real DATABASE_URL leak into unit tests."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_FILE", raising=False)
    monkeypatch.delenv("JWT_SECRET_FILE", raising=False)
    monkeypatch.delenv("DOCUMENT_HASH_SECRET_FILE", raising=False)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import storage_service
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "certificates.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)
    monkeypatch.setenv("ADMIN_INITIAL_ROLE", "admin")
    monkeypatch.setenv("FRONTEND_ADMIN_URL", "http://localhost:5173")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("LOGIN_BACKOFF_BASE_MS", "0")
    monkeypatch.setenv("LOGIN_BACKOFF_MAX_MS", "0")

    storage_service.reset_storage_cache()  # rebuild with the patched paths

    import main

    client = TestClient(
        main.create_app(),
        base_url="https://admin-api.test",
        headers={"Origin": "http://localhost:5173"},
    )
    yield client
    storage_service.reset_storage_cache()


@pytest.fixture
def auth_headers(client) -> dict:
    resp = client.post(
        "/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert resp.status_code == 200, resp.text
    assert "access_token" not in resp.json()
    return {}
