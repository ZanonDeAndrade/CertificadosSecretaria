"""CLI for saga reconciliation (see services/reconciliation.py).

Usage:
    python reconcile.py --dry-run                 # report only, change nothing
    python reconcile.py                           # run all passes
    python reconcile.py --pending-max-age 60      # stale-pending threshold (min)

Resolves: stale ``pending`` reservations, ``ativo`` rows without a file, and
``failed`` rows with an orphaned uploaded file (compensation). Safe to schedule
(cron) and idempotent.
"""

from __future__ import annotations

import argparse
import json
import sys

from certificados_backend.services.reconciliation import (
    DEFAULT_PENDING_MAX_AGE_MINUTES,
    run_reconciliation,
)

import observability


def main(argv: list[str] | None = None) -> int:
    observability.configure_logging()
    parser = argparse.ArgumentParser(description="Reconcilia o estado dos certificados.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem alterar nada.")
    parser.add_argument(
        "--pending-max-age",
        type=int,
        default=DEFAULT_PENDING_MAX_AGE_MINUTES,
        help="Idade (min) a partir da qual um 'pending' é considerado expirado.",
    )
    parser.add_argument("--max-rows", type=int, default=10_000)
    args = parser.parse_args(argv)

    report = run_reconciliation(
        pending_max_age_minutes=args.pending_max_age,
        dry_run=args.dry_run,
        max_rows=args.max_rows,
    )

    print(json.dumps({"event": "reconciliation_completed", **report}, sort_keys=True))
    return 1 if report["compensation_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
