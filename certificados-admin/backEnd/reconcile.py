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
import logging
import sys
from pathlib import Path

for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

# Ensure the backEnd dir is importable (services package).
_BACKEND_DIR = str(Path(__file__).resolve().parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from services.reconciliation import (  # noqa: E402
    DEFAULT_PENDING_MAX_AGE_MINUTES,
    run_reconciliation,
)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Reconcilia o estado dos certificados.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem alterar nada.")
    parser.add_argument(
        "--pending-max-age",
        type=int,
        default=DEFAULT_PENDING_MAX_AGE_MINUTES,
        help="Idade (min) a partir da qual um 'pending' é considerado expirado.",
    )
    args = parser.parse_args(argv)

    report = run_reconciliation(
        pending_max_age_minutes=args.pending_max_age, dry_run=args.dry_run
    )

    # ASCII-only output so it prints on any console encoding (e.g. Windows cp1252).
    print("\n-------- Relatorio da reconciliacao --------")
    print(f"  Modo:                        {'DRY-RUN' if args.dry_run else 'EXECUCAO'}")
    print(f"  Pending -> failed:           {report['pending_failed']}")
    print(f"  Ativo sem arquivo -> failed: {report['active_without_file_failed']}")
    print(f"  Arquivos orfaos removidos:   {report['compensated']}")
    print(f"  Erros de compensacao:        {report['compensation_errors']}")
    print("--------------------------------------------")
    return 1 if report["compensation_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
