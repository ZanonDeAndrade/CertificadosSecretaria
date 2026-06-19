"""Tests for admin authentication and route protection.

Uses FastAPI's TestClient against a fresh app bound to a temporary database.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient

ADMIN_USER = "secretaria"
ADMIN_PASS = "senha-super-secreta"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "certificates.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)
    monkeypatch.setenv("FRONTEND_ADMIN_URL", "http://localhost:5173")

    import main

    app = main.create_app()
    return TestClient(app)


def _login(client) -> str:
    resp = client.post(
        "/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ── Public routes stay open ───────────────────────────────────────────────────


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_validate_is_public(client):
    resp = client.get("/validate/CERT-2026-UNKNOWN")
    assert resp.status_code == 200
    assert resp.json() == {"valid": False}


# ── Login ─────────────────────────────────────────────────────────────────────


def test_login_with_valid_credentials(client):
    resp = client.post(
        "/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["user"]["username"] == ADMIN_USER
    # HttpOnly cookie was set.
    assert "admin_token" in resp.cookies


def test_login_with_invalid_password(client):
    resp = client.post(
        "/auth/login", json={"username": ADMIN_USER, "password": "errada"}
    )
    assert resp.status_code == 401


def test_login_with_unknown_user(client):
    resp = client.post(
        "/auth/login", json={"username": "ninguem", "password": "x"}
    )
    assert resp.status_code == 401


# ── Session ───────────────────────────────────────────────────────────────────


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401


def test_me_with_bearer_token(client):
    token = _login(client)
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == ADMIN_USER


def test_me_with_cookie_after_login(client):
    _login(client)  # cookie is stored by the TestClient
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == ADMIN_USER


def test_logout_clears_cookie(client):
    _login(client)
    assert client.get("/auth/me").status_code == 200
    client.post("/auth/logout")
    # cookie cleared → no longer authenticated
    assert client.get("/auth/me").status_code == 401


# ── Protected admin routes ────────────────────────────────────────────────────


def test_admin_route_rejects_without_token(client):
    # Auth runs before business logic: 401, not 404.
    assert client.get("/certificate-file/CERT-2026-NOPE").status_code == 401
    assert client.get("/admin/certificates/CERT-2026-NOPE/metadata").status_code == 401


def test_admin_route_allows_with_token(client):
    token = _login(client)
    # Authenticated but certificate does not exist → 404 (auth passed).
    resp = client.get(
        "/admin/certificates/CERT-2026-NOPE/metadata",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_visual_templates_route_is_protected(client):
    assert client.get("/visual-templates").status_code == 401
    token = _login(client)
    resp = client.get(
        "/visual-templates", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
