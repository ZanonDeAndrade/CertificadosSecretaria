from __future__ import annotations

import base64
import io

import pytest
from certificados_backend import backup

from storage_service.base import RetrievedFile


def _key() -> bytes:
    return bytes(range(32))


def test_encrypted_artifact_round_trip_and_tamper_detection():
    raw = io.BytesIO()
    writer = backup.EncryptedWriter(
        raw,
        key=_key(),
        header=backup._artifact_header("test"),
    )
    payload = b"bounded-payload" * 10_000
    writer.write(payload[:1234])
    writer.write(payload[1234:])
    size, digest = writer.finish()
    assert size == len(payload)
    assert len(digest) == 64

    reader = backup.EncryptedReader(io.BytesIO(raw.getvalue()), key=_key())
    assert reader.header["kind"] == "test"
    assert reader.read() == payload

    tampered = bytearray(raw.getvalue())
    tampered[-backup.TAG_SIZE - 1] ^= 1
    with pytest.raises(backup.BackupError, match="integridade"):
        backup.EncryptedReader(io.BytesIO(tampered), key=_key()).read()


def test_backup_key_requires_exactly_256_bits(monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", base64.b64encode(b"short").decode())
    with pytest.raises(backup.BackupError, match="32 bytes"):
        backup._load_encryption_key()


def test_pdf_artifact_has_no_personal_data_and_verifies(tmp_path, monkeypatch):
    rows = [
        {
            "id": index,
            "unique_code": f"CERT-{index:04d}",
            "participant_name": f"Pessoa Sigilosa {index}",
            "drive_file_id": f"drive-{index}",
            "checksum_sha256": None,
        }
        for index in range(1, 8)
    ]
    monkeypatch.setattr(backup, "_iter_certificate_rows", lambda _url: iter(rows))
    monkeypatch.setattr(
        backup,
        "download_certificate",
        lambda row, verify: RetrievedFile(
            content=b"%PDF-1.7\n" + str(row["id"]).encode() * 128,
            filename="ignored.pdf",
        ),
    )
    artifact = tmp_path / "pdfs.csbk"
    info, count = backup.backup_pdfs(
        "sqlite:///ignored.db",
        artifact,
        key=_key(),
    )
    assert count == len(rows)
    assert info.plaintext_bytes > 0
    assert b"Pessoa Sigilosa" not in artifact.read_bytes()
    verified = backup.verify_pdf_artifact(artifact, key=_key())
    assert set(verified) == {str(row["unique_code"]) for row in rows}


def test_restore_refuses_non_disposable_database_before_pg_restore(tmp_path):
    artifact = tmp_path / "db.csbk"
    with artifact.open("wb") as raw:
        writer = backup.EncryptedWriter(
            raw,
            key=_key(),
            header=backup._artifact_header("postgresql", database="production"),
        )
        writer.write(b"synthetic-pg-dump")
        writer.finish()

    with pytest.raises(backup.BackupError, match="restore.*drill"):
        backup.restore_database(
            artifact,
            "postgresql+psycopg://user:pass@db/production_copy",
            key=_key(),
        )


def test_gcs_destination_requires_dedicated_prefix():
    with pytest.raises(backup.BackupError, match="prefixo dedicado"):
        backup._parse_gs_uri("gs://backup-bucket")
    assert backup._parse_gs_uri("gs://backup-bucket/certificados/prod") == (
        "backup-bucket",
        "certificados/prod",
    )


def test_restore_target_requires_verified_tls_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(backup.BackupError, match="verify-full"):
        backup._require_verified_tls(
            "postgresql+psycopg://user:pass@db/certificados_restore_drill?sslmode=require",
            target="restore",
        )
    backup._require_verified_tls(
        "postgresql+psycopg://user:pass@db/certificados_restore_drill?sslmode=verify-full",
        target="restore",
    )


def test_production_backup_refuses_local_destination(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:pass@db/certificados?sslmode=verify-full",
    )
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", base64.b64encode(_key()).decode())
    with pytest.raises(backup.BackupError, match="gs://"):
        backup.run_backup("/same-host/backups", include_pdfs=False, retention_days=35)


def test_pg_tools_receive_separate_libpq_environment(monkeypatch):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    environment = backup._pg_environment(
        "postgresql+psycopg://backup_user:ci-only-password@db.example:5433/"
        "certificados?sslmode=verify-full&sslrootcert=/run/secrets/postgres-ca.pem"
    )
    assert environment["PGHOST"] == "db.example"
    assert environment["PGPORT"] == "5433"
    assert environment["PGUSER"] == "backup_user"
    assert environment["PGDATABASE"] == "certificados"
    assert environment["PGSSLMODE"] == "verify-full"
    assert environment["PGSSLROOTCERT"] == "/run/secrets/postgres-ca.pem"
    assert environment["PGPASSWORD"] == "ci-only-password"
    assert "postgresql://" not in environment["PGDATABASE"]
