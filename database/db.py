"""Shared SQLite access layer for CertificadosSecretaria.

Imported by BOTH projects:

  - certificados-admin   → grava certificados ao gerá-los
  - certificados-consulta → lê certificados (busca por nome / código)

Paths are resolved once here so the two projects always agree on where the
database file and the PDF storage live:

  DATABASE_PATH  env var → arquivo .db compartilhado
                           (default: <repo>/database/certificates.db)
  STORAGE_DIR    env var → raiz do armazenamento de PDFs
                           (default: <repo>/storage  →  PDFs em <repo>/storage/pdfs)

The module is import-safe: it never opens a connection at import time.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# db.py lives in <repo_root>/database/db.py
REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal, dependency-free .env loader for the shared project config.

    Parses simple KEY=VALUE lines from a single .env at the repo root, so both
    projects pick up the same DATABASE_PATH / STORAGE_DIR. Real environment
    variables always win (we never overwrite what's already set)."""
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


def _path_from_env(default: Path, *vars: str) -> Path:
    """Return the first non-empty env var among ``vars`` as a Path, else default."""
    for var in vars:
        raw = os.getenv(var, "").strip()
        if raw:
            return Path(raw).expanduser()
    return default


# ── Canonical, shared paths (single source of truth for both projects) ─────────
# New names: DB_PATH / LOCAL_STORAGE_PATH. Legacy aliases kept for compatibility.
DATABASE_PATH: Path = _path_from_env(
    REPO_ROOT / "database" / "certificates.db", "DB_PATH", "DATABASE_PATH"
)
STORAGE_DIR: Path = _path_from_env(
    REPO_ROOT / "storage", "LOCAL_STORAGE_PATH", "STORAGE_DIR"
)
PDFS_DIR: Path = STORAGE_DIR / "pdfs"

SCHEMA_PATH: Path = Path(__file__).resolve().parent / "schema.sql"


# ── Connection / bootstrap ─────────────────────────────────────────────────────

def _ensure_parent_dirs() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PDFS_DIR.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """Open a connection to the shared database with sensible defaults.

    Callers are responsible for closing the connection (the helpers below do).
    WAL mode is enabled so the admin (writer) and consulta (reader) can hit the
    same file concurrently without locking each other out.
    """
    _ensure_parent_dirs()
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# Columns added after the initial release. The migration below adds any that
# are missing on existing databases (SQLite ALTER TABLE ADD COLUMN preserves
# all existing rows/data). Keep in sync with schema.sql.
_EXTRA_COLUMNS: dict[str, str] = {
    # storage (1ª etapa)
    "storage_provider": "TEXT NOT NULL DEFAULT 'local'",
    "drive_file_id": "TEXT",
    "drive_folder_id": "TEXT",
    "original_filename": "TEXT",
    "mime_type": "TEXT NOT NULL DEFAULT 'application/pdf'",
    "file_size": "INTEGER",
    "checksum_sha256": "TEXT",
    "status": "TEXT NOT NULL DEFAULT 'ativo'",
    # modelo expandido + lifecycle (2ª etapa)
    "participant_email": "TEXT",
    "participant_document": "TEXT",
    "course_name": "TEXT",
    "workload_hours": "INTEGER",
    "start_date": "TEXT",
    "end_date": "TEXT",
    "business_key": "TEXT",
    "issued_by": "INTEGER",
    "revoked_at": "TEXT",
    "revoked_by": "INTEGER",
    "revoke_reason": "TEXT",
    "updated_at": "TEXT",
}

_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_certificates_participant_name ON certificates (participant_name)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_event_name ON certificates (event_name)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_course_name ON certificates (course_name)",
    "CREATE INDEX IF NOT EXISTS idx_certificates_status ON certificates (status)",
    # NULLs são distintos no SQLite, então certificados antigos sem business_key
    # não conflitam neste índice único.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_certificates_business_key ON certificates (business_key)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log (created_at)",
)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add any columns missing on a pre-existing certificates table.

    Safe and idempotent: only columns absent from PRAGMA table_info are added,
    so no data is ever lost and re-running is a no-op.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(certificates)")}
    if not existing:
        return  # table not created yet; schema.sql already has every column
    for column, ddl in _EXTRA_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE certificates ADD COLUMN {column} {ddl}")


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes AFTER columns are guaranteed to exist."""
    for statement in _INDEXES:
        conn.execute(statement)


def init_db() -> None:
    """Create the tables if they don't exist and run lightweight migrations.

    Idempotent; safe to call on every startup of either project."""
    _ensure_parent_dirs()
    schema = SCHEMA_PATH.read_text("utf-8")
    conn = get_connection()
    try:
        conn.executescript(schema)  # tables only (CREATE TABLE IF NOT EXISTS)
        _ensure_columns(conn)       # add new columns to old tables
        _ensure_indexes(conn)       # then build indexes on guaranteed columns
        conn.commit()
    finally:
        conn.close()


# ── Writes (used by certificados-admin) ────────────────────────────────────────

def existing_codes() -> set[str]:
    """Return all unique codes already stored, upper-cased (for collision checks)."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT unique_code FROM certificates").fetchall()
    finally:
        conn.close()
    return {row["unique_code"].upper() for row in rows}


