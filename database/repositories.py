"""Repository layer — all certificate/admin/audit SQL lives here.

Repositories wrap a SQLAlchemy ``Session`` (the unit of work / transaction) and
return plain ``dict`` rows, so the rest of the application keeps the exact same
data shape it had with the previous hand-written layer (``row["unique_code"]``,
``row.get("status")``, …). No raw SQL is spread across the routes/services.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, cast

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .models import (
    AdminUser,
    AuditLog,
    AuthSession,
    Certificate,
    EmissionBatch,
    EmissionBatchItem,
    GoogleDriveConnection,
    GoogleDriveFolderGrant,
    InstitutionalSettings,
    LoginThrottle,
    PublicRateLimit,
    TemplateVersion,
    TemplateVersionSequence,
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
    "participant_document_hash_key_id",
    "course_name",
    "event_name",
    "workload_hours",
    "issue_date",
    "start_date",
    "end_date",
    "pdf_path",
    "certificate_text",
    "certificate_type",
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
    "institutional_snapshot",
    "issued_by",
    "batch_id",
)


def _normalize_insert_row(row: dict) -> dict:
    from .privacy import (
        LEGACY_DOCUMENT_KEY_ID,
        document_hash_with_key_id,
        normalize_name,
    )

    normalized = {col: row.get(col) for col in _INSERT_COLUMNS}
    normalized["participant_name_normalized"] = normalize_name(normalized["participant_name"])
    raw_document = normalized["participant_document"]
    if normalized["participant_document_hash"]:
        normalized["participant_document_hash_key_id"] = (
            normalized["participant_document_hash_key_id"] or LEGACY_DOCUMENT_KEY_ID
        )
    else:
        (
            normalized["participant_document_hash"],
            normalized["participant_document_hash_key_id"],
        ) = document_hash_with_key_id(raw_document)
    # The raw document is transient input only. There is no opt-out: development
    # and tests follow the same privacy invariant as production.
    normalized["participant_document"] = None
    normalized["pdf_path"] = normalized["pdf_path"] or ""
    normalized["storage_provider"] = normalized["storage_provider"] or "local"
    normalized["mime_type"] = normalized["mime_type"] or "application/pdf"
    normalized["status"] = normalized["status"] or "ativo"
    return normalized


def _to_dict(mapping: Any) -> dict:
    return dict(mapping)


def _table(model: Any) -> Any:
    """Return an ORM table while preserving SQLAlchemy's runtime Core behavior."""
    return model.__table__


def _affected(result: Any) -> int:
    """Typed access to DML rowcount (``Session.execute`` exposes a broad Result)."""
    return int(cast(CursorResult[Any], result).rowcount or 0)


