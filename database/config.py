"""Database configuration (shared by certificados-admin and certificados-consulta).

Single source of truth for:

  - ``APP_ENV``        → "development" (default) | "local_server" | "production"
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

import ipaddress
import os
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

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


if (os.getenv("CERTIFICADOS_DISABLE_DOTENV") or "").strip().lower() not in {
    "1",
    "true",
    "yes",
}:
    _load_dotenv(REPO_ROOT / ".env")


# ── App environment ────────────────────────────────────────────────────────────


def get_app_env() -> str:
    return (os.getenv("APP_ENV") or "development").strip().lower()


def is_production() -> bool:
    return get_app_env() in ("prod", "production")


def is_local_server() -> bool:
    """True for the hardened HTTP deployment used only inside a trusted LAN."""
    return get_app_env() in {"local_server", "local-server", "lan"}


def requires_postgresql() -> bool:
    """Whether this runtime must use PostgreSQL instead of the dev SQLite fallback."""
    return is_production() or is_local_server()


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
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def read_secret(name: str) -> str:
    """Read ``NAME`` or ``NAME_FILE`` without logging the secret value."""
    direct = (os.getenv(name) or "").strip()
    if direct:
        return direct
    file_path = (os.getenv(f"{name}_FILE") or "").strip()
    if not file_path:
        return ""
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise ConfigError(f"{name}_FILE configurado não foi encontrado.")
    value = path.read_text("utf-8").strip()
    if not value or "\n" in value or "\r" in value:
        raise ConfigError(f"{name}_FILE deve conter somente um valor.")
    return value


def get_configured_database_url() -> str:
    """Return the explicitly configured URL, supporting a secret file.

    ``DATABASE_URL`` wins. ``DATABASE_URL_FILE`` is intended for Docker/Kubernetes
    secrets and local secure files so the password does not need to live in the
    repository-level ``.env``.
    """
    return read_secret("DATABASE_URL")


def get_database_url() -> str | None:
    """Return the effective DATABASE_URL, or ``None`` when unresolved in prod.

    - ``DATABASE_URL`` env → normalised and returned.
    - else, in production → ``None`` (caller must fail-closed).
    - else (dev/test) → local SQLite URL.
    """
    raw = get_configured_database_url()
    if raw:
        return normalize_database_url(raw)
    if requires_postgresql():
        return None
    return default_sqlite_url()


def is_sqlite_url(url: str | None) -> bool:
    return url is not None and url.startswith("sqlite")


# ── Connection pool tuning (PostgreSQL) ────────────────────────────────────────


def _int_env(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def pool_settings() -> dict:
    """Keyword args for ``create_engine`` pooling (PostgreSQL/server engines)."""
    return {
        "pool_size": _int_env("DB_POOL_SIZE", 5),
        "max_overflow": _int_env("DB_MAX_OVERFLOW", 10),
        "pool_timeout": _int_env("DB_POOL_TIMEOUT", 30),
        "pool_recycle": _int_env("DB_POOL_RECYCLE", 1800),
        # Keep the safe production default. Local development may explicitly
        # disable this extra round-trip when using a managed pooler such as
        # Neon; pool_recycle still limits how long a connection is retained.
        "pool_pre_ping": _bool_env("DB_POOL_PRE_PING", True),
    }


# ── Fail-closed startup validation (production) ────────────────────────────────


class ConfigError(RuntimeError):
    """Raised at startup when a required production setting is missing."""


def validate_forwarded_allow_ips() -> None:
    """Reject wildcard/unbounded proxy trust before a production app starts."""

    raw = (os.getenv("FORWARDED_ALLOW_IPS") or "").strip()
    if not raw:
        if requires_postgresql():
            raise ConfigError("Em produção, FORWARDED_ALLOW_IPS deve listar proxies confiáveis.")
        return
    for item in (part.strip() for part in raw.split(",")):
        if not item or item == "*":
            raise ConfigError("FORWARDED_ALLOW_IPS não aceita curinga.")
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError as exc:
            raise ConfigError("FORWARDED_ALLOW_IPS contém IP/CIDR inválido.") from exc
        if network.prefixlen == 0:
            raise ConfigError("FORWARDED_ALLOW_IPS não aceita rede irrestrita.")


def require_production_database() -> None:
    """Abort hardened runtimes unless they use PostgreSQL.

    The local-server profile talks to a PostgreSQL container over an isolated
    Docker network, where TLS would add no transport boundary. Public
    production still requires certificate verification for external databases.
    """
    if not requires_postgresql():
        return
    url = get_configured_database_url()
    if not url:
        raise ConfigError(
            "APP_ENV exige PostgreSQL. Defina DATABASE_URL ou DATABASE_URL_FILE."
        )
    normalized = normalize_database_url(url)
    if not normalized.startswith("postgresql"):
        raise ConfigError(
            "Em produção, DATABASE_URL deve apontar para um PostgreSQL "
            f"(recebido: esquema não suportado em '{normalized.split('://', 1)[0]}://')."
        )
    try:
        parsed = make_url(normalized)
    except (ArgumentError, ValueError) as exc:
        raise ConfigError("DATABASE_URL de produção é inválida.") from exc
    sslmode = str(parsed.query.get("sslmode") or "").strip().lower()
    if is_production() and sslmode != "verify-full":
        raise ConfigError(
            "Em produção, PostgreSQL exige sslmode=verify-full para validar "
            "a CA e o hostname do servidor."
        )
