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
from datetime import datetime, timedelta, timezone

import observability
from database import db
from storage_service import StorageError, delete_certificate

LOGGER = logging.getLogger("certificados.reconcile")

DEFAULT_PENDING_MAX_AGE_MINUTES = 30


def run_reconciliation(
    *,
    pending_max_age_minutes: int = DEFAULT_PENDING_MAX_AGE_MINUTES,
    dry_run: bool = False,
    max_rows: int = 10_000,
    page_size: int = 200,
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
    remaining = max(1, min(int(max_rows), 100_000))
    page_size = max(1, min(int(page_size), 2_000))

    # 1) Stale pending reservations → mark failed (no file was finalized).
    after_id = 0
    while remaining:
        page = db.list_pending_certificates(
            cutoff, after_id=after_id, limit=min(page_size, remaining)
        )
        if not page:
            break
        for cert in page:
            after_id = int(cert["id"])
            remaining -= 1
            code = cert["unique_code"]
            if dry_run:
                LOGGER.info("event=reconcile_pending dry_run=true")
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
    after_id = 0
    while remaining:
        page = db.list_active_without_file(after_id=after_id, limit=min(page_size, remaining))
        if not page:
            break
        for cert in page:
            after_id = int(cert["id"])
            remaining -= 1
            code = cert["unique_code"]
            if dry_run:
                LOGGER.info("event=reconcile_missing_file dry_run=true")
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
    after_id = 0
    while remaining:
        page = db.list_failed_with_orphan(after_id=after_id, limit=min(page_size, remaining))
        if not page:
            break
        for cert in page:
            after_id = int(cert["id"])
            remaining -= 1
            code = cert["unique_code"]
            if dry_run:
                LOGGER.info("event=reconcile_compensation dry_run=true")
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
                observability.metrics.increment(observability.CERTS_COMPENSATED)
                report["compensated"] += 1
            except (StorageError, FileNotFoundError, OSError) as exc:
                LOGGER.error(
                    "event=reconcile_compensation_failed error_type=%s",
                    type(exc).__name__,
                )
                observability.metrics.increment(observability.RECONCILIATION_ERRORS)
                db.insert_audit_log(
                    action="reconcile_compensation_error",
                    target_type="certificate",
                    target_id=code,
                    details=f"falha de infraestrutura ({type(exc).__name__})",
                )
                report["compensation_errors"] += 1

    report["limit_reached"] = remaining == 0
    return report
