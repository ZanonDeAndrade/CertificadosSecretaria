"""Migrate legacy local certificate PDFs to Google Drive.

For each certificate stored locally (has ``pdf_path``) and not yet on Drive
(no ``drive_file_id``):

  1. resolve the local file and verify it exists;
  2. upload it via the storage layer (GoogleDriveStorage);
  3. update the DB with drive_file_id + metadata + checksum_sha256
     (the local pdf_path is kept as a backup reference);

It never re-uploads a certificate that already has a drive_file_id, supports a
``--dry-run`` mode, emits privacy-safe event logs and prints a final report.

Usage:
    python migrate_to_drive.py --dry-run        # simula, não envia nada
    python migrate_to_drive.py                  # executa a migração
    python migrate_to_drive.py --limit 50       # processa no máximo 50

Requires (real run): STORAGE_PROVIDER=google_drive + credenciais e
GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID configurados no .env.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from database import db

LOGGER = logging.getLogger("certificados.migrate")


def run_migration(dry_run: bool = False, limit: int | None = None) -> dict:
    db.init_db()
    pending = db.certificates_pending_drive_migration()
    if limit is not None:
        pending = pending[:limit]

    report = {"migrated": 0, "skipped": 0, "not_found": 0, "failed": 0, "total": len(pending)}

    storage = None
    if not dry_run:
        from storage_service.google_drive import GoogleDriveStorage  # lazy

        storage = GoogleDriveStorage()  # raises if folder/credentials missing

    for cert in pending:
        code = cert["unique_code"]

        if (cert.get("drive_file_id") or "").strip():
            LOGGER.info("event=drive_migration_skipped")
            report["skipped"] += 1
            continue

        local_path = db.resolve_pdf_path(cert.get("pdf_path") or "")
        if not local_path.is_file():
            LOGGER.warning("event=drive_migration_missing")
            report["not_found"] += 1
            continue

        content = local_path.read_bytes()
        if dry_run:
            LOGGER.info(
                "event=drive_migration_dry_run bytes=%d",
                len(content),
            )
            report["migrated"] += 1
            continue

        try:
            assert storage is not None
            stored = storage.save(
                content,
                filename=cert.get("original_filename") or local_path.name,
                mime_type=cert.get("mime_type") or "application/pdf",
            )
            if not stored.drive_file_id:
                raise RuntimeError("Upload no Drive não retornou um identificador.")
            db.set_drive_metadata(
                code,
                drive_file_id=stored.drive_file_id,
                drive_folder_id=stored.drive_folder_id,
                original_filename=stored.original_filename,
                mime_type=stored.mime_type,
                file_size=stored.file_size,
                checksum_sha256=stored.checksum_sha256,
            )
            LOGGER.info("event=drive_migration_succeeded")
            report["migrated"] += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            LOGGER.error(
                "event=drive_migration_failed error_type=%s",
                type(exc).__name__,
            )
            report["failed"] += 1

    return report


def main(argv: list[str]) -> int:
    import observability

    observability.configure_logging()
    parser = argparse.ArgumentParser(description="Migra PDFs locais para o Google Drive.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem enviar nada.")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de certificados.")
    args = parser.parse_args(argv)

    report = run_migration(dry_run=args.dry_run, limit=args.limit)

    print(json.dumps({"event": "drive_migration_completed", **report}, sort_keys=True))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
