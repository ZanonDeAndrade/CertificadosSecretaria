"""SQLAlchemy engine + session management with connection pooling.

A single engine is cached per resolved URL, so:

  - production (PostgreSQL) gets a pooled engine (``pool_pre_ping`` + recycle);
  - development/test (SQLite) gets a thread-safe engine with the WAL +
    ``foreign_keys`` pragmas the old hand-written layer set.

``session_scope()`` is the unit of work: it commits on success, rolls back on
error, and always closes the session — giving repositories real transactions.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from . import config

# url -> (engine, session_factory)
_REGISTRY: dict[str, tuple[Engine, sessionmaker]] = {}


def _build(url: str) -> tuple[Engine, sessionmaker]:
    if config.is_sqlite_url(url):
        connect_args = {"check_same_thread": False}
        if ":memory:" in url or url == "sqlite://":
            engine = create_engine(
                url, connect_args=connect_args, poolclass=StaticPool, future=True
            )
        else:
            engine = create_engine(url, connect_args=connect_args, future=True)

        # pysqlite does not honour transactions/SAVEPOINTs correctly unless
        # SQLAlchemy is left in charge of emitting BEGIN. Disable the driver's
        # implicit transaction handling and emit BEGIN ourselves so rollbacks
        # (and nested savepoints used by the repository) behave like PostgreSQL.
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            # Let concurrent writers wait for the lock instead of failing fast —
            # the saga reserves rows from multiple workers/threads.
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        @event.listens_for(engine, "begin")
        def _sqlite_begin(conn):  # noqa: ANN001
            conn.exec_driver_sql("BEGIN")
    else:
        engine = create_engine(url, future=True, **config.pool_settings())

    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return engine, factory


def _resolve(url: str | None) -> tuple[Engine, sessionmaker]:
    if not url:
        raise config.ConfigError(
            "DATABASE_URL não resolvido. Em produção defina DATABASE_URL "
            "(PostgreSQL); em desenvolvimento um SQLite local é usado."
        )
    if url not in _REGISTRY:
        _REGISTRY[url] = _build(url)
    return _REGISTRY[url]


def get_engine(url: str | None) -> Engine:
    return _resolve(url)[0]


def get_session_factory(url: str | None) -> sessionmaker:
    return _resolve(url)[1]


@contextmanager
def session_scope(url: str | None) -> Iterator[Session]:
    """Transactional session: commit on success, rollback on error, always close."""
    factory = get_session_factory(url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engines() -> None:
    """Dispose and forget all cached engines (used by tests after env changes)."""
    for engine, _factory in _REGISTRY.values():
        engine.dispose()
    _REGISTRY.clear()
