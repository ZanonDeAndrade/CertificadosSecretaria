"""Migration 0014: versions become models, courses are registered, and the
certificate → version link gains a foreign key.

The grouping rules are unit-tested on synthetic versions, then the migration
itself runs on SQLite (always) and on PostgreSQL when ``TEST_DATABASE_URL``
points at a disposable database. Nothing here touches real data.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from database import config as db_config
from database.template_grouping import VersionRow, group_versions

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()
MOSTRA = "scientific_initiation"


def _alembic_config() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


def _row(
    number: int,
    name: str | None,
    *,
    certificate_type: str | None = None,
    active: bool = False,
) -> VersionRow:
    return VersionRow(
        id=number,
        version_number=number,
        name=name,
        certificate_type=certificate_type,
        is_active=active,
    )


# ── Grouping rules ─────────────────────────────────────────────────────────────


def test_real_history_becomes_two_models_with_the_active_version_current():
    """The AMF database of 2026-10-28: v1 and v4 deleted, v6 copied across types."""
    groups = group_versions(
        [
            _row(2, "Cópia de v1"),
            _row(3, "Cópia de v2"),
            _row(5, "Cópia de v4", active=True),
            _row(6, "Cópia de v5", certificate_type=MOSTRA),
            _row(7, "Cópia de v6", certificate_type=MOSTRA, active=True),
        ]
    )
    by_name = {group.name: group for group in groups}
    assert set(by_name) == {"Modelo genérico", "Modelo Mostra de Iniciação Científica"}
    generic = by_name["Modelo genérico"]
    assert generic.version_ids == [2, 3, 5] and generic.current_version_id == 5
    mostra = by_name["Modelo Mostra de Iniciação Científica"]
    assert mostra.certificate_type == MOSTRA
    assert mostra.version_ids == [6, 7] and mostra.current_version_id == 7


def test_a_named_inactive_version_and_its_copies_form_their_own_model():
    groups = group_versions(
        [
            _row(5, "Cópia de v4", active=True),
            _row(10, "Certificado_OPL"),
            _row(11, "Cópia de v10"),
        ]
    )
    by_name = {group.name: group for group in groups}
    assert set(by_name) == {"Modelo genérico", "Certificado_OPL"}
    opl = by_name["Certificado_OPL"]
    # The copy follows its chain and, with no active version, the newest is current.
    assert opl.version_ids == [10, 11] and opl.current_version_id == 11


def test_versions_newer_than_the_active_one_split_into_a_draft_model():
    groups = group_versions(
        [
            _row(3, "Cópia de v2"),
            _row(4, "Cópia de v3", active=True),
            _row(5, "Cópia de v4"),
            _row(6, "Cópia de v5"),
        ]
    )
    by_name = {group.name: group for group in groups}
    assert by_name["Modelo genérico"].version_ids == [3, 4]
    assert by_name["Modelo genérico"].current_version_id == 4
    draft = by_name["Cópia de v5"]
    assert draft.version_ids == [5, 6] and draft.current_version_id == 6


def test_an_active_version_with_its_own_name_names_the_type_model():
    groups = group_versions(
        [
            _row(1, "Padrão"),
            _row(2, "Nova versão"),
            _row(3, "Modelo 2026", active=True),
            _row(4, "Ajuste de assinatura"),
        ]
    )
    by_name = {group.name: group for group in groups}
    assert by_name["Modelo 2026"].version_ids == [1, 2, 3]
    assert by_name["Ajuste de assinatura"].version_ids == [4]


def test_duplicate_model_names_are_made_unique():
    groups = group_versions([_row(1, "Mesmo nome"), _row(2, "Mesmo nome")])
    assert sorted(group.name for group in groups) == ["Mesmo nome", "Mesmo nome (2)"]


def test_no_versions_means_no_models():
    assert group_versions([]) == []


# ── The migration on SQLite ────────────────────────────────────────────────────


def _seed_versions(connection, *, orphan: bool) -> None:
    rows = [
        (2, "Cópia de v1", None, 0, None),
        (3, "Cópia de v2", None, 0, None),
        (5, "Cópia de v4", None, 1, "__generic__"),
        (6, "Cópia de v5", MOSTRA, 0, None),
        (7, "Cópia de v6", MOSTRA, 1, MOSTRA),
        (10, "Certificado_OPL", None, 0, None),
    ]
    for version_id, name, certificate_type, is_active, key in rows:
        connection.execute(
            text(
                "INSERT INTO template_versions (id, version_number, name, layout_json, "
                "image_width, image_height, background_mime_type, is_active, certificate_type, "
                "active_type_key) VALUES (:id, :id, :name, '{}', 100, 70, 'image/png', "
                ":is_active, :certificate_type, :key)"
            ),
            {
                "id": version_id,
                "name": name,
                "is_active": is_active,
                "certificate_type": certificate_type,
                "key": key,
            },
        )
    certificates = [("CERT-2026-MIG001", 3), ("CERT-2026-MIG002", 6)]
    if orphan:
        certificates.append(("CERT-2026-MIG404", 1))
    for code, version_id in certificates:
        connection.execute(
            text(
                "INSERT INTO certificates (unique_code, participant_name, event_name, "
                "issue_date, status, template_version_id, template_snapshot) "
                "VALUES (:code, 'Pessoa Exemplo Alfa', 'Evento Sintético', '2026-08-15', "
                "'ativo', :version_id, '{}')"
            ),
            {"code": code, "version_id": version_id},
        )


def _models(connection) -> dict[str, dict]:
    rows = connection.execute(
        text(
            "SELECT t.id, t.name, t.certificate_type, t.revision, "
            "(SELECT group_concat(v.version_number) FROM template_versions v "
            " WHERE v.template_id = t.id) AS numbers "
            "FROM certificate_templates t ORDER BY t.id"
        )
    ).all()
    return {
        row.name: {
            "id": row.id,
            "type": row.certificate_type,
            "revision": row.revision,
            "numbers": sorted(int(n) for n in str(row.numbers).split(",")),
        }
        for row in rows
    }


def _prepare(tmp_path, monkeypatch, name: str) -> tuple[Config, str]:
    database_url = f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CERTIFICADOS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("DATABASE_URL", database_url)
    return _alembic_config(), database_url


def test_upgrade_files_versions_under_models_and_seeds_courses(tmp_path, monkeypatch):
    cfg, database_url = _prepare(tmp_path, monkeypatch, "templates.db")
    command.upgrade(cfg, "0013")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_versions(connection, orphan=False)

    command.upgrade(cfg, "head")
    command.check(cfg)

    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0015"
        )
        models = _models(connection)
        assert models["Modelo genérico"]["numbers"] == [2, 3, 5]
        assert models["Modelo genérico"]["revision"] == 3
        assert models["Modelo Mostra de Iniciação Científica"]["numbers"] == [6, 7]
        assert models["Modelo Mostra de Iniciação Científica"]["type"] == MOSTRA
        assert models["Certificado_OPL"]["numbers"] == [10]
        # Versions, their numbers, names and activity are untouched.
        active = connection.execute(
            text("SELECT version_number FROM template_versions WHERE is_active = 1 ORDER BY 1")
        ).scalars()
        assert list(active) == [5, 7]
        assert (
            connection.execute(
                text("SELECT count(*) FROM template_versions WHERE template_id IS NULL")
            ).scalar_one()
            == 0
        )
        courses = connection.execute(text("SELECT name FROM courses ORDER BY name")).scalars()
        assert "Sistemas de Informação" in list(courses)
        assert connection.execute(text("SELECT count(*) FROM courses")).scalar_one() == 8
        foreign_keys = {
            fk["name"] for fk in inspect(engine).get_foreign_keys("certificates") if fk["name"]
        }
        assert "fk_certificates_template_version_id" in foreign_keys

    # The key is enforced: a version a certificate points at cannot be deleted.
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = ON"))
        with pytest.raises(IntegrityError):
            connection.execute(text("DELETE FROM template_versions WHERE id = 3"))


def test_downgrade_keeps_every_version_and_upgrade_runs_again(tmp_path, monkeypatch):
    cfg, database_url = _prepare(tmp_path, monkeypatch, "roundtrip.db")
    command.upgrade(cfg, "0013")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_versions(connection, orphan=False)
    command.upgrade(cfg, "head")

    command.downgrade(cfg, "0013")
    with engine.connect() as connection:
        tables = set(inspect(engine).get_table_names())
        assert "certificate_templates" not in tables and "courses" not in tables
        columns = {column["name"] for column in inspect(engine).get_columns("template_versions")}
        assert "template_id" not in columns
        assert connection.execute(text("SELECT count(*) FROM template_versions")).scalar_one() == 6
        assert connection.execute(text("SELECT count(*) FROM certificates")).scalar_one() == 2

    command.upgrade(cfg, "head")
    command.check(cfg)
    with engine.connect() as connection:
        assert len(_models(connection)) == 3


def test_sqlite_skips_the_certificate_key_when_an_orphan_exists(tmp_path, monkeypatch, capfd):
    cfg, database_url = _prepare(tmp_path, monkeypatch, "orphan.db")
    command.upgrade(cfg, "0013")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_versions(connection, orphan=True)

    capfd.readouterr()
    command.upgrade(cfg, "head")
    # alembic.ini routes the migration logger to the console (and resets any
    # other handler on each run), so the warning is read from stderr.
    assert "versões inexistentes" in capfd.readouterr().err

    foreign_keys = {
        fk["name"] for fk in inspect(engine).get_foreign_keys("certificates") if fk["name"]
    }
    assert "fk_certificates_template_version_id" not in foreign_keys
    with engine.connect() as connection:
        # The orphan certificate is exactly as it was.
        assert (
            connection.execute(
                text(
                    "SELECT template_version_id FROM certificates WHERE unique_code = 'CERT-2026-MIG404'"
                )
            ).scalar_one()
            == 1
        )


# ── The migration on PostgreSQL ────────────────────────────────────────────────


@pytest.mark.postgres
def test_postgres_upgrade_survives_an_orphan_with_a_not_valid_key(monkeypatch):
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
        command.upgrade(cfg, "0013")
        with engine.begin() as connection:
            _seed_versions(connection, orphan=True)

        # The orphan does not stop the upgrade, and nothing about it changes.
        command.upgrade(cfg, "head")
        command.check(cfg)
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0015"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT template_version_id FROM certificates "
                        "WHERE unique_code = 'CERT-2026-MIG404'"
                    )
                ).scalar_one()
                == 1
            )
            validated = connection.execute(
                text(
                    "SELECT convalidated FROM pg_constraint "
                    "WHERE conname = 'fk_certificates_template_version_id'"
                )
            ).scalar_one()
            assert validated is False
            models = _models_pg(connection)
            assert models["Modelo genérico"] == [2, 3, 5]
            assert models["Modelo Mostra de Iniciação Científica"] == [6, 7]
            assert models["Certificado_OPL"] == [10]

        # Enforced from now on: new rows and deletions of referenced versions.
        with engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.execute(text("DELETE FROM template_versions WHERE id = 3"))
        with engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO certificates (unique_code, participant_name, event_name, "
                        "issue_date, status, template_version_id) VALUES ('CERT-2026-MIG999', "
                        "'Pessoa Exemplo Beta', 'Evento', '2026-08-15', 'ativo', 999)"
                    )
                )

        command.downgrade(cfg, "0013")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM template_versions")).scalar_one() == 6
            )
            assert connection.execute(text("SELECT count(*) FROM certificates")).scalar_one() == 3
        command.upgrade(cfg, "head")
        command.check(cfg)
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()


def _models_pg(connection) -> dict[str, list[int]]:
    rows = connection.execute(
        text(
            "SELECT t.name, array_agg(v.version_number ORDER BY v.version_number) AS numbers "
            "FROM certificate_templates t JOIN template_versions v ON v.template_id = t.id "
            "GROUP BY t.name"
        )
    ).all()
    return {row.name: list(row.numbers) for row in rows}
