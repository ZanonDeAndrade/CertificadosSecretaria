"""Environment-driven configuration for the storage layer.

All secrets come exclusively from environment variables (never from the
database or hardcoded values). A single repo-root ``.env`` is loaded the same
way ``database/db.py`` does it, so both projects pick up identical settings.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any

from .base import StorageConfigError

# storage_service/ lives directly under the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal, dependency-free .env loader (real env vars always win)."""
    if not path.is_file():
        return
    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(REPO_ROOT / ".env")


# ── Simple getters ──────────────────────────────────────────────────────────


def get_storage_provider() -> str:
    """``local`` (default) or ``google_drive``."""
    return (os.getenv("STORAGE_PROVIDER") or "local").strip().lower()


def get_drive_folder_id() -> str | None:
    value = (os.getenv("GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID") or "").strip()
    return value or None


def get_public_validation_base_url() -> str | None:
    """Base URL used to build the public validation link / QR (e.g.
    https://certificados.exemplo.edu.br). Returned without a trailing slash."""
    value = (os.getenv("PUBLIC_VALIDATION_BASE_URL") or "").strip()
    return value.rstrip("/") or None


def get_max_file_size_bytes() -> int | None:
    """Optional cap for a single certificate PDF, from
    ``MAX_CERTIFICATE_FILE_SIZE_MB``. Returns ``None`` when unset/invalid."""
    raw = (os.getenv("MAX_CERTIFICATE_FILE_SIZE_MB") or "").strip()
    if not raw:
        return None
    try:
        mb = float(raw)
    except ValueError:
        return None
    if mb <= 0:
        return None
    return int(mb * 1024 * 1024)


# ── Service-account credentials (Google Drive) ────────────────────────────────


def load_service_account_info() -> dict[str, Any]:
    """Return the service-account credentials as a dict.

    Resolution order (no secret is ever persisted or logged):
      1. ``GOOGLE_SERVICE_ACCOUNT_JSON_BASE64`` — preferred for production.
      2. ``GOOGLE_SERVICE_ACCOUNT_FILE`` — path to a JSON file (local dev only).
    """
    b64 = (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64") or "").strip()
    if b64:
        try:
            decoded = base64.b64decode(b64)
            return json.loads(decoded)
        except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
            raise StorageConfigError(
                "GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 inválido (base64/JSON)."
            ) from exc

    file_path = (os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "").strip()
    if file_path:
        path = Path(file_path).expanduser()
        if not path.is_file():
            raise StorageConfigError(
                f"GOOGLE_SERVICE_ACCOUNT_FILE não encontrado: {path}"
            )
        try:
            return json.loads(path.read_text("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise StorageConfigError(
                "GOOGLE_SERVICE_ACCOUNT_FILE não contém JSON válido."
            ) from exc

    raise StorageConfigError(
        "Credenciais do Google Drive ausentes. Defina "
        "GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 ou GOOGLE_SERVICE_ACCOUNT_FILE."
    )
