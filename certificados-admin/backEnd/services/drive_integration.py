"""Secure Google OAuth + Picker bridge for per-event Drive destinations."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from certificados_backend.services import audit_service, job_crypto
from fastapi import HTTPException

from database import config as db_config
from database import db
from storage_service import config as storage_config
from storage_service.google_drive import GoogleDriveStorage

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
_FOLDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,255}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _required_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="Integração com Google Drive indisponível.")
    return value


def _required_secret(name: str) -> str:
    value = db_config.read_secret(name)
    if not value:
        raise HTTPException(status_code=503, detail="Integração com Google Drive indisponível.")
    return value


def _client_secret() -> str:
    return _required_secret("GOOGLE_PICKER_CLIENT_SECRET")


def _redirect_uri() -> str:
    value = _required_env("GOOGLE_DRIVE_OAUTH_REDIRECT_URI")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=503, detail="Callback OAuth do Google Drive inválido.")
    if db_config.is_production() and parsed.scheme != "https":
        raise HTTPException(status_code=503, detail="Callback OAuth deve usar HTTPS.")
    return value


def validate_configuration() -> None:
    """Fail closed at admin startup without making a Google network call."""
    if not db_config.is_production():
        return
    _required_env("GOOGLE_PICKER_CLIENT_ID")
    _client_secret()
    _required_secret("GOOGLE_PICKER_API_KEY")
    _redirect_uri()
    frontend_return_url(connected=True)
    principals = _technical_principals()
    if len(principals) != 2 or {role for _email, role in principals} != {"writer", "reader"}:
        raise HTTPException(
            status_code=503,
            detail="Identidades técnicas distintas de escrita e leitura são obrigatórias.",
        )


def frontend_return_url(*, connected: bool) -> str:
    base = _required_env("ADMIN_FRONTEND_URL").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=503, detail="URL do painel inválida.")
    status = "connected" if connected else "error"
    return f"{base}/emitir?google_drive={status}"


def _state_aad(user_id: int) -> str:
    return f"google-drive-oauth:{user_id}:pkce:v1"


def _token_aad(user_id: int) -> str:
    return f"google-drive-oauth:{user_id}:access-token:v1"


def begin_oauth(actor: dict) -> dict[str, str]:
    user_id = int(actor["id"])
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    encrypted = job_crypto.encrypt_json({"verifier": verifier}, aad=_state_aad(user_id))
    db.store_google_drive_oauth_state(
        user_id,
        {
            "state_hash": _sha(state),
            "pkce_verifier_ciphertext": encrypted.ciphertext,
            "pkce_verifier_nonce": encrypted.nonce,
            "pkce_verifier_key_id": encrypted.key_id,
            "state_expires_at": _now() + timedelta(minutes=10),
        },
    )
    query = urlencode(
        {
            "client_id": _required_env("GOOGLE_PICKER_CLIENT_ID"),
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": DRIVE_FILE_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "include_granted_scopes": "false",
            "prompt": "select_account consent",
        }
    )
    return {"authorization_url": f"{AUTHORIZATION_ENDPOINT}?{query}"}


def _post_form(url: str, values: dict[str, str]) -> dict[str, Any]:
    request = UrlRequest(
        url,
        data=urlencode(values).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed Google endpoint
            value = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - normalize Google/network errors
        raise HTTPException(
            status_code=502,
            detail="Não foi possível concluir a autenticação com o Google.",
        ) from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=502, detail="Resposta OAuth do Google inválida.")
    return value


def _user_drive_service(access_token: str) -> Any:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail="Bibliotecas Google indisponíveis.") from exc
    credentials = Credentials(token=access_token, scopes=[DRIVE_FILE_SCOPE])
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def complete_oauth(actor: dict, *, state: str, code: str) -> None:
    if not state or not code:
        raise HTTPException(status_code=400, detail="Callback OAuth incompleto.")
    state_hash = _sha(state)
    row = db.get_google_drive_connection_by_state(state_hash)
    if not row or int(row["user_id"]) != int(actor["id"]):
        raise HTTPException(status_code=400, detail="State OAuth inválido ou reutilizado.")
    expires = _utc(row.get("state_expires_at"))
    if expires is None or expires <= _now():
        raise HTTPException(status_code=400, detail="A sessão de conexão com o Google expirou.")
    if not db.consume_google_drive_oauth_state(int(actor["id"]), state_hash):
        raise HTTPException(status_code=400, detail="State OAuth inválido ou reutilizado.")
    try:
        payload = job_crypto.decrypt_json(
            row["pkce_verifier_ciphertext"],
            row["pkce_verifier_nonce"],
            str(row["pkce_verifier_key_id"]),
            aad=_state_aad(int(actor["id"])),
        )
        verifier = str(payload["verifier"])
    except (KeyError, TypeError, job_crypto.PayloadCryptoError) as exc:
        raise HTTPException(status_code=400, detail="Sessão OAuth inválida.") from exc
    token = _post_form(
        TOKEN_ENDPOINT,
        {
            "client_id": _required_env("GOOGLE_PICKER_CLIENT_ID"),
            "client_secret": _client_secret(),
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri(),
        },
    )
    access_token = str(token.get("access_token") or "")
    granted = set(str(token.get("scope") or "").split())
    if not access_token or DRIVE_FILE_SCOPE not in granted:
        raise HTTPException(status_code=400, detail="O Google não concedeu acesso ao Drive.")
    try:
        expires_in = max(60, min(int(token.get("expires_in") or 3600), 7200))
        about = _user_drive_service(access_token).about().get(fields="user(emailAddress)").execute()
        account_email = str((about.get("user") or {}).get("emailAddress") or "")[:320]
    except Exception as exc:  # noqa: BLE001 - normalize token/API failures
        raise HTTPException(
            status_code=502,
            detail="A conta foi autenticada, mas o Google Drive não respondeu.",
        ) from exc
    encrypted = job_crypto.encrypt_json(
        {"access_token": access_token}, aad=_token_aad(int(actor["id"]))
    )
    connected_at = _now()
    if not db.complete_google_drive_connection(
        int(actor["id"]),
        {
            "access_token_ciphertext": encrypted.ciphertext,
            "access_token_nonce": encrypted.nonce,
            "access_token_key_id": encrypted.key_id,
            "token_expires_at": connected_at + timedelta(seconds=expires_in),
            "account_email": account_email or None,
            "connected_at": connected_at,
        },
    ):
        raise HTTPException(status_code=409, detail="State OAuth já utilizado.")
    audit_service.record(
        "google_drive_connected",
        actor=actor,
        target_type="google_drive_connection",
        target_id=str(actor["id"]),
        details={"scope": "drive.file"},
    )


def cancel_oauth(actor: dict, *, state: str) -> None:
    """Consume a denied OAuth attempt so its state can never be replayed."""
    state_hash = _sha(state) if state else ""
    row = db.get_google_drive_connection_by_state(state_hash) if state_hash else None
    if not row or int(row["user_id"]) != int(actor["id"]):
        raise HTTPException(status_code=400, detail="State OAuth inválido ou reutilizado.")
    if not db.consume_google_drive_oauth_state(int(actor["id"]), state_hash):
        raise HTTPException(status_code=400, detail="State OAuth inválido ou reutilizado.")


def _active_token(actor: dict) -> tuple[dict, str]:
    row = db.get_google_drive_connection(int(actor["id"]))
    expires = _utc((row or {}).get("token_expires_at"))
    if not row or expires is None or expires <= _now() + timedelta(seconds=30):
        raise HTTPException(status_code=401, detail="Google Drive não conectado ou token expirado.")
    try:
        value = job_crypto.decrypt_json(
            row["access_token_ciphertext"],
            row["access_token_nonce"],
            str(row["access_token_key_id"]),
            aad=_token_aad(int(actor["id"])),
        )
        token = str(value["access_token"])
    except (KeyError, TypeError, job_crypto.PayloadCryptoError) as exc:
        raise HTTPException(status_code=401, detail="Conexão Google Drive inválida.") from exc
    return row, token


def connection_status(actor: dict) -> dict[str, Any]:
    if storage_config.get_storage_provider() == "local":
        return {
            "connected": True,
            "account_email": "Armazenamento local do servidor",
            "expires_at": None,
            "storage_provider": "local",
        }
    row = db.get_google_drive_connection(int(actor["id"]))
    expires = _utc((row or {}).get("token_expires_at"))
    connected = bool(expires is not None and expires > _now() + timedelta(seconds=30))
    return {
        "connected": connected,
        "account_email": row.get("account_email") if connected and row else None,
        "expires_at": expires if connected else None,
        "storage_provider": "google_drive",
    }


def picker_session(actor: dict) -> dict[str, Any]:
    row, token = _active_token(actor)
    return {
        "access_token": token,
        "api_key": _required_secret("GOOGLE_PICKER_API_KEY"),
        "app_id": (os.getenv("GOOGLE_PICKER_APP_ID") or "").strip() or None,
        "expires_at": row["token_expires_at"],
    }


def _folder_hash(folder_id: str) -> str:
    return _sha(folder_id)


def _validate_folder_id(folder_id: str) -> str:
    clean = (folder_id or "").strip()
    if not _FOLDER_ID_RE.fullmatch(clean):
        raise HTTPException(status_code=422, detail="A pasta selecionada possui ID inválido.")
    return clean


def _folder_metadata(service: Any, folder_id: str, *, require_share: bool = True) -> dict[str, Any]:
    try:
        value = (
            service.files()
            .get(
                fileId=folder_id,
                fields=("id,name,mimeType,trashed,capabilities(canAddChildren,canShare)"),
                supportsAllDrives=True,
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 - Google exceptions normalized for UI
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status in {401, 403}:
            detail = "A conta não possui permissão para acessar essa pasta."
        elif status == 404:
            detail = "A pasta selecionada não existe ou foi removida."
        elif status == 429:
            detail = "O Google Drive limitou temporariamente as solicitações. Tente novamente."
        else:
            detail = "Não foi possível validar a pasta no Google Drive."
        raise HTTPException(
            status_code=502 if status not in {401, 403, 404} else 422, detail=detail
        ) from exc
    if value.get("mimeType") != FOLDER_MIME_TYPE:
        raise HTTPException(status_code=422, detail="Selecione uma pasta, não um arquivo.")
    if value.get("trashed"):
        raise HTTPException(status_code=422, detail="A pasta selecionada está na lixeira.")
    capabilities = value.get("capabilities") or {}
    if not capabilities.get("canAddChildren"):
        raise HTTPException(status_code=422, detail="A pasta não permite adicionar certificados.")
    if require_share and not capabilities.get("canShare"):
        raise HTTPException(
            status_code=422,
            detail="A pasta não permite conceder acesso à identidade técnica.",
        )
    return value


def _technical_principals() -> list[tuple[str, str]]:
    writer = (os.getenv("GOOGLE_DRIVE_UPLOAD_PRINCIPAL_EMAIL") or "").strip()
    reader = (os.getenv("GOOGLE_DRIVE_PUBLIC_READER_EMAIL") or "").strip()
    if db_config.is_production() and (not writer or not reader):
        raise HTTPException(
            status_code=503,
            detail="Identidades técnicas do Google Drive não configuradas.",
        )
    values: dict[str, str] = {}
    if writer:
        values[writer.casefold()] = "writer"
    if reader and reader.casefold() not in values:
        values[reader.casefold()] = "reader"
    return [(email, role) for email, role in values.items()]


def _validate_technical_oauth_client() -> None:
    """Ensure the durable ``drive.file`` token belongs to the Picker app.

    A folder selected through Picker is granted to that OAuth application. A
    token issued to the same Google account by a different OAuth client still
    receives ``404`` from Drive even after the account is added as ``writer``.
    Service-account credentials are not bound to an OAuth client and therefore
    do not use this check.
    """
    if storage_config.get_storage_provider() != "google_drive":
        return
    if storage_config.get_drive_auth_mode() != "oauth_user":
        return
    try:
        token_client_id = str(storage_config.load_oauth_token_info().get("client_id") or "")
    except Exception as exc:  # noqa: BLE001 - normalize configuration failures for the UI
        raise HTTPException(
            status_code=503,
            detail="A credencial técnica do Google Drive não está disponível.",
        ) from exc
    picker_client_id = _required_env("GOOGLE_PICKER_CLIENT_ID")
    if not token_client_id or not hmac.compare_digest(token_client_id, picker_client_id):
        raise HTTPException(
            status_code=503,
            detail=(
                "A credencial técnica do Google Drive pertence a outro aplicativo OAuth. "
                "Autorize novamente a identidade de upload com o cliente OAuth atual."
            ),
        )


def _ensure_permission(service: Any, folder_id: str, email: str, role: str) -> None:
    try:
        permissions = (
            service.permissions()
            .list(
                fileId=folder_id,
                fields="permissions(id,type,emailAddress,role)",
                supportsAllDrives=True,
            )
            .execute()
            .get("permissions", [])
        )
        current = next(
            (
                value
                for value in permissions
                if value.get("type") == "user"
                and str(value.get("emailAddress") or "").casefold() == email.casefold()
            ),
            None,
        )
        if current and (
            current.get("role") == role or current.get("role") in {"owner", "organizer"}
        ):
            return
        if current:
            service.permissions().update(
                fileId=folder_id,
                permissionId=current["id"],
                body={"role": role},
                supportsAllDrives=True,
            ).execute()
        else:
            service.permissions().create(
                fileId=folder_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=False,
                supportsAllDrives=True,
            ).execute()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=422,
            detail="Não foi possível compartilhar a pasta com a identidade técnica.",
        ) from exc


def _technical_folder_metadata(folder_id: str) -> dict[str, Any]:
    if storage_config.get_storage_provider() != "google_drive":
        return {
            "mimeType": FOLDER_MIME_TYPE,
            "trashed": False,
            "capabilities": {"canAddChildren": True},
        }
    service = GoogleDriveStorage(folder_id=folder_id).service
    return _folder_metadata(service, folder_id, require_share=False)


def select_folder(actor: dict, *, folder_id: str, event: str) -> dict[str, Any]:
    clean = _validate_folder_id(folder_id)
    _row, token = _active_token(actor)
    service = _user_drive_service(token)
    metadata = _folder_metadata(service, clean)
    _validate_technical_oauth_client()
    for email, role in _technical_principals():
        _ensure_permission(service, clean, email, role)
    _technical_folder_metadata(clean)
    name = str(metadata.get("name") or "Pasta selecionada").strip()[:255]
    folder_hash = _folder_hash(clean)
    previous = db.get_google_drive_folder_grant(int(actor["id"]), folder_hash)
    db.upsert_google_drive_folder_grant(
        {
            "user_id": int(actor["id"]),
            "folder_id": clean,
            "folder_id_hash": folder_hash,
            "folder_name": name,
            "can_add_children": 1,
        }
    )
    audit_service.record(
        "google_drive_folder_changed" if previous else "google_drive_folder_selected",
        actor=actor,
        target_type="google_drive_folder",
        target_id=folder_hash[:16],
        details={"event": event or None, "folder_ref": folder_hash[:16]},
    )
    return {"folder_name": name, "ready": True}


def validate_batch_destinations(*, actor: dict, destinations: dict[str, str]) -> dict[str, str]:
    validated: dict[str, str] = {}
    for event, folder_id in destinations.items():
        clean = _validate_folder_id(folder_id)
        grant = db.get_google_drive_folder_grant(int(actor["id"]), _folder_hash(clean))
        if not grant or grant.get("folder_id") != clean or not grant.get("can_add_children"):
            raise HTTPException(
                status_code=422,
                detail="Selecione novamente uma pasta válida para todos os eventos.",
            )
        _technical_folder_metadata(clean)
        validated[event] = clean
    return validated


def disconnect(actor: dict) -> None:
    token = None
    try:
        _row, token = _active_token(actor)
    except HTTPException:
        pass
    db.clear_google_drive_connection(int(actor["id"]))
    if token:
        try:
            _post_form(REVOKE_ENDPOINT, {"token": token})
        except HTTPException:
            pass
    audit_service.record(
        "google_drive_disconnected",
        actor=actor,
        target_type="google_drive_connection",
        target_id=str(actor["id"]),
        details={"existing_certificates_unchanged": True},
    )
