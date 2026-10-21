"""Shared pytest fixtures: an admin TestClient bound to a temp database."""

from __future__ import annotations

import hashlib
import os

import pytest

# Tests must never inherit or load a developer's real .env/database.
os.environ["CERTIFICADOS_DISABLE_DOTENV"] = "1"

ADMIN_USER = "secretaria"
ADMIN_PASS = "Senha-Sintetica-1!"
JWT_FIXTURE_MATERIAL = hashlib.sha256(b"academic-test-fixture").hexdigest()


@pytest.fixture(autouse=True)
def isolate_database_credentials(monkeypatch):
    """Never let a developer's real DATABASE_URL leak into unit tests."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_FILE", raising=False)
    monkeypatch.delenv("JWT_SECRET_FILE", raising=False)
    monkeypatch.delenv("DOCUMENT_HASH_SECRET_FILE", raising=False)


@pytest.fixture
def client(tmp_path, monkeypatch, isolate_database_credentials):
    from fastapi.testclient import TestClient

    import storage_service
    from database import db
    from database import engine as db_engine

    # Make the isolation dependency explicit: pytest may otherwise order two
    # same-scope fixtures that share ``monkeypatch`` differently between runs.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_FILE", raising=False)
    db_engine.reset_engines()

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "certificates.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("JWT_SECRET", JWT_FIXTURE_MATERIAL)
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)
    monkeypatch.setenv("ADMIN_INITIAL_ROLE", "admin")
    monkeypatch.setenv("FRONTEND_ADMIN_URL", "http://localhost:5173")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("LOGIN_BACKOFF_BASE_MS", "0")
    monkeypatch.setenv("LOGIN_BACKOFF_MAX_MS", "0")

    storage_service.reset_storage_cache()  # rebuild with the patched paths

    from certificados_backend import main

    client = TestClient(
        main.create_app(),
        base_url="https://admin-api.test",
        headers={"Origin": "http://localhost:5173"},
    )
    yield client
    storage_service.reset_storage_cache()
    db_engine.reset_engines()


@pytest.fixture
def postgres_engine(monkeypatch, isolate_database_credentials):
    """Disposable PostgreSQL schema for concurrency and worker contracts."""

    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    from database import config as db_config
    from database import engine as db_engine
    from database.models import Base

    raw_url = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL não definido.")
    url = db_config.normalize_database_url(raw_url)
    if not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL não aponta para PostgreSQL.")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    db_engine.reset_engines()
    engine = create_engine(url, future=True, pool_size=8, max_overflow=4)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip("PostgreSQL de teste indisponível.")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        db_engine.reset_engines()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def auth_headers(client) -> dict:
    resp = client.post("/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    assert resp.status_code == 200, resp.text
    assert "access_token" not in resp.json()
    return {}
