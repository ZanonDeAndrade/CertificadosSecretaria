"""CLI for periodic certificate integrity verification (see services/integrity.py).

Usage:
    python verify_integrity.py --dry-run        # report only, change nothing
    python verify_integrity.py                  # verify + quarantine mismatches
    python verify_integrity.py --limit 200      # cap how many to check

Schedule it (cron) to catch tampering/corruption of the stored PDFs.
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

from services.integrity import run_integrity_check  # noqa: E402


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Verifica a integridade dos certificados.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem bloquear nada.")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de certificados.")
    args = parser.parse_args(argv)

    report = run_integrity_check(limit=args.limit, dry_run=args.dry_run)

    print("\n-------- Verificacao de integridade --------")
    print(f"  Modo:        {'DRY-RUN' if args.dry_run else 'EXECUCAO'}")
    print(f"  Verificados: {report['checked']} / {report['total']}")
    print(f"  OK:          {report['ok']}")
    print(f"  Bloqueados:  {report['blocked']}")
    print(f"  Erros:       {report['errors']}")
    print("--------------------------------------------")
    return 1 if report["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
