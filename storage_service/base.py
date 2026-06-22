"""Storage abstraction for certificate PDFs.

Defines the provider-agnostic contract used by the rest of the system. No part
of the application (generator, routes, main) should import a concrete provider
directly — they go through ``storage_service.get_storage()`` and the
``CertificateStorage`` interface below.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

DEFAULT_MIME_TYPE = "application/pdf"


# ── Exceptions ──────────────────────────────────────────────────────────────


class StorageError(Exception):
    """Base error for any storage operation failure (upload/download)."""


class StorageConfigError(StorageError):
    """Raised when the storage backend is misconfigured (missing env, etc.)."""


class StorageIntegrityError(StorageError):
    """Raised when a downloaded file fails size / checksum / MIME verification."""


# ── Value objects ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StoredFile:
    """Result of persisting a certificate PDF.

    Carries exactly the metadata that must be saved on the ``certificates``
    table so the file can be retrieved later without leaking provider-specific
    paths/links to the public area.
    """

    storage_provider: str
    original_filename: str
    mime_type: str
    file_size: int
    checksum_sha256: str
    created_at: str
    drive_file_id: str | None = None
    drive_folder_id: str | None = None
    # STORAGE_DIR-relative path when stored locally (e.g. "pdfs/Joao_CERT-...pdf");
    # empty string for remote providers.
    pdf_path: str = ""

    def as_db_fields(self) -> dict[str, Any]:
        """Subset of fields persisted on the certificates table."""
        return {
            "storage_provider": self.storage_provider,
            "drive_file_id": self.drive_file_id,
            "drive_folder_id": self.drive_folder_id,
            "original_filename": self.original_filename,
            "mime_type": self.mime_type,
            "file_size": self.file_size,
            "checksum_sha256": self.checksum_sha256,
            "pdf_path": self.pdf_path,
        }


@dataclass(frozen=True)
class RetrievedFile:
    """A downloaded certificate, ready to be streamed by the backend.

    Intentionally carries ONLY bytes + display metadata — never a provider
    URL or internal id — so the public download path cannot leak Drive links.
    """

    content: bytes
    filename: str
    mime_type: str = DEFAULT_MIME_TYPE


# ── Helpers ───────────────────────────────────────────────────────────────────


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


PDF_MAGIC = b"%PDF-"


def looks_like_pdf(content: bytes) -> bool:
    """True if ``content`` begins with the PDF magic bytes."""
    return content[:5] == PDF_MAGIC


def verify_pdf_integrity(
    content: bytes,
    *,
    expected_size: int | None = None,
    expected_checksum: str | None = None,
) -> None:
    """Confirm the bytes are a PDF and match the recorded size/checksum.

    Raises :class:`StorageIntegrityError` on any mismatch so the caller can
    block the file and refuse to serve tampered/corrupt content.
    """
    if not looks_like_pdf(content):
        raise StorageIntegrityError("MIME inválido: o conteúdo não é um PDF.")
    if expected_size is not None and len(content) != int(expected_size):
        raise StorageIntegrityError(
            f"Tamanho divergente: {len(content)} bytes != {int(expected_size)} esperados."
        )
    if expected_checksum:
        actual = sha256_hex(content)
        if actual != str(expected_checksum):
            raise StorageIntegrityError("Checksum SHA-256 divergente.")


# ── Interface ─────────────────────────────────────────────────────────────────


class CertificateStorage(ABC):
    """Provider-agnostic certificate storage contract."""

    #: short, stable identifier persisted as ``storage_provider``
    provider: str = "abstract"

    @abstractmethod
    def save(
        self,
        content: bytes,
        *,
        filename: str,
        mime_type: str = DEFAULT_MIME_TYPE,
    ) -> StoredFile:
        """Persist ``content`` and return its storage metadata."""

    @abstractmethod
    def download(self, cert_row: Mapping[str, Any]) -> bytes:
        """Return the raw bytes for a certificate given its DB row."""

    @abstractmethod
    def delete(self, cert_row: Mapping[str, Any]) -> None:
        """Delete the stored file referenced by ``cert_row`` (saga compensation).

        Must be **idempotent**: deleting an already-absent file is a no-op, not
        an error. Raises :class:`StorageError` only on an unexpected failure.
        """
