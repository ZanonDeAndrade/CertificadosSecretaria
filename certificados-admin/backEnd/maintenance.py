"""Explicit bounded maintenance operations; none run during web startup."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import observability
from database import db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manutenção do CertificadosSecretaria.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    private = subparsers.add_parser(
        "backfill-private-data", description="Normaliza e pseudonimiza em lotes."
    )
    private.add_argument("--batch-size", type=int, default=500)
    private.add_argument("--max-rows", type=int)
    private.add_argument("--retention-days", type=int)
    cleanup = subparsers.add_parser(
        "cleanup-runtime",
        description="Remove sessões, contadores e payloads temporários expirados.",
    )
    cleanup.add_argument("--session-retention-days", type=int, default=7)
    cleanup.add_argument("--rate-limit-retention-hours", type=int, default=48)
    cleanup.add_argument("--job-payload-retention-days", type=int, default=7)
    args = parser.parse_args(argv)
    observability.configure_logging()
    db.init_db()
    if args.command == "backfill-private-data":
        changed = db.prepare_private_data(
            args.retention_days,
            batch_size=args.batch_size,
            max_rows=args.max_rows,
        )
        print(f"Campos atualizados: {changed}")
    elif args.command == "cleanup-runtime":
        now = datetime.now(timezone.utc)
        session_days = max(1, min(int(args.session_retention_days), 365))
        rate_hours = max(1, min(int(args.rate_limit_retention_hours), 24 * 30))
        payload_days = max(1, min(int(args.job_payload_retention_days), 90))
        report = {
            "auth_sessions": db.cleanup_auth_sessions(now - timedelta(days=session_days)),
            "login_throttles": db.cleanup_login_throttles(now - timedelta(hours=rate_hours)),
            "public_rate_limits": db.cleanup_public_rate_limits(now - timedelta(hours=rate_hours)),
            "job_payload_fields": db.purge_terminal_emission_payloads(
                now - timedelta(days=payload_days)
            ),
        }
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
