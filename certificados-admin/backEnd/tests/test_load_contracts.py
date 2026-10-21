"""Bounded maximum-size contracts for queueing and ZIP assembly."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tracemalloc
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest
from certificados_backend.services import certificate_management

from database import db
from storage_service import RetrievedFile

pytestmark = pytest.mark.load

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _maximum_sheet(count: int) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(
        {
            "nome": [f"Participante Sintético {index:04d}" for index in range(count)],
            "carga_horaria": [8] * count,
            "curso": ["Curso de Carga"] * count,
            "evento": ["Evento de Carga"] * count,
            "data_emissao": ["10/06/2026"] * count,
        }
    ).to_excel(buffer, index=False)
    return buffer.getvalue()


def test_maximum_institutional_batch_is_queued_without_request_time_generation(
    client, auth_headers, monkeypatch
):
    maximum = 2_000
    monkeypatch.setenv("BATCH_WORKER_MODE", "external")
    workbook = _maximum_sheet(maximum)
    folder_id = "folder-load-contract-0001"
    user_id = int(client.get("/auth/me").json()["id"])
    db.upsert_google_drive_folder_grant(
        {
            "user_id": user_id,
            "folder_id": folder_id,
            "folder_id_hash": hashlib.sha256(folder_id.encode()).hexdigest(),
            "folder_name": "Evento de Carga",
            "can_add_children": 1,
        }
    )
    tracemalloc.start()
    response = client.post(
        "/emission-batches",
        files={"file": ("lote-maximo.xlsx", workbook, XLSX_MIME)},
        data={
            "texto_padrao": "participou com {{carga_horaria}} horas.",
            "certificate_type": "listener",
            "drive_folders_json": json.dumps({"Evento de Carga": folder_id}),
        },
        headers={"Idempotency-Key": "maximum-load-batch-0001"},
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert response.status_code == 202, response.text
    batch = response.json()
    assert batch["status"] == "queued"
    assert batch["valid_count"] == maximum
    assert batch["processed_count"] == 0
    assert len(db.get_emission_batch_items(batch["id"])) == maximum
    # Includes parsing the complete XLSX and encrypting all durable items. This
    # catches accidental retention of PDFs/results in the HTTP process.
    assert peak < 192 * 1024 * 1024
    print(f"load_metric=batch_rows:{maximum} tracemalloc_peak_bytes:{peak}")


def test_maximum_zip_keeps_only_one_pdf_in_memory(tmp_path, monkeypatch):
    count = 100
    per_pdf = 256 * 1024
    monkeypatch.setenv("MAX_ZIP_CERTIFICATES", str(count))
    monkeypatch.setenv("MAX_ZIP_TOTAL_BYTES", str(40 * 1024 * 1024))
    monkeypatch.setenv("MIN_TEMP_FREE_BYTES", str(1024 * 1024))
    monkeypatch.setenv("DOWNLOAD_TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(certificate_management, "_download_limit", lambda *_a, **_k: None)
    monkeypatch.setattr(
        certificate_management.audit_service,
        "record",
        lambda *_a, **_k: None,
    )

    calls = 0

    def retrieve(code: str):
        nonlocal calls
        calls += 1
        # os.urandom is deliberately incompressible and allocated per item.
        content = b"%PDF-" + os.urandom(per_pdf - 5)
        return (
            {"unique_code": code, "participant_name": f"Pessoa {code}"},
            RetrievedFile(content=content, filename=f"{code}.pdf"),
        )

    monkeypatch.setattr(certificate_management, "retrieve", retrieve)
    codes = [f"CERT-LOAD-{index:03d}" for index in range(count)]
    tracemalloc.start()
    response = certificate_management.download_zip(
        codes,
        actor={"id": 1, "username": "load", "role": "admin"},
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    archive_path = Path(str(response.path))
    try:
        assert calls == count
        with ZipFile(archive_path) as archive:
            assert len(archive.namelist()) == count
        assert archive_path.stat().st_size <= 40 * 1024 * 1024
        # 25 MiB went through the ZIP; peak Python allocations remain bounded
        # because no list of PDF bytes is retained.
        assert peak < 12 * 1024 * 1024
        print(
            f"load_metric=zip_certificates:{count} "
            f"uncompressed_bytes:{count * per_pdf} tracemalloc_peak_bytes:{peak}"
        )
    finally:
        certificate_management._remove_temp_file(str(archive_path))
