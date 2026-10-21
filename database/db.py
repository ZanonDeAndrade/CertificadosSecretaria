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
    EmissionBatchRepository,
    GoogleDriveIntegrationRepository,
    InstitutionalSettingsRepository,
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
STORAGE_DIR: Path = _path_from_env(REPO_ROOT / "storage", "LOCAL_STORAGE_PATH", "STORAGE_DIR")
PDFS_DIR: Path = STORAGE_DIR / "pdfs"


def _current_database_url() -> str:
    """Resolve the SQLAlchemy URL for the current process/test.

    ``DATABASE_URL`` (env) wins. Otherwise, in dev/test, a SQLite URL is derived
    from the (monkeypatch-friendly) module-level ``DATABASE_PATH``. In production
    a missing ``DATABASE_URL`` is a hard error (fail-closed).
    """
    raw = config.get_configured_database_url()
    if raw:
        return config.normalize_database_url(raw)
    if config.requires_postgresql():
        raise config.ConfigError(
            "Este ambiente exige DATABASE_URL ou DATABASE_URL_FILE (PostgreSQL)."
        )
    return f"sqlite:///{Path(DATABASE_PATH).as_posix()}"


def _session():
    return engine.session_scope(_current_database_url())


def check_connection() -> None:
    """Execute a minimal database round-trip for readiness checks."""
    eng = engine.get_engine(_current_database_url())
    with eng.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()


# ── Legacy SQLite auto-migration (dev only) ────────────────────────────────────
# Columns added after the initial release; applied to OLD SQLite databases that
# predate them (PostgreSQL schema is owned by Alembic migrations). Keep in sync
# with database/models.py.
_EXTRA_COLUMNS: dict[str, str] = {
    # Per-work certificates (authors, team, work title).
    "authors_json": "TEXT",
    "authors_search": "TEXT",
    "team_name": "TEXT",
    "work_title": "TEXT",
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
    "event_name_normalized": "TEXT",
    "participant_document_hash": "TEXT",
    "participant_document_hash_key_id": "TEXT",
    "course_name": "TEXT",
    "certificate_type": "TEXT",
    "workload_hours": "INTEGER",
    "start_date": "TEXT",
    "end_date": "TEXT",
    "business_key": "TEXT",
    "template_used": "TEXT",
    "template_version_id": "INTEGER",
    "template_snapshot": "TEXT",
    "institutional_snapshot": "TEXT",
    "issued_by": "INTEGER",
    "batch_id": "TEXT",
    "revoked_at": "TEXT",
    "revoked_by": "INTEGER",
    "revoke_reason": "TEXT",
    "updated_at": "TEXT",
    "reissue_count": "INTEGER NOT NULL DEFAULT 0",
    "reissued_at": "TEXT",
    "reissued_by": "INTEGER",
}

_ADMIN_USER_EXTRA_COLUMNS: dict[str, str] = {
    "name": "TEXT",
    "must_change_password": "INTEGER NOT NULL DEFAULT 0",
    "password_changed_at": "TEXT",
    "updated_at": "TEXT",
    "created_by": "INTEGER",
}

_EMISSION_BATCH_EXTRA_COLUMNS: dict[str, str] = {
    "certificate_type": "TEXT",
}

_TEMPLATE_VERSION_EXTRA_COLUMNS: dict[str, str] = {
    "certificate_type": "TEXT",
    "active_type_key": "TEXT",
}

