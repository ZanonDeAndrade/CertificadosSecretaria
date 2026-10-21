"""Database-backed emission worker suitable for a low-cost Cloud Run Job."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from certificados_backend.services import batch_service
from certificados_backend.services.runtime import build_certificate_service

import observability
from database import config as db_config
from database import db
from database.privacy import validate_production_privacy_config
from storage_service import config as storage_config

LOGGER = logging.getLogger("certificados.job_worker")


def validate_startup() -> None:
    db_config.require_production_database()
    if db_config.is_local_server():
        storage_config.validate_local_server_storage()
    else:
        storage_config.validate_production_storage(required_access="read_write")
    validate_production_privacy_config()
    batch_service.validate_runtime_configuration()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Processa lotes duráveis de emissão.")
    parser.add_argument("--once", action="store_true", help="Processa no máximo um lote.")
    parser.add_argument("--batch-id", help="Tenta processar somente o lote informado.")
    parser.add_argument("--max-jobs", type=int, default=100, help="Limite por execução.")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=0,
        help="Mantém worker residente consultando a fila (0 encerra quando vazia).",
    )
    args = parser.parse_args(argv)
    observability.configure_logging()
    validate_startup()
    db.init_db()
    service = build_certificate_service()
    limit = 1 if args.once or args.batch_id else max(1, min(args.max_jobs, 1000))
    processed = 0
    poll_seconds = max(0.0, min(float(args.poll_seconds), 30.0))
    while processed < limit:
        claimed = batch_service.run_one_job(service, batch_id=args.batch_id)
        if not claimed:
            if poll_seconds and not args.once and not args.batch_id:
                time.sleep(poll_seconds)
                continue
            break
        processed += 1
        if args.batch_id:
            break
    LOGGER.info("event=job_worker_finished processed=%d", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
