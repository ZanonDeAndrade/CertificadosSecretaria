"""Local filesystem storage — intended for development only.

PDFs are written under ``STORAGE_DIR/pdfs`` and referenced by a
``STORAGE_DIR``-relative ``pdf_path`` (e.g. ``pdfs/Joao Silva_Evento_2026.pdf``),
keeping full backward compatibility with certificates issued before the storage
abstraction existed.

A new certificate is created exclusively (``O_EXCL``): the file of another
certificate is never overwritten, which would break its recorded hash. When the
name is taken the content goes to the ``_2``, ``_3``… variant instead. Only a
reissue rewrites a file, and only the one its own row points at.
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
from .filenames import numbered_filenames

LOGGER = logging.getLogger("certificados.storage.local")

_CREATE_EXCLUSIVE = os.O_WRONLY | os.O_CREAT | os.O_EXCL


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
        """Create a NEW file under ``filename`` or its first free ``_n`` variant.

        Creation is exclusive and atomic at the file system level: two
        emissions racing for the same name both succeed, under two names, and
        neither can replace a file that already exists. There is no "check,
        then write" window.
        """
        self._pdfs_dir.mkdir(parents=True, exist_ok=True)
        for candidate in numbered_filenames(_basename(filename)):
            dest = self._pdfs_dir / candidate
            try:
                descriptor = os.open(dest, _CREATE_EXCLUSIVE, 0o644)
            except FileExistsError:
                continue
            except OSError as exc:  # pragma: no cover - filesystem dependent
                raise StorageError(f"Falha ao gravar PDF localmente: {exc}") from exc
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
            except OSError as exc:  # pragma: no cover - filesystem dependent
                dest.unlink(missing_ok=True)
                raise StorageError(f"Falha ao gravar PDF localmente: {exc}") from exc
            LOGGER.info("Certificado salvo no storage local")
            return self._stored(dest, content, mime_type)
        raise StorageError("Não há nome livre para gravar o PDF localmente.")

    def replace(
        self,
        content: bytes,
        *,
        cert_row: Mapping[str, Any],
        filename: str,
        mime_type: str = DEFAULT_MIME_TYPE,
    ) -> StoredFile:
        """Rewrite the file ``cert_row`` points at (a reissue), keeping its path.

        The target is the certificate's own ``pdf_path``, resolved strictly
        inside the storage root; ``filename`` is used only when the row has no
        local file yet, and then as a new, exclusive file.
        """
        if not (cert_row.get("pdf_path") or "").strip():
            return self.save(content, filename=filename, mime_type=mime_type)
        dest = self._resolve_within_storage(str(cert_row["pdf_path"]))
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, dest)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            temporary.unlink(missing_ok=True)
            raise StorageError(f"Falha ao regravar PDF localmente: {exc}") from exc
        LOGGER.info("Certificado reemitido regravado no storage local")
        return self._stored(dest, content, mime_type)

    def _stored(self, dest: Path, content: bytes, mime_type: str) -> StoredFile:
        rel = os.path.relpath(dest, self._storage_dir).replace(os.sep, "/")
        return StoredFile(
            storage_provider=self.provider,
            original_filename=dest.name,
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
            raise FileNotFoundError("Arquivo local do certificado não encontrado.")
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
        LOGGER.info("Certificado local removido em compensação")


def _basename(filename: str) -> str:
    """``filename`` as a single path component, or a ``StorageError``.

    Callers pass names already cleaned by ``storage_service.filenames``; this
    only refuses a separator or a bare dot that would escape the PDF folder.
    """
    name = (filename or "").strip()
    if not name or name in {".", ".."} or Path(name).name != name:
        raise StorageError("Nome de arquivo inválido para o storage local.")
    return name