_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_certificates_participant_name ON certificates (participant_name)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_name_normalized ON certificates (participant_name_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_name_normalized_status ON certificates (participant_name_normalized, status)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_event_name ON certificates (event_name)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_event_name_normalized ON certificates (event_name_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_course_name ON certificates (course_name)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_status ON certificates (status)",
    # Chronological ordering/filtering uses the real (ISO) issue date.
    "CREATE INDEX IF NOT EXISTS idx_certificates_issue_date ON certificates (issue_date)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_batch_id ON certificates (batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_certificate_type ON certificates (certificate_type)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_certificates_business_key ON certificates (business_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_template_versions_active_type_key ON template_versions (active_type_key)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_action_created_at ON audit_log (action, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_actor_created_at ON audit_log (actor_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_target ON audit_log (target_type, target_id)",
)


def _legacy_sqlite_migrate(eng) -> None:
    """Add any columns/indexes missing on a pre-existing SQLite database.

    Safe and idempotent; PostgreSQL is migrated with Alembic instead.
    """
    with eng.begin() as conn:
        existing = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(certificates)").fetchall()
        }
        if existing:  # table already there → add any missing columns
            for column, ddl in _EXTRA_COLUMNS.items():
                if column not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE certificates ADD COLUMN {column} {ddl}")
            if "event_name_normalized" not in existing:
                _backfill_event_name_normalized(conn)
        existing_users = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(admin_users)").fetchall()
        }
        if existing_users:
            for column, ddl in _ADMIN_USER_EXTRA_COLUMNS.items():
                if column not in existing_users:
                    conn.exec_driver_sql(f"ALTER TABLE admin_users ADD COLUMN {column} {ddl}")
            conn.exec_driver_sql(
                "UPDATE admin_users SET name = username WHERE name IS NULL OR trim(name) = ''"
            )
        existing_batches = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(emission_batches)").fetchall()
        }
        if existing_batches:
            for column, ddl in _EMISSION_BATCH_EXTRA_COLUMNS.items():
                if column not in existing_batches:
                    conn.exec_driver_sql(f"ALTER TABLE emission_batches ADD COLUMN {column} {ddl}")
        existing_versions = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(template_versions)").fetchall()
        }
        if existing_versions:
            # Templates per type: the version active so far becomes the generic
            # one, and one active version per type replaces the single-active rule.
            for column, ddl in _TEMPLATE_VERSION_EXTRA_COLUMNS.items():
                if column not in existing_versions:
                    conn.exec_driver_sql(f"ALTER TABLE template_versions ADD COLUMN {column} {ddl}")
            conn.exec_driver_sql("DROP INDEX IF EXISTS uq_template_versions_single_active")
            conn.exec_driver_sql(
                "UPDATE template_versions SET active_type_key = '__generic__' "
                "WHERE is_active = 1 AND active_type_key IS NULL"
            )
        for statement in _INDEXES:
            conn.exec_driver_sql(statement)


def _backfill_event_name_normalized(conn) -> None:
    """Fill the event search column of rows written before it existed."""
    from .privacy import normalize_name

    rows = conn.exec_driver_sql("SELECT id, event_name FROM certificates").fetchall()
    for row_id, event_name in rows:
        conn.exec_driver_sql(
            "UPDATE certificates SET event_name_normalized = ? WHERE id = ?",
            (normalize_name(event_name), row_id),
        )


def init_db() -> None:
    """Ensure the schema exists. Idempotent; safe on every startup.

    - **PostgreSQL in every environment**: the schema is owned exclusively by
      Alembic; this function only checks connectivity. Running ORM ``create_all``
      against a database on an older revision can pre-create future tables and
      make the next migration fail with ``DuplicateTable``.
    - **SQLite dev/test**: creates tables from the ORM metadata and applies the
      legacy auto-migration for old local databases.
    """
    url = _current_database_url()
    eng = engine.get_engine(url)
    if not config.is_sqlite_url(url):
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return
    Base.metadata.create_all(eng)
    _legacy_sqlite_migrate(eng)