# Full ordered column list used by insert_certificates. Each row is normalised
# to contain every key (with sensible defaults) so callers may pass only the
# fields they have.
_INSERT_COLUMNS = (
    "unique_code",
    "participant_name",
    "participant_email",
    "participant_document",
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
    "issued_by",
)


def _normalize_insert_row(row: dict) -> dict:
    normalized = {col: row.get(col) for col in _INSERT_COLUMNS}
    # NOT NULL columns need non-null defaults.
    normalized["pdf_path"] = normalized["pdf_path"] or ""
    normalized["storage_provider"] = normalized["storage_provider"] or "local"
    normalized["mime_type"] = normalized["mime_type"] or "application/pdf"
    normalized["status"] = normalized["status"] or "ativo"
    return normalized


def insert_certificates(rows: list[dict]) -> None:
    """Bulk-insert generated certificates. Skips rows whose unique_code already
    exists (INSERT OR IGNORE) so a retry never raises on duplicates."""
    if not rows:
        return
    columns = ", ".join(_INSERT_COLUMNS)
    placeholders = ", ".join(f":{col}" for col in _INSERT_COLUMNS)
    normalized = [_normalize_insert_row(row) for row in rows]
    conn = get_connection()
    try:
        conn.executemany(
            f"INSERT OR IGNORE INTO certificates ({columns}) VALUES ({placeholders})",
            normalized,
        )
        conn.commit()
    finally:
        conn.close()


# ── Reads (used by both, mainly certificados-consulta) ──────────────────────────

