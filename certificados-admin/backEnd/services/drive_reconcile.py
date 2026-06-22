"""Drive ↔ banco reconciliation — detect drift without exposing personal data.

It cross-references the Google Drive folder with the database **using only
opaque file ids and certificate codes** (never names, documents or e-mails):

  - **orphan_drive**: files present in Drive but referenced by no certificate
    (candidates for deletion — reported as file ids only);
  - **missing_in_drive**: certificates whose ``drive_file_id`` is not found in
    the folder (reported as verifier codes only).

Deletion of orphans is opt-in (``apply=True``) and never touches the database.
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
from storage_service import StorageError  # noqa: E402

LOGGER = logging.getLogger("certificados.drive_reconcile")


def run_drive_reconciliation(*, apply: bool = False) -> dict:
    """Compare the Drive folder with the DB. ``apply`` deletes orphan Drive files."""
    from storage_service.google_drive import GoogleDriveStorage

    db.init_db()
    index = db.drive_file_index()  # {drive_file_id: unique_code} — no PII
    storage = GoogleDriveStorage()
    drive_ids = {f["id"] for f in storage.list_folder()}
    db_ids = set(index.keys())

    orphan_drive = sorted(drive_ids - db_ids)               # file ids only
    missing_in_drive = sorted(index[i] for i in (db_ids - drive_ids))  # codes only

    report = {
        "drive_files": len(drive_ids),
        "db_files": len(db_ids),
        "orphan_drive_count": len(orphan_drive),
        "missing_in_drive_count": len(missing_in_drive),
        "orphan_drive_file_ids": orphan_drive,
        "missing_in_drive_codes": missing_in_drive,
        "deleted": 0,
        "applied": apply,
    }

    if apply:
        for file_id in orphan_drive:
            try:
                storage.delete({"drive_file_id": file_id})
                report["deleted"] += 1
            except (StorageError, FileNotFoundError) as exc:
                LOGGER.error("Falha ao excluir órfão do Drive %s: %s", file_id, exc)

    db.insert_audit_log(
        action="drive_reconcile",
        target_type="storage",
        details=(
            f"drive={report['drive_files']} db={report['db_files']} "
            f"orfaos={report['orphan_drive_count']} ausentes={report['missing_in_drive_count']} "
            f"excluidos={report['deleted']}"
        ),
    )
    return report