def prepare_private_data(
    retention_days: int | None = None,
    *,
    batch_size: int = 500,
    max_rows: int | None = None,
) -> int:
    """Explicit, bounded backfill; never called as part of application startup."""
    from sqlalchemy import select

    from .models import Certificate
    from .privacy import (
        LEGACY_DOCUMENT_KEY_ID,
        document_hash_with_key_id,
        normalize_name,
    )

    changed = 0
    processed = 0
    last_id = 0
    batch_size = max(1, min(int(batch_size), 5000))
    while max_rows is None or processed < max_rows:
        current_limit = (
            batch_size if max_rows is None else min(batch_size, max(0, int(max_rows) - processed))
        )
        if current_limit <= 0:
            break
        with _session() as session:
            rows = (
                session.execute(
                    select(Certificate)
                    .where(Certificate.id > last_id)
                    .order_by(Certificate.id)
                    .limit(current_limit)
                )
                .scalars()
                .all()
            )
            if not rows:
                break
            last_id = int(rows[-1].id)
            processed += len(rows)
            for row in rows:
                normalized_name = normalize_name(row.participant_name)
                if row.participant_document_hash:
                    hashed_document = row.participant_document_hash
                    hash_key_id = row.participant_document_hash_key_id or LEGACY_DOCUMENT_KEY_ID
                else:
                    hashed_document, hash_key_id = document_hash_with_key_id(
                        row.participant_document
                    )
                if row.participant_name_normalized != normalized_name:
                    row.participant_name_normalized = normalized_name
                    changed += 1
                if row.participant_document_hash != hashed_document:
                    row.participant_document_hash = hashed_document
                    changed += 1
                if row.participant_document_hash_key_id != hash_key_id:
                    row.participant_document_hash_key_id = hash_key_id
                    changed += 1
                if row.participant_document is not None:
                    row.participant_document = None
                    changed += 1

    with _session() as session:
        # Retention is a set-based database operation, so it does not materialize
        # the certificate table in process memory.
        if retention_days is None:
            settings = InstitutionalSettingsRepository(session).get()
            if settings is not None:
                retention_days = int(settings.get("retention_days") or 0)
            else:
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
            batch_id = str(fields.get("batch_id") or "")
            retryable = (
                batch_id
                and str(existing.get("batch_id") or "") == batch_id
                and existing.get("status") == "failed"
                and not existing.get("drive_file_id")
                and not existing.get("pdf_path")
            )
            if retryable:
                with _session() as s:
                    reopened = CertificateRepository(s).retry_failed_reservation(
                        code=str(existing["unique_code"]),
                        business_key=business_key,
                        batch_id=batch_id,
                        fields=fields,
                    )
                if reopened:
                    return str(existing["unique_code"]), None
                existing = get_by_business_key(business_key)
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
    raise RuntimeError("Não foi possível reservar um código único após várias tentativas.")


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


def list_pending_certificates(
    cutoff: datetime, *, after_id: int = 0, limit: int | None = None
) -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).pending_older_than(cutoff, after_id=after_id, limit=limit)


def list_active_without_file(*, after_id: int = 0, limit: int | None = None) -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).active_without_file(after_id=after_id, limit=limit)


def list_failed_with_orphan(*, after_id: int = 0, limit: int | None = None) -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).failed_with_orphan_file(after_id=after_id, limit=limit)


def block_certificate_integrity(unique_code: str) -> bool:
    """Mark a certificate as integrity-blocked (tampered/corrupt file)."""
    with _session() as s:
        return CertificateRepository(s).set_integrity_blocked(unique_code, True)


def rotate_certificate_document_hash(
    unique_code: str,
    *,
    expected_hash: str,
    new_hash: str,
    new_key_id: str,
) -> bool:
    """Persist a lazy HMAC rotation without ever receiving plaintext."""

    with _session() as s:
        return CertificateRepository(s).rotate_document_hash(
            unique_code,
            expected_hash=expected_hash,
            new_hash=new_hash,
            new_key_id=new_key_id,
        )


def list_active_with_remote_file(*, after_id: int = 0, limit: int | None = None) -> list[dict]:
    """Active, non-blocked certificates that have a file to verify periodically."""
    with _session() as s:
        return CertificateRepository(s).active_with_remote_file(after_id=after_id, limit=limit)


def drive_file_index() -> dict[str, str]:
    """``drive_file_id -> unique_code`` for every certificate stored on Drive."""
    with _session() as s:
        return CertificateRepository(s).drive_file_index()


