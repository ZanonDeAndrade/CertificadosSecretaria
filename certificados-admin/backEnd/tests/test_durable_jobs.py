"""PostgreSQL contracts for durable, resumable emission workers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from typing import Any

import pytest
from certificados_backend.services import batch_service, job_crypto
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from database.models import AuditLog, Certificate, EmissionBatchItem
from database.repositories import CertificateRepository, EmissionBatchRepository

pytestmark = pytest.mark.postgres


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _batch(batch_id: str, *, status: str = "queued", **values: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": batch_id,
        "idempotency_key": f"idempotency-{batch_id}",
        "request_sha256": "a" * 64,
        "status": status,
        "total_rows": 1,
        "valid_count": 1,
        "invalid_count": 0,
        "processed_count": 0,
        "generated_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
        "max_attempts": 3,
    }
    base.update(values)
    return base


def test_only_one_postgres_worker_claims_a_job(postgres_engine):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False, future=True)
    with factory.begin() as session:
        EmissionBatchRepository(session).create(_batch("job-concurrent-claim"))

    barrier = Barrier(2)

    def claim(worker: str) -> str | None:
        with factory.begin() as session:
            barrier.wait(timeout=5)
            claimed = EmissionBatchRepository(session).claim(
                worker_id=worker,
                now=_now(),
                lease_expires_at=_now() + timedelta(minutes=5),
            )
            return str(claimed["id"]) if claimed else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("worker-a", "worker-b")))
    assert sorted(value for value in results if value) == ["job-concurrent-claim"]

    with factory() as session:
        batch = EmissionBatchRepository(session).get("job-concurrent-claim")
        assert batch is not None
        assert batch["status"] == "processing"
        assert batch["attempt_count"] == 1


def test_stale_lease_is_reclaimed_and_processing_item_resets(postgres_engine):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False, future=True)
    with factory.begin() as session:
        EmissionBatchRepository(session).create(
            _batch(
                "job-stale-recovery",
                status="processing",
                attempt_count=1,
                lease_owner="dead-worker",
                lease_expires_at=_now() - timedelta(minutes=1),
            ),
            [
                {
                    "batch_id": "job-stale-recovery",
                    "row_number": 2,
                    "status": "processing",
                    "business_key": "b" * 64,
                    "payload_ciphertext": b"ciphertext",
                    "payload_nonce": b"0" * 12,
                    "payload_key_id": "development-v1",
                    "attempt_count": 1,
                }
            ],
        )

    with factory.begin() as session:
        claimed = EmissionBatchRepository(session).claim(
            worker_id="replacement-worker",
            now=_now(),
            lease_expires_at=_now() + timedelta(minutes=5),
        )
        assert claimed is not None
        assert claimed["attempt_count"] == 2
    with factory() as session:
        item = session.execute(select(EmissionBatchItem)).scalar_one()
        assert item.status == "queued"


def test_retry_after_crash_reuses_existing_certificate_without_duplicate(
    postgres_engine, monkeypatch
):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False, future=True)
    batch_id = "job-idempotent-retry"
    business_key = "c" * 64
    name = "Pessoa de Retomada"
    document = "12345678900"
    context = job_crypto.encrypt_json(
        {
            "body_template": "participou com {{carga_horaria}} horas.",
            "snapshot": {
                "institution_name": "Instituição",
                "issue_location": "Cidade",
                "signatory_name": "Assinante",
                "signatory_title": "Cargo",
                "public_url": "https://certificados.example.test",
            },
        },
        aad=batch_service._context_aad(batch_id),
    )
    row_payload = job_crypto.encrypt_json(
        {
            "row_number": 2,
            "nome": name,
            "carga_horaria": 8,
            "curso": "Direito",
            "evento": "Evento",
            "data_emissao": "2026-06-10",
            "email": "pessoa@example.test",
            "documento": document,
            "data_inicio": "",
            "data_fim": "",
        },
        aad=batch_service._row_aad(batch_id, 2, business_key),
    )
    assert name.encode() not in row_payload.ciphertext
    assert document.encode() not in row_payload.ciphertext

    with factory.begin() as session:
        EmissionBatchRepository(session).create(
            _batch(
                batch_id,
                context_ciphertext=context.ciphertext,
                context_nonce=context.nonce,
                payload_key_id=context.key_id,
            ),
            [
                {
                    "batch_id": batch_id,
                    "row_number": 2,
                    "status": "queued",
                    "business_key": business_key,
                    "payload_ciphertext": row_payload.ciphertext,
                    "payload_nonce": row_payload.nonce,
                    "payload_key_id": row_payload.key_id,
                    "attempt_count": 1,
                }
            ],
        )
        CertificateRepository(session).insert_many(
            [
                {
                    "unique_code": "CERT-RETRY-0001",
                    "participant_name": name,
                    "event_name": "Evento",
                    "issue_date": "10 de junho de 2026",
                    "business_key": business_key,
                    "batch_id": batch_id,
                    "status": "ativo",
                    "storage_provider": "local",
                    "pdf_path": "/synthetic/already-finalized.pdf",
                }
            ]
        )

    class NoGeneration:
        def generate_certificates(self, *_args, **_kwargs):
            raise AssertionError("retry idempotente não deve gerar um segundo PDF")

    monkeypatch.setattr(
        batch_service,
        "configured_service",
        lambda _base, _snapshot: NoGeneration(),
    )
    assert batch_service.run_one_job(object(), batch_id=batch_id, worker_id="retry-worker")

    with factory() as session:
        assert session.execute(select(func.count()).select_from(Certificate)).scalar_one() == 1
        item = session.execute(select(EmissionBatchItem)).scalar_one()
        assert item.status == "generated"
        assert item.certificate_code == "CERT-RETRY-0001"
        assert item.payload_ciphertext is None
        batch = EmissionBatchRepository(session).get(batch_id)
        assert batch is not None
        assert batch["status"] == "completed"
        assert batch["generated_count"] == 1


def test_tampered_job_payload_fails_closed_and_is_audited(postgres_engine, monkeypatch):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False, future=True)
    batch_id = "job-tampered-payload"
    context = job_crypto.encrypt_json(
        {"body_template": "texto", "snapshot": {}},
        aad=batch_service._context_aad(batch_id),
    )
    tampered = bytearray(context.ciphertext)
    tampered[-1] ^= 1
    with factory.begin() as session:
        EmissionBatchRepository(session).create(
            _batch(
                batch_id,
                context_ciphertext=bytes(tampered),
                context_nonce=context.nonce,
                payload_key_id=context.key_id,
            )
        )
    monkeypatch.setattr(batch_service, "configured_service", lambda *_args: object())
    assert batch_service.run_one_job(object(), batch_id=batch_id, worker_id="worker-tamper")

    with factory() as session:
        batch = EmissionBatchRepository(session).get(batch_id)
        assert batch is not None
        assert batch["status"] == "failed"
        assert batch["last_error_code"] == "job_payload_integrity"
        incidents = session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "integrity_incident")
        ).scalar_one()
        assert incidents == 1
