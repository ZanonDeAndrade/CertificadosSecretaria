"""Repository layer — all certificate/admin/audit SQL lives here.

Repositories wrap a SQLAlchemy ``Session`` (the unit of work / transaction) and
return plain ``dict`` rows, so the rest of the application keeps the exact same
data shape it had with the previous hand-written layer (``row["unique_code"]``,
``row.get("status")``, …). No raw SQL is spread across the routes/services.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    AdminUser,
    AuditLog,
    AuthSession,
    Certificate,
    LoginThrottle,
    PublicRateLimit,
    TemplateVersion,
    utcnow,
)

# Columns accepted by an insert (id / created_at are DB-managed).
_INSERT_COLUMNS = (
    "unique_code",
    "participant_name",
    "participant_name_normalized",
    "participant_email",
    "participant_document",
    "participant_document_hash",
    "course_name",
    "event_name",
    "workload_hours",
    "issue_date",
    "start_date",
    "end_date",
    "pdf_path",
    "certificate_text",
    "storage_provider",
    "drive_file_id",
    "drive_folder_id",
    "original_filename",
    "mime_type",
    "file_size",
    "checksum_sha256",
    "status",
    "business_key",
    "template_used",
    "template_version_id",
    "template_snapshot",
    "issued_by",
)


def _normalize_insert_row(row: dict) -> dict:
    from .privacy import document_hash, normalize_name

    normalized = {col: row.get(col) for col in _INSERT_COLUMNS}
    normalized["participant_name_normalized"] = normalize_name(normalized["participant_name"])
    raw_document = normalized["participant_document"]
    normalized["participant_document_hash"] = (
        normalized["participant_document_hash"] or document_hash(raw_document)
    )
    if os.getenv("MINIMIZE_DOCUMENT_PLAINTEXT", "true").strip().lower() not in {"0", "false", "no"}:
        normalized["participant_document"] = None
    else:
        from .privacy import normalize_document

        normalized["participant_document"] = normalize_document(raw_document) or None
    normalized["pdf_path"] = normalized["pdf_path"] or ""
    normalized["storage_provider"] = normalized["storage_provider"] or "local"
    normalized["mime_type"] = normalized["mime_type"] or "application/pdf"
    normalized["status"] = normalized["status"] or "ativo"
    return normalized


def _to_dict(mapping: Any) -> dict:
    return dict(mapping)


# ── Certificates ────────────────────────────────────────────────────────────────

_SEARCHABLE = {
    "name": Certificate.participant_name,
    "course": Certificate.course_name,
    "event": Certificate.event_name,
}


class CertificateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # writes -------------------------------------------------------------------

    def insert_many(self, rows: list[dict]) -> None:
        """Strict bulk insert (no INSERT OR IGNORE).

        Raises ``IntegrityError`` on a ``unique_code`` / ``business_key``
        conflict — uniqueness is enforced by the database, never pre-checked
        outside a transaction. Used for seeding/migration of distinct rows.
        """
        if not rows:
            return
        values = [_normalize_insert_row(r) for r in rows]
        self.session.execute(insert(Certificate.__table__), values)

    # ── Saga: reserve → finalize → fail ──────────────────────────────────────
    def insert_pending(self, *, code: str, business_key: str | None, fields: dict) -> None:
        """Insert a single ``pending`` reservation.

        Relies entirely on the UNIQUE constraints (unique_code / business_key):
        a conflict raises ``IntegrityError``, which the caller resolves (retry a
        new code, or report the existing certificate as a duplicate).
        """
        raw_values = {k: v for k, v in fields.items() if k in _INSERT_COLUMNS}
        raw_values["unique_code"] = code
        raw_values["business_key"] = business_key
        raw_values["status"] = "pending"
        values = _normalize_insert_row(raw_values)
        # Set created_at explicitly (not the server default) so the reconciliation
        # age comparison uses the same tz handling as the Python-side cutoff.
        values["created_at"] = utcnow()
        self.session.execute(insert(Certificate.__table__).values(**values))

    def finalize(self, unique_code: str, drive_fields: dict) -> bool:
        """Promote a reserved (``pending``) row to ``ativo`` with storage metadata.

        Guarded by ``status == 'pending'`` so a finalize never resurrects a
        revoked/failed row or double-finalizes.
        """
        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .where(Certificate.status == "pending")
            .values(
                storage_provider=drive_fields.get("storage_provider") or "local",
                drive_file_id=drive_fields.get("drive_file_id"),
                drive_folder_id=drive_fields.get("drive_folder_id"),
                original_filename=drive_fields.get("original_filename"),
                mime_type=drive_fields.get("mime_type") or "application/pdf",
                file_size=drive_fields.get("file_size"),
                checksum_sha256=drive_fields.get("checksum_sha256"),
                pdf_path=drive_fields.get("pdf_path") or "",
                status="ativo",
                updated_at=utcnow(),
            )
        )
        return result.rowcount > 0

    def mark_failed(
        self,
        unique_code: str,
        *,
        drive_file_id: str | None = None,
        drive_folder_id: str | None = None,
        pdf_path: str | None = None,
    ) -> bool:
        """Mark a certificate ``failed``, recording any orphan file pointer so
        reconciliation can compensate it later."""
        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .values(
                status="failed",
                drive_file_id=drive_file_id,
                drive_folder_id=drive_folder_id,
                pdf_path=pdf_path,
                updated_at=utcnow(),
            )
        )
        return result.rowcount > 0

    def clear_storage(self, unique_code: str) -> bool:
        """Null out storage pointers after a successful compensating delete."""
        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .values(
                drive_file_id=None,
                drive_folder_id=None,
                pdf_path="",
                file_size=None,
                checksum_sha256=None,
                updated_at=utcnow(),
            )
        )
        return result.rowcount > 0

    def set_integrity_blocked(self, unique_code: str, blocked: bool) -> bool:
        """Block (or unblock) a certificate whose stored file failed integrity."""
        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .values(integrity_blocked=1 if blocked else 0, updated_at=utcnow())
        )
        return result.rowcount > 0

    def active_with_remote_file(self) -> list[dict]:
        """Active, non-blocked certificates that have a stored file to verify."""
        has_drive = and_(
            Certificate.drive_file_id.is_not(None), Certificate.drive_file_id != ""
        )
        has_local = and_(
            Certificate.pdf_path.is_not(None), Certificate.pdf_path != ""
        )
        rows = self.session.execute(
            select(Certificate.__table__)
            .where(Certificate.status == "ativo")
            .where(Certificate.integrity_blocked == 0)
            .where(or_(has_drive, has_local))
            .order_by(Certificate.id)
        ).mappings().all()
        return [_to_dict(r) for r in rows]

    def update_status(
        self,
        unique_code: str,
        *,
        status: str,
        revoked_by: int | None = None,
        revoke_reason: str | None = None,
    ) -> bool:
        revoked_at = utcnow() if status == "revogado" else None
        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .values(
                status=status,
                revoked_at=revoked_at,
                revoked_by=revoked_by,
                revoke_reason=revoke_reason,
                updated_at=utcnow(),
            )
        )
        return result.rowcount > 0

    def set_drive_metadata(
        self,
        unique_code: str,
        *,
        drive_file_id: str,
        drive_folder_id: str | None,
        original_filename: str | None,
        mime_type: str | None,
        file_size: int | None,
        checksum_sha256: str | None,
    ) -> bool:
        values: dict[str, Any] = {
            "storage_provider": "google_drive",
            "drive_file_id": drive_file_id,
            "drive_folder_id": drive_folder_id,
            "file_size": file_size,
            "checksum_sha256": checksum_sha256,
            "updated_at": utcnow(),
        }
        if original_filename is not None:
            values["original_filename"] = original_filename
        if mime_type is not None:
            values["mime_type"] = mime_type
        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .values(**values)
        )
        return result.rowcount > 0

    def update_file(self, unique_code: str, fields: dict) -> bool:
        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .values(
                storage_provider=fields.get("storage_provider") or "local",
                drive_file_id=fields.get("drive_file_id"),
                drive_folder_id=fields.get("drive_folder_id"),
                original_filename=fields.get("original_filename"),
                mime_type=fields.get("mime_type") or "application/pdf",
                file_size=fields.get("file_size"),
                checksum_sha256=fields.get("checksum_sha256"),
                pdf_path=fields.get("pdf_path") or "",
                updated_at=utcnow(),
            )
        )
        return result.rowcount > 0

    # reads --------------------------------------------------------------------

    def get_by_code(self, unique_code: str) -> dict | None:
        code = unique_code.strip()
        if not code:
            return None
        row = self.session.execute(
            select(Certificate.__table__)
            .where(func.lower(Certificate.unique_code) == func.lower(code))
            .limit(1)
        ).mappings().first()
        return _to_dict(row) if row else None

    def get_by_business_key(self, business_key: str) -> dict | None:
        if not business_key:
            return None
        row = self.session.execute(
            select(Certificate.__table__)
            .where(Certificate.business_key == business_key)
            .limit(1)
        ).mappings().first()
        return _to_dict(row) if row else None

    def search_by_name(self, name: str) -> list[dict]:
        from .privacy import normalize_name

        term = normalize_name(name)
        if not term:
            return []
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.session.execute(
            select(Certificate.__table__)
            .where(Certificate.participant_name_normalized.like(f"%{escaped}%", escape="\\"))
            .order_by(
                func.lower(Certificate.participant_name),
                Certificate.issue_date,
                Certificate.id,
            )
        ).mappings().all()
        return [_to_dict(r) for r in rows]

    def list(
        self,
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
        conditions = []
        if name:
            from .privacy import normalize_name

            term = normalize_name(name)
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                Certificate.participant_name_normalized.like(f"%{escaped}%", escape="\\")
            )
        if code:
            conditions.append(
                func.lower(Certificate.unique_code) == func.lower(code.strip())
            )
        if course:
            conditions.append(Certificate.course_name.ilike(f"%{course.strip()}%"))
        if event:
            conditions.append(Certificate.event_name.ilike(f"%{event.strip()}%"))
        if status:
            conditions.append(Certificate.status == status.strip())
        if statuses:
            conditions.append(Certificate.status.in_(statuses))

        order_col = (
            Certificate.issue_date if order_by == "issue_date" else Certificate.created_at
        )
        order_col = order_col.desc() if descending else order_col.asc()
        id_order = Certificate.id.desc() if descending else Certificate.id.asc()
        limit = max(1, min(int(limit), 200))
        offset = max(0, min(int(offset), 10_000))

        total = self.session.execute(
            select(func.count()).select_from(Certificate).where(*conditions)
        ).scalar_one()
        rows = self.session.execute(
            select(Certificate.__table__)
            .where(*conditions)
            .order_by(order_col, id_order)
            .limit(limit)
            .offset(offset)
        ).mappings().all()
        return [_to_dict(r) for r in rows], int(total)

    def by_normalized_name(self, name: str, limit: int = 100) -> list[dict]:
        from .privacy import normalize_name

        term = normalize_name(name)
        if not term:
            return []
        rows = self.session.execute(
            select(Certificate.__table__)
            .where(Certificate.participant_name_normalized == term)
            .order_by(Certificate.id)
            .limit(max(1, min(int(limit), 100)))
        ).mappings().all()
        return [_to_dict(row) for row in rows]

    def pending_drive_migration(self) -> list[dict]:
        rows = self.session.execute(
            select(Certificate.__table__)
            .where(
                (Certificate.drive_file_id.is_(None))
                | (Certificate.drive_file_id == "")
            )
            .where(Certificate.pdf_path.is_not(None))
            .where(Certificate.pdf_path != "")
            .order_by(Certificate.id)
        ).mappings().all()
        return [_to_dict(r) for r in rows]

    # ── Reconciliation queries ───────────────────────────────────────────────
    def pending_older_than(self, cutoff: datetime) -> list[dict]:
        """Reservations stuck in ``pending`` since before ``cutoff`` (crashed saga)."""
        rows = self.session.execute(
            select(Certificate.__table__)
            .where(Certificate.status == "pending")
            .where(Certificate.created_at < cutoff)
            .order_by(Certificate.id)
        ).mappings().all()
        return [_to_dict(r) for r in rows]

    def active_without_file(self) -> list[dict]:
        """``ativo`` rows with no usable file pointer (drive_file_id and pdf_path empty)."""
        no_drive = or_(Certificate.drive_file_id.is_(None), Certificate.drive_file_id == "")
        no_local = or_(Certificate.pdf_path.is_(None), Certificate.pdf_path == "")
        rows = self.session.execute(
            select(Certificate.__table__)
            .where(Certificate.status == "ativo")
            .where(no_drive)
            .where(no_local)
            .order_by(Certificate.id)
        ).mappings().all()
        return [_to_dict(r) for r in rows]

    def failed_with_orphan_file(self) -> list[dict]:
        """``failed`` rows that still point at an uploaded file needing deletion."""
        has_drive = and_(
            Certificate.drive_file_id.is_not(None), Certificate.drive_file_id != ""
        )
        has_local = and_(
            Certificate.pdf_path.is_not(None), Certificate.pdf_path != ""
        )
        rows = self.session.execute(
            select(Certificate.__table__)
            .where(Certificate.status == "failed")
            .where(or_(has_drive, has_local))
            .order_by(Certificate.id)
        ).mappings().all()
        return [_to_dict(r) for r in rows]

    def drive_file_index(self) -> dict[str, str]:
        """Map ``drive_file_id -> unique_code`` for all rows on Drive.

        Carries NO personal data — only the verifier code and the opaque file id
        — so a Drive×DB reconciliation can run without exposing names/documents.
        """
        rows = self.session.execute(
            select(Certificate.drive_file_id, Certificate.unique_code)
            .where(Certificate.drive_file_id.is_not(None))
            .where(Certificate.drive_file_id != "")
        ).all()
        return {file_id: code for file_id, code in rows}


# ── Admin users ─────────────────────────────────────────────────────────────────

class AdminUserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_username(self, username: str) -> dict | None:
        row = self.session.execute(
            select(AdminUser.__table__)
            .where(AdminUser.username == username.strip())
            .limit(1)
        ).mappings().first()
        return _to_dict(row) if row else None

    def get_by_id(self, user_id: int) -> dict | None:
        row = self.session.execute(
            select(AdminUser.__table__).where(AdminUser.id == user_id).limit(1)
        ).mappings().first()
        return _to_dict(row) if row else None

    def create(self, username: str, password_hash: str, role: str = "secretaria") -> int | None:
        if self.get_by_username(username):
            return None
        try:
            with self.session.begin_nested():
                result = self.session.execute(
                    insert(AdminUser.__table__).values(
                        username=username.strip(),
                        password_hash=password_hash,
                        role=role,
                    )
                )
            return int(result.inserted_primary_key[0])
        except IntegrityError:
            return None

    def count(self) -> int:
        return int(
            self.session.execute(select(func.count()).select_from(AdminUser)).scalar_one()
        )

    def set_active(self, user_id: int, active: bool) -> bool:
        result = self.session.execute(
            update(AdminUser)
            .where(AdminUser.id == user_id)
            .values(is_active=1 if active else 0)
        )
        return result.rowcount > 0

    def set_role(self, user_id: int, role: str) -> bool:
        result = self.session.execute(
            update(AdminUser).where(AdminUser.id == user_id).values(role=role)
        )
        return result.rowcount > 0


# ── Revocable auth sessions ──────────────────────────────────────────────────


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive DateTime values to aware UTC values."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class AuthSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        session_id: str,
        user_id: int,
        expires_at: datetime,
        ip_hash: str | None = None,
        user_agent_hash: str | None = None,
    ) -> None:
        self.session.execute(
            insert(AuthSession.__table__).values(
                session_id=session_id,
                user_id=user_id,
                expires_at=expires_at,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
                created_at=utcnow(),
            )
        )

    def get_active(self, session_id: str, now: datetime) -> dict | None:
        row = self.session.execute(
            select(AuthSession.__table__)
            .where(AuthSession.session_id == session_id)
            .where(AuthSession.revoked_at.is_(None))
            .where(AuthSession.expires_at > now)
            .limit(1)
        ).mappings().first()
        return _to_dict(row) if row else None

    def revoke(self, session_id: str, reason: str = "logout") -> bool:
        result = self.session.execute(
            update(AuthSession)
            .where(AuthSession.session_id == session_id)
            .where(AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoke_reason=reason[:64])
        )
        return result.rowcount > 0

    def revoke_all(self, user_id: int, reason: str = "revoke_all") -> int:
        result = self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id)
            .where(AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoke_reason=reason[:64])
        )
        return int(result.rowcount)

    def cleanup(self, before: datetime) -> int:
        result = self.session.execute(
            delete(AuthSession).where(AuthSession.expires_at < before)
        )
        return int(result.rowcount)

    def set_expiry(self, session_id: str, expires_at: datetime) -> bool:
        """Administrative helper used by maintenance and expiry contract tests."""
        result = self.session.execute(
            update(AuthSession)
            .where(AuthSession.session_id == session_id)
            .values(expires_at=expires_at)
        )
        return result.rowcount > 0


# ── Persistent login throttling ──────────────────────────────────────────────


class PublicRateLimitRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def consume(
        self, bucket_key: str, *, now: datetime, window_seconds: int, limit: int
    ) -> tuple[bool, int]:
        row = self.session.execute(
            select(PublicRateLimit)
            .where(PublicRateLimit.bucket_key == bucket_key)
            .with_for_update()
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            self.session.add(
                PublicRateLimit(
                    bucket_key=bucket_key,
                    request_count=1,
                    window_started_at=now,
                    updated_at=now,
                )
            )
            self.session.flush()
            return True, window_seconds
        elapsed = max(0, int((now - _as_utc(row.window_started_at)).total_seconds()))
        if elapsed >= window_seconds:
            row.request_count = 1
            row.window_started_at = now
            allowed = True
            retry_after = window_seconds
        else:
            row.request_count = int(row.request_count) + 1
            allowed = row.request_count <= limit
            retry_after = max(1, window_seconds - elapsed)
        row.updated_at = now
        self.session.flush()
        return allowed, retry_after

    def cleanup(self, before: datetime) -> int:
        result = self.session.execute(
            delete(PublicRateLimit).where(PublicRateLimit.updated_at < before)
        )
        return int(result.rowcount or 0)


class LoginThrottleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_many(self, scopes: list[tuple[str, str]]) -> list[dict]:
        if not scopes:
            return []
        conditions = [
            and_(LoginThrottle.scope_type == scope_type, LoginThrottle.scope_key == key)
            for scope_type, key in scopes
        ]
        rows = self.session.execute(
            select(LoginThrottle.__table__).where(or_(*conditions))
        ).mappings().all()
        return [_to_dict(row) for row in rows]

    def record_failures(
        self,
        scopes: list[tuple[str, str, int]],
        *,
        now: datetime,
        window_seconds: int,
        lockout_seconds: int,
    ) -> list[dict]:
        results: list[dict] = []
        window_cutoff = now - timedelta(seconds=window_seconds)
        for scope_type, key, threshold in scopes:
            row = self.session.execute(
                select(LoginThrottle)
                .where(LoginThrottle.scope_type == scope_type)
                .where(LoginThrottle.scope_key == key)
                .with_for_update()
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                failures = 1
                blocked_until = (
                    now + timedelta(seconds=lockout_seconds)
                    if failures >= threshold
                    else None
                )
                self.session.add(
                    LoginThrottle(
                        scope_type=scope_type,
                        scope_key=key,
                        failures=failures,
                        window_started_at=now,
                        last_failed_at=now,
                        blocked_until=blocked_until,
                        updated_at=now,
                    )
                )
            else:
                expired_block = row.blocked_until and _as_utc(row.blocked_until) <= now
                expired_window = _as_utc(row.window_started_at) < window_cutoff
                if expired_block or expired_window:
                    failures = 1
                    row.window_started_at = now
                else:
                    failures = int(row.failures) + 1
                blocked_until = (
                    now + timedelta(seconds=lockout_seconds)
                    if failures >= threshold
                    else None
                )
                row.failures = failures
                row.last_failed_at = now
                row.blocked_until = blocked_until
                row.updated_at = now
            results.append(
                {
                    "scope_type": scope_type,
                    "scope_key": key,
                    "failures": failures,
                    "blocked_until": blocked_until,
                }
            )
        self.session.flush()
        return results

    def clear(self, scope_type: str, key: str) -> None:
        self.session.execute(
            delete(LoginThrottle)
            .where(LoginThrottle.scope_type == scope_type)
            .where(LoginThrottle.scope_key == key)
        )

    def cleanup(self, before: datetime) -> int:
        result = self.session.execute(
            delete(LoginThrottle)
            .where(LoginThrottle.updated_at < before)
            .where(
                or_(
                    LoginThrottle.blocked_until.is_(None),
                    LoginThrottle.blocked_until < utcnow(),
                )
            )
        )
        return int(result.rowcount)


# ── Audit log ────────────────────────────────────────────────────────────────────

# ── Template versions (single global template) ──────────────────────────────────

# All columns except the (potentially large) background image blob.
_VERSION_META = (
    TemplateVersion.id,
    TemplateVersion.version_number,
    TemplateVersion.name,
    TemplateVersion.layout_json,
    TemplateVersion.image_width,
    TemplateVersion.image_height,
    TemplateVersion.background_mime_type,
    TemplateVersion.is_active,
    TemplateVersion.created_at,
    TemplateVersion.created_by,
    TemplateVersion.activated_at,
    TemplateVersion.activated_by,
)


class TemplateVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        name: str | None,
        layout_json: str,
        image_width: int,
        image_height: int,
        background_image: bytes | None,
        background_mime_type: str,
        created_by: int | None = None,
    ) -> dict:
        next_num = (
            self.session.execute(
                select(func.coalesce(func.max(TemplateVersion.version_number), 0))
            ).scalar_one()
            + 1
        )
        result = self.session.execute(
            insert(TemplateVersion.__table__).values(
                version_number=next_num,
                name=name,
                layout_json=layout_json,
                image_width=image_width,
                image_height=image_height,
                background_image=background_image,
                background_mime_type=background_mime_type,
                is_active=0,
                created_at=utcnow(),
                created_by=created_by,
            )
        )
        return {"id": int(result.inserted_primary_key[0]), "version_number": next_num}

    def get(self, version_id: int) -> dict | None:
        row = self.session.execute(
            select(*_VERSION_META).where(TemplateVersion.id == version_id).limit(1)
        ).mappings().first()
        return _to_dict(row) if row else None

    def get_active(self) -> dict | None:
        row = self.session.execute(
            select(*_VERSION_META)
            .where(TemplateVersion.is_active == 1)
            .order_by(TemplateVersion.version_number.desc())
            .limit(1)
        ).mappings().first()
        return _to_dict(row) if row else None

    def list_all(self) -> list[dict]:
        rows = self.session.execute(
            select(*_VERSION_META).order_by(TemplateVersion.version_number.desc())
        ).mappings().all()
        return [_to_dict(r) for r in rows]

    def count(self) -> int:
        return int(
            self.session.execute(
                select(func.count()).select_from(TemplateVersion)
            ).scalar_one()
        )

    def get_background(self, version_id: int) -> tuple[bytes | None, str] | None:
        row = self.session.execute(
            select(
                TemplateVersion.background_image, TemplateVersion.background_mime_type
            )
            .where(TemplateVersion.id == version_id)
            .limit(1)
        ).first()
        if row is None:
            return None
        return row[0], row[1]

    def activate(self, version_id: int, actor: int | None = None) -> bool:
        """Make exactly one version active (atomic within the caller's txn)."""
        exists = self.session.execute(
            select(TemplateVersion.id).where(TemplateVersion.id == version_id).limit(1)
        ).first()
        if not exists:
            return False
        self.session.execute(
            update(TemplateVersion)
            .where(TemplateVersion.is_active == 1)
            .values(is_active=0)
        )
        self.session.execute(
            update(TemplateVersion)
            .where(TemplateVersion.id == version_id)
            .values(is_active=1, activated_at=utcnow(), activated_by=actor)
        )
        return True


class AuditLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def insert(
        self,
        *,
        action: str,
        actor_id: int | None = None,
        actor_username: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        details: str | None = None,
    ) -> None:
        self.session.execute(
            insert(AuditLog.__table__).values(
                action=action,
                actor_id=actor_id,
                actor_username=actor_username,
                target_type=target_type,
                target_id=target_id,
                details=details,
            )
        )

    def list(self, action: str | None = None, limit: int = 100) -> list[dict]:
        statement = select(AuditLog.__table__)
        if action:
            statement = statement.where(AuditLog.action == action)
        rows = self.session.execute(
            statement.order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500)))
        ).mappings().all()
        return [_to_dict(row) for row in rows]