def _inserted_id(result: Any) -> int:
    primary_key = cast(CursorResult[Any], result).inserted_primary_key
    if not primary_key:
        raise RuntimeError("O banco não retornou a chave da linha inserida.")
    return int(primary_key[0])


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
        self.session.execute(insert(_table(Certificate)), values)

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
        self.session.execute(insert(_table(Certificate)).values(**values))

    def retry_failed_reservation(
        self, *, code: str, business_key: str, batch_id: str, fields: dict
    ) -> bool:
        """Reuse this batch's compensated reservation without changing its code."""
        values = _normalize_insert_row(
            {
                **{key: value for key, value in fields.items() if key in _INSERT_COLUMNS},
                "unique_code": code,
                "business_key": business_key,
                "status": "pending",
            }
        )
        values.pop("unique_code", None)
        values.pop("business_key", None)
        values.update(
            status="pending",
            drive_file_id=None,
            drive_folder_id=None,
            pdf_path="",
            file_size=None,
            checksum_sha256=None,
            updated_at=utcnow(),
        )
        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(code.strip()))
            .where(Certificate.business_key == business_key)
            .where(Certificate.batch_id == batch_id)
            .where(Certificate.status == "failed")
            .where(Certificate.drive_file_id.is_(None))
            .where(or_(Certificate.pdf_path.is_(None), Certificate.pdf_path == ""))
            .values(**values)
        )
        return _affected(result) == 1

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
        return _affected(result) > 0

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
        return _affected(result) > 0

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
        return _affected(result) > 0

    def set_integrity_blocked(self, unique_code: str, blocked: bool) -> bool:
        """Block (or unblock) a certificate whose stored file failed integrity."""
        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .values(integrity_blocked=1 if blocked else 0, updated_at=utcnow())
        )
        return _affected(result) > 0

    def rotate_document_hash(
        self,
        unique_code: str,
        *,
        expected_hash: str,
        new_hash: str,
        new_key_id: str,
    ) -> bool:
        """Rotate a document HMAC only after a successful user confirmation.

        The expected-hash guard prevents a concurrent writer from being
        overwritten.  No plaintext document enters this repository method.
        """

        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .where(Certificate.participant_document_hash == expected_hash)
            .values(
                participant_document_hash=new_hash,
                participant_document_hash_key_id=new_key_id,
                participant_document=None,
                updated_at=utcnow(),
            )
        )
        return _affected(result) > 0

    def active_with_remote_file(self, *, after_id: int = 0, limit: int | None = None) -> list[dict]:
        """Active, non-blocked certificates that have a stored file to verify."""
        has_drive = and_(Certificate.drive_file_id.is_not(None), Certificate.drive_file_id != "")
        has_local = and_(Certificate.pdf_path.is_not(None), Certificate.pdf_path != "")
        statement = (
            select(Certificate.__table__)
            .where(Certificate.id > max(0, int(after_id)))
            .where(Certificate.status == "ativo")
            .where(Certificate.integrity_blocked == 0)
            .where(or_(has_drive, has_local))
            .order_by(Certificate.id)
        )
        if limit is not None:
            statement = statement.limit(max(1, min(int(limit), 2000)))
        rows = self.session.execute(statement).mappings().all()
        return [_to_dict(r) for r in rows]

    def update_status(
        self,
        unique_code: str,
        *,
        status: str,
        revoked_by: int | None = None,
        revoke_reason: str | None = None,
        expected_status: str | None = None,
    ) -> bool:
        revoked_at = utcnow() if status == "revogado" else None
        statement = update(Certificate).where(
            func.lower(Certificate.unique_code) == func.lower(unique_code.strip())
        )
        if expected_status is not None:
            statement = statement.where(Certificate.status == expected_status)
        result = self.session.execute(
            statement.values(
                status=status,
                revoked_at=revoked_at,
                revoked_by=revoked_by,
                revoke_reason=revoke_reason,
                updated_at=utcnow(),
            )
        )
        return _affected(result) > 0

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
        return _affected(result) > 0

    def update_file(
        self, unique_code: str, fields: dict, *, reissued_by: int | None = None
    ) -> bool:
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
                integrity_blocked=0,
                reissue_count=Certificate.reissue_count + 1,
                reissued_at=utcnow(),
                reissued_by=reissued_by,
                updated_at=utcnow(),
            )
        )
        return _affected(result) > 0

    def restore_file(self, unique_code: str, fields: dict, *, expected_checksum: str) -> bool:
        """Attach a verified backup copy without counting it as a reissue.

        The checksum guard prevents a restore drill from attaching an artifact
        to metadata that changed after the backup was produced.
        """

        result = self.session.execute(
            update(Certificate)
            .where(func.lower(Certificate.unique_code) == func.lower(unique_code.strip()))
            .where(Certificate.checksum_sha256 == expected_checksum)
            .values(
                storage_provider=fields.get("storage_provider") or "local",
                drive_file_id=fields.get("drive_file_id"),
                drive_folder_id=fields.get("drive_folder_id"),
                original_filename=fields.get("original_filename"),
                mime_type=fields.get("mime_type") or "application/pdf",
                file_size=fields.get("file_size"),
                checksum_sha256=fields.get("checksum_sha256"),
                pdf_path=fields.get("pdf_path") or "",
                integrity_blocked=0,
                updated_at=utcnow(),
            )
        )
        return _affected(result) > 0

    # reads --------------------------------------------------------------------

    def get_by_code(self, unique_code: str) -> dict | None:
        code = unique_code.strip()
        if not code:
            return None
        row = (
            self.session.execute(
                select(Certificate.__table__)
                .where(func.lower(Certificate.unique_code) == func.lower(code))
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def get_by_business_key(self, business_key: str) -> dict | None:
        if not business_key:
            return None
        row = (
            self.session.execute(
                select(Certificate.__table__)
                .where(Certificate.business_key == business_key)
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def search_by_name(self, name: str) -> list[dict]:
        from .privacy import normalize_name

        term = normalize_name(name)
        if not term:
            return []
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = (
            self.session.execute(
                select(Certificate.__table__)
                .where(Certificate.participant_name_normalized.like(f"%{escaped}%", escape="\\"))
                .order_by(
                    func.lower(Certificate.participant_name),
                    Certificate.issue_date,
                    Certificate.id,
                )
            )
            .mappings()
            .all()
        )
        return [_to_dict(r) for r in rows]

    def list_by_document_hashes(
        self,
        hashes_by_key_id: dict[str, str],
        *,
        statuses: tuple[str, ...] = ("ativo", "revogado"),
    ) -> list[dict]:
        """Return every certificate for an exact, versioned RA HMAC.

        ``participant_document_hash_key_id IS NULL`` is retained only for
        compatibility with rows created before migration 0006.  No plaintext
        academic record reaches this repository or appears in SQL parameters.
        """

        if not hashes_by_key_id:
            return []
        hash_conditions = [
            and_(
                Certificate.participant_document_hash == digest,
                or_(
                    Certificate.participant_document_hash_key_id == key_id,
                    Certificate.participant_document_hash_key_id.is_(None),
                ),
            )
            for key_id, digest in hashes_by_key_id.items()
        ]
        rows = (
            self.session.execute(
                select(Certificate.__table__)
                .where(or_(*hash_conditions))
                .where(Certificate.status.in_(statuses))
                .order_by(Certificate.issue_date.desc(), Certificate.id.desc())
            )
            .mappings()
            .all()
        )
        return [_to_dict(row) for row in rows]

    def list(
        self,
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
        conditions: list[ColumnElement[bool]] = []
        if name:
            from .privacy import normalize_name

            term = normalize_name(name)
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                Certificate.participant_name_normalized.like(f"%{escaped}%", escape="\\")
            )
        if code:
            escaped_code = (
                code.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            conditions.append(Certificate.unique_code.ilike(f"%{escaped_code}%", escape="\\"))
        if course:
            conditions.append(Certificate.course_name.ilike(f"%{course.strip()}%"))
        if event:
            conditions.append(Certificate.event_name.ilike(f"%{event.strip()}%"))
        if certificate_type:
            conditions.append(Certificate.certificate_type == certificate_type.strip())
        if status:
            conditions.append(Certificate.status == status.strip())
        if statuses:
            conditions.append(Certificate.status.in_(statuses))
        if issue_date_from:
            conditions.append(Certificate.issue_date >= issue_date_from.strip())
        if issue_date_to:
            conditions.append(Certificate.issue_date <= issue_date_to.strip())
        if batch_id:
            conditions.append(Certificate.batch_id == batch_id.strip())

        order_base = cast(
            ColumnElement[Any],
            Certificate.issue_date if order_by == "issue_date" else Certificate.created_at,
        )
        order_col = order_base.desc() if descending else order_base.asc()
        id_order = Certificate.id.desc() if descending else Certificate.id.asc()
        limit = max(1, min(int(limit), 200))
        offset = max(0, min(int(offset), 10_000))

        total = self.session.execute(
            select(func.count()).select_from(Certificate).where(*conditions)
        ).scalar_one()
        rows = (
            self.session.execute(
                select(Certificate.__table__)
                .where(*conditions)
                .order_by(order_col, id_order)
                .limit(limit)
                .offset(offset)
            )
            .mappings()
            .all()
        )
        return [_to_dict(r) for r in rows], int(total)

    def dashboard_stats(self, recent_days: int = 30) -> dict:
        """Aggregate counters for the operations dashboard.

        Every number here answers a question the secretariat actually asks, and
        each one is reachable as a filtered view of the history screen — no
        counter exists purely to fill a tile.

        ``integrity_blocked`` counts certificates whose stored file no longer
        matches its recorded hash; ``active_without_file`` counts active records
        whose PDF is missing from storage. Both mean a download will fail, so
        they are surfaced instead of being discovered by a complaining student.
        """
        cutoff = utcnow() - timedelta(days=max(1, recent_days))

        no_drive = or_(Certificate.drive_file_id.is_(None), Certificate.drive_file_id == "")
        no_local = or_(Certificate.pdf_path.is_(None), Certificate.pdf_path == "")
        # One aggregate query instead of eight sequential COUNT round-trips.
        # This matters materially when the application and Neon are in
        # different regions, while preserving exactly the same definitions.
        row = (
            self.session.execute(
                select(
                    func.count(Certificate.id).label("total"),
                    func.count(Certificate.id)
                    .filter(Certificate.status == "ativo")
                    .label("active"),
                    func.count(Certificate.id)
                    .filter(Certificate.status == "revogado")
                    .label("revoked"),
                    func.count(Certificate.id)
                    .filter(Certificate.status == "failed")
                    .label("failed"),
                    func.count(Certificate.id)
                    .filter(Certificate.status == "pending")
                    .label("pending"),
                    func.count(Certificate.id)
                    .filter(Certificate.created_at >= cutoff)
                    .label("recent"),
                    func.count(Certificate.id)
                    .filter(Certificate.integrity_blocked == 1)
                    .label("integrity_blocked"),
                    func.count(Certificate.id)
                    .filter(and_(Certificate.status == "ativo", no_drive, no_local))
                    .label("active_without_file"),
                )
            )
            .mappings()
            .one()
        )

        return {
            "total": int(row["total"] or 0),
            "active": int(row["active"] or 0),
            "revoked": int(row["revoked"] or 0),
            "failed": int(row["failed"] or 0),
            "pending": int(row["pending"] or 0),
            "recent_days": recent_days,
            "recent": int(row["recent"] or 0),
            "integrity_blocked": int(row["integrity_blocked"] or 0),
            "active_without_file": int(row["active_without_file"] or 0),
        }

    def recent(self, limit: int = 8) -> List[dict]:
        """Most recently created certificates, newest first."""
        rows = (
            self.session.execute(
                select(Certificate.__table__)
                .order_by(Certificate.created_at.desc(), Certificate.id.desc())
                .limit(max(1, min(int(limit), 50)))
            )
            .mappings()
            .all()
        )
        return [_to_dict(row) for row in rows]

    def by_normalized_name(self, name: str, limit: int = 100) -> List[dict]:
        from .privacy import normalize_name

        term = normalize_name(name)
        if not term:
            return []
        rows = (
            self.session.execute(
                select(Certificate.__table__)
                .where(Certificate.participant_name_normalized == term)
                .order_by(Certificate.id)
                .limit(max(1, min(int(limit), 100)))
            )
            .mappings()
            .all()
        )
        return [_to_dict(row) for row in rows]

    def pending_drive_migration(self) -> List[dict]:
        rows = (
            self.session.execute(
                select(Certificate.__table__)
                .where((Certificate.drive_file_id.is_(None)) | (Certificate.drive_file_id == ""))
                .where(Certificate.pdf_path.is_not(None))
                .where(Certificate.pdf_path != "")
                .order_by(Certificate.id)
            )
            .mappings()
            .all()
        )
        return [_to_dict(r) for r in rows]

    # ── Reconciliation queries ───────────────────────────────────────────────
    def pending_older_than(
        self, cutoff: datetime, *, after_id: int = 0, limit: int | None = None
    ) -> List[dict]:
        """Reservations stuck in ``pending`` since before ``cutoff`` (crashed saga)."""
        statement = (
            select(Certificate.__table__)
            .where(Certificate.id > max(0, int(after_id)))
            .where(Certificate.status == "pending")
            .where(Certificate.created_at < cutoff)
            .order_by(Certificate.id)
        )
        if limit is not None:
            statement = statement.limit(max(1, min(int(limit), 2000)))
        rows = self.session.execute(statement).mappings().all()
        return [_to_dict(r) for r in rows]

    def active_without_file(self, *, after_id: int = 0, limit: int | None = None) -> List[dict]:
        """``ativo`` rows with no usable file pointer (drive_file_id and pdf_path empty)."""
        no_drive = or_(Certificate.drive_file_id.is_(None), Certificate.drive_file_id == "")
        no_local = or_(Certificate.pdf_path.is_(None), Certificate.pdf_path == "")
        statement = (
            select(Certificate.__table__)
            .where(Certificate.id > max(0, int(after_id)))
            .where(Certificate.status == "ativo")
            .where(no_drive)
            .where(no_local)
            .order_by(Certificate.id)
        )
        if limit is not None:
            statement = statement.limit(max(1, min(int(limit), 2000)))
        rows = self.session.execute(statement).mappings().all()
        return [_to_dict(r) for r in rows]

    def failed_with_orphan_file(self, *, after_id: int = 0, limit: int | None = None) -> List[dict]:
        """``failed`` rows that still point at an uploaded file needing deletion."""
        has_drive = and_(Certificate.drive_file_id.is_not(None), Certificate.drive_file_id != "")
        has_local = and_(Certificate.pdf_path.is_not(None), Certificate.pdf_path != "")
        statement = (
            select(Certificate.__table__)
            .where(Certificate.id > max(0, int(after_id)))
            .where(Certificate.status == "failed")
            .where(or_(has_drive, has_local))
            .order_by(Certificate.id)
        )
        if limit is not None:
            statement = statement.limit(max(1, min(int(limit), 2000)))
        rows = self.session.execute(statement).mappings().all()
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

    def drive_file_index_by_folder(self) -> dict[str | None, dict[str, str]]:
        """Group opaque Drive file ids by their persisted destination folder."""
        rows = self.session.execute(
            select(
                Certificate.drive_folder_id,
                Certificate.drive_file_id,
                Certificate.unique_code,
            )
            .where(Certificate.drive_file_id.is_not(None))
            .where(Certificate.drive_file_id != "")
        ).all()
        grouped: dict[str | None, dict[str, str]] = {}
        for folder_id, file_id, code in rows:
            grouped.setdefault(folder_id or None, {})[file_id] = code
        return grouped


# ── Admin users ─────────────────────────────────────────────────────────────────


class AdminUserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_username(self, username: str) -> dict | None:
        row = (
            self.session.execute(
                select(AdminUser.__table__)
                .where(func.lower(AdminUser.username) == username.strip().lower())
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def get_by_id(self, user_id: int) -> dict | None:
        row = (
            self.session.execute(
                select(AdminUser.__table__).where(AdminUser.id == user_id).limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def create(
        self,
        username: str,
        password_hash: str,
        role: str = "secretaria",
        *,
        name: str | None = None,
        must_change_password: bool = False,
        created_by: int | None = None,
    ) -> int | None:
        if self.get_by_username(username):
            return None
        try:
            with self.session.begin_nested():
                result = self.session.execute(
                    insert(_table(AdminUser)).values(
                        name=(name or username).strip(),
                        username=username.strip(),
                        password_hash=password_hash,
                        role=role,
                        must_change_password=1 if must_change_password else 0,
                        created_by=created_by,
                    )
                )
            return _inserted_id(result)
        except IntegrityError:
            return None

    def count(self) -> int:
        return int(self.session.execute(select(func.count()).select_from(AdminUser)).scalar_one())

    def set_active(self, user_id: int, active: bool) -> bool:
        result = self.session.execute(
            update(AdminUser)
            .where(AdminUser.id == user_id)
            .values(is_active=1 if active else 0, updated_at=utcnow())
        )
        return _affected(result) > 0

    def set_role(self, user_id: int, role: str) -> bool:
        result = self.session.execute(
            update(AdminUser).where(AdminUser.id == user_id).values(role=role, updated_at=utcnow())
        )
        return _affected(result) > 0

    def update_identity_and_role(
        self,
        user_id: int,
        *,
        name: str | None = None,
        username: str | None = None,
        role: str | None = None,
    ) -> bool:
        values: dict[str, Any] = {"updated_at": utcnow()}
        if name is not None:
            values["name"] = name.strip()
        if username is not None:
            values["username"] = username.strip()
        if role is not None:
            values["role"] = role
        if len(values) == 1:
            return False
        result = self.session.execute(
            update(AdminUser).where(AdminUser.id == user_id).values(**values)
        )
        return _affected(result) > 0

    def set_password(
        self,
        user_id: int,
        password_hash: str,
        *,
        must_change_password: bool,
    ) -> bool:
        result = self.session.execute(
            update(AdminUser)
            .where(AdminUser.id == user_id)
            .values(
                password_hash=password_hash,
                must_change_password=1 if must_change_password else 0,
                password_changed_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        return _affected(result) > 0

    def list_all(self) -> list[dict]:
        """Every admin user, without the password hash.

        Read-only listing for the "Usuários" screen. ``password_hash`` is
        selected out explicitly rather than filtered afterwards, so the secret
        never reaches the response layer at all.
        """
        rows = (
            self.session.execute(
                select(
                    AdminUser.id,
                    AdminUser.name,
                    AdminUser.username,
                    AdminUser.role,
                    AdminUser.is_active,
                    AdminUser.must_change_password,
                    AdminUser.password_changed_at,
                    AdminUser.created_at,
                    AdminUser.updated_at,
                ).order_by(AdminUser.username.asc())
            )
            .mappings()
            .all()
        )
        return [_to_dict(row) for row in rows]

    def count_active_admins(self, exclude_user_id: int | None = None) -> int:
        """Active users holding the ``admin`` role.

        Used to refuse the change that would leave the installation with no way
        back in — demoting or deactivating the last administrator.
        """
        conditions = [AdminUser.role == "admin", AdminUser.is_active == 1]
        if exclude_user_id is not None:
            conditions.append(AdminUser.id != exclude_user_id)
        return int(
            self.session.execute(
                select(func.count()).select_from(AdminUser).where(*conditions)
            ).scalar_one()
        )


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
            insert(_table(AuthSession)).values(
                session_id=session_id,
                user_id=user_id,
                expires_at=expires_at,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
                created_at=utcnow(),
            )
        )

    def get_active(self, session_id: str, now: datetime) -> dict | None:
        row = (
            self.session.execute(
                select(AuthSession.__table__)
                .where(AuthSession.session_id == session_id)
                .where(AuthSession.revoked_at.is_(None))
                .where(AuthSession.expires_at > now)
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def get_active_user(self, session_id: str, now: datetime) -> dict | None:
        """Validate a session and load its user/policy flags in one query."""
        row = (
            self.session.execute(
                select(
                    *AdminUser.__table__.c,
                    InstitutionalSettings.secretaria_can_revoke.label("secretaria_can_revoke"),
                    InstitutionalSettings.secretaria_can_reissue.label("secretaria_can_reissue"),
                )
                .select_from(AuthSession)
                .join(AdminUser, AdminUser.id == AuthSession.user_id)
                .outerjoin(InstitutionalSettings, InstitutionalSettings.id == 1)
                .where(AuthSession.session_id == session_id)
                .where(AuthSession.revoked_at.is_(None))
                .where(AuthSession.expires_at > now)
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def revoke(self, session_id: str, reason: str = "logout") -> bool:
        result = self.session.execute(
            update(AuthSession)
            .where(AuthSession.session_id == session_id)
            .where(AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoke_reason=reason[:64])
        )
        return _affected(result) > 0

    def revoke_all(
        self,
        user_id: int,
        reason: str = "revoke_all",
        *,
        exclude_session_id: str | None = None,
    ) -> int:
        statement = (
            update(AuthSession)
            .where(AuthSession.user_id == user_id)
            .where(AuthSession.revoked_at.is_(None))
        )
        if exclude_session_id:
            statement = statement.where(AuthSession.session_id != exclude_session_id)
        result = self.session.execute(
            statement.values(revoked_at=utcnow(), revoke_reason=reason[:64])
        )
        return _affected(result)

    def cleanup(self, before: datetime) -> int:
        result = self.session.execute(delete(AuthSession).where(AuthSession.expires_at < before))
        return _affected(result)

    def set_expiry(self, session_id: str, expires_at: datetime) -> bool:
        """Administrative helper used by maintenance and expiry contract tests."""
        result = self.session.execute(
            update(AuthSession)
            .where(AuthSession.session_id == session_id)
            .values(expires_at=expires_at)
        )
        return _affected(result) > 0


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
        return _affected(result)


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
        rows = (
            self.session.execute(select(LoginThrottle.__table__).where(or_(*conditions)))
            .mappings()
            .all()
        )
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
                    now + timedelta(seconds=lockout_seconds) if failures >= threshold else None
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
                    now + timedelta(seconds=lockout_seconds) if failures >= threshold else None
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
        return _affected(result)


# ── Institutional settings ───────────────────────────────────────────────────


class GoogleDriveIntegrationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def connection(self, user_id: int) -> dict | None:
        row = (
            self.session.execute(
                select(GoogleDriveConnection.__table__)
                .where(GoogleDriveConnection.user_id == user_id)
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def connection_by_state(self, state_hash: str) -> dict | None:
        row = (
            self.session.execute(
                select(GoogleDriveConnection.__table__)
                .where(GoogleDriveConnection.state_hash == state_hash)
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def store_state(self, user_id: int, values: dict) -> dict:
        current = self.connection(user_id)
        safe = dict(values)
        safe["updated_at"] = utcnow()
        if current:
            self.session.execute(
                update(GoogleDriveConnection)
                .where(GoogleDriveConnection.user_id == user_id)
                .values(**safe)
            )
        else:
            self.session.execute(
                insert(_table(GoogleDriveConnection)).values(user_id=user_id, **safe)
            )
        return self.connection(user_id) or {"user_id": user_id, **safe}

    def consume_state(self, user_id: int, state_hash: str) -> bool:
        result = self.session.execute(
            update(GoogleDriveConnection)
            .where(GoogleDriveConnection.user_id == user_id)
            .where(GoogleDriveConnection.state_hash == state_hash)
            .values(state_hash=None, updated_at=utcnow())
        )
        return _affected(result) == 1

    def complete_connection(self, user_id: int, values: dict) -> bool:
        safe = dict(values)
        safe.update(
            state_hash=None,
            pkce_verifier_ciphertext=None,
            pkce_verifier_nonce=None,
            pkce_verifier_key_id=None,
            state_expires_at=None,
            updated_at=utcnow(),
        )
        result = self.session.execute(
            update(GoogleDriveConnection)
            .where(GoogleDriveConnection.user_id == user_id)
            # The one-time state is consumed before the external token call.
            # A new OAuth start racing that call installs a new non-null state
            # and therefore prevents the stale callback from overwriting it.
            .where(GoogleDriveConnection.state_hash.is_(None))
            .values(**safe)
        )
        return _affected(result) == 1

    def clear_connection(self, user_id: int) -> int:
        self.session.execute(
            delete(GoogleDriveFolderGrant).where(GoogleDriveFolderGrant.user_id == user_id)
        )
        result = self.session.execute(
            delete(GoogleDriveConnection).where(GoogleDriveConnection.user_id == user_id)
        )
        return _affected(result)

    def upsert_grant(self, values: dict) -> dict:
        user_id = int(values["user_id"])
        folder_hash = str(values["folder_id_hash"])
        row = self.grant(user_id, folder_hash)
        safe = dict(values)
        safe["validated_at"] = utcnow()
        if row:
            self.session.execute(
                update(GoogleDriveFolderGrant)
                .where(GoogleDriveFolderGrant.id == int(row["id"]))
                .values(**safe)
            )
        else:
            self.session.execute(insert(_table(GoogleDriveFolderGrant)).values(**safe))
        return self.grant(user_id, folder_hash) or safe

    def grant(self, user_id: int, folder_hash: str) -> dict | None:
        row = (
            self.session.execute(
                select(GoogleDriveFolderGrant.__table__)
                .where(GoogleDriveFolderGrant.user_id == user_id)
                .where(GoogleDriveFolderGrant.folder_id_hash == folder_hash)
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None


class InstitutionalSettingsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self) -> dict | None:
        row = (
            self.session.execute(
                select(InstitutionalSettings.__table__)
                .where(InstitutionalSettings.id == 1)
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def create(self, values: dict) -> dict:
        self.session.execute(insert(_table(InstitutionalSettings)).values(id=1, **values))
        return self.get() or {"id": 1, **values}

    def update(self, values: dict, *, actor_id: int | None = None) -> dict | None:
        safe_values = dict(values)
        safe_values["updated_at"] = utcnow()
        safe_values["updated_by"] = actor_id
        result = self.session.execute(
            update(InstitutionalSettings).where(InstitutionalSettings.id == 1).values(**safe_values)
        )
        if not _affected(result):
            return None
        return self.get()


# ── Emission batches ─────────────────────────────────────────────────────────


class EmissionBatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, values: dict, items: list[dict] | None = None) -> dict:
        self.session.execute(insert(_table(EmissionBatch)).values(**values))
        if items:
            self.session.execute(insert(_table(EmissionBatchItem)), items)
        return self.get(str(values["id"])) or dict(values)

    def get(self, batch_id: str) -> dict | None:
        row = (
            self.session.execute(
                select(EmissionBatch.__table__).where(EmissionBatch.id == batch_id).limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def purge_terminal_payloads(self, before: datetime) -> int:
        """Remove encrypted retry material after its bounded retention period.

        Business/audit counters remain queryable. Only payloads that could
        reconstruct participant input are removed, and only for terminal jobs.
        """

        terminal_ids = select(EmissionBatch.id).where(
            EmissionBatch.status.in_(("completed", "partial", "failed", "cancelled")),
            EmissionBatch.updated_at < before,
        )
        item_result = self.session.execute(
            update(EmissionBatchItem)
            .where(EmissionBatchItem.batch_id.in_(terminal_ids))
            .where(EmissionBatchItem.payload_ciphertext.is_not(None))
            .values(
                payload_ciphertext=None,
                payload_nonce=None,
                payload_key_id=None,
                updated_at=utcnow(),
            )
        )
        batch_result = self.session.execute(
            update(EmissionBatch)
            .where(EmissionBatch.id.in_(terminal_ids))
            .where(EmissionBatch.context_ciphertext.is_not(None))
            .values(
                context_ciphertext=None,
                context_nonce=None,
                payload_key_id=None,
                updated_at=utcnow(),
            )
        )
        return _affected(item_result) + _affected(batch_result)

    def get_by_idempotency_key(self, key: str) -> dict | None:
        row = (
            self.session.execute(
                select(EmissionBatch.__table__).where(EmissionBatch.idempotency_key == key).limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def items(self, batch_id: str, *, statuses: tuple[str, ...] | None = None) -> list[dict]:
        statement = select(EmissionBatchItem.__table__).where(
            EmissionBatchItem.batch_id == batch_id
        )
        if statuses:
            statement = statement.where(EmissionBatchItem.status.in_(statuses))
        rows = self.session.execute(statement.order_by(EmissionBatchItem.id)).mappings().all()
        return [_to_dict(row) for row in rows]

    def claim(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        batch_id: str | None = None,
    ) -> dict | None:
        """Atomically claim one queued or stale job.

        PostgreSQL emits ``FOR UPDATE SKIP LOCKED`` so multiple Cloud Run Job
        tasks can poll safely. SQLite ignores the unsupported lock clause but
        still serializes writes, which is sufficient for local/test use.
        """
        eligible = or_(
            and_(
                EmissionBatch.status == "queued",
                or_(
                    EmissionBatch.next_attempt_at.is_(None),
                    EmissionBatch.next_attempt_at <= now,
                ),
            ),
            and_(
                EmissionBatch.status == "processing",
                EmissionBatch.lease_expires_at.is_not(None),
                EmissionBatch.lease_expires_at < now,
            ),
        )
        statement = (
            select(EmissionBatch)
            .where(eligible)
            .where(EmissionBatch.attempt_count < EmissionBatch.max_attempts)
            .order_by(EmissionBatch.created_at, EmissionBatch.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if batch_id is not None:
            statement = statement.where(EmissionBatch.id == batch_id)
        batch = self.session.execute(statement).scalar_one_or_none()
        if batch is None:
            return None
        if batch.status == "processing":
            self.session.execute(
                update(EmissionBatchItem)
                .where(EmissionBatchItem.batch_id == batch.id)
                .where(EmissionBatchItem.status == "processing")
                .values(status="queued", updated_at=now)
            )
        batch.status = "processing"
        batch.attempt_count = int(batch.attempt_count) + 1
        batch.lease_owner = worker_id
        batch.lease_expires_at = lease_expires_at
        batch.worker_heartbeat_at = now
        batch.started_at = batch.started_at or now
        batch.completed_at = None
        batch.error_message = None
        batch.last_error_code = None
        batch.updated_at = now
        self.session.flush()
        return self.get(batch.id)

    def heartbeat(
        self,
        batch_id: str,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        result = self.session.execute(
            update(EmissionBatch)
            .where(EmissionBatch.id == batch_id)
            .where(EmissionBatch.status == "processing")
            .where(EmissionBatch.lease_owner == worker_id)
            .values(
                worker_heartbeat_at=now,
                lease_expires_at=lease_expires_at,
                updated_at=now,
            )
        )
        return _affected(result) == 1

    def mark_item_processing(self, item_id: int, *, now: datetime) -> bool:
        result = self.session.execute(
            update(EmissionBatchItem)
            .where(EmissionBatchItem.id == item_id)
            .where(EmissionBatchItem.status == "queued")
            .values(
                status="processing",
                attempt_count=EmissionBatchItem.attempt_count + 1,
                started_at=now,
                completed_at=None,
                error_code=None,
                error_message=None,
                updated_at=now,
            )
        )
        return _affected(result) == 1

    def mark_item(
        self,
        item_id: int,
        *,
        status: str,
        certificate_code: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        clear_payload: bool = False,
    ) -> bool:
        values: dict[str, Any] = {
            "status": status,
            "certificate_code": certificate_code,
            "error_code": error_code,
            "error_message": error_message[:500] if error_message else None,
            "completed_at": utcnow(),
            "updated_at": utcnow(),
        }
        if clear_payload:
            values.update(
                payload_ciphertext=None,
                payload_nonce=None,
                payload_key_id=None,
            )
        result = self.session.execute(
            update(EmissionBatchItem)
            .where(EmissionBatchItem.id == item_id)
            .where(EmissionBatchItem.status == "processing")
            .values(**values)
        )
        return _affected(result) == 1

    def counts(self, batch_id: str) -> dict[str, int]:
        rows = self.session.execute(
            select(EmissionBatchItem.status, func.count())
            .where(EmissionBatchItem.batch_id == batch_id)
            .group_by(EmissionBatchItem.status)
        ).all()
        return {str(status): int(count) for status, count in rows}

    def request_cancel(self, batch_id: str, *, now: datetime) -> str | None:
        batch = self.session.execute(
            select(EmissionBatch).where(EmissionBatch.id == batch_id).with_for_update()
        ).scalar_one_or_none()
        if batch is None:
            return None
        if batch.status in {"completed", "partial", "failed", "cancelled"}:
            return batch.status
        batch.cancel_requested_at = now
        batch.updated_at = now
        if batch.status == "queued":
            batch.status = "cancelled"
            batch.completed_at = now
            batch.context_ciphertext = None
            batch.context_nonce = None
            batch.payload_key_id = None
            self.session.execute(
                update(EmissionBatchItem)
                .where(EmissionBatchItem.batch_id == batch_id)
                .where(EmissionBatchItem.status == "queued")
                .values(
                    status="cancelled",
                    payload_ciphertext=None,
                    payload_nonce=None,
                    payload_key_id=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
        self.session.flush()
        return batch.status

    def cancel_remaining(self, batch_id: str, *, now: datetime) -> int:
        result = self.session.execute(
            update(EmissionBatchItem)
            .where(EmissionBatchItem.batch_id == batch_id)
            .where(EmissionBatchItem.status == "queued")
            .values(
                status="cancelled",
                payload_ciphertext=None,
                payload_nonce=None,
                payload_key_id=None,
                completed_at=now,
                updated_at=now,
            )
        )
        return _affected(result)

    def release(
        self,
        batch_id: str,
        *,
        worker_id: str,
        retry_at: datetime | None,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> bool:
        """Release a lease after an infrastructure-level worker failure."""
        batch = self.session.execute(
            select(EmissionBatch)
            .where(EmissionBatch.id == batch_id)
            .where(EmissionBatch.status == "processing")
            .where(EmissionBatch.lease_owner == worker_id)
            .with_for_update()
        ).scalar_one_or_none()
        if batch is None:
            return False
        retrying = retry_at is not None and batch.attempt_count < batch.max_attempts
        self.session.execute(
            update(EmissionBatchItem)
            .where(EmissionBatchItem.batch_id == batch_id)
            .where(EmissionBatchItem.status == "processing")
            .values(
                status="queued" if retrying else "failed",
                error_code=None if retrying else error_code,
                error_message=None if retrying else error_message[:500],
                completed_at=None if retrying else now,
                updated_at=now,
            )
        )
        batch.status = "queued" if retrying else "failed"
        batch.next_attempt_at = retry_at if retrying else None
        batch.lease_owner = None
        batch.lease_expires_at = None
        batch.worker_heartbeat_at = now
        batch.last_error_code = error_code
        batch.error_message = error_message[:500]
        batch.completed_at = None if retrying else now
        batch.updated_at = now
        self.session.flush()
        return True

    def retry(self, batch_id: str, *, now: datetime) -> bool:
        batch = self.session.execute(
            select(EmissionBatch).where(EmissionBatch.id == batch_id).with_for_update()
        ).scalar_one_or_none()
        if (
            batch is None
            or batch.status not in {"failed", "partial"}
            or batch.attempt_count >= batch.max_attempts
            or not batch.context_ciphertext
        ):
            return False
        reset = self.session.execute(
            update(EmissionBatchItem)
            .where(EmissionBatchItem.batch_id == batch_id)
            .where(EmissionBatchItem.status == "failed")
            .where(EmissionBatchItem.payload_ciphertext.is_not(None))
            .values(
                status="queued",
                error_code=None,
                error_message=None,
                completed_at=None,
                updated_at=now,
            )
        )
        if _affected(reset) == 0:
            return False
        batch.status = "queued"
        batch.next_attempt_at = now
        batch.lease_owner = None
        batch.lease_expires_at = None
        batch.cancel_requested_at = None
        batch.completed_at = None
        batch.error_message = None
        batch.last_error_code = None
        batch.updated_at = now
        self.session.flush()
        return True

    def update(self, batch_id: str, values: dict) -> bool:
        safe_values = dict(values)
        safe_values["updated_at"] = utcnow()
        result = self.session.execute(
            update(EmissionBatch).where(EmissionBatch.id == batch_id).values(**safe_values)
        )
        return _affected(result) > 0

    def list(
        self,
        *,
        created_by: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        conditions = []
        if created_by is not None:
            conditions.append(EmissionBatch.created_by == created_by)
        total = int(
            self.session.execute(
                select(func.count()).select_from(EmissionBatch).where(*conditions)
            ).scalar_one()
        )
        rows = (
            self.session.execute(
                select(EmissionBatch.__table__)
                .where(*conditions)
                .order_by(EmissionBatch.created_at.desc())
                .limit(max(1, min(int(limit), 100)))
                .offset(max(0, int(offset)))
            )
            .mappings()
            .all()
        )
        return [_to_dict(row) for row in rows], total


# ── Audit log ────────────────────────────────────────────────────────────────

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
        sequence = self.session.execute(
            select(TemplateVersionSequence).where(TemplateVersionSequence.id == 1).with_for_update()
        ).scalar_one_or_none()
        if sequence is None:
            # Fresh dev/test databases are created from metadata rather than
            # migrations. Production migration 0008 always seeds this row.
            next_seed = (
                int(
                    self.session.execute(
                        select(func.coalesce(func.max(TemplateVersion.version_number), 0))
                    ).scalar_one()
                )
                + 1
            )
            sequence = TemplateVersionSequence(id=1, next_number=next_seed)
            self.session.add(sequence)
            self.session.flush()
        next_num = int(sequence.next_number)
        sequence.next_number = next_num + 1
        self.session.flush()
        result = self.session.execute(
            insert(_table(TemplateVersion)).values(
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
        return {"id": _inserted_id(result), "version_number": next_num}

    def get(self, version_id: int) -> dict | None:
        row = (
            self.session.execute(
                select(*_VERSION_META).where(TemplateVersion.id == version_id).limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def get_active(self) -> dict | None:
        row = (
            self.session.execute(
                select(*_VERSION_META)
                .where(TemplateVersion.is_active == 1)
                .order_by(TemplateVersion.version_number.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _to_dict(row) if row else None

    def list_all(self) -> list[dict]:
        rows = (
            self.session.execute(
                select(*_VERSION_META).order_by(TemplateVersion.version_number.desc())
            )
            .mappings()
            .all()
        )
        return [_to_dict(r) for r in rows]

    def count(self) -> int:
        return int(
            self.session.execute(select(func.count()).select_from(TemplateVersion)).scalar_one()
        )

    def get_background(self, version_id: int) -> tuple[bytes | None, str] | None:
        row = self.session.execute(
            select(TemplateVersion.background_image, TemplateVersion.background_mime_type)
            .where(TemplateVersion.id == version_id)
            .limit(1)
        ).first()
        if row is None:
            return None
        return row[0], row[1]

    def activate(self, version_id: int, actor: int | None = None) -> bool:
        """Make exactly one version active (atomic within the caller's txn)."""
        # The singleton sequence row doubles as a portable advisory lock. It
        # serializes create/activate across PostgreSQL workers; SQLite already
        # serializes writers.
        sequence_id = self.session.execute(
            select(TemplateVersionSequence.id)
            .where(TemplateVersionSequence.id == 1)
            .with_for_update()
        ).scalar_one_or_none()
        if sequence_id is None:
            next_number = (
                int(
                    self.session.execute(
                        select(func.coalesce(func.max(TemplateVersion.version_number), 0))
                    ).scalar_one()
                )
                + 1
            )
            self.session.add(TemplateVersionSequence(id=1, next_number=next_number))
            self.session.flush()
        exists = self.session.execute(
            select(TemplateVersion.id).where(TemplateVersion.id == version_id).limit(1)
        ).first()
        if not exists:
            return False
        self.session.execute(
            update(TemplateVersion).where(TemplateVersion.is_active == 1).values(is_active=0)
        )
        self.session.execute(
            update(TemplateVersion)
            .where(TemplateVersion.id == version_id)
            .values(is_active=1, activated_at=utcnow(), activated_by=actor)
        )
        return True

    def rename(self, version_id: int, name: str) -> dict | None:
        """Rename only the human label; the immutable layout stays untouched."""
        exists = self.session.execute(
            select(TemplateVersion.id).where(TemplateVersion.id == version_id).limit(1)
        ).first()
        if not exists:
            return None
        self.session.execute(
            update(TemplateVersion).where(TemplateVersion.id == version_id).values(name=name)
        )
        self.session.flush()
        return self.get(version_id)

    def delete_if_unused(self, version_id: int) -> tuple[str, dict | None]:
        """Delete an inactive, unreferenced version without weakening history.

        The row is locked while the guards are evaluated. The active version,
        the last remaining version, and versions recorded by certificates are
        deliberately preserved.
        """
        version_row = (
            self.session.execute(
                select(*_VERSION_META)
                .where(TemplateVersion.id == version_id)
                .with_for_update()
                .limit(1)
            )
            .mappings()
            .first()
        )
        if version_row is None:
            return "not_found", None
        version = _to_dict(version_row)
        if bool(version["is_active"]):
            return "active", version
        total = int(
            self.session.execute(select(func.count()).select_from(TemplateVersion)).scalar_one()
        )
        if total <= 1:
            return "last_version", version
        references = int(
            self.session.execute(
                select(func.count())
                .select_from(Certificate)
                .where(Certificate.template_version_id == version_id)
            ).scalar_one()
        )
        if references:
            return "referenced", version
        self.session.execute(delete(TemplateVersion).where(TemplateVersion.id == version_id))
        return "deleted", version


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
            insert(_table(AuditLog)).values(
                action=action,
                actor_id=actor_id,
                actor_username=actor_username,
                target_type=target_type,
                target_id=target_id,
                details=details,
            )
        )

    def list(
        self,
        *,
        action: str | None = None,
        actions: tuple[str, ...] | None = None,
        actor: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        conditions = []
        if action:
            conditions.append(AuditLog.action == action)
        elif actions:
            conditions.append(AuditLog.action.in_(actions))
        if actor:
            escaped = actor.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(AuditLog.actor_username.ilike(f"%{escaped}%", escape="\\"))
        if target_type:
            conditions.append(AuditLog.target_type == target_type.strip())
        if target_id:
            escaped = (
                target_id.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            conditions.append(AuditLog.target_id.ilike(f"%{escaped}%", escape="\\"))
        if date_from:
            conditions.append(AuditLog.created_at >= date_from)
        if date_to:
            conditions.append(AuditLog.created_at <= date_to)
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        total = int(
            self.session.execute(
                select(func.count()).select_from(AuditLog).where(*conditions)
            ).scalar_one()
        )
        rows = (
            self.session.execute(
                select(AuditLog.__table__)
                .where(*conditions)
                .order_by(AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
            .mappings()
            .all()
        )
        return [_to_dict(row) for row in rows], total
