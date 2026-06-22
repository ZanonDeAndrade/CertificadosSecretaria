"""Database configuration (shared by certificados-admin and certificados-consulta).

Single source of truth for:

  - ``APP_ENV``        → "development" (default) | "production"
  - ``DATABASE_URL``   → SQLAlchemy URL (PostgreSQL in production, SQLite in dev/test)
  - connection-pool tuning (PostgreSQL only)

Resolution rules
----------------
* ``DATABASE_URL`` (env) always wins. ``postgres://`` / ``postgresql://`` are
  normalised to the ``postgresql+psycopg`` driver (psycopg 3).
* When ``DATABASE_URL`` is **not** set:
    - in **production** → ``get_database_url()`` returns ``None`` and
      ``require_production_database()`` raises (fail-closed, see startup checks);
    - in **development/test** → a local SQLite file is used (legacy ``DB_PATH`` /
      ``DATABASE_PATH`` are honoured for the file location).

No secret is ever logged or persisted here.
"""
from __future__ import annotations

import os
from pathlib import Path

# database/ lives directly under the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal, dependency-free .env loader (real env vars always win)."""
    if not path.is_file():
        return
    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(REPO_ROOT / ".env")


# ── App environment ────────────────────────────────────────────────────────────

def get_app_env() -> str:
    return (os.getenv("APP_ENV") or "development").strip().lower()


def is_production() -> bool:
    return get_app_env() in ("prod", "production")


# ── Default local SQLite location (development/test only) ──────────────────────

def _default_sqlite_path() -> Path:
    for var in ("DB_PATH", "DATABASE_PATH"):
        raw = os.getenv(var, "").strip()
        if raw:
            return Path(raw).expanduser()
    return REPO_ROOT / "database" / "certificates.db"


def default_sqlite_url() -> str:
    return f"sqlite:///{_default_sqlite_path().as_posix()}"


# ── DATABASE_URL ───────────────────────────────────────────────────────────────

def normalize_database_url(url: str) -> str:
    """Normalise a raw URL to a SQLAlchemy-compatible driver URL.

    ``postgres://`` and ``postgresql://`` → ``postgresql+psycopg://`` (psycopg 3).
    SQLite and already-qualified URLs are returned unchanged.
    """
    url = (url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_database_url() -> str | None:
    """Return the effective DATABASE_URL, or ``None`` when unresolved in prod.

    - ``DATABASE_URL`` env → normalised and returned.
    - else, in production → ``None`` (caller must fail-closed).
    - else (dev/test) → local SQLite URL.
    """
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if raw:
        return normalize_database_url(raw)
    if is_production():
        return None
    return default_sqlite_url()


def is_sqlite_url(url: str | None) -> bool:
    return bool(url) and url.startswith("sqlite")


# ── Connection pool tuning (PostgreSQL) ────────────────────────────────────────

def _int_env(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def pool_settings() -> dict:
    """Keyword args for ``create_engine`` pooling (PostgreSQL/server engines)."""
    return {
        "pool_size": _int_env("DB_POOL_SIZE", 5),
        "max_overflow": _int_env("DB_MAX_OVERFLOW", 10),
        "pool_timeout": _int_env("DB_POOL_TIMEOUT", 30),
        "pool_recycle": _int_env("DB_POOL_RECYCLE", 1800),
        "pool_pre_ping": True,
    }


# ── Fail-closed startup validation (production) ────────────────────────────────

class ConfigError(RuntimeError):
    """Raised at startup when a required production setting is missing."""


def require_production_database() -> None:
    """Abort startup in production when DATABASE_URL is missing or not PostgreSQL."""
    if not is_production():
        return
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise ConfigError(
            "APP_ENV=production exige DATABASE_URL (PostgreSQL). Defina DATABASE_URL."
        )
    normalized = normalize_database_url(url)
    if not normalized.startswith("postgresql"):
        raise ConfigError(
            "Em produção, DATABASE_URL deve apontar para um PostgreSQL "
            f"(recebido: esquema não suportado em '{normalized.split('://', 1)[0]}://')."
        )
