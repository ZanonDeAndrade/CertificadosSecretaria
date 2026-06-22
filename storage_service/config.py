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
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from .base import StorageConfigError

# storage_service/ lives directly under the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PUBLIC_VALIDATION_BASE_URL = "http://localhost:8001"


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


# ── App environment ─────────────────────────────────────────────────────────


def get_app_env() -> str:
    return (os.getenv("APP_ENV") or "development").strip().lower()


def is_production() -> bool:
    return get_app_env() in ("prod", "production")


# ── Simple getters ──────────────────────────────────────────────────────────


def get_storage_provider() -> str:
    """``google_drive`` ou ``local``.

    Em produção o padrão é ``google_drive`` (o local nunca é usado como
    armazenamento definitivo); em desenvolvimento o padrão é ``local``.
    """
    raw = (os.getenv("STORAGE_PROVIDER") or "").strip().lower()
    if raw:
        return raw
    return "google_drive" if is_production() else "local"


def get_drive_folder_id() -> str | None:
    value = (os.getenv("GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID") or "").strip()
    return value or None


def get_drive_auth_mode() -> str:
    """Return the credential strategy used by the Google Drive backend.

    ``service_account`` remains the compatibility default. ``oauth_user`` uses
    an offline OAuth token belonging to a real Google user, which allows the
    application to consume that user's personal Drive quota.
    """
    raw = (os.getenv("GOOGLE_DRIVE_AUTH_MODE") or "service_account").strip().lower()
    aliases = {
        "service_account": "service_account",
        "service-account": "service_account",
        "oauth": "oauth_user",
        "oauth_user": "oauth_user",
        "oauth-user": "oauth_user",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise StorageConfigError(
            "GOOGLE_DRIVE_AUTH_MODE deve ser 'service_account' ou 'oauth_user'."
        ) from exc


def normalize_public_validation_base_url(value: str) -> str:
    """Validate and normalize the public origin/base path used by QR links.

    Only absolute HTTP(S) URLs are accepted. Credentials, query strings and
    fragments are forbidden because they make the validation route ambiguous.
    Repeated/trailing path separators are collapsed so callers cannot produce
    ``//validar`` accidentally.
    """
    raw = (value or "").strip()
    if not raw:
        raise StorageConfigError("PUBLIC_VALIDATION_BASE_URL não foi definida.")
    if "\\" in raw or any(ord(char) < 32 or char.isspace() for char in raw):
        raise StorageConfigError("PUBLIC_VALIDATION_BASE_URL contém caracteres inválidos.")
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        raise StorageConfigError("PUBLIC_VALIDATION_BASE_URL contém escape inválido.")

    try:
        parsed = urlsplit(raw)
        # Accessing .port validates malformed/non-numeric port values.
        parsed.port
    except ValueError as exc:
        raise StorageConfigError("PUBLIC_VALIDATION_BASE_URL é inválida.") from exc

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise StorageConfigError(
            "PUBLIC_VALIDATION_BASE_URL deve ser uma URL HTTP(S) absoluta."
        )
    if parsed.username or parsed.password:
        raise StorageConfigError(
            "PUBLIC_VALIDATION_BASE_URL não pode conter usuário ou senha."
        )
    if parsed.query or parsed.fragment:
        raise StorageConfigError(
            "PUBLIC_VALIDATION_BASE_URL não pode conter query string ou fragmento."
        )

    segments = [segment for segment in parsed.path.split("/") if segment]
    if any(segment in {".", ".."} for segment in segments):
        raise StorageConfigError(
            "PUBLIC_VALIDATION_BASE_URL não pode conter segmentos '.' ou '..'."
        )
    normalized_path = f"/{'/'.join(segments)}" if segments else ""
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, normalized_path, "", "")
    )


def get_public_validation_base_url() -> str:
    """Return the validated base URL used by every certificate QR.

    Development defaults to the local public app. Production has no fallback
    and is validated explicitly during startup.
    """
    value = (os.getenv("PUBLIC_VALIDATION_BASE_URL") or "").strip()
    if not value:
        value = DEFAULT_PUBLIC_VALIDATION_BASE_URL
    return normalize_public_validation_base_url(value)


def build_public_validation_url(code: str) -> str:
    """Build the canonical public validation URL for a certificate code."""
    clean_code = (code or "").strip()
    if not clean_code:
        raise ValueError("O código de validação não pode ser vazio.")
    return f"{get_public_validation_base_url()}/validar/{quote(clean_code, safe='')}"


def validate_production_public_validation_url() -> None:
    """Require an explicit HTTPS public validation base URL in production."""
    if not is_production():
        return
    value = (os.getenv("PUBLIC_VALIDATION_BASE_URL") or "").strip()
    base_url = normalize_public_validation_base_url(value)
    if urlsplit(base_url).scheme != "https":
        raise StorageConfigError(
            "Em produção, PUBLIC_VALIDATION_BASE_URL deve usar HTTPS."
        )


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


def load_oauth_token_info() -> dict[str, Any]:
    """Load an authorized-user OAuth token without logging or persisting it.

    The token is generated once by ``authorize_google_drive.py``. Production
    should inject it as base64; a file path is convenient for local setup.
    """
    b64 = (os.getenv("GOOGLE_OAUTH_TOKEN_JSON_BASE64") or "").strip()
    if b64:
        try:
            info = json.loads(base64.b64decode(b64))
        except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
            raise StorageConfigError(
                "GOOGLE_OAUTH_TOKEN_JSON_BASE64 inválido (base64/JSON)."
            ) from exc
    else:
        file_path = (os.getenv("GOOGLE_OAUTH_TOKEN_FILE") or "").strip()
        if not file_path:
            raise StorageConfigError(
                "Token OAuth do Google Drive ausente. Defina "
                "GOOGLE_OAUTH_TOKEN_JSON_BASE64 ou GOOGLE_OAUTH_TOKEN_FILE."
            )
        path = Path(file_path).expanduser()
        if not path.is_file():
            raise StorageConfigError(f"GOOGLE_OAUTH_TOKEN_FILE não encontrado: {path}")
        try:
            info = json.loads(path.read_text("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise StorageConfigError(
                "GOOGLE_OAUTH_TOKEN_FILE não contém JSON válido."
            ) from exc

    required = {"refresh_token", "token_uri", "client_id", "client_secret"}
    missing = sorted(key for key in required if not info.get(key))
    if missing:
        raise StorageConfigError(
            "Token OAuth incompleto; campos ausentes: " + ", ".join(missing)
        )
    return info


# ── Fail-closed startup validation (production) ────────────────────────────────


def validate_production_storage() -> None:
    """Abort startup in production unless Google Drive is fully configured.

    Requires ``STORAGE_PROVIDER=google_drive``, a folder id and loadable
    credentials for the selected auth mode. No local fallback is allowed.
    """
    if not is_production():
        return
    provider = get_storage_provider()
    if provider != "google_drive":
        raise StorageConfigError(
            "Em produção, STORAGE_PROVIDER deve ser 'google_drive' "
            f"(recebido: '{provider}'). O storage local não é permitido em produção."
        )
    if not get_drive_folder_id():
        raise StorageConfigError(
            "Em produção, GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID é obrigatório."
        )
    auth_mode = get_drive_auth_mode()
    if auth_mode == "oauth_user":
        load_oauth_token_info()
    else:
        load_service_account_info()
