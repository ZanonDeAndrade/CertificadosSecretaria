"""Regression tests for PostgreSQL schema ownership and pre-created future tables."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from database.models import Base

REPO_ROOT = Path(__file__).resolve().parents[3]


def _alembic_config() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


def test_upgrade_repairs_compatible_tables_precreated_before_0007(tmp_path, monkeypatch):
    database_path = tmp_path / "precreated-future-tables.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CERTIFICADOS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("DATABASE_URL", database_url)

    cfg = _alembic_config()
    command.upgrade(cfg, "0005")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO admin_users (username, password_hash, role) "
                "VALUES ('synthetic.admin', 'not-a-real-hash', 'admin')"
            )
        )

    # Reproduces the old bug: create_all skipped legacy tables but created the
    # future tables from the latest ORM while Alembic still reported 0005.
    Base.metadata.create_all(engine)
    assert inspect(engine).has_table("institutional_settings")

    command.upgrade(cfg, "head")
    command.check(cfg)

    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0013"
        )
        assert (
            connection.execute(
                text("SELECT username FROM admin_users WHERE username = 'synthetic.admin'")
            ).scalar_one()
            == "synthetic.admin"
        )


def test_init_db_never_runs_create_all_for_postgres(monkeypatch):
    from database import db

    fake_connection = MagicMock()
    fake_engine = MagicMock()
    fake_engine.connect.return_value.__enter__.return_value = fake_connection
    monkeypatch.setattr(
        db,
        "_current_database_url",
        lambda: "postgresql+psycopg://synthetic@db.invalid/certificados",
    )
    monkeypatch.setattr(db.engine, "get_engine", lambda _url: fake_engine)

    def forbidden_create_all(*_args, **_kwargs):
        raise AssertionError("create_all não pode administrar schema PostgreSQL")

    monkeypatch.setattr(db.Base.metadata, "create_all", forbidden_create_all)

    db.init_db()

    fake_connection.execute.assert_called_once()


def test_certificate_type_migration_preserves_legacy_rows_and_enforces_domain(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "certificate-types.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CERTIFICADOS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("DATABASE_URL", database_url)

    cfg = _alembic_config()
    command.upgrade(cfg, "0010")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO certificates "
                "(unique_code, participant_name, event_name, issue_date) "
                "VALUES ('CERT-2025-LEGACY', 'Pessoa Legada', 'Evento Histórico', '2025-08-15')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO emission_batches "
                "(id, idempotency_key, request_sha256, status, total_rows, valid_count, "
                "invalid_count, processed_count, generated_count, duplicate_count, failed_count) "
                "VALUES ('legacy-batch', 'legacy-idempotency-key', :digest, 'completed', "
                "1, 1, 0, 1, 1, 0, 0)"
            ),
            {"digest": "a" * 64},
        )

    command.upgrade(cfg, "head")
    command.check(cfg)

    certificate_columns = {column["name"] for column in inspect(engine).get_columns("certificates")}
    batch_columns = {column["name"] for column in inspect(engine).get_columns("emission_batches")}
    assert "certificate_type" in certificate_columns
    assert "certificate_type" in batch_columns
    with engine.connect() as connection:
        legacy = connection.execute(
            text(
                "SELECT unique_code, certificate_type FROM certificates "
                "WHERE unique_code = 'CERT-2025-LEGACY'"
            )
        ).one()
        legacy_batch = connection.execute(
            text("SELECT id, certificate_type FROM emission_batches WHERE id = 'legacy-batch'")
        ).one()
        assert tuple(legacy) == ("CERT-2025-LEGACY", None)
        assert tuple(legacy_batch) == ("legacy-batch", None)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE certificates SET certificate_type = 'arbitrary' "
                    "WHERE unique_code = 'CERT-2025-LEGACY'"
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE emission_batches SET certificate_type = 'arbitrary' "
                    "WHERE id = 'legacy-batch'"
                )
            )

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE certificates SET certificate_type = 'listener' "
                "WHERE unique_code = 'CERT-2025-LEGACY'"
            )
        )
        connection.execute(
            text(
                "UPDATE emission_batches SET certificate_type = 'speaker' WHERE id = 'legacy-batch'"
            )
        )


def _insert_legacy_events(engine) -> None:
    with engine.begin() as connection:
        for code, event in (
            ("CERT-2025-EVT001", "Semana de Inovação"),
            ("CERT-2025-EVT002", "  JORNADA   JURÍDICA "),
        ):
            connection.execute(
                text(
                    "INSERT INTO certificates "
                    "(unique_code, participant_name, event_name, issue_date) "
                    "VALUES (:code, 'Pessoa Legada', :event, '2025-08-15')"
                ),
                {"code": code, "event": event},
            )


def _normalized_events(engine) -> dict[str, str | None]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT unique_code, event_name_normalized FROM certificates")
        ).all()
    return {code: normalized for code, normalized in rows}


def test_event_name_migration_fills_existing_certificates_and_downgrades(tmp_path, monkeypatch):
    database_path = tmp_path / "event-name.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CERTIFICADOS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("DATABASE_URL", database_url)

    cfg = _alembic_config()
    command.upgrade(cfg, "0012")
    engine = create_engine(database_url)
    _insert_legacy_events(engine)

    command.upgrade(cfg, "head")
    command.check(cfg)
    assert _normalized_events(engine) == {
        "CERT-2025-EVT001": "semana de inovacao",
        "CERT-2025-EVT002": "jornada juridica",
    }
    indexes = {index["name"] for index in inspect(engine).get_indexes("certificates")}
    assert "idx_certificates_event_name_normalized" in indexes

    command.downgrade(cfg, "0012")
    columns = {column["name"] for column in inspect(engine).get_columns("certificates")}
    assert "event_name_normalized" not in columns
    command.upgrade(cfg, "head")
    assert _normalized_events(engine)["CERT-2025-EVT001"] == "semana de inovacao"


def test_legacy_sqlite_startup_fills_the_event_search_column(tmp_path, monkeypatch):
    from database import db
    from database import engine as db_engine

    database_path = tmp_path / "legacy-startup.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CERTIFICADOS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(_alembic_config(), "0012")
    engine = create_engine(database_url)
    _insert_legacy_events(engine)

    db_engine.reset_engines()
    try:
        db.init_db()
    finally:
        db_engine.reset_engines()
    assert _normalized_events(engine) == {
        "CERT-2025-EVT001": "semana de inovacao",
        "CERT-2025-EVT002": "jornada juridica",
    }
