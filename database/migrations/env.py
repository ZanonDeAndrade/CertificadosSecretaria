"""Alembic environment for CertificadosSecretaria.

The URL is resolved from :mod:`database.config` (DATABASE_URL in production,
local SQLite in development), so the same migrations run against PostgreSQL and
SQLite. Batch mode is enabled for SQLite so ALTER operations work there too.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the shared `database` package importable (repo root is two levels up).
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from database import config as db_config  # noqa: E402
from database.models import Base  # noqa: E402

cfg = context.config
if cfg.config_file_name is not None:
    fileConfig(cfg.config_file_name)

target_metadata = Base.metadata

# Resolve the effective URL (env DATABASE_URL or local SQLite default).
_URL = db_config.get_database_url() or db_config.default_sqlite_url()
cfg.set_main_option("sqlalchemy.url", _URL)

_IS_SQLITE = db_config.is_sqlite_url(_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=_IS_SQLITE,
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
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
