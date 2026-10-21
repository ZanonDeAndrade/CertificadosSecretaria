"""Periodic integrity verification of stored certificate files (F12).

Downloads each active certificate and confirms it is a PDF whose size + SHA-256
match what was recorded at issuance. A mismatch quarantines the certificate
(``integrity_blocked``) and writes an audit incident, so a tampered/corrupt file
is never served again.
"""

from __future__ import annotations

import logging

import observability
from database import db
from storage_service import (
    StorageError,
    StorageIntegrityError,
    download_certificate,
)

LOGGER = logging.getLogger("certificados.integrity")


def run_integrity_check(*, limit: int | None = None, dry_run: bool = False) -> dict:
    """Verify every active certificate's stored file; block mismatches."""
    db.init_db()
    report = {
        "total": 0,
        "checked": 0,
        "ok": 0,
        "blocked": 0,
        "errors": 0,
        "dry_run": dry_run,
    }
    remaining = 100_000 if limit is None else max(1, min(int(limit), 100_000))
    after_id = 0
    while remaining:
        page = db.list_active_with_remote_file(
            after_id=after_id,
            limit=min(200, remaining),
        )
        if not page:
            break
        report["total"] += len(page)
        for cert in page:
            after_id = int(cert["id"])
            remaining -= 1
            code = cert["unique_code"]
            report["checked"] += 1
            try:
                download_certificate(cert, verify=True)
                report["ok"] += 1
            except StorageIntegrityError as exc:
                report["blocked"] += 1
                LOGGER.error(
                    "event=integrity_failed error_type=%s",
                    type(exc).__name__,
                )
                observability.metrics.increment(observability.INTEGRITY_INCIDENTS)
                if not dry_run:
                    db.block_certificate_integrity(code)
                    db.insert_audit_log(
                        action="integrity_incident",
                        target_type="certificate",
                        target_id=code,
                        details=f"verificação periódica falhou ({type(exc).__name__})",
                    )
            except (StorageError, FileNotFoundError) as exc:
                report["errors"] += 1
                LOGGER.warning(
                    "event=integrity_check_unavailable error_type=%s",
                    type(exc).__name__,
                )

    report["limit_reached"] = remaining == 0
    return report
