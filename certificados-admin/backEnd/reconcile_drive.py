"""CLI for Drive ↔ banco reconciliation (see services/drive_reconcile.py).

Usage:
    python reconcile_drive.py                 # report only (orphans + missing)
    python reconcile_drive.py --apply         # also DELETE orphan Drive files

Reports only aggregate counts. Identifiers remain internal and are not printed.
Requires STORAGE_PROVIDER=google_drive + credentials configured.
"""

from __future__ import annotations

import argparse
import json
import sys

from certificados_backend.services.drive_reconcile import run_drive_reconciliation


def main(argv: list[str] | None = None) -> int:
    import observability

    observability.configure_logging()
    parser = argparse.ArgumentParser(description="Reconcilia Drive x banco (sem PII).")
    parser.add_argument("--apply", action="store_true", help="Exclui arquivos órfãos do Drive.")
    args = parser.parse_args(argv)

    report = run_drive_reconciliation(apply=args.apply)

    print(json.dumps({"event": "drive_reconciliation_completed", **report}, sort_keys=True))
    return 1 if report["missing_in_drive_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
