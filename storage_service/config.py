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


if (os.getenv("CERTIFICADOS_DISABLE_DOTENV") or "").strip().lower() not in {
    "1",
    "true",
    "yes",
}:
    _load_dotenv(REPO_ROOT / ".env")


# ── App environment ─────────────────────────────────────────────────────────


def get_app_env() -> str:
    return (os.getenv("APP_ENV") or "development").strip().lower()


def is_production() -> bool:
    return get_app_env() in ("prod", "production")


def is_local_server() -> bool:
    """True for the hardened, HTTP-only deployment inside a private LAN."""
    return get_app_env() in {"local_server", "local-server", "lan"}


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


def get_drive_access_mode() -> str:
    """Return ``read_write`` for admin/jobs or ``read_only`` for public reads."""

    default = "read_only" if (os.getenv("APP_TARGET") or "").strip() == "consulta" else "read_write"
    raw = (os.getenv("GOOGLE_DRIVE_ACCESS_MODE") or default).strip().lower()
    aliases = {
        "read_only": "read_only",
        "read-only": "read_only",
        "readonly": "read_only",
        "read_write": "read_write",
        "read-write": "read_write",
        "readwrite": "read_write",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise StorageConfigError(
            "GOOGLE_DRIVE_ACCESS_MODE deve ser 'read_only' ou 'read_write'."
        ) from exc


def get_drive_scopes() -> list[str]:
    if get_drive_access_mode() == "read_only":
        return ["https://www.googleapis.com/auth/drive.readonly"]
    return ["https://www.googleapis.com/auth/drive.file"]


def validate_declared_scopes(scopes: object) -> None:
    """Require an exact least-privilege scope set when metadata declares it."""

    if isinstance(scopes, str):
        declared = set(scopes.split())
    elif isinstance(scopes, list):
        declared = {str(scope) for scope in scopes}
    else:
        declared = set()
    expected = set(get_drive_scopes())
    if is_production() and not declared:
        raise StorageConfigError(
            "A credencial de produção deve declarar explicitamente o escopo do Drive."
        )
    if declared and declared != expected:
        raise StorageConfigError(
            "A credencial não declara exatamente o escopo exigido pelo perfil de acesso."
        )


def _credential_names(kind: str) -> tuple[str, str]:
    """Select profile-specific credential variables.

    Production never falls back from PUBLIC/ADMIN variables to a shared generic
    credential, which makes accidental privilege sharing a startup error.
    """

    profile = "PUBLIC" if get_drive_access_mode() == "read_only" else "ADMIN"
    if kind == "oauth":
        return f"GOOGLE_{profile}_OAUTH_TOKEN_JSON_BASE64", f"GOOGLE_{profile}_OAUTH_TOKEN_FILE"
    return (
        f"GOOGLE_{profile}_SERVICE_ACCOUNT_JSON_BASE64",
        f"GOOGLE_{profile}_SERVICE_ACCOUNT_FILE",
    )


def _first_configured(*names: str) -> tuple[str, str]:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return name, value
    return "", ""


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
        raise StorageConfigError("PUBLIC_VALIDATION_BASE_URL deve ser uma URL HTTP(S) absoluta.")
    if parsed.username or parsed.password:
        raise StorageConfigError("PUBLIC_VALIDATION_BASE_URL não pode conter usuário ou senha.")
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
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, normalized_path, "", ""))


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
        raise StorageConfigError("Em produção, PUBLIC_VALIDATION_BASE_URL deve usar HTTPS.")


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
    profile_b64, profile_file = _credential_names("service_account")
    b64_names = [profile_b64]
    file_names = [profile_file]
    if not is_production():
        b64_names.append("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")
        file_names.append("GOOGLE_SERVICE_ACCOUNT_FILE")
    _b64_name, b64 = _first_configured(*b64_names)
    if b64:
        try:
            decoded = base64.b64decode(b64)
            info = json.loads(decoded)
        except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
            raise StorageConfigError(
                "GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 inválido (base64/JSON)."
            ) from exc

    else:
        _file_name, file_path = _first_configured(*file_names)
        if not file_path:
            raise StorageConfigError(
                "Credencial de Service Account ausente para o perfil de acesso selecionado."
            )
        path = Path(file_path).expanduser()
        if not path.is_file():
            raise StorageConfigError("Arquivo de Service Account configurado não foi encontrado.")
        try:
            info = json.loads(path.read_text("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise StorageConfigError("GOOGLE_SERVICE_ACCOUNT_FILE não contém JSON válido.") from exc

    if not isinstance(info, dict):
        raise StorageConfigError("Credencial de Service Account deve ser um objeto JSON.")
    # Service-account credential JSON has no OAuth ``scopes`` field; the exact
    # scope is supplied programmatically by ``get_drive_scopes`` when building
    # the credentials. OAuth authorized-user tokens are validated below.
    return info


def load_oauth_token_info() -> dict[str, Any]:
    """Load an authorized-user OAuth token without logging or persisting it.

    The token is generated once by ``authorize_google_drive.py``. Production
    should inject it as base64; a file path is convenient for local setup.
    """
    profile_b64, profile_file = _credential_names("oauth")
    b64_names = [profile_b64]
    file_names = [profile_file]
    if not is_production():
        b64_names.append("GOOGLE_OAUTH_TOKEN_JSON_BASE64")
        file_names.append("GOOGLE_OAUTH_TOKEN_FILE")
    _b64_name, b64 = _first_configured(*b64_names)
    if b64:
        try:
            info = json.loads(base64.b64decode(b64))
        except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
            raise StorageConfigError(
                "GOOGLE_OAUTH_TOKEN_JSON_BASE64 inválido (base64/JSON)."
            ) from exc
    else:
        _file_name, file_path = _first_configured(*file_names)
        if not file_path:
            raise StorageConfigError(
                "Token OAuth do Google Drive ausente para o perfil de acesso selecionado."
            )
        path = Path(file_path).expanduser()
        if not path.is_file():
            raise StorageConfigError("Arquivo de token OAuth configurado não foi encontrado.")
        try:
            info = json.loads(path.read_text("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise StorageConfigError("GOOGLE_OAUTH_TOKEN_FILE não contém JSON válido.") from exc

    required = {"refresh_token", "token_uri", "client_id", "client_secret"}
    missing = sorted(key for key in required if not info.get(key))
    if missing:
        raise StorageConfigError("Token OAuth incompleto; campos ausentes: " + ", ".join(missing))
    validate_declared_scopes(info.get("scopes"))
    return info


# ── Fail-closed startup validation (production) ────────────────────────────────


def validate_production_storage(*, required_access: str | None = None) -> None:
    """Abort startup in production unless Google Drive is fully configured.

    Requires ``STORAGE_PROVIDER=google_drive`` and loadable credentials for the
    selected auth mode. The global folder is intentionally optional: new panel
    emissions supply a validated folder per event; legacy tools still fail at
    operation time when they call the storage without one.
    """
    if not is_production():
        return
    provider = get_storage_provider()
    if provider != "google_drive":
        raise StorageConfigError(
            "Em produção, STORAGE_PROVIDER deve ser 'google_drive' "
            f"(recebido: '{provider}'). O storage local não é permitido em produção."
        )
    access_mode = get_drive_access_mode()
    if required_access and access_mode != required_access:
        raise StorageConfigError(
            "O perfil de acesso ao Drive não corresponde ao serviço em execução."
        )
    auth_mode = get_drive_auth_mode()
    if auth_mode == "oauth_user":
        load_oauth_token_info()
    else:
        load_service_account_info()


def validate_local_server_storage() -> None:
    """Require an explicit persistent local filesystem for the LAN profile."""
    if not is_local_server():
        return
    provider = get_storage_provider()
    if provider != "local":
        raise StorageConfigError(
            "APP_ENV=local_server exige STORAGE_PROVIDER=local; "
            "o diretório persistente deve ser protegido e incluído no backup."
        )
    path = (os.getenv("LOCAL_STORAGE_PATH") or os.getenv("STORAGE_DIR") or "").strip()
    if not path:
        raise StorageConfigError(
            "APP_ENV=local_server exige LOCAL_STORAGE_PATH em um volume persistente."
        )
