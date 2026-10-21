"""Encrypted PostgreSQL and PDF backup/restore drills.

The command is intentionally explicit: it never runs during web startup and it
refuses to restore over the configured production database.  Artifacts are
stream-encrypted with AES-256-GCM and may be written to a separate GCS bucket.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator
from urllib.parse import unquote, urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

import observability
from database import config as db_config
from database.engine import get_engine, session_scope
from database.models import Certificate
from database.repositories import CertificateRepository
from storage_service import (
    StorageError,
    delete_certificate,
    download_certificate,
    get_storage,
    reset_storage_cache,
)

MAGIC = b"CSBK1\n"
TAG_SIZE = 16
NONCE_SIZE = 12
MAX_HEADER_BYTES = 16 * 1024
CHUNK_SIZE = 1024 * 1024
SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DISPOSABLE_DB_RE = re.compile(r"^[A-Za-z0-9_-]*(?:restore|drill)[A-Za-z0-9_-]*$")


class BackupError(RuntimeError):
    """A sanitized backup or restore failure."""


@dataclass(frozen=True)
class ArtifactInfo:
    path: str
    kind: str
    plaintext_bytes: int
    sha256: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_encryption_key() -> bytes:
    encoded = db_config.read_secret("BACKUP_ENCRYPTION_KEY")
    if not encoded:
        raise BackupError("BACKUP_ENCRYPTION_KEY ou BACKUP_ENCRYPTION_KEY_FILE é obrigatório.")
    try:
        key = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BackupError("A chave de backup deve ser base64 válido.") from exc
    if len(key) != 32:
        raise BackupError("A chave de backup deve representar exatamente 32 bytes.")
    return key


class EncryptedWriter(io.RawIOBase):
    """Small streaming envelope: authenticated header + ciphertext + GCM tag."""

    def __init__(self, destination: BinaryIO, *, key: bytes, header: dict[str, Any]) -> None:
        super().__init__()
        self._destination = destination
        self.header_bytes = _canonical_json(header)
        if len(self.header_bytes) > MAX_HEADER_BYTES:
            raise BackupError("Cabeçalho de backup excede o limite.")
        nonce = os.urandom(NONCE_SIZE)
        self._destination.write(MAGIC)
        self._destination.write(len(self.header_bytes).to_bytes(4, "big"))
        self._destination.write(nonce)
        self._destination.write(self.header_bytes)
        self._encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        self._encryptor.authenticate_additional_data(self.header_bytes)
        self.plaintext_bytes = 0
        self._digest = hashlib.sha256()
        self._finalized = False

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        if self._finalized:
            raise ValueError("Artefato já finalizado.")
        chunk = bytes(data)
        if not chunk:
            return 0
        self._destination.write(self._encryptor.update(chunk))
        self._digest.update(chunk)
        self.plaintext_bytes += len(chunk)
        return len(chunk)

    def tell(self) -> int:
        return self.plaintext_bytes

    def flush(self) -> None:
        self._destination.flush()

    def finish(self) -> tuple[int, str]:
        if not self._finalized:
            tail = self._encryptor.finalize()
            if tail:
                self._destination.write(tail)
            self._destination.write(self._encryptor.tag)
            self._destination.flush()
            self._finalized = True
        return self.plaintext_bytes, self._digest.hexdigest()


class EncryptedReader(io.RawIOBase):
    """Bounded streaming decryptor for an artifact seekable source."""

    def __init__(self, source: BinaryIO, *, key: bytes) -> None:
        super().__init__()
        self._source = source
        if self._source.read(len(MAGIC)) != MAGIC:
            raise BackupError("Formato de backup inválido.")
        raw_length = self._source.read(4)
        if len(raw_length) != 4:
            raise BackupError("Cabeçalho de backup truncado.")
        header_length = int.from_bytes(raw_length, "big")
        if header_length < 2 or header_length > MAX_HEADER_BYTES:
            raise BackupError("Tamanho de cabeçalho de backup inválido.")
        nonce = self._source.read(NONCE_SIZE)
        self.header_bytes = self._source.read(header_length)
        if len(nonce) != NONCE_SIZE or len(self.header_bytes) != header_length:
            raise BackupError("Cabeçalho de backup truncado.")
        try:
            parsed = json.loads(self.header_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupError("Cabeçalho de backup inválido.") from exc
        if not isinstance(parsed, dict):
            raise BackupError("Cabeçalho de backup inválido.")
        self.header: dict[str, Any] = parsed
        payload_start = self._source.tell()
        self._source.seek(0, os.SEEK_END)
        final_size = self._source.tell()
        if final_size < payload_start + TAG_SIZE:
            raise BackupError("Artefato de backup truncado.")
        self._source.seek(final_size - TAG_SIZE)
        tag = self._source.read(TAG_SIZE)
        self._remaining = final_size - TAG_SIZE - payload_start
        self._source.seek(payload_start)
        self._decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        self._decryptor.authenticate_additional_data(self.header_bytes)
        self._finalized = False

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self._finalized:
            return b""
        requested = self._remaining if size is None or size < 0 else min(size, self._remaining)
        ciphertext = self._source.read(requested)
        if len(ciphertext) != requested:
            raise BackupError("Artefato de backup truncado.")
        self._remaining -= len(ciphertext)
        plaintext = self._decryptor.update(ciphertext)
        if self._remaining == 0:
            try:
                plaintext += self._decryptor.finalize()
            except InvalidTag as exc:
                raise BackupError(
                    "Falha de integridade/autenticidade do artefato de backup."
                ) from exc
            self._finalized = True
        return plaintext


def _artifact_header(kind: str, **metadata: Any) -> dict[str, Any]:
    return {
        "format": 1,
        "kind": kind,
        "created_at": _utc_now().isoformat(),
        "application": "certificados-secretaria",
        **metadata,
    }


def _database_name(url: str) -> str:
    try:
        return unquote(
            urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1)).path.lstrip("/")
        )
    except ValueError as exc:
        raise BackupError("URL do PostgreSQL inválida.") from exc


def _pg_url(url: str) -> str:
    normalized = db_config.normalize_database_url(url)
    if not normalized.startswith("postgresql+psycopg://"):
        raise BackupError("Backup operacional exige PostgreSQL.")
    return "postgresql://" + normalized[len("postgresql+psycopg://") :]


def _pg_environment(url: str) -> dict[str, str]:
    """Translate a SQLAlchemy URL to libpq env vars without argv credentials."""
    normalized = db_config.normalize_database_url(url)
    try:
        parsed = make_url(normalized)
    except (ArgumentError, ValueError, TypeError) as exc:
        raise BackupError("URL do PostgreSQL inválida.") from exc
    if not parsed.drivername.startswith("postgresql") or not parsed.database:
        raise BackupError("Backup operacional exige PostgreSQL.")
    environment = os.environ.copy()
    environment["PGDATABASE"] = parsed.database
    if parsed.host:
        environment["PGHOST"] = parsed.host
    if parsed.port:
        environment["PGPORT"] = str(parsed.port)
    if parsed.username:
        environment["PGUSER"] = parsed.username
    if parsed.password:
        environment["PGPASSWORD"] = parsed.password
    libpq_query_names = {
        "application_name": "PGAPPNAME",
        "connect_timeout": "PGCONNECT_TIMEOUT",
        "sslcert": "PGSSLCERT",
        "sslcrl": "PGSSLCRL",
        "sslkey": "PGSSLKEY",
        "sslmode": "PGSSLMODE",
        "sslrootcert": "PGSSLROOTCERT",
    }
    for query_name, environment_name in libpq_query_names.items():
        value = parsed.query.get(query_name)
        if value:
            environment[environment_name] = str(value)
    return environment


def _require_verified_tls(url: str, *, target: str) -> None:
    """Apply the same fail-closed TLS rule to explicit restore URLs."""
    if not db_config.is_production():
        return
    try:
        parsed = make_url(db_config.normalize_database_url(url))
    except (ArgumentError, ValueError, TypeError) as exc:
        raise BackupError(f"URL PostgreSQL de {target} inválida.") from exc
    if str(parsed.query.get("sslmode") or "").lower() != "verify-full":
        raise BackupError(f"PostgreSQL de {target} exige sslmode=verify-full em produção.")


def _run_pg_dump(url: str, writer: EncryptedWriter) -> None:
    env = _pg_environment(url)
    try:
        process = subprocess.Popen(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError as exc:
        raise BackupError("pg_dump não está instalado na imagem operacional.") from exc
    assert process.stdout is not None
    while True:
        chunk = process.stdout.read(CHUNK_SIZE)
        if not chunk:
            break
        writer.write(chunk)
    process.stdout.close()
    if process.wait() != 0:
        raise BackupError("pg_dump falhou; consulte o log operacional protegido.")


def backup_database(url: str, destination: Path, *, key: bytes) -> ArtifactInfo:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        with temporary.open("xb") as raw:
            writer = EncryptedWriter(
                raw,
                key=key,
                header=_artifact_header("postgresql", database=_database_name(url)),
            )
            _run_pg_dump(url, writer)
            size, digest = writer.finish()
            os.fsync(raw.fileno())
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return ArtifactInfo(str(destination), "postgresql", size, digest)


def _iter_certificate_rows(url: str, page_size: int = 250) -> Iterator[dict[str, Any]]:
    last_id = 0
    while True:
        with session_scope(url) as session:
            rows = (
                session.execute(
                    select(Certificate.__table__)
                    .where(Certificate.id > last_id)
                    .where(
                        (Certificate.drive_file_id.is_not(None))
                        | (Certificate.pdf_path.is_not(None))
                    )
                    .order_by(Certificate.id)
                    .limit(page_size)
                )
                .mappings()
                .all()
            )
        if not rows:
            return
        for row in rows:
            copied = dict(row)
            last_id = int(copied["id"])
            yield copied


def _tar_add_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o600
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def backup_pdfs(url: str, destination: Path, *, key: bytes) -> tuple[ArtifactInfo, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    count = 0
    manifest = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    try:
        with temporary.open("xb") as raw:
            writer = EncryptedWriter(
                raw,
                key=key,
                header=_artifact_header("certificate-pdfs"),
            )
            with tarfile.open(fileobj=writer, mode="w|") as archive:
                for row in _iter_certificate_rows(url):
                    code = str(row.get("unique_code") or "")
                    if not SAFE_CODE_RE.fullmatch(code):
                        raise BackupError("Código de certificado inválido no banco.")
                    try:
                        retrieved = download_certificate(row, verify=True)
                    except (FileNotFoundError, StorageError) as exc:
                        raise BackupError(
                            f"PDF ausente ou inválido durante o backup (código {code})."
                        ) from exc
                    member = f"certificates/{code}.pdf"
                    checksum = hashlib.sha256(retrieved.content).hexdigest()
                    _tar_add_bytes(archive, member, retrieved.content)
                    record = {
                        "code": code,
                        "member": member,
                        "size": len(retrieved.content),
                        "sha256": checksum,
                    }
                    manifest.write(_canonical_json(record) + b"\n")
                    count += 1
                manifest.seek(0)
                manifest_bytes = manifest.read()
                _tar_add_bytes(archive, "manifest.ndjson", manifest_bytes)
            size, digest = writer.finish()
            os.fsync(raw.fileno())
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        manifest.close()
    return ArtifactInfo(str(destination), "certificate-pdfs", size, digest), count


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    if parsed.scheme != "gs" or not parsed.netloc:
        raise BackupError("Destino GCS deve usar gs://bucket/prefixo.")
    prefix = parsed.path.strip("/")
    if not prefix:
        raise BackupError("Use um prefixo dedicado no bucket de backup.")
    return parsed.netloc, prefix


def _gcs_client() -> Any:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise BackupError("Instale o grupo de dependências 'ops' para usar GCS.") from exc
    return storage.Client()


def _publish_to_gcs(local_path: Path, destination: str) -> str:
    bucket_name, prefix = _parse_gs_uri(destination)
    client = _gcs_client()
    blob = client.bucket(bucket_name).blob(f"{prefix.rstrip('/')}/{local_path.name}")
    blob.metadata = {"certificados-backup": "true", "format": "csbk1"}
    blob.upload_from_filename(str(local_path), if_generation_match=0)
    return f"gs://{bucket_name}/{blob.name}"


def enforce_gcs_retention(destination: str, *, retention_days: int) -> int:
    if retention_days < 1:
        raise BackupError("A retenção deve ser de pelo menos um dia.")
    bucket_name, prefix = _parse_gs_uri(destination)
    cutoff = _utc_now() - timedelta(days=retention_days)
    removed = 0
    client = _gcs_client()
    for blob in client.list_blobs(bucket_name, prefix=f"{prefix.rstrip('/')}/"):
        metadata = blob.metadata or {}
        if metadata.get("certificados-backup") != "true":
            continue
        created = blob.time_created
        if created and created < cutoff:
            blob.delete(if_generation_match=blob.generation)
            removed += 1
    return removed


@contextmanager
def _local_artifact(source: str) -> Iterator[Path]:
    if not source.startswith("gs://"):
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise BackupError("Artefato de backup não encontrado.")
        yield path
        return
    bucket_name, object_name = _parse_gs_uri(source)
    temporary_dir = Path(tempfile.mkdtemp(prefix="certificados-restore-"))
    local_path = temporary_dir / Path(object_name).name
    try:
        _gcs_client().bucket(bucket_name).blob(object_name).download_to_filename(str(local_path))
        yield local_path
    finally:
        local_path.unlink(missing_ok=True)
        temporary_dir.rmdir()


def _decrypt_to_file(source: Path, destination: Any, *, key: bytes) -> dict[str, Any]:
    with source.open("rb") as raw:
        reader = EncryptedReader(raw, key=key)
        while True:
            chunk = reader.read(CHUNK_SIZE)
            if not chunk:
                break
            destination.write(chunk)
        return reader.header


def verify_artifact(
    source: Path, *, key: bytes, expected_kind: str | None = None
) -> dict[str, Any]:
    sink = hashlib.sha256()
    with source.open("rb") as raw:
        reader = EncryptedReader(raw, key=key)
        if expected_kind and reader.header.get("kind") != expected_kind:
            raise BackupError("O tipo do artefato não corresponde à operação.")
        while True:
            chunk = reader.read(CHUNK_SIZE)
            if not chunk:
                break
            sink.update(chunk)
        return {**reader.header, "plaintext_sha256": sink.hexdigest()}


def _max_restore_pdf_bytes() -> int:
    raw = (os.getenv("RESTORE_MAX_PDF_MB") or "25").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise BackupError("RESTORE_MAX_PDF_MB inválido.") from exc
    return max(1, min(value, 100)) * 1024 * 1024


def verify_pdf_artifact(source: Path, *, key: bytes) -> dict[str, dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    declared: dict[str, dict[str, Any]] = {}
    max_pdf_bytes = _max_restore_pdf_bytes()
    with source.open("rb") as raw:
        reader = EncryptedReader(raw, key=key)
        if reader.header.get("kind") != "certificate-pdfs":
            raise BackupError("Artefato não contém PDFs de certificados.")
        try:
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise BackupError("Membro inválido no backup de PDFs.")
                    if member.name == "manifest.ndjson":
                        for line in extracted:
                            record = json.loads(line)
                            code = str(record.get("code") or "")
                            declared[code] = record
                        continue
                    match = re.fullmatch(r"certificates/([A-Za-z0-9._-]{1,64})\.pdf", member.name)
                    if not match or member.size > max_pdf_bytes:
                        raise BackupError("Membro inseguro ou grande demais no backup de PDFs.")
                    content = extracted.read(max_pdf_bytes + 1)
                    if len(content) != member.size or len(content) > max_pdf_bytes:
                        raise BackupError("PDF truncado ou grande demais no backup.")
                    code = match.group(1)
                    seen[code] = {
                        "member": member.name,
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
        except (tarfile.TarError, json.JSONDecodeError) as exc:
            raise BackupError("Conteúdo do backup de PDFs é inválido.") from exc
    if not declared or set(declared) != set(seen):
        raise BackupError("Manifesto de PDFs ausente ou divergente.")
    for code, actual in seen.items():
        expected = declared[code]
        if (
            expected.get("member") != actual["member"]
            or int(expected.get("size") or -1) != actual["size"]
            or expected.get("sha256") != actual["sha256"]
        ):
            raise BackupError("Manifesto de PDFs falhou na verificação.")
    return seen


def restore_database(source: Path, target_url: str, *, key: bytes) -> dict[str, Any]:
    _require_verified_tls(target_url, target="restore")
    target_pg_url = _pg_url(target_url)
    target_name = _database_name(target_url)
    configured_url = db_config.get_configured_database_url()
    if configured_url and target_pg_url == _pg_url(configured_url):
        raise BackupError("Restauração sobre o banco configurado é proibida.")
    if not DISPOSABLE_DB_RE.fullmatch(target_name):
        raise BackupError("O banco de destino deve conter 'restore' ou 'drill' no nome.")
    with tempfile.NamedTemporaryFile(prefix="certificados-db-", suffix=".dump") as dump:
        header = _decrypt_to_file(source, dump, key=key)
        if header.get("kind") != "postgresql":
            raise BackupError("Artefato não contém um dump PostgreSQL.")
        if str(header.get("database") or "") == target_name:
            raise BackupError("O destino não pode ter o mesmo nome do banco de origem.")
        dump.flush()
        env = _pg_environment(target_url)
        try:
            result = subprocess.run(
                [
                    "pg_restore",
                    "--dbname",
                    env["PGDATABASE"],
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    dump.name,
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BackupError("pg_restore não está instalado na imagem operacional.") from exc
        if result.returncode != 0:
            raise BackupError("pg_restore falhou; consulte o log operacional protegido.")
    return header


def restore_pdfs(source: Path, target_url: str, *, key: bytes) -> tuple[int, int]:
    verified = verify_pdf_artifact(source, key=key)
    restored = 0
    skipped = 0
    max_pdf_bytes = _max_restore_pdf_bytes()
    reset_storage_cache()
    with source.open("rb") as raw:
        reader = EncryptedReader(raw, key=key)
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                match = re.fullmatch(r"certificates/([A-Za-z0-9._-]{1,64})\.pdf", member.name)
                if not member.isfile() or not match:
                    continue
                code = match.group(1)
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise BackupError("PDF não pôde ser lido no restore.")
                content = extracted.read(max_pdf_bytes + 1)
                if len(content) != member.size or len(content) > max_pdf_bytes:
                    raise BackupError("PDF truncado ou grande demais durante o restore.")
                metadata = verified[code]
                with session_scope(target_url) as session:
                    row = (
                        session.execute(
                            select(Certificate.__table__).where(Certificate.unique_code == code)
                        )
                        .mappings()
                        .first()
                    )
                if not row:
                    raise BackupError("PDF sem metadado correspondente no banco restaurado.")
                expected_checksum = str(row.get("checksum_sha256") or "")
                if expected_checksum != metadata["sha256"]:
                    raise BackupError("Checksum do PDF diverge do metadado restaurado.")
                try:
                    download_certificate(dict(row), verify=True)
                except (FileNotFoundError, StorageError):
                    pass
                else:
                    skipped += 1
                    continue
                # Preserve the destination recorded in the restored database;
                # legacy rows without one retain the explicit global fallback.
                stored = get_storage(row.get("drive_folder_id")).save(
                    content,
                    filename=f"{code}.pdf",
                    mime_type="application/pdf",
                )
                fields = stored.as_db_fields()
                attached = False
                if fields.get("checksum_sha256") == expected_checksum:
                    # The drill's target URL is an explicit safety boundary. Do
                    # not use the process-global DB facade here: that would risk
                    # attaching restore metadata to the configured source DB.
                    with session_scope(target_url) as target_session:
                        attached = CertificateRepository(target_session).restore_file(
                            code,
                            fields,
                            expected_checksum=expected_checksum,
                        )
                if not attached:
                    try:
                        delete_certificate(fields)
                    except StorageError:
                        pass
                    raise BackupError("Falha atômica ao vincular PDF restaurado.")
                restored += 1
    return restored, skipped


def _target_counts(target_url: str) -> dict[str, int]:
    engine = get_engine(target_url)
    tables = ("certificates", "emission_batches", "audit_log", "admin_users")
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for table_name in tables:
            counts[table_name] = int(
                connection.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar_one()
            )
    return counts


def run_backup(destination: str, *, include_pdfs: bool, retention_days: int) -> dict[str, Any]:
    key = _load_encryption_key()
    db_config.require_production_database()
    if db_config.is_production() and not destination.startswith("gs://"):
        raise BackupError("Produção exige BACKUP_DESTINATION em armazenamento gs:// separado.")
    url = db_config.get_configured_database_url()
    if not url:
        raise BackupError("DATABASE_URL/DATABASE_URL_FILE é obrigatório para backup.")
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    use_gcs = destination.startswith("gs://")
    workdir = (
        Path(tempfile.mkdtemp(prefix="certificados-backup-")) if use_gcs else Path(destination)
    )
    workdir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    try:
        db_path = workdir / f"certificados_{stamp}_database.csbk"
        db_info = backup_database(url, db_path, key=key)
        db_location = _publish_to_gcs(db_path, destination) if use_gcs else str(db_path)
        artifacts.append({**db_info.__dict__, "path": db_location})
        pdf_count = 0
        if include_pdfs:
            pdf_path = workdir / f"certificados_{stamp}_pdfs.csbk"
            pdf_info, pdf_count = backup_pdfs(url, pdf_path, key=key)
            pdf_location = _publish_to_gcs(pdf_path, destination) if use_gcs else str(pdf_path)
            artifacts.append({**pdf_info.__dict__, "path": pdf_location})
        removed = (
            enforce_gcs_retention(destination, retention_days=retention_days) if use_gcs else 0
        )
        return {
            "completed_at": _utc_now().isoformat(),
            "artifacts": artifacts,
            "pdf_count": pdf_count,
            "expired_objects_removed": removed,
        }
    finally:
        if use_gcs:
            for path in workdir.glob("*"):
                path.unlink(missing_ok=True)
            workdir.rmdir()


def run_restore_drill(
    database_artifact: str,
    *,
    target_url: str,
    pdf_artifact: str | None,
    restore_files: bool,
) -> dict[str, Any]:
    key = _load_encryption_key()
    started = _utc_now()
    with _local_artifact(database_artifact) as db_source:
        db_header = restore_database(db_source, target_url, key=key)
    restored = skipped = 0
    if pdf_artifact:
        with _local_artifact(pdf_artifact) as pdf_source:
            verified = verify_pdf_artifact(pdf_source, key=key)
            if restore_files:
                restored, skipped = restore_pdfs(pdf_source, target_url, key=key)
    else:
        verified = {}
    completed = _utc_now()
    return {
        "status": "passed",
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "duration_seconds": round((completed - started).total_seconds(), 3),
        "database_backup_created_at": db_header.get("created_at"),
        "row_counts": _target_counts(target_url),
        "pdfs_verified": len(verified),
        "pdfs_restored": restored,
        "pdfs_already_available": skipped,
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup e restore drill criptografados.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("create")
    backup_parser.add_argument("--destination", required=True)
    backup_parser.add_argument("--without-pdfs", action="store_true")
    backup_parser.add_argument("--retention-days", type=int, default=35)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--artifact", required=True)
    restore_parser = subparsers.add_parser("restore-drill")
    restore_parser.add_argument("--database-artifact", required=True)
    restore_parser.add_argument("--pdf-artifact")
    restore_parser.add_argument("--restore-files", action="store_true")
    restore_parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    observability.configure_logging()
    try:
        if args.command == "create":
            if db_config.is_production() and not args.without_pdfs:
                from storage_service import config as storage_config

                storage_config.validate_production_storage(required_access="read_only")
            report = run_backup(
                args.destination,
                include_pdfs=not args.without_pdfs,
                retention_days=args.retention_days,
            )
        elif args.command == "verify":
            key = _load_encryption_key()
            with _local_artifact(args.artifact) as artifact:
                report = verify_artifact(artifact, key=key)
        else:
            db_config.require_production_database()
            target_url = db_config.read_secret("RESTORE_DATABASE_URL")
            if not target_url:
                raise BackupError(
                    "RESTORE_DATABASE_URL ou RESTORE_DATABASE_URL_FILE é obrigatório."
                )
            normalized_target = db_config.normalize_database_url(target_url)
            _require_verified_tls(normalized_target, target="restore")
            if db_config.is_production() and args.restore_files:
                from storage_service import config as storage_config

                storage_config.validate_production_storage(required_access="read_write")
            report = run_restore_drill(
                args.database_artifact,
                target_url=normalized_target,
                pdf_artifact=args.pdf_artifact,
                restore_files=args.restore_files,
            )
            _write_report(Path(args.report).expanduser().resolve(), report)
        if args.command == "create":
            observability.metrics.increment(observability.BACKUPS_COMPLETED)
        elif args.command == "restore-drill":
            observability.metrics.increment(observability.RESTORE_DRILLS_COMPLETED)
        print(json.dumps(report, sort_keys=True))
        return 0
    except BackupError as exc:
        if args.command == "create":
            observability.metrics.increment(observability.BACKUPS_FAILED)
        elif args.command == "restore-drill":
            observability.metrics.increment(observability.RESTORE_DRILLS_FAILED)
        print(
            json.dumps({"event": "backup_failed", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
