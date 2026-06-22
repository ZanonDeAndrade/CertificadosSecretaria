"""Local filesystem storage — intended for development only.

PDFs are written under ``STORAGE_DIR/pdfs`` and referenced by a
``STORAGE_DIR``-relative ``pdf_path`` (e.g. ``pdfs/Joao_CERT-2026-AB1234.pdf``),
keeping full backward compatibility with certificates issued before the storage
abstraction existed.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Mapping

from .base import (
    DEFAULT_MIME_TYPE,
    CertificateStorage,
    StorageError,
    StoredFile,
    sha256_hex,
    utc_now_iso,
)

LOGGER = logging.getLogger("certificados.storage.local")


class LocalStorage(CertificateStorage):
    provider = "local"

    def __init__(
        self,
        pdfs_dir: Path | str | None = None,
        storage_dir: Path | str | None = None,
    ) -> None:
        if pdfs_dir is None or storage_dir is None:
            # Fall back to the canonical shared paths only when not injected,
            # so the class stays unit-testable without the database package.
            from database.db import PDFS_DIR, STORAGE_DIR  # local import

            self._pdfs_dir = Path(pdfs_dir) if pdfs_dir else PDFS_DIR
            self._storage_dir = Path(storage_dir) if storage_dir else STORAGE_DIR
        else:
            self._pdfs_dir = Path(pdfs_dir)
            self._storage_dir = Path(storage_dir)

    def save(
        self,
        content: bytes,
        *,
        filename: str,
        mime_type: str = DEFAULT_MIME_TYPE,
    ) -> StoredFile:
        self._pdfs_dir.mkdir(parents=True, exist_ok=True)
        dest = self._pdfs_dir / filename
        try:
            dest.write_bytes(content)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            raise StorageError(f"Falha ao gravar PDF localmente: {exc}") from exc

        rel = os.path.relpath(dest, self._storage_dir).replace(os.sep, "/")
        LOGGER.info("Certificado salvo localmente: %s", rel)
        return StoredFile(
            storage_provider=self.provider,
            original_filename=filename,
            mime_type=mime_type,
            file_size=len(content),
            checksum_sha256=sha256_hex(content),
            created_at=utc_now_iso(),
            drive_file_id=None,
            drive_folder_id=None,
            pdf_path=rel,
        )

    def _resolve_within_storage(self, pdf_path: str) -> Path:
        """Resolve a ``pdf_path`` strictly inside ``storage_dir``.

        Absolute paths and ``..`` traversal are REJECTED (no reading/deleting
        files outside the storage root, even if a row was tampered with).
        """
        p = (pdf_path or "").strip()
        if not p:
            raise FileNotFoundError("Certificado sem pdf_path local.")
        candidate = Path(p)
        if candidate.is_absolute() or candidate.drive or candidate.root:
            raise StorageError("Caminho absoluto não é permitido no storage local.")
        if ".." in candidate.parts:
            raise StorageError("Travessia de diretório não é permitida.")
        base = self._storage_dir.resolve()
        full = (base / candidate).resolve()
        if full != base and not full.is_relative_to(base):
            raise StorageError("Caminho fora do diretório de armazenamento.")
        return full

    def download(self, cert_row: Mapping[str, Any]) -> bytes:
        path = self._resolve_within_storage(cert_row.get("pdf_path") or "")
        if not path.is_file():
            raise FileNotFoundError(f"Arquivo local não encontrado: {path}")
        return path.read_bytes()

    def delete(self, cert_row: Mapping[str, Any]) -> None:
        """Remove the local PDF. Idempotent (missing file is a no-op)."""
        if not (cert_row.get("pdf_path") or "").strip():
            return
        path = self._resolve_within_storage(cert_row["pdf_path"])
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            raise StorageError(f"Falha ao remover PDF local: {exc}") from exc
        LOGGER.info("Certificado local removido (compensação): %s", cert_row["pdf_path"])
