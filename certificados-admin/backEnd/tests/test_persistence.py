"""Unit tests for the new SQLAlchemy persistence layer and fail-closed startup.

These run entirely on SQLite. The PostgreSQL-specific behaviour is exercised by
``test_integration_postgres.py`` (skipped unless ``TEST_DATABASE_URL`` is set).
"""
from __future__ import annotations

import pytest

from database import config as db_config
from database import engine as db_engine
from database.models import Base
from database.repositories import (
    AdminUserRepository,
    AuditLogRepository,
    CertificateRepository,
)


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


def _cert(code: str, **over) -> dict:
    base = {
        "unique_code": code,
        "participant_name": "Ana Souza",
        "event_name": "Semana Jurídica",
        "course_name": "Direito",
        "issue_date": "10 de junho de 2026",
        "business_key": code.lower(),
        "template_used": "default",
    }
    base.update(over)
    return base


# ── DATABASE_URL normalisation ─────────────────────────────────────────────────


def test_normalize_postgres_url_uses_psycopg_driver():
    assert db_config.normalize_database_url("postgres://u:p@h/db") == (
        "postgresql+psycopg://u:p@h/db"
    )
    assert db_config.normalize_database_url("postgresql://u:p@h/db") == (
        "postgresql+psycopg://u:p@h/db"
    )
    # SQLite untouched.
    assert db_config.normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_database_url_can_be_loaded_from_secret_file(monkeypatch, tmp_path):
    secret = tmp_path / "database-url.txt"
    secret.write_text("postgresql://u:p@h/db?sslmode=require\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret))

    assert db_config.get_database_url() == (
        "postgresql+psycopg://u:p@h/db?sslmode=require"
    )


def test_direct_database_url_wins_over_secret_file(monkeypatch, tmp_path):
    secret = tmp_path / "database-url.txt"
    secret.write_text("postgresql://file:file@file/db", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://env:env@env/db")
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret))

    assert db_config.get_database_url() == "postgresql+psycopg://env:env@env/db"


# ── Repository CRUD ─────────────────────────────────────────────────────────────


def test_insert_and_get_by_code(session):
    repo = CertificateRepository(session)
    repo.insert_many([_cert("CERT-2026-AAAAAA")])
    session.commit()

    row = repo.get_by_code("cert-2026-aaaaaa")  # case-insensitive
    assert row is not None
    assert row["participant_name"] == "Ana Souza"
    assert row["template_used"] == "default"  # new metadata persisted
    assert row["status"] == "ativo"
    assert (row["pdf_path"] or "") == ""  # never stores a local PDF by default


def test_insert_is_strict_no_insert_or_ignore(session):
    """Duplicates must RAISE (no INSERT OR IGNORE) — uniqueness is the DB's job."""
    from sqlalchemy.exc import IntegrityError

    repo = CertificateRepository(session)
    repo.insert_many([_cert("CERT-2026-AAAAAA", business_key="bk-1")])
    session.commit()

    # Same unique_code → IntegrityError (not silently skipped).
    with pytest.raises(IntegrityError):
        repo.insert_many([_cert("CERT-2026-AAAAAA", business_key="bk-2")])
    session.rollback()

    # Same business_key → IntegrityError.
    with pytest.raises(IntegrityError):
        repo.insert_many([_cert("CERT-2026-BBBBBB", business_key="bk-1")])
    session.rollback()

    _rows, total = repo.list()
    assert total == 1


def test_update_status_revoke_sets_timestamp(session):
    repo = CertificateRepository(session)
    revoker_id = AdminUserRepository(session).create("secretaria", "hash")  # FK target
    repo.insert_many([_cert("CERT-2026-AAAAAA")])
    session.commit()

    assert repo.update_status("CERT-2026-AAAAAA", status="revogado", revoked_by=revoker_id) is True
    session.commit()

    row = repo.get_by_code("CERT-2026-AAAAAA")
    assert row["status"] == "revogado"
    assert row["revoked_by"] == revoker_id
    assert row["revoked_at"] is not None


def test_set_drive_metadata_marks_provider(session):
    repo = CertificateRepository(session)
    repo.insert_many([_cert("CERT-2026-AAAAAA")])
    session.commit()

    ok = repo.set_drive_metadata(
        "CERT-2026-AAAAAA",
        drive_file_id="drv-1",
        drive_folder_id="fld-1",
        original_filename="ana.pdf",
        mime_type="application/pdf",
        file_size=123,
        checksum_sha256="deadbeef",
    )
    session.commit()
    assert ok is True

    row = repo.get_by_code("CERT-2026-AAAAAA")
    assert row["storage_provider"] == "google_drive"
    assert row["drive_file_id"] == "drv-1"
    assert row["checksum_sha256"] == "deadbeef"


def test_admin_user_repository_create_is_idempotent(session):
    repo = AdminUserRepository(session)
    uid = repo.create("secretaria", "hash")
    session.commit()
    assert isinstance(uid, int)
    assert repo.create("secretaria", "hash2") is None  # already exists
    assert repo.count() == 1


def test_audit_log_repository_insert(session):
    AuditLogRepository(session).insert(action="login", actor_username="secretaria")
    session.commit()
    # Smoke: a row exists.
    from sqlalchemy import func, select
    from database.models import AuditLog

    n = session.execute(select(func.count()).select_from(AuditLog)).scalar_one()
    assert n == 1


# ── Transactions ────────────────────────────────────────────────────────────────


def test_session_scope_rolls_back_on_error(tmp_path):
    url = f"sqlite:///{(tmp_path / 'rb.db').as_posix()}"
    eng = db_engine.get_engine(url)
    Base.metadata.create_all(eng)
    try:
        with pytest.raises(RuntimeError):
            with db_engine.session_scope(url) as s:
                CertificateRepository(s).insert_many([_cert("CERT-2026-ROLLBK")])
                raise RuntimeError("boom")  # should roll back the insert
        with db_engine.session_scope(url) as s:
            assert CertificateRepository(s).get_by_code("CERT-2026-ROLLBK") is None
    finally:
        db_engine.reset_engines()


# ── Fail-closed startup (production) ────────────────────────────────────────────


def test_require_production_database_raises_without_url(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_FILE", raising=False)
    with pytest.raises(db_config.ConfigError):
        db_config.require_production_database()


def test_require_production_database_rejects_sqlite(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///prod.db")
    with pytest.raises(db_config.ConfigError):
        db_config.require_production_database()


def test_require_production_database_accepts_postgres(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    db_config.require_production_database()  # must not raise


def test_auth_requires_jwt_secret_in_production(monkeypatch):
    import auth

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        auth.require_production_secret()

    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(RuntimeError):
        auth.require_production_secret()

    monkeypatch.setenv(
        "JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef"
    )
    auth.require_production_secret()  # ok


def test_storage_validation_requires_google_drive_in_production(monkeypatch):
    from storage_service import config as storage_config

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    with pytest.raises(storage_config.StorageConfigError):
        storage_config.validate_production_storage()


def test_get_storage_has_no_local_fallback_in_production(monkeypatch):
    import storage_service
    from storage_service import StorageConfigError

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    storage_service.reset_storage_cache()
    try:
        with pytest.raises(StorageConfigError):
            storage_service.get_storage()
    finally:
        storage_service.reset_storage_cache()
