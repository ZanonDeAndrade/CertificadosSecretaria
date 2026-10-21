"""Drive ↔ banco reconciliation — detect drift without exposing personal data.

It cross-references the Google Drive folder with the database internally using
opaque file ids and certificate codes (never names, documents or e-mails):

  - **orphan_drive**: files present in Drive but referenced by no certificate
    (candidates for deletion; identifiers are not written to logs);
  - **missing_in_drive**: certificates whose ``drive_file_id`` is not found in
    the folder (reported as verifier codes only).

Deletion of orphans is opt-in (``apply=True``) and never touches the database.
"""

from __future__ import annotations

import logging

from database import db
from storage_service import StorageError

LOGGER = logging.getLogger("certificados.drive_reconcile")


def run_drive_reconciliation(*, apply: bool = False) -> dict[str, object]:
    """Compare the Drive folder with the DB. ``apply`` deletes orphan Drive files."""
    from storage_service.google_drive import GoogleDriveStorage

    db.init_db()
    indexes = db.drive_file_index_by_folder()
    drive_ids: set[str] = set()
    db_ids: set[str] = set()
    orphan_drive: list[tuple[GoogleDriveStorage, str]] = []
    missing_in_drive: list[str] = []
    for folder_id, index in indexes.items():
        # ``None`` exists only for legacy rows and deliberately uses the old
        # configured-folder fallback. New rows always persist their folder.
        storage = GoogleDriveStorage(folder_id=folder_id)
        folder_drive_ids = {f["id"] for f in storage.list_folder()}
        folder_db_ids = set(index)
        drive_ids.update(folder_drive_ids)
        db_ids.update(folder_db_ids)
        orphan_drive.extend((storage, file_id) for file_id in folder_drive_ids - folder_db_ids)
        missing_in_drive.extend(index[file_id] for file_id in folder_db_ids - folder_drive_ids)

    report: dict[str, object] = {
        "drive_files": len(drive_ids),
        "db_files": len(db_ids),
        "folders_checked": len(indexes),
        "orphan_drive_count": len(orphan_drive),
        "missing_in_drive_count": len(missing_in_drive),
        "deleted": 0,
        "applied": apply,
    }

    deleted = 0
    if apply:
        for storage, file_id in orphan_drive:
            try:
                storage.delete({"drive_file_id": file_id})
                deleted += 1
            except (StorageError, FileNotFoundError) as exc:
                LOGGER.error(
                    "event=drive_orphan_delete_failed error_type=%s",
                    type(exc).__name__,
                )
        report["deleted"] = deleted

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
