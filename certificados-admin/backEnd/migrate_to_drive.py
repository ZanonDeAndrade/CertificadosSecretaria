"""Migrate legacy local certificate PDFs to Google Drive.

For each certificate stored locally (has ``pdf_path``) and not yet on Drive
(no ``drive_file_id``):

  1. resolve the local file and verify it exists;
  2. upload it via the storage layer (GoogleDriveStorage);
  3. update the DB with drive_file_id + metadata + checksum_sha256
     (the local pdf_path is kept as a backup reference);

It never re-uploads a certificate that already has a drive_file_id, supports a
``--dry-run`` mode, logs every action and prints a final report.

Usage:
    python migrate_to_drive.py --dry-run        # simula, não envia nada
    python migrate_to_drive.py                  # executa a migração
    python migrate_to_drive.py --limit 50       # processa no máximo 50

Requires (real run): STORAGE_PROVIDER=google_drive + credenciais e
GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID configurados no .env.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make the shared `database` package and storage layer importable.
for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

from database import db  # noqa: E402
from storage_service.base import sha256_hex  # noqa: E402

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
            LOGGER.info("[skip] %s já está no Drive.", code)
            report["skipped"] += 1
            continue

        local_path = db.resolve_pdf_path(cert.get("pdf_path") or "")
        if not local_path.is_file():
            LOGGER.warning("[missing] %s: arquivo local não encontrado (%s).", code, local_path)
            report["not_found"] += 1
            continue

        content = local_path.read_bytes()
        checksum = sha256_hex(content)

        if dry_run:
            LOGGER.info(
                "[dry-run] migraria %s (%s, %d bytes, sha256=%s…).",
                code, local_path.name, len(content), checksum[:12],
            )
            report["migrated"] += 1
            continue

        try:
            stored = storage.save(
                content,
                filename=cert.get("original_filename") or local_path.name,
                mime_type=cert.get("mime_type") or "application/pdf",
            )
            db.set_drive_metadata(
                code,
                drive_file_id=stored.drive_file_id,
                drive_folder_id=stored.drive_folder_id,
                original_filename=stored.original_filename,
                mime_type=stored.mime_type,
                file_size=stored.file_size,
                checksum_sha256=stored.checksum_sha256,
            )
            LOGGER.info("[ok] %s migrado (drive_file_id=%s).", code, stored.drive_file_id)
            report["migrated"] += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            LOGGER.error("[fail] %s: %s", code, exc)
            report["failed"] += 1

    return report


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Migra PDFs locais para o Google Drive.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem enviar nada.")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de certificados.")
    args = parser.parse_args(argv)

    report = run_migration(dry_run=args.dry_run, limit=args.limit)

    print("\n-------- Relatório da migração --------")
    print(f"  Modo:        {'DRY-RUN (nada enviado)' if args.dry_run else 'EXECUÇÃO'}")
    print(f"  Total alvo:  {report['total']}")
    print(f"  Migrados:    {report['migrated']}")
    print(f"  Ignorados:   {report['skipped']} (já no Drive)")
    print(f"  Não encontrados: {report['not_found']}")
    print(f"  Falhas:      {report['failed']}")
    print("---------------------------------------")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
