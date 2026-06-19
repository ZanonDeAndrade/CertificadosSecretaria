"""Pluggable certificate storage layer.

Public API:

    from storage_service import get_storage, download_certificate

``get_storage()`` returns the configured backend (``local`` or
``google_drive``) for *writing* new certificates. ``download_certificate()`` is
a provider-aware *reader* that also implements the legacy fallback: if a row has
no ``drive_file_id`` it serves the old local file under ``storage/pdfs/``.

Concrete providers are never imported by the rest of the app directly.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Mapping

from . import config
from .base import (
    CertificateStorage,
    RetrievedFile,
    StorageConfigError,
    StorageError,
    StoredFile,
)
from .google_drive import GoogleDriveStorage
from .local import LocalStorage

__all__ = [
    "CertificateStorage",
    "RetrievedFile",
    "StoredFile",
    "StorageError",
    "StorageConfigError",
    "get_storage",
    "download_certificate",
    "reset_storage_cache",
    "config",
]

LOGGER = logging.getLogger("certificados.storage")


@lru_cache(maxsize=None)
def get_storage() -> CertificateStorage:
    """Return the storage backend selected by ``STORAGE_PROVIDER`` (cached)."""
    provider = config.get_storage_provider()
    if provider == "google_drive":
        LOGGER.info("Storage provider: google_drive")
        return GoogleDriveStorage()
    if provider not in ("local", ""):
        LOGGER.warning("STORAGE_PROVIDER desconhecido (%s); usando 'local'.", provider)
    LOGGER.info("Storage provider: local")
    return LocalStorage()


def reset_storage_cache() -> None:
    """Clear the cached backend (used by tests after changing env vars)."""
    get_storage.cache_clear()


def _fallback_filename(cert_row: Mapping[str, Any]) -> str:
    name = cert_row.get("original_filename")
    if name:
        return str(name)
    code = cert_row.get("unique_code") or "certificado"
    return f"{code}.pdf"


def download_certificate(cert_row: Mapping[str, Any]) -> RetrievedFile:
    """Fetch a certificate's bytes, provider-aware, with local fallback.

    - If the row carries a ``drive_file_id`` → download from Google Drive.
    - Otherwise → serve the legacy local file (``pdf_path`` under STORAGE_DIR).

    Returns a :class:`RetrievedFile` that contains only bytes + display
    metadata — never a Drive link or internal id — so callers cannot
    accidentally expose provider internals to the public.
    """
    filename = _fallback_filename(cert_row)
    mime_type = cert_row.get("mime_type") or "application/pdf"

    if (cert_row.get("drive_file_id") or "").strip():
        content = GoogleDriveStorage().download(cert_row)
        return RetrievedFile(content=content, filename=filename, mime_type=mime_type)

    # Legacy / local provider fallback.
    content = LocalStorage().download(cert_row)
    return RetrievedFile(content=content, filename=filename, mime_type=mime_type)