def get_by_code(unique_code: str) -> dict | None:
    """Look up a single certificate by its exact code (case-insensitive)."""
    code = unique_code.strip()
    if not code:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM certificates WHERE unique_code = ? COLLATE NOCASE LIMIT 1",
            (code,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def search_by_name(name: str) -> list[dict]:
    """Partial, case-insensitive search by participant name."""
    term = name.strip()
    if not term:
        return []
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM certificates
            WHERE participant_name LIKE ? COLLATE NOCASE
            ORDER BY participant_name COLLATE NOCASE, issue_date, id
            """,
            (f"%{term}%",),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def resolve_pdf_path(pdf_path: str) -> Path:
    """Resolve a stored (STORAGE_DIR-relative) pdf_path to an absolute path.

    Absolute paths are returned unchanged, so legacy/external rows still work.
    """
    candidate = Path(pdf_path)
    return candidate if candidate.is_absolute() else (STORAGE_DIR / candidate)


# ── Admin certificate queries (history) ─────────────────────────────────────────

def business_key_exists(business_key: str) -> bool:
    """True if a certificate with this idempotency key already exists."""
    return get_by_business_key(business_key) is not None


def get_by_business_key(business_key: str) -> dict | None:
    """Return the existing certificate for an idempotency key, if any."""
    if not business_key:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM certificates WHERE business_key = ? LIMIT 1",
            (business_key,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


_SEARCHABLE = {
    "name": "participant_name",
    "course": "course_name",
    "event": "event_name",
}


def list_certificates(
    *,
    name: str | None = None,
    code: str | None = None,
    course: str | None = None,
    event: str | None = None,
    status: str | None = None,
    order_by: str = "created_at",
    descending: bool = True,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Filtered, paginated certificate listing for the admin area.

    Returns ``(rows, total)`` where ``total`` ignores limit/offset.
    """
    clauses: list[str] = []
    params: list = []
    if name:
        clauses.append("participant_name LIKE ? COLLATE NOCASE")
        params.append(f"%{name.strip()}%")
    if code:
        clauses.append("unique_code = ? COLLATE NOCASE")
        params.append(code.strip())
    if course:
        clauses.append("course_name LIKE ? COLLATE NOCASE")
        params.append(f"%{course.strip()}%")
    if event:
        clauses.append("event_name LIKE ? COLLATE NOCASE")
        params.append(f"%{event.strip()}%")
    if status:
        clauses.append("status = ?")
        params.append(status.strip())

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    order_col = "issue_date" if order_by == "issue_date" else "created_at"
    direction = "DESC" if descending else "ASC"
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    conn = get_connection()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM certificates{where}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM certificates{where} "
            f"ORDER BY {order_col} {direction}, id {direction} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows], int(total)


def certificates_pending_drive_migration() -> list[dict]:
    """Certificates stored locally (have pdf_path) and not yet on Drive."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM certificates "
            "WHERE (drive_file_id IS NULL OR drive_file_id = '') "
            "AND pdf_path IS NOT NULL AND pdf_path != '' "
            "ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


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
    """Mark a certificate as stored on Drive, **keeping** the legacy pdf_path."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE certificates
               SET storage_provider = 'google_drive',
                   drive_file_id    = :drive_file_id,
                   drive_folder_id  = :drive_folder_id,
                   original_filename = COALESCE(:original_filename, original_filename),
                   mime_type        = COALESCE(:mime_type, mime_type),
                   file_size        = :file_size,
                   checksum_sha256  = :checksum_sha256,
                   updated_at       = datetime('now')
             WHERE unique_code = :unique_code COLLATE NOCASE
            """,
            {
                "drive_file_id": drive_file_id,
                "drive_folder_id": drive_folder_id,
                "original_filename": original_filename,
                "mime_type": mime_type,
                "file_size": file_size,
                "checksum_sha256": checksum_sha256,
                "unique_code": unique_code.strip(),
            },
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_certificate_file(unique_code: str, fields: dict) -> bool:
    """Replace storage metadata for a certificate (used on reissue)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE certificates
               SET storage_provider = :storage_provider,
                   drive_file_id    = :drive_file_id,
                   drive_folder_id  = :drive_folder_id,
                   original_filename = :original_filename,
                   mime_type        = :mime_type,
                   file_size        = :file_size,
                   checksum_sha256  = :checksum_sha256,
                   pdf_path         = :pdf_path,
                   updated_at       = datetime('now')
             WHERE unique_code = :unique_code COLLATE NOCASE
            """,
            {
                "storage_provider": fields.get("storage_provider") or "local",
                "drive_file_id": fields.get("drive_file_id"),
                "drive_folder_id": fields.get("drive_folder_id"),
                "original_filename": fields.get("original_filename"),
                "mime_type": fields.get("mime_type") or "application/pdf",
                "file_size": fields.get("file_size"),
                "checksum_sha256": fields.get("checksum_sha256"),
                "pdf_path": fields.get("pdf_path") or "",
                "unique_code": unique_code.strip(),
            },
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_certificate_status(
    unique_code: str,
    *,
    status: str,
    revoked_by: int | None = None,
    revoke_reason: str | None = None,
) -> bool:
    """Set a certificate's status (e.g. 'revogado'). Returns True if updated."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE certificates
               SET status = ?,
                   revoked_at = CASE WHEN ? = 'revogado' THEN datetime('now') ELSE NULL END,
                   revoked_by = ?,
                   revoke_reason = ?,
                   updated_at = datetime('now')
             WHERE unique_code = ? COLLATE NOCASE
            """,
            (status, status, revoked_by, revoke_reason, unique_code.strip()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Admin users ─────────────────────────────────────────────────────────────────

def get_admin_user_by_username(username: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM admin_users WHERE username = ? LIMIT 1",
            (username.strip(),),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_admin_user_by_id(user_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM admin_users WHERE id = ? LIMIT 1", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def create_admin_user(username: str, password_hash: str, role: str = "secretaria") -> int | None:
    """Create an admin user. Returns the new id, or None if it already existed."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)",
            (username.strip(), password_hash, role),
        )
        conn.commit()
        return cur.lastrowid if cur.rowcount > 0 else None
    finally:
        conn.close()


def count_admin_users() -> int:
    conn = get_connection()
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()["n"])
    finally:
        conn.close()


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
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO audit_log
                (actor_id, actor_username, action, target_type, target_id, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (actor_id, actor_username, action, target_type, target_id, details),
        )
        conn.commit()
    finally:
        conn.close()
