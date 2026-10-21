"""Alembic environment for CertificadosSecretaria.

The URL is resolved from :mod:`database.config` (DATABASE_URL in production,
local SQLite in development), so the same migrations run against PostgreSQL and
SQLite. Batch mode is enabled for SQLite so ALTER operations work there too.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from database import config as db_config
from database.models import Base

cfg = context.config
if cfg.config_file_name is not None:
    fileConfig(cfg.config_file_name)

target_metadata = Base.metadata

# Resolve the effective URL (env DATABASE_URL or local SQLite default).
_URL = db_config.get_database_url() or db_config.default_sqlite_url()
cfg.set_main_option("sqlalchemy.url", _URL)

_IS_SQLITE = db_config.is_sqlite_url(_URL)


def include_object(obj, name, type_, reflected, compare_to):
    """Keep the PostgreSQL-only trigram index out of autogenerate drift.

    The index is created explicitly by migration 0004 and intentionally is not
    part of portable ORM metadata, because SQLite cannot represent GIN/trgm.
    """

    if type_ == "index" and name == "idx_certificates_name_normalized_trgm":
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=_IS_SQLITE,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        cfg.get_section(cfg.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=_IS_SQLITE,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
