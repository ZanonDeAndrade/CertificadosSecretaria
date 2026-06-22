"""SQLAlchemy ORM models — the schema source of truth for Alembic.

The ``certificates`` table stores **only metadata** about each certificate: the
PDF bytes are NEVER stored here. The definitive file lives in Google Drive
(``drive_file_id``) in production; ``pdf_path`` is a legacy/development-only
pointer kept for backward compatibility with rows issued before the storage
abstraction (local fallback).

These models map cleanly to both PostgreSQL (production) and SQLite (dev/test):
only portable column types are used (Integer / String / Text / DateTime).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Allowed lifecycle/lookup values, enforced by CHECK constraints (F16).
CERTIFICATE_STATUSES = ("pending", "ativo", "revogado", "failed")
STORAGE_PROVIDERS = ("local", "google_drive")
ADMIN_ROLES = ("admin", "secretaria", "auditor")


def _in_list_sql(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({rendered})"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unique_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # ── Identity / academic data ────────────────────────────────────────────
    participant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    participant_name_normalized: Mapped[str | None] = mapped_column(String(255))
    participant_email: Mapped[str | None] = mapped_column(String(255))
    participant_document: Mapped[str | None] = mapped_column(String(64))
    participant_document_hash: Mapped[str | None] = mapped_column(String(64))
    course_name: Mapped[str | None] = mapped_column(String(255))
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    workload_hours: Mapped[int | None] = mapped_column(Integer)
    issue_date: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[str | None] = mapped_column(String(64))
    end_date: Mapped[str | None] = mapped_column(String(64))
    certificate_text: Mapped[str | None] = mapped_column(Text)

    # ── Storage metadata (definitive file lives in Drive) ────────────────────
    storage_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="local", default="local"
    )
    drive_file_id: Mapped[str | None] = mapped_column(String(255))
    drive_folder_id: Mapped[str | None] = mapped_column(String(255))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="application/pdf",
        default="application/pdf",
    )
    file_size: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    # Set when a download/periodic check finds the stored file tampered/corrupt;
    # blocked files are never served again until cleared.
    integrity_blocked: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    # Legacy/dev-only pointer to a local PDF (STORAGE_DIR-relative). Never used
    # as the definitive store in production.
    pdf_path: Mapped[str | None] = mapped_column(Text)
    # Which template produced this certificate (human label, e.g. "v3").
    template_used: Mapped[str | None] = mapped_column(String(128))
    # The exact global-template version used + an immutable snapshot of its
    # layout, so a reissue reproduces the original certificate faithfully.
    template_version_id: Mapped[int | None] = mapped_column(Integer)
    template_snapshot: Mapped[str | None] = mapped_column(Text)

    # ── Lifecycle / audit ────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="ativo", default="ativo"
    )
    business_key: Mapped[str | None] = mapped_column(String(64))
    # ON DELETE SET NULL: removing/anonymising a user never destroys certificate
    # history (the link is cleared, the row stays).
    issued_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        default=utcnow,
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_certificates_participant_name", "participant_name"),
        Index("idx_certificates_name_normalized", "participant_name_normalized"),
        Index(
            "idx_certificates_name_normalized_status",
            "participant_name_normalized",
            "status",
        ),
        Index("idx_certificates_event_name", "event_name"),
        Index("idx_certificates_course_name", "course_name"),
        Index("idx_certificates_status", "status"),
        # NULL business_keys are distinct, so legacy rows without one do not
        # collide on this unique index.
        Index("idx_certificates_business_key", "business_key", unique=True),
        # Chronological ordering uses the real (ISO) issue date.
        Index("idx_certificates_issue_date", "issue_date"),
        CheckConstraint(
            _in_list_sql("status", CERTIFICATE_STATUSES), name="ck_certificates_status"
        ),
        CheckConstraint(
            _in_list_sql("storage_provider", STORAGE_PROVIDERS),
            name="ck_certificates_storage_provider",
        ),
    )


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="secretaria", default="secretaria"
    )
    is_active: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", default=1
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        default=utcnow,
    )

    __table_args__ = (
        CheckConstraint(_in_list_sql("role", ADMIN_ROLES), name="ck_admin_users_role"),
    )


class AuthSession(Base):
    """Server-side session backing each JWT ``jti``.

    JWT signature/expiry are necessary but not sufficient: every request must
    also find a non-revoked, non-expired row here. This makes logout and global
    user-session revocation effective across workers and deployments.
    """

    __tablename__ = "auth_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("idx_auth_sessions_user_id", "user_id"),
        Index("idx_auth_sessions_expires_at", "expires_at"),
        Index("idx_auth_sessions_revoked_at", "revoked_at"),
    )


class LoginThrottle(Base):
    """Persistent/distributed failed-login state for an IP or username hash."""

    __tablename__ = "login_throttles"

    scope_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=utcnow
    )

    __table_args__ = (
        Index("idx_login_throttles_blocked_until", "blocked_until"),
        Index("idx_login_throttles_updated_at", "updated_at"),
    )


class PublicRateLimit(Base):
    """Shared request counter used by every public worker/deployment."""

    __tablename__ = "public_rate_limits"

    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=utcnow
    )

    __table_args__ = (Index("idx_public_rate_limits_updated_at", "updated_at"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ON DELETE SET NULL: the audit trail survives user removal (actor_username is
    # also kept as a durable textual record of who acted).
    actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    actor_username: Mapped[str | None] = mapped_column(String(150))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        default=utcnow,
    )

    __table_args__ = (
        Index("idx_audit_log_created_at", "created_at"),
    )


class TemplateVersion(Base):
    """An immutable version of the single global certificate template.

    Every edit in the visual editor creates a new row (never mutated). Exactly
    one row has ``is_active = 1`` at a time. The background image bytes live here
    (durable DB storage — never APPDATA/local JSON), and ``layout_json`` is the
    frozen snapshot of elements + dimensions + background reference.
    """

    __tablename__ = "template_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    # Immutable snapshot: {background, image_width, image_height, elements:[...]}.
    layout_json: Mapped[str] = mapped_column(Text, nullable=False)
    image_width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Durable background image bytes (loaded only when rendering/serving).
    background_image: Mapped[bytes | None] = mapped_column(LargeBinary)
    background_mime_type: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="image/png", default="image/png"
    )
    is_active: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        default=utcnow,
    )
    created_by: Mapped[int | None] = mapped_column(Integer)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("idx_template_versions_is_active", "is_active"),
    )
