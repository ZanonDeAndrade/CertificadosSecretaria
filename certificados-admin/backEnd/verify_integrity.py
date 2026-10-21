"""CLI for periodic certificate integrity verification (see services/integrity.py).

Usage:
    python verify_integrity.py --dry-run        # report only, change nothing
    python verify_integrity.py                  # verify + quarantine mismatches
    python verify_integrity.py --limit 200      # cap how many to check

Schedule it (cron) to catch tampering/corruption of the stored PDFs.
"""

from __future__ import annotations

import argparse
import json
import sys

from certificados_backend.services.integrity import run_integrity_check

import observability


def main(argv: list[str] | None = None) -> int:
    observability.configure_logging()
    parser = argparse.ArgumentParser(description="Verifica a integridade dos certificados.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem bloquear nada.")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de certificados.")
    args = parser.parse_args(argv)

    report = run_integrity_check(limit=args.limit, dry_run=args.dry_run)

    print(json.dumps({"event": "integrity_check_completed", **report}, sort_keys=True))
    return 1 if report["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
