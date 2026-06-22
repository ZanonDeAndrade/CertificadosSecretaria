"""Periodic integrity verification of stored certificate files (F12).

Downloads each active certificate and confirms it is a PDF whose size + SHA-256
match what was recorded at issuance. A mismatch quarantines the certificate
(``integrity_blocked``) and writes an audit incident, so a tampered/corrupt file
is never served again.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

from database import db  # noqa: E402
from storage_service import (  # noqa: E402
    StorageError,
    StorageIntegrityError,
    download_certificate,
)

LOGGER = logging.getLogger("certificados.integrity")


def run_integrity_check(*, limit: int | None = None, dry_run: bool = False) -> dict:
    """Verify every active certificate's stored file; block mismatches."""
    db.init_db()
    pending = db.list_active_with_remote_file()
    if limit is not None:
        pending = pending[:limit]

    report = {
        "total": len(pending),
        "checked": 0,
        "ok": 0,
        "blocked": 0,
        "errors": 0,
        "dry_run": dry_run,
    }

    for cert in pending:
        code = cert["unique_code"]
        report["checked"] += 1
        try:
            download_certificate(cert, verify=True)
            report["ok"] += 1
        except StorageIntegrityError as exc:
            report["blocked"] += 1
            LOGGER.error("Integridade falhou em %s: %s", code, exc)
            if not dry_run:
                db.block_certificate_integrity(code)
                db.insert_audit_log(
                    action="integrity_incident",
                    target_type="certificate",
                    target_id=code,
                    details=("verificação periódica: " + str(exc))[:480],
                )
        except (StorageError, FileNotFoundError) as exc:
            report["errors"] += 1
            LOGGER.warning("Não foi possível verificar %s: %s", code, exc)

    return report
