"""Google Drive storage backend (production).

Uses a **Service Account** and the Google Drive API. Credentials come strictly
from environment variables (see ``config.load_service_account_info``); nothing
is read from or written to the database, and no secret is ever logged.

Files are uploaded into ``GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID`` and are **not**
made public — only the service account (and whoever the folder is shared with)
can read them. The public area never receives a Drive link; downloads are
proxied by the backend using the verification code.

The ``googleapiclient`` / ``google.oauth2`` imports are deliberately lazy
(inside methods) so the rest of the system — and the test suite — can import
this module without the Google libraries installed.
"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Any, Mapping

from . import config
from .base import (
    DEFAULT_MIME_TYPE,
    CertificateStorage,
    StorageConfigError,
    StorageError,
    StoredFile,
    sha256_hex,
    utc_now_iso,
)

LOGGER = logging.getLogger("certificados.storage.gdrive")

# drive.file: access limited to files the app creates — least privilege.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GoogleDriveStorage(CertificateStorage):
    provider = "google_drive"

    def __init__(self, folder_id: str | None = None, service: Any = None) -> None:
        self._folder_id = folder_id or config.get_drive_folder_id()
        if not self._folder_id:
            raise StorageConfigError(
                "GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID não definido."
            )
        # ``service`` may be injected (e.g. fakes in tests); otherwise built lazily.
        self._service = service

    # ── Service client ────────────────────────────────────────────────────────

    @property
    def service(self) -> Any:
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _build_service(self) -> Any:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover - depends on env
            raise StorageConfigError(
                "Bibliotecas do Google ausentes. Instale "
                "'google-api-python-client' e 'google-auth'."
            ) from exc

        info = config.load_service_account_info()
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    # ── Operations ──────────────────────────────────────────────────────────────

    def save(
        self,
        content: bytes,
        *,
        filename: str,
        mime_type: str = DEFAULT_MIME_TYPE,
    ) -> StoredFile:
        try:
            from googleapiclient.errors import HttpError
            from googleapiclient.http import MediaIoBaseUpload
        except ImportError as exc:  # pragma: no cover
            raise StorageConfigError(
                "Bibliotecas do Google ausentes para upload."
            ) from exc

        media = MediaIoBaseUpload(BytesIO(content), mimetype=mime_type, resumable=False)
        metadata = {"name": filename, "parents": [self._folder_id]}
        try:
            created = (
                self.service.files()
                .create(
                    body=metadata,
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            LOGGER.error("Falha no upload para o Drive (arquivo=%s): %s", filename, exc)
            raise StorageError("Falha ao enviar o certificado para o Google Drive.") from exc

        file_id = created["id"]
        LOGGER.info(
            "Certificado enviado ao Drive: file_id=%s folder_id=%s",
            file_id,
            self._folder_id,
        )
        return StoredFile(
            storage_provider=self.provider,
            original_filename=filename,
            mime_type=mime_type,
            file_size=len(content),
            checksum_sha256=sha256_hex(content),
            created_at=utc_now_iso(),
            drive_file_id=file_id,
            drive_folder_id=self._folder_id,
            pdf_path="",
        )

    def download(self, cert_row: Mapping[str, Any]) -> bytes:
        file_id = (cert_row.get("drive_file_id") or "").strip()
        if not file_id:
            raise FileNotFoundError("Certificado sem drive_file_id.")

        try:
            from googleapiclient.errors import HttpError
            from googleapiclient.http import MediaIoBaseDownload
        except ImportError as exc:  # pragma: no cover
            raise StorageConfigError(
                "Bibliotecas do Google ausentes para download."
            ) from exc

        buffer = BytesIO()
        try:
            request = self.service.files().get_media(
                fileId=file_id, supportsAllDrives=True
            )
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status == 404:
                LOGGER.warning("Arquivo do Drive não encontrado: file_id=%s", file_id)
                raise FileNotFoundError("Arquivo não encontrado no Google Drive.") from exc
            LOGGER.error("Falha no download do Drive (file_id=%s): %s", file_id, exc)
            raise StorageError("Falha ao obter o certificado do Google Drive.") from exc

        return buffer.getvalue()
