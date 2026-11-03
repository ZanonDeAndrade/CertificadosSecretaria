"""Migration 0015: keyed e-mail hashes per certificate.

Runs on SQLite (always) and on PostgreSQL when ``TEST_DATABASE_URL`` points
at a disposable database. Certificates already present are untouched: the
new table starts empty and the downgrade drops only it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from database import config as db_config

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()
TABLE = "certificate_email_hashes"


def _alembic_config() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


def _prepare(tmp_path, monkeypatch, name: str) -> tuple[Config, str]:
    database_url = f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CERTIFICADOS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("DATABASE_URL", database_url)
    return _alembic_config(), database_url


def _seed_certificate(connection, code: str) -> int:
    connection.execute(
        text(
            "INSERT INTO certificates (unique_code, participant_name, event_name, issue_date, "
            "status, template_snapshot) VALUES (:code, 'Pessoa Exemplo Alfa', "
            "'Evento Sintético', '2026-08-15', 'ativo', '{}')"
        ),
        {"code": code},
    )
    return int(
        connection.execute(
            text("SELECT id FROM certificates WHERE unique_code = :code"), {"code": code}
        ).scalar_one()
    )


def _signature(connection) -> list[tuple]:
    return [
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT unique_code, participant_name, status, template_snapshot "
                "FROM certificates ORDER BY unique_code"
            )
        ).all()
    ]


def _assert_schema(engine) -> None:
    inspector = inspect(engine)
    assert inspector.has_table(TABLE)
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    assert columns == {"id", "certificate_id", "position", "email_hash", "hash_key_id"}
    indexes = {index["name"]: index for index in inspector.get_indexes(TABLE)}
    assert set(indexes) >= {
        "idx_certificate_email_hashes_hash_key",
        "idx_certificate_email_hashes_certificate",
        "uq_certificate_email_hashes_position",
    }
    assert indexes["uq_certificate_email_hashes_position"]["unique"]
    foreign_keys = inspector.get_foreign_keys(TABLE)
    assert [key["referred_table"] for key in foreign_keys] == ["certificates"]
    assert foreign_keys[0]["options"].get("ondelete", "").upper() == "CASCADE"


def test_upgrade_adds_the_table_without_touching_certificates(tmp_path, monkeypatch):
    cfg, database_url = _prepare(tmp_path, monkeypatch, "emails.db")
    command.upgrade(cfg, "0014")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_certificate(connection, "CERT-2026-MIG001")
        before = _signature(connection)

    command.upgrade(cfg, "head")
    command.check(cfg)
    _assert_schema(engine)
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0015"
        )
        assert _signature(connection) == before
        assert connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0

    # Down and up again: the certificate survives, the table comes back empty.
    command.downgrade(cfg, "0014")
    assert not inspect(engine).has_table(TABLE)
    with engine.connect() as connection:
        assert _signature(connection) == before
    command.upgrade(cfg, "head")
    command.check(cfg)
    _assert_schema(engine)
    engine.dispose()


def test_upgrade_tolerates_a_table_created_by_the_orm_startup(tmp_path, monkeypatch):
    """A development SQLite database may already have the table from create_all."""
    from database.models import Base

    cfg, database_url = _prepare(tmp_path, monkeypatch, "orm-first.db")
    command.upgrade(cfg, "0014")
    engine = create_engine(database_url)
    Base.metadata.tables[TABLE].create(engine)
    command.upgrade(cfg, "head")
    command.check(cfg)
    _assert_schema(engine)
    engine.dispose()


@pytest.mark.postgres
def test_postgres_upgrade_creates_the_table_and_cascades_on_delete(monkeypatch):
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL não definido.")
    url = db_config.normalize_database_url(TEST_DATABASE_URL)
    if not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL não aponta para PostgreSQL.")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CERTIFICADOS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic_config()
    engine = create_engine(url, future=True)
    try:
        with engine.connect():
            pass
    except Exception:  # noqa: BLE001 - unreachable server → skip, don't fail
        engine.dispose()
        pytest.skip("PostgreSQL de teste indisponível.")

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    try:
        command.upgrade(cfg, "0014")
        with engine.begin() as connection:
            certificate_id = _seed_certificate(connection, "CERT-2026-MIG001")
            before = _signature(connection)
        command.upgrade(cfg, "head")
        command.check(cfg)
        _assert_schema(engine)
        with engine.begin() as connection:
            assert _signature(connection) == before
            connection.execute(
                text(
                    f"INSERT INTO {TABLE} (certificate_id, position, email_hash, hash_key_id) "
                    "VALUES (:id, 1, :digest, 'v1')"
                ),
                {"id": certificate_id, "digest": "a" * 64},
            )
            # Removing a certificate removes its hashes with it.
            connection.execute(
                text("DELETE FROM certificates WHERE id = :id"), {"id": certificate_id}
            )
            assert connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0
        command.downgrade(cfg, "0014")
        assert not inspect(engine).has_table(TABLE)
        command.upgrade(cfg, "head")
        command.check(cfg)
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()
