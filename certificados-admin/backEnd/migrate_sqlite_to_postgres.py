"""Copy the current SQLite dataset into an empty PostgreSQL database.

The PostgreSQL schema must already be at Alembic head. All rows are copied in a
single target transaction, preserving primary keys and foreign-key references.
The command refuses a non-empty target to avoid accidental duplication.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, select, text

for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "database" / "models.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

from database import config  # noqa: E402
from database.models import Base  # noqa: E402

TABLE_ORDER = (
    "admin_users",
    "template_versions",
    "certificates",
    "auth_sessions",
    "login_throttles",
    "public_rate_limits",
    "audit_log",
)


def _counts(connection) -> dict[str, int]:  # noqa: ANN001
    return {
        name: int(connection.execute(select(func.count()).select_from(Base.metadata.tables[name])).scalar_one())
        for name in TABLE_ORDER
    }


def migrate(source_path: Path, *, dry_run: bool = False) -> dict[str, int]:
    target_url = config.get_database_url()
    if not target_url or not target_url.startswith("postgresql"):
        raise RuntimeError("O destino configurado não é PostgreSQL.")
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite não encontrado: {source_path}")

    source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")
    target_engine = create_engine(target_url, pool_pre_ping=True)
    try:
        missing = [
            name for name in TABLE_ORDER if name not in inspect(target_engine).get_table_names()
        ]
        if missing:
            raise RuntimeError(
                "Schema PostgreSQL incompleto; execute 'alembic upgrade head'. "
                "Tabelas ausentes: " + ", ".join(missing)
            )

        with source_engine.connect() as source, target_engine.connect() as target:
            source_counts = _counts(source)
            target_counts = _counts(target)
            non_empty = {name: count for name, count in target_counts.items() if count}
            if non_empty:
                summary = ", ".join(f"{name}={count}" for name, count in non_empty.items())
                raise RuntimeError(f"Destino PostgreSQL não está vazio: {summary}")
            if dry_run:
                return source_counts

        with source_engine.connect() as source, target_engine.begin() as target:
            for name in TABLE_ORDER:
                table = Base.metadata.tables[name]
                rows = [dict(row) for row in source.execute(select(table)).mappings()]
                if rows:
                    target.execute(table.insert(), rows)

            for name in TABLE_ORDER:
                table = Base.metadata.tables[name]
                if "id" not in table.c:
                    continue
                target.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {name}), 1), "
                        f"(SELECT MAX(id) IS NOT NULL FROM {name}))"
                    ),
                    {"table_name": name},
                )
        return source_counts
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migra todos os dados do SQLite para um PostgreSQL vazio."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=config.REPO_ROOT / "database" / "certificates.db",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    counts = migrate(args.source.expanduser().resolve(), dry_run=args.dry_run)
    mode = "DRY-RUN" if args.dry_run else "MIGRAÇÃO CONCLUÍDA"
    print(f"-------- {mode} --------")
    for name in TABLE_ORDER:
        print(f"  {name}: {counts[name]}")
    print("---------------------------------------")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
