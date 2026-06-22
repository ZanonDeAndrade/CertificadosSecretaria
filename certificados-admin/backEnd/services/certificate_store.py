"""Certificate code generation + lookup helpers for certificados-admin.

Persistence itself now goes through the saga in :mod:`services.certificate_service`
(reserve → upload → finalize), which relies on the database UNIQUE constraints
instead of pre-checking codes outside a transaction. This module only provides
the random code factory and the legacy lookup shape used by ``/validate``.
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


def generate_code(year: int | None = None) -> str:
    """Return a fresh random ``CERT-<ano>-XXXXXX`` code.

    Uniqueness is NOT checked here — the saga inserts under the UNIQUE
    constraint and retries on the (astronomically rare) collision.
    """
    return _generate_code(year if year is not None else datetime.now().year)


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
