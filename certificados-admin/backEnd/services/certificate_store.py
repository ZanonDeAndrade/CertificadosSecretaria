"""Certificate persistence for certificados-admin.

Backed by the shared SQLite database (database/db.py) so that
certificados-consulta can read what the admin writes. The public function
names (allocate_codes / save_certificates / find_certificate) are kept stable
so the rest of the backend keeps working unchanged.
"""
from __future__ import annotations

import secrets
import sys
from datetime import datetime
from pathlib import Path

# Make the shared `database` package importable regardless of how deep this app
# lives, by walking up to the repo root that contains database/db.py.
for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

from database import db  # noqa: E402  (import after sys.path bootstrap)

# Code format: CERT-<ano>-<6 chars>, e.g. CERT-2026-AB1234.
# Alphabet excludes ambiguous characters (0/O, 1/I) so codes are easy to read,
# type and dictate over the phone.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6


def _generate_code(year: int) -> str:
    suffix = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    return f"CERT-{year}-{suffix}"


def allocate_codes(count: int, year: int | None = None) -> list[str]:
    """Generate `count` unique CERT-ANO-XXXXXX codes, collision-safe vs the DB."""
    if year is None:
        year = datetime.now().year
    existing = db.existing_codes()
    seen: set[str] = set()
    codes: list[str] = []
    while len(codes) < count:
        code = _generate_code(year)
        key = code.upper()
        if key in existing or key in seen:
            continue
        seen.add(key)
        codes.append(code)
    return codes


def save_certificates(entries: list[dict]) -> None:
    """Persist generated certificates into the shared SQLite database.

    Each entry must contain: validationCode, name, event, issued_at/date and
    (optionally) certificate_text plus the storage metadata produced by the
    storage layer (storage_provider, drive_file_id, drive_folder_id,
    original_filename, mime_type, file_size, checksum_sha256, pdf_path).
    """
    db.init_db()
    rows = [
        {
            "unique_code": entry["validationCode"],
            "participant_name": entry["name"],
            "participant_email": entry.get("participant_email"),
            "participant_document": entry.get("participant_document"),
            "course_name": entry.get("course_name"),
            "event_name": entry["event"],
            "workload_hours": entry.get("workload_hours"),
            "issue_date": entry.get("issued_at") or entry.get("date") or "",
            "start_date": entry.get("start_date"),
            "end_date": entry.get("end_date"),
            "pdf_path": entry.get("pdf_path") or "",
            "certificate_text": entry.get("certificate_text"),
            "storage_provider": entry.get("storage_provider"),
            "drive_file_id": entry.get("drive_file_id"),
            "drive_folder_id": entry.get("drive_folder_id"),
            "original_filename": entry.get("original_filename"),
            "mime_type": entry.get("mime_type"),
            "file_size": entry.get("file_size"),
            "checksum_sha256": entry.get("checksum_sha256"),
            "status": entry.get("status"),
            "business_key": entry.get("business_key"),
            "issued_by": entry.get("issued_by"),
        }
        for entry in entries
    ]
    db.insert_certificates(rows)


def find_certificate(code: str) -> dict | None:
    """Return a certificate shaped like the legacy JSON store (for /validate)."""
    row = db.get_by_code(code)
    if not row:
        return None
    return {
        "validationCode": row["unique_code"],
        "name": row["participant_name"],
        "event": row["event_name"],
        "issued_at": row["issue_date"],
        "date": row["issue_date"],
        "certificate_text": row.get("certificate_text"),
    }