def drive_file_index_by_folder() -> dict[str | None, dict[str, str]]:
    with _session() as s:
        return CertificateRepository(s).drive_file_index_by_folder()


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
    certificate_type: str | None = None,
    status: str | None = None,
    statuses: tuple[str, ...] | None = None,
    issue_date_from: str | None = None,
    issue_date_to: str | None = None,
    batch_id: str | None = None,
    order_by: str = "created_at",
    descending: bool = True,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    with _session() as s:
        return CertificateRepository(s).list(
            name=name,
            code=code,
            course=course,
            event=event,
            certificate_type=certificate_type,
            status=status,
            statuses=statuses,
            issue_date_from=issue_date_from,
            issue_date_to=issue_date_to,
            batch_id=batch_id,
            order_by=order_by,
            descending=descending,
            limit=limit,
            offset=offset,
        )


def list_certificates_by_document_hashes(
    hashes_by_key_id: dict[str, str],
    *,
    statuses: tuple[str, ...] = ("ativo", "revogado"),
) -> list[dict]:
    """Find certificates by versioned RA hashes, never by plaintext RA."""

    with _session() as s:
        return CertificateRepository(s).list_by_document_hashes(
            hashes_by_key_id,
            statuses=statuses,
        )


def certificate_dashboard_stats(recent_days: int = 30) -> dict:
    with _session() as s:
        return CertificateRepository(s).dashboard_stats(recent_days=recent_days)


def recent_certificates(limit: int = 8) -> list[dict]:
    with _session() as s:
        return CertificateRepository(s).recent(limit=limit)


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


def update_certificate_file(
    unique_code: str, fields: dict, *, reissued_by: int | None = None
) -> bool:
    with _session() as s:
        return CertificateRepository(s).update_file(unique_code, fields, reissued_by=reissued_by)


def restore_certificate_file(unique_code: str, fields: dict, *, expected_checksum: str) -> bool:
    """Attach a verified PDF backup without changing reissue history."""

    with _session() as s:
        return CertificateRepository(s).restore_file(
            unique_code,
            fields,
            expected_checksum=expected_checksum,
        )


def update_certificate_status(
    unique_code: str,
    *,
    status: str,
    revoked_by: int | None = None,
    revoke_reason: str | None = None,
    expected_status: str | None = None,
) -> bool:
    with _session() as s:
        return CertificateRepository(s).update_status(
            unique_code,
            status=status,
            revoked_by=revoked_by,
            revoke_reason=revoke_reason,
            expected_status=expected_status,
        )


# ── Admin users ─────────────────────────────────────────────────────────────────


def get_admin_user_by_username(username: str) -> dict | None:
    with _session() as s:
        return AdminUserRepository(s).get_by_username(username)


def get_admin_user_by_id(user_id: int) -> dict | None:
    with _session() as s:
        return AdminUserRepository(s).get_by_id(user_id)


def create_admin_user(
    username: str,
    password_hash: str,
    role: str = "secretaria",
    *,
    name: str | None = None,
    must_change_password: bool = False,
    created_by: int | None = None,
) -> int | None:
    with _session() as s:
        return AdminUserRepository(s).create(
            username,
            password_hash,
            role,
            name=name,
            must_change_password=must_change_password,
            created_by=created_by,
        )


def count_admin_users() -> int:
    with _session() as s:
        return AdminUserRepository(s).count()


def list_admin_users() -> list[dict]:
    with _session() as s:
        return AdminUserRepository(s).list_all()


def count_active_admins(exclude_user_id: int | None = None) -> int:
    with _session() as s:
        return AdminUserRepository(s).count_active_admins(exclude_user_id=exclude_user_id)


def set_admin_user_active(user_id: int, active: bool) -> bool:
    with _session() as s:
        changed = AdminUserRepository(s).set_active(user_id, active)
        if changed and not active:
            AuthSessionRepository(s).revoke_all(user_id, "user_deactivated")
        return changed


def set_admin_user_role(user_id: int, role: str) -> bool:
    with _session() as s:
        return AdminUserRepository(s).set_role(user_id, role)


