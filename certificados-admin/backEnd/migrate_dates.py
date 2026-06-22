"""Convert legacy 'por extenso' dates to ISO and report unconvertible ones (F8).

``issue_date`` / ``start_date`` / ``end_date`` are now stored as ISO
(``YYYY-MM-DD``) so ordering is chronological. This idempotent script converts
any rows still in the old 'por extenso' form and reports the ``issue_date``
values it could not parse (those are left untouched for manual review).

Usage:
    python migrate_dates.py --dry-run     # report only, change nothing
    python migrate_dates.py               # convert in place
"""
from __future__ import annotations

import argparse
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

from sqlalchemy import select  # noqa: E402

from database import db, engine  # noqa: E402
from database.models import Certificate  # noqa: E402
from utils.dates import to_iso  # noqa: E402


def run_migration(dry_run: bool = False) -> dict:
    db.init_db()
    report: dict = {"scanned": 0, "converted": 0, "unconvertible": []}
    url = db._current_database_url()
    with engine.session_scope(url) as session:
        rows = session.execute(select(Certificate)).scalars().all()
        for row in rows:
            report["scanned"] += 1
            for col in ("issue_date", "start_date", "end_date"):
                current = getattr(row, col)
                if not current:
                    continue
                iso = to_iso(current)
                if iso is None:
                    if col == "issue_date":
                        report["unconvertible"].append((row.unique_code, current))
                    continue
                if iso != current:
                    report["converted"] += 1
                    if not dry_run:
                        setattr(row, col, iso)
        if dry_run:
            session.rollback()
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Converte datas legadas para ISO.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar.")
    args = parser.parse_args(argv)

    report = run_migration(dry_run=args.dry_run)
    print("\n-------- Migracao de datas (por extenso -> ISO) --------")
    print(f"  Modo:           {'DRY-RUN' if args.dry_run else 'EXECUCAO'}")
    print(f"  Linhas:         {report['scanned']}")
    print(f"  Campos ISO:     {report['converted']}")
    print(f"  Nao convertidas (issue_date): {len(report['unconvertible'])}")
    for code, value in report["unconvertible"][:50]:
        print(f"    - {code}: {value!r}")
    print("-------------------------------------------------------")
    return 1 if report["unconvertible"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
