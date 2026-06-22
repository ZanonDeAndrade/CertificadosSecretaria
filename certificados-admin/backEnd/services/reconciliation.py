"""Saga reconciliation — repairs certificates left inconsistent by a crash.

The generation saga (reserve → upload → finalize, with compensation) handles the
common failure inline. A hard crash between steps can still leave:

  1. **stale ``pending``**      — reserved but never finalized (no usable file);
  2. **``ativo`` without file** — finalized rows whose storage pointer is empty;
  3. **``failed`` with orphan** — a known uploaded file the inline compensation
     could not delete (e.g. Drive was momentarily unreachable).

``run_reconciliation`` resolves each class idempotently and writes an audit trail.
It is safe to run repeatedly (cron/manual) and never deletes business data — it
only marks broken rows ``failed`` and removes orphaned files.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make the shared packages importable regardless of CWD.
for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

from database import db  # noqa: E402
from storage_service import StorageError, delete_certificate  # noqa: E402

LOGGER = logging.getLogger("certificados.reconcile")

DEFAULT_PENDING_MAX_AGE_MINUTES = 30


def run_reconciliation(
    *,
    pending_max_age_minutes: int = DEFAULT_PENDING_MAX_AGE_MINUTES,
    dry_run: bool = False,
) -> dict:
    """Run all reconciliation passes and return a report (counts)."""
    db.init_db()
    report = {
        "pending_failed": 0,
        "active_without_file_failed": 0,
        "compensated": 0,
        "compensation_errors": 0,
        "dry_run": dry_run,
    }

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=pending_max_age_minutes)

    # 1) Stale pending reservations → mark failed (no file was finalized).
    for cert in db.list_pending_certificates(cutoff):
        code = cert["unique_code"]
        if dry_run:
            LOGGER.info("[dry-run] pending expirado → failed: %s", code)
            report["pending_failed"] += 1
            continue
        db.mark_certificate_failed(code)
        db.insert_audit_log(
            action="reconcile_pending_failed",
            target_type="certificate",
            target_id=code,
            details=f"pending expirado (> {pending_max_age_minutes} min)",
        )
        report["pending_failed"] += 1

    # 2) Active certificates with no usable file pointer → mark failed.
    for cert in db.list_active_without_file():
        code = cert["unique_code"]
        if dry_run:
            LOGGER.info("[dry-run] ativo sem arquivo → failed: %s", code)
            report["active_without_file_failed"] += 1
            continue
        db.mark_certificate_failed(code)
        db.insert_audit_log(
            action="reconcile_active_without_file",
            target_type="certificate",
            target_id=code,
            details="certificado ativo sem arquivo associado",
        )
        report["active_without_file_failed"] += 1

    # 3) Failed rows still pointing at an uploaded file → delete + clear pointer.
    for cert in db.list_failed_with_orphan():
        code = cert["unique_code"]
        if dry_run:
            LOGGER.info("[dry-run] compensaria arquivo órfão: %s", code)
            report["compensated"] += 1
            continue
        try:
            delete_certificate(cert)
            db.clear_certificate_storage(code)
            db.insert_audit_log(
                action="reconcile_compensated",
                target_type="certificate",
                target_id=code,
                details="arquivo órfão removido",
            )
            report["compensated"] += 1
        except (StorageError, FileNotFoundError, OSError) as exc:
            LOGGER.error("Falha ao compensar %s: %s", code, exc)
            db.insert_audit_log(
                action="reconcile_compensation_error",
                target_type="certificate",
                target_id=code,
                details=str(exc)[:300],
            )
            report["compensation_errors"] += 1

    return report