def update_admin_user(
    user_id: int,
    *,
    name: str | None = None,
    username: str | None = None,
    role: str | None = None,
) -> bool:
    with _session() as s:
        return AdminUserRepository(s).update_identity_and_role(
            user_id, name=name, username=username, role=role
        )


def set_admin_user_password(
    user_id: int, password_hash: str, *, must_change_password: bool
) -> bool:
    with _session() as s:
        return AdminUserRepository(s).set_password(
            user_id,
            password_hash,
            must_change_password=must_change_password,
        )


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


def get_active_auth_session_user(session_id: str, now: datetime) -> dict | None:
    with _session() as s:
        return AuthSessionRepository(s).get_active_user(session_id, now)


def revoke_auth_session(session_id: str, reason: str = "logout") -> bool:
    with _session() as s:
        return AuthSessionRepository(s).revoke(session_id, reason)


def revoke_all_auth_sessions(
    user_id: int,
    reason: str = "revoke_all",
    *,
    exclude_session_id: str | None = None,
) -> int:
    with _session() as s:
        return AuthSessionRepository(s).revoke_all(
            user_id, reason, exclude_session_id=exclude_session_id
        )


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


# ── Institutional settings ───────────────────────────────────────────────────


def get_google_drive_connection(user_id: int) -> dict | None:
    with _session() as s:
        return GoogleDriveIntegrationRepository(s).connection(user_id)


def get_google_drive_connection_by_state(state_hash: str) -> dict | None:
    with _session() as s:
        return GoogleDriveIntegrationRepository(s).connection_by_state(state_hash)


def store_google_drive_oauth_state(user_id: int, values: dict) -> dict:
    with _session() as s:
        return GoogleDriveIntegrationRepository(s).store_state(user_id, values)


def consume_google_drive_oauth_state(user_id: int, state_hash: str) -> bool:
    with _session() as s:
        return GoogleDriveIntegrationRepository(s).consume_state(user_id, state_hash)


def complete_google_drive_connection(user_id: int, values: dict) -> bool:
    with _session() as s:
        return GoogleDriveIntegrationRepository(s).complete_connection(user_id, values)


def clear_google_drive_connection(user_id: int) -> int:
    with _session() as s:
        return GoogleDriveIntegrationRepository(s).clear_connection(user_id)


def upsert_google_drive_folder_grant(values: dict) -> dict:
    with _session() as s:
        return GoogleDriveIntegrationRepository(s).upsert_grant(values)


def get_google_drive_folder_grant(user_id: int, folder_hash: str) -> dict | None:
    with _session() as s:
        return GoogleDriveIntegrationRepository(s).grant(user_id, folder_hash)


def get_institutional_settings() -> dict | None:
    with _session() as s:
        return InstitutionalSettingsRepository(s).get()


def create_institutional_settings(values: dict) -> dict:
    with _session() as s:
        return InstitutionalSettingsRepository(s).create(values)


def update_institutional_settings(values: dict, *, actor_id: int | None = None) -> dict | None:
    with _session() as s:
        return InstitutionalSettingsRepository(s).update(values, actor_id=actor_id)


# ── Emission batches ─────────────────────────────────────────────────────────


def create_emission_batch(values: dict, items: list[dict] | None = None) -> dict:
    with _session() as s:
        return EmissionBatchRepository(s).create(values, items)


def get_emission_batch(batch_id: str) -> dict | None:
    with _session() as s:
        return EmissionBatchRepository(s).get(batch_id)


def get_emission_batch_by_idempotency_key(key: str) -> dict | None:
    with _session() as s:
        return EmissionBatchRepository(s).get_by_idempotency_key(key)


def get_emission_batch_items(
    batch_id: str, *, statuses: tuple[str, ...] | None = None
) -> list[dict]:
    with _session() as s:
        return EmissionBatchRepository(s).items(batch_id, statuses=statuses)


