"""CLI for Drive ↔ banco reconciliation (see services/drive_reconcile.py).

Usage:
    python reconcile_drive.py                 # report only (orphans + missing)
    python reconcile_drive.py --apply         # also DELETE orphan Drive files

Reports ONLY opaque file ids and certificate codes — never personal data.
Requires STORAGE_PROVIDER=google_drive + credentials configured.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
for _ancestor in _BACKEND_DIR.parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

from services.drive_reconcile import run_drive_reconciliation  # noqa: E402


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Reconcilia Drive x banco (sem PII).")
    parser.add_argument("--apply", action="store_true", help="Exclui arquivos órfãos do Drive.")
    args = parser.parse_args(argv)

    report = run_drive_reconciliation(apply=args.apply)

    print("\n-------- Reconciliacao Drive x banco --------")
    print(f"  Arquivos no Drive:        {report['drive_files']}")
    print(f"  Arquivos no banco:        {report['db_files']}")
    print(f"  Orfaos no Drive:          {report['orphan_drive_count']}")
    for file_id in report["orphan_drive_file_ids"][:50]:
        print(f"    - file_id={file_id}")
    print(f"  Ausentes no Drive (codigo): {report['missing_in_drive_count']}")
    for code in report["missing_in_drive_codes"][:50]:
        print(f"    - {code}")
    print(f"  Orfaos excluidos:         {report['deleted']}")
    print("---------------------------------------------")
    return 1 if report["missing_in_drive_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
