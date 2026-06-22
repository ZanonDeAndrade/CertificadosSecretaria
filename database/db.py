"""Shared persistence facade for CertificadosSecretaria.

Imported by BOTH projects:

  - certificados-admin   → grava certificados ao gerá-los
  - certificados-consulta → lê certificados (busca por nome / código)

The actual SQL lives in :mod:`database.repositories` (SQLAlchemy), backed by a
pooled engine resolved from ``DATABASE_URL`` (PostgreSQL in production, SQLite in
dev/test). This module keeps the historical function names/shapes so the routes,
services and tests keep working unchanged — it is a thin facade that opens a
transactional session and delegates to a repository.

Path resolution (single source of truth for both projects):

  DATABASE_URL  env var → PostgreSQL em produção (obrigatório).
                          Em dev/test, um SQLite local é usado:
  DB_PATH       env var → arquivo .db (default: <repo>/database/certificates.db)
  STORAGE_DIR/LOCAL_STORAGE_PATH → raiz do storage LOCAL (apenas dev/legado).

Import-safe: never opens a connection at import time.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from . import config, engine
from .models import Base
from .repositories import (
    AdminUserRepository,
    AuditLogRepository,
    AuthSessionRepository,
    CertificateRepository,
    LoginThrottleRepository,
    PublicRateLimitRepository,
    TemplateVersionRepository,
)

# database/db.py lives in <repo_root>/database/db.py
REPO_ROOT = config.REPO_ROOT


def _path_from_env(default: Path, *vars: str) -> Path:
    for var in vars:
        raw = os.getenv(var, "").strip()
        if raw:
            return Path(raw).expanduser()
    return default


# ── Shared paths ───────────────────────────────────────────────────────────────
# DATABASE_PATH is the *local SQLite* file location (dev/test). In production the
# engine comes from DATABASE_URL and this value is unused. Kept module-level so
# tests can monkeypatch it (the engine URL is derived from it when DATABASE_URL
# is not set).
DATABASE_PATH: Path = _path_from_env(
    REPO_ROOT / "database" / "certificates.db", "DB_PATH", "DATABASE_PATH"
)
# Local PDF storage root (development / legacy fallback only).
STORAGE_DIR: Path = _path_from_env(
    REPO_ROOT / "storage", "LOCAL_STORAGE_PATH", "STORAGE_DIR"
)
PDFS_DIR: Path = STORAGE_DIR / "pdfs"


def _current_database_url() -> str:
    """Resolve the SQLAlchemy URL for the current process/test.

    ``DATABASE_URL`` (env) wins. Otherwise, in dev/test, a SQLite URL is derived
    from the (monkeypatch-friendly) module-level ``DATABASE_PATH``. In production
    a missing ``DATABASE_URL`` is a hard error (fail-closed).
    """
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if raw:
        return config.normalize_database_url(raw)
    if config.is_production():
        raise config.ConfigError(
            "APP_ENV=production exige DATABASE_URL (PostgreSQL)."
        )
    return f"sqlite:///{Path(DATABASE_PATH).as_posix()}"


def _session():
    return engine.session_scope(_current_database_url())


# ── Legacy SQLite auto-migration (dev only) ────────────────────────────────────
# Columns added after the initial release; applied to OLD SQLite databases that
# predate them (PostgreSQL schema is owned by Alembic migrations). Keep in sync
# with database/models.py.
_EXTRA_COLUMNS: dict[str, str] = {
    "storage_provider": "TEXT NOT NULL DEFAULT 'local'",
    "drive_file_id": "TEXT",
    "drive_folder_id": "TEXT",
    "original_filename": "TEXT",
    "mime_type": "TEXT NOT NULL DEFAULT 'application/pdf'",
    "file_size": "INTEGER",
    "checksum_sha256": "TEXT",
    "integrity_blocked": "INTEGER NOT NULL DEFAULT 0",
    "status": "TEXT NOT NULL DEFAULT 'ativo'",
    "participant_email": "TEXT",
    "participant_document": "TEXT",
    "participant_name_normalized": "TEXT",
    "participant_document_hash": "TEXT",
    "course_name": "TEXT",
    "workload_hours": "INTEGER",
    "start_date": "TEXT",
    "end_date": "TEXT",
    "business_key": "TEXT",
    "template_used": "TEXT",
    "template_version_id": "INTEGER",
    "template_snapshot": "TEXT",
    "issued_by": "INTEGER",
    "revoked_at": "TEXT",
    "revoked_by": "INTEGER",
    "revoke_reason": "TEXT",
    "updated_at": "TEXT",
}

_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_certificates_participant_name ON certificates (participant_name)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_name_normalized ON certificates (participant_name_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_name_normalized_status ON certificates (participant_name_normalized, status)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_event_name ON certificates (event_name)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_course_name ON certificates (course_name)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_status ON certificates (status)",
    # Chronological ordering/filtering uses the real (ISO) issue date.
    "CREATE INDEX IF NOT EXISTS idx_certificates_issue_date ON certificates (issue_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_certificates_business_key ON certificates (business_key)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log (created_at)",
)


def _legacy_sqlite_migrate(eng) -> None:
    """Add any columns/indexes missing on a pre-existing SQLite database.

    Safe and idempotent; PostgreSQL is migrated with Alembic instead.
    """
    with eng.begin() as conn:
        existing = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(certificates)").fetchall()
        }
        if existing:  # table already there → add any missing columns
            for column, ddl in _EXTRA_COLUMNS.items():
                if column not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE certificates ADD COLUMN {column} {ddl}"
                    )
        for statement in _INDEXES:
            conn.exec_driver_sql(statement)


def init_db() -> None:
    """Ensure the schema exists. Idempotent; safe on every startup.

    - **production**: schema is owned by Alembic; this only checks connectivity.
    - **dev/test**: creates the tables from the ORM metadata and applies the
      legacy SQLite auto-migration for old databases.
    """
    url = _current_database_url()
    eng = engine.get_engine(url)
    if config.is_production():
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return
    Base.metadata.create_all(eng)
    if config.is_sqlite_url(url):
        _legacy_sqlite_migrate(eng)


def prepare_private_data() -> int:
    """Backfill searchable names/hashes and erase legacy plaintext when configured."""
    from .privacy import document_hash, normalize_name
    from .models import Certificate
    from sqlalchemy import select

    changed = 0
    minimize = os.getenv("MINIMIZE_DOCUMENT_PLAINTEXT", "true").strip().lower() not in {"0", "false", "no"}
    with _session() as session:
        rows = session.execute(select(Certificate)).scalars().all()
        for row in rows:
            normalized_name = normalize_name(row.participant_name)
            hashed_document = row.participant_document_hash or document_hash(row.participant_document)
            if row.participant_name_normalized != normalized_name:
                row.participant_name_normalized = normalized_name
                changed += 1
            if row.participant_document_hash != hashed_document:
                row.participant_document_hash = hashed_document
                changed += 1
            if minimize and row.participant_document is not None:
                row.participant_document = None
                changed += 1
        try:
            retention_days = max(0, int(os.getenv("PRIVATE_DATA_RETENTION_DAYS", "0")))
        except ValueError:
            retention_days = 0
        if retention_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            result = session.execute(
                update(Certificate)
                .where(Certificate.created_at < cutoff)
                .where(
                    (Certificate.participant_email.is_not(None))
                    | (Certificate.participant_document.is_not(None))
                )
                .values(participant_email=None, participant_document=None)
            )
            changed += int(result.rowcount or 0)
    return changed


# ── Certificates: writes ────────────────────────────────────────────────────────

def insert_certificates(rows: list[dict]) -> None:
    """Strict insert (no INSERT OR IGNORE). Raises on a UNIQUE conflict."""
    if not rows:
        return
    with _session() as s:
        CertificateRepository(s).insert_many(rows)


# ── Saga: reservation / finalization / failure ──────────────────────────────────

def reserve_certificate(
    *,
    business_key: str | None,
    fields: dict,
    code_factory: Callable[[], str],
    max_attempts: int = 25,
) -> tuple[str | None, dict | None]:
    """Atomically reserve a ``pending`` certificate. Returns ``(code, existing)``.

    - ``(code, None)``     → a new reservation was committed under ``code``.
    - ``(None, existing)`` → the ``business_key`` already exists (duplicate).

    Uniqueness is enforced by the database UNIQUE constraints — never by a check
    outside the transaction. Each attempt is its own committed transaction, and
    a ``business_key`` conflict is resolved with a FRESH read (so concurrently
    committed rows are visible, avoiding snapshot pitfalls on SQLite).
    """
    if business_key:
        existing = get_by_business_key(business_key)
        if existing is not None:
            return None, existing

    for _ in range(max_attempts):
        code = code_factory()
        try:
            with _session() as s:
                CertificateRepository(s).insert_pending(
                    code=code, business_key=business_key, fields=fields
                )
            return code, None
        except IntegrityError:
            # A business_key collision (concurrent insert) → report duplicate;
            # otherwise it was a unique_code collision → retry with a new code.
            if business_key:
                existing = get_by_business_key(business_key)
                if existing is not None:
                    return None, existing
            continue
    raise RuntimeError(
        "Não foi possível reservar um código único após várias tentativas."
    )


def finalize_certificate(unique_code: str, drive_fields: dict) -> bool:
    """Promote a reserved row to ``ativo`` with storage metadata (saga step 3)."""
    with _session() as s:
        return CertificateRepository(s).finalize(unique_code, drive_fields)


def mark_certificate_failed(
    unique_code: str,
    *,
    drive_file_id: str | None = None,
    drive_folder_id: str | None = None,
    pdf_path: str | None = None,
) -> bool:
    """Mark a certificate ``failed`` (saga compensation), recording orphan pointers."""
    with _session() as s:
        return CertificateRepository(s).mark_failed(
            unique_code,
            drive_file_id=drive_file_id,
            drive_folder_id=drive_folder_id,
            pdf_path=pdf_path,
        )


def clear_certificate_storage(unique_code: str) -> bool:
    """Null out storage pointers after a successful compensating delete."""
    with _session() as s:
        return CertificateRepository(s).clear_storage(unique_code)


def list_pending_certificates(cutoff: datetime) -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).pending_older_than(cutoff)


def list_active_without_file() -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).active_without_file()


def list_failed_with_orphan() -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).failed_with_orphan_file()


def block_certificate_integrity(unique_code: str) -> bool:
    """Mark a certificate as integrity-blocked (tampered/corrupt file)."""
    with _session() as s:
        return CertificateRepository(s).set_integrity_blocked(unique_code, True)


def list_active_with_remote_file() -> list[dict]:
    """Active, non-blocked certificates that have a file to verify periodically."""
    with _session() as s:
        return CertificateRepository(s).active_with_remote_file()


def drive_file_index() -> dict[str, str]:
    """``drive_file_id -> unique_code`` for every certificate stored on Drive."""
    with _session() as s:
        return CertificateRepository(s).drive_file_index()


# ── Certificates: reads ─────────────────────────────────────────────────────────

def get_by_code(unique_code: str) -> dict | None:
    with _session() as s:
        return CertificateRepository(s).get_by_code(unique_code)


def search_by_name(name: str) -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).search_by_name(name)


def certificates_by_normalized_name(name: str, limit: int = 100) -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).by_normalized_name(name, limit)


def resolve_pdf_path(pdf_path: str) -> Path:
    """Resolve a stored (STORAGE_DIR-relative) pdf_path to an absolute path.

    Absolute paths are returned unchanged (legacy/external rows still work).
    """
    candidate = Path(pdf_path)
    return candidate if candidate.is_absolute() else (STORAGE_DIR / candidate)


def business_key_exists(business_key: str) -> bool:
    return get_by_business_key(business_key) is not None


def get_by_business_key(business_key: str) -> dict | None:
    with _session() as s:
        return CertificateRepository(s).get_by_business_key(business_key)


def list_certificates(
    *,
    name: str | None = None,
    code: str | None = None,
    course: str | None = None,
    event: str | None = None,
    status: str | None = None,
    statuses: tuple[str, ...] | None = None,
    order_by: str = "created_at",
    descending: bool = True,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    with _session() as s:
        return CertificateRepository(s).list(
            name=name, code=code, course=course, event=event, status=status, statuses=statuses,
            order_by=order_by, descending=descending, limit=limit, offset=offset,
        )


def certificates_pending_drive_migration() -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).pending_drive_migration()


def set_drive_metadata(
    unique_code: str,
    *,
    drive_file_id: str,
    drive_folder_id: str | None,
    original_filename: str | None,
    mime_type: str | None,
    file_size: int | None,
    checksum_sha256: str | None,
) -> bool:
    with _session() as s:
        return CertificateRepository(s).set_drive_metadata(
            unique_code,
            drive_file_id=drive_file_id,
            drive_folder_id=drive_folder_id,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=file_size,
            checksum_sha256=checksum_sha256,
        )


def update_certificate_file(unique_code: str, fields: dict) -> bool:
    with _session() as s:
        return CertificateRepository(s).update_file(unique_code, fields)


def update_certificate_status(
    unique_code: str,
    *,
    status: str,
    revoked_by: int | None = None,
    revoke_reason: str | None = None,
) -> bool:
    with _session() as s:
        return CertificateRepository(s).update_status(
            unique_code, status=status, revoked_by=revoked_by, revoke_reason=revoke_reason
        )


# ── Admin users ─────────────────────────────────────────────────────────────────

def get_admin_user_by_username(username: str) -> dict | None:
    with _session() as s:
        return AdminUserRepository(s).get_by_username(username)


def get_admin_user_by_id(user_id: int) -> dict | None:
    with _session() as s:
        return AdminUserRepository(s).get_by_id(user_id)


def create_admin_user(username: str, password_hash: str, role: str = "secretaria") -> int | None:
    with _session() as s:
        return AdminUserRepository(s).create(username, password_hash, role)


def count_admin_users() -> int:
    with _session() as s:
        return AdminUserRepository(s).count()


def set_admin_user_active(user_id: int, active: bool) -> bool:
    with _session() as s:
        changed = AdminUserRepository(s).set_active(user_id, active)
        if changed and not active:
            AuthSessionRepository(s).revoke_all(user_id, "user_deactivated")
        return changed


def set_admin_user_role(user_id: int, role: str) -> bool:
    with _session() as s:
        return AdminUserRepository(s).set_role(user_id, role)


# ── Revocable authentication sessions ───────────────────────────────────────


def create_auth_session(
    *,
    session_id: str,
    user_id: int,
    expires_at: datetime,
    ip_hash: str | None = None,
    user_agent_hash: str | None = None,
) -> None:
    with _session() as s:
        AuthSessionRepository(s).create(
            session_id=session_id,
            user_id=user_id,
            expires_at=expires_at,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )


def get_active_auth_session(session_id: str, now: datetime) -> dict | None:
    with _session() as s:
        return AuthSessionRepository(s).get_active(session_id, now)


def revoke_auth_session(session_id: str, reason: str = "logout") -> bool:
    with _session() as s:
        return AuthSessionRepository(s).revoke(session_id, reason)


def revoke_all_auth_sessions(user_id: int, reason: str = "revoke_all") -> int:
    with _session() as s:
        return AuthSessionRepository(s).revoke_all(user_id, reason)


def cleanup_auth_sessions(before: datetime) -> int:
    with _session() as s:
        return AuthSessionRepository(s).cleanup(before)


def set_auth_session_expiry(session_id: str, expires_at: datetime) -> bool:
    with _session() as s:
        return AuthSessionRepository(s).set_expiry(session_id, expires_at)


# ── Distributed login throttling (shared SQL database) ──────────────────────


def get_login_throttles(scopes: list[tuple[str, str]]) -> list[dict]:
    with _session() as s:
        return LoginThrottleRepository(s).get_many(scopes)


def record_login_failures(
    scopes: list[tuple[str, str, int]],
    *,
    now: datetime,
    window_seconds: int,
    lockout_seconds: int,
) -> list[dict]:
    # A concurrent first failure can race on the composite primary key. Retry
    # the whole transaction once; subsequent updates use SELECT ... FOR UPDATE.
    for attempt in range(2):
        try:
            with _session() as s:
                return LoginThrottleRepository(s).record_failures(
                    scopes,
                    now=now,
                    window_seconds=window_seconds,
                    lockout_seconds=lockout_seconds,
                )
        except IntegrityError:
            if attempt:
                raise
    return []  # pragma: no cover


def clear_login_throttle(scope_type: str, key: str) -> None:
    with _session() as s:
        LoginThrottleRepository(s).clear(scope_type, key)


def cleanup_login_throttles(before: datetime) -> int:
    with _session() as s:
        return LoginThrottleRepository(s).cleanup(before)


def consume_public_rate_limit(
    bucket_key: str, *, now: datetime, window_seconds: int, limit: int
) -> tuple[bool, int]:
    for attempt in range(2):
        try:
            with _session() as s:
                return PublicRateLimitRepository(s).consume(
                    bucket_key, now=now, window_seconds=window_seconds, limit=limit
                )
        except IntegrityError:
            if attempt:
                raise
    return False, window_seconds


def cleanup_public_rate_limits(before: datetime) -> int:
    with _session() as s:
        return PublicRateLimitRepository(s).cleanup(before)


# ── Template versions (single global template) ──────────────────────────────────

def create_template_version(
    *,
    name: str | None,
    layout_json: str,
    image_width: int,
    image_height: int,
    background_image: bytes | None,
    background_mime_type: str,
    created_by: int | None = None,
) -> dict:
    with _session() as s:
        return TemplateVersionRepository(s).create(
            name=name,
            layout_json=layout_json,
            image_width=image_width,
            image_height=image_height,
            background_image=background_image,
            background_mime_type=background_mime_type,
            created_by=created_by,
        )


def get_template_version(version_id: int) -> dict | None:
    with _session() as s:
        return TemplateVersionRepository(s).get(version_id)


def get_active_template_version() -> dict | None:
    with _session() as s:
        return TemplateVersionRepository(s).get_active()


def list_template_versions() -> list[dict]:
    with _session() as s:
        return TemplateVersionRepository(s).list_all()


def count_template_versions() -> int:
    with _session() as s:
        return TemplateVersionRepository(s).count()


def get_template_background(version_id: int) -> tuple[bytes | None, str] | None:
    with _session() as s:
        return TemplateVersionRepository(s).get_background(version_id)


def activate_template_version(version_id: int, actor: int | None = None) -> bool:
    with _session() as s:
        return TemplateVersionRepository(s).activate(version_id, actor)


# ── Audit log ───────────────────────────────────────────────────────────────────

def insert_audit_log(
    *,
    action: str,
    actor_id: int | None = None,
    actor_username: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: str | None = None,
) -> None:
    with _session() as s:
        AuditLogRepository(s).insert(
            action=action,
            actor_id=actor_id,
            actor_username=actor_username,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )


def list_audit_logs(action: str | None = None, limit: int = 100) -> list[dict]:
    with _session() as s:
        return AuditLogRepository(s).list(action=action, limit=limit)