def claim_emission_batch(
    *,
    worker_id: str,
    now: datetime,
    lease_expires_at: datetime,
    batch_id: str | None = None,
) -> dict | None:
    with _session() as s:
        return EmissionBatchRepository(s).claim(
            worker_id=worker_id,
            now=now,
            lease_expires_at=lease_expires_at,
            batch_id=batch_id,
        )


def heartbeat_emission_batch(
    batch_id: str,
    *,
    worker_id: str,
    now: datetime,
    lease_expires_at: datetime,
) -> bool:
    with _session() as s:
        return EmissionBatchRepository(s).heartbeat(
            batch_id,
            worker_id=worker_id,
            now=now,
            lease_expires_at=lease_expires_at,
        )


def mark_emission_batch_item_processing(item_id: int, *, now: datetime) -> bool:
    with _session() as s:
        return EmissionBatchRepository(s).mark_item_processing(item_id, now=now)


def mark_emission_batch_item(
    item_id: int,
    *,
    status: str,
    certificate_code: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    clear_payload: bool = False,
) -> bool:
    with _session() as s:
        return EmissionBatchRepository(s).mark_item(
            item_id,
            status=status,
            certificate_code=certificate_code,
            error_code=error_code,
            error_message=error_message,
            clear_payload=clear_payload,
        )


def emission_batch_item_counts(batch_id: str) -> dict[str, int]:
    with _session() as s:
        return EmissionBatchRepository(s).counts(batch_id)


def purge_terminal_emission_payloads(before: datetime) -> int:
    with _session() as s:
        return EmissionBatchRepository(s).purge_terminal_payloads(before)


def request_emission_batch_cancel(batch_id: str, *, now: datetime) -> str | None:
    with _session() as s:
        return EmissionBatchRepository(s).request_cancel(batch_id, now=now)


def cancel_remaining_emission_batch_items(batch_id: str, *, now: datetime) -> int:
    with _session() as s:
        return EmissionBatchRepository(s).cancel_remaining(batch_id, now=now)


def release_emission_batch(
    batch_id: str,
    *,
    worker_id: str,
    retry_at: datetime | None,
    error_code: str,
    error_message: str,
    now: datetime,
) -> bool:
    with _session() as s:
        return EmissionBatchRepository(s).release(
            batch_id,
            worker_id=worker_id,
            retry_at=retry_at,
            error_code=error_code,
            error_message=error_message,
            now=now,
        )


def retry_emission_batch(batch_id: str, *, now: datetime) -> bool:
    with _session() as s:
        return EmissionBatchRepository(s).retry(batch_id, now=now)


def update_emission_batch(batch_id: str, values: dict) -> bool:
    with _session() as s:
        return EmissionBatchRepository(s).update(batch_id, values)


def list_emission_batches(
    *, created_by: int | None = None, limit: int = 20, offset: int = 0
) -> tuple[list[dict], int]:
    with _session() as s:
        return EmissionBatchRepository(s).list(created_by=created_by, limit=limit, offset=offset)


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
    certificate_type: str | None = None,
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
            certificate_type=certificate_type,
        )


def get_template_version(version_id: int) -> dict | None:
    with _session() as s:
        return TemplateVersionRepository(s).get(version_id)


def get_active_template_version(certificate_type: str | None = None) -> dict | None:
    with _session() as s:
        return TemplateVersionRepository(s).get_active(certificate_type)


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


def rename_template_version(version_id: int, name: str) -> dict | None:
    with _session() as s:
        return TemplateVersionRepository(s).rename(version_id, name)


def delete_template_version_if_unused(version_id: int) -> tuple[str, dict | None]:
    with _session() as s:
        return TemplateVersionRepository(s).delete_if_unused(version_id)


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
        rows, _total = AuditLogRepository(s).list(action=action, limit=limit)
        return rows


def list_audit_logs_page(
    *,
    action: str | None = None,
    actions: tuple[str, ...] | None = None,
    actor: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    with _session() as s:
        return AuditLogRepository(s).list(
            action=action,
            actions=actions,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
