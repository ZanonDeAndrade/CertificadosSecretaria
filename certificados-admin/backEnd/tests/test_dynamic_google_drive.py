"""Per-event Google Drive destinations: security, durability and worker contracts."""

from __future__ import annotations

import hashlib
import io
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest
from certificados_backend.services import drive_integration
from fastapi import HTTPException

from database import db
from storage_service import StorageError
from storage_service import config as storage_config
from storage_service.base import CertificateStorage, StoredFile, sha256_hex, utc_now_iso

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BODY = "participou da atividade, com {{carga_horaria}} horas."
FOLDER_MIME = "application/vnd.google-apps.folder"


class _Execute:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.value


class FakeDriveService:
    def __init__(
        self,
        *,
        mime_type: str = FOLDER_MIME,
        can_add: bool = True,
        can_share: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.mime_type = mime_type
        self.can_add = can_add
        self.can_share = can_share
        self.error = error
        self.permissions_created: list[dict] = []

    def about(self):
        return self

    def get(self, **kwargs):
        if "fields" in kwargs and str(kwargs["fields"]).startswith("user("):
            return _Execute({"user": {"emailAddress": "secretaria@instituicao.example"}})
        return _Execute(
            {
                "id": kwargs.get("fileId"),
                "name": "Pasta oficial 2026",
                "mimeType": self.mime_type,
                "trashed": False,
                "capabilities": {
                    "canAddChildren": self.can_add,
                    "canShare": self.can_share,
                },
            },
            self.error,
        )

    def files(self):
        return self

    def permissions(self):
        return _FakePermissions(self)


class _FakePermissions:
    def __init__(self, owner: FakeDriveService) -> None:
        self.owner = owner

    def list(self, **_kwargs):
        return _Execute({"permissions": []})

    def create(self, **kwargs):
        self.owner.permissions_created.append(kwargs["body"])
        return _Execute({"id": "permission-created"})

    def update(self, **_kwargs):
        return _Execute({})


class FakeGenerator:
    def render_pdf_bytes_default(self, *_args, **_kwargs):
        return b"%PDF-1.4\ndynamic-folder\n%%EOF"

    def render_pdf_bytes_visual(self, *_args, **_kwargs):
        return b"%PDF-1.4\ndynamic-folder\n%%EOF"


@pytest.fixture
def google_drive_profile(client, monkeypatch):
    monkeypatch.setenv("STORAGE_PROVIDER", "google_drive")
    monkeypatch.setattr(
        drive_integration,
        "_technical_folder_metadata",
        lambda _folder_id: {
            "mimeType": FOLDER_MIME,
            "trashed": False,
            "capabilities": {"canAddChildren": True},
        },
    )


class FolderRecordingStorage(CertificateStorage):
    provider = "google_drive"

    def __init__(self, *, folder_id: str = "unused-global", shared=None) -> None:
        self.folder_id = folder_id
        self.shared = shared or {"attempted": [], "saved": [], "deleted": [], "fail_next": False}

    def for_folder(self, folder_id: str):
        return FolderRecordingStorage(folder_id=folder_id, shared=self.shared)

    def save(self, content, *, filename, mime_type="application/pdf") -> StoredFile:
        self.shared["attempted"].append(self.folder_id)
        if self.shared["fail_next"]:
            self.shared["fail_next"] = False
            raise StorageError("falha sintética de upload")
        file_id = f"file-{len(self.shared['saved']) + 1:04d}"
        self.shared["saved"].append((self.folder_id, file_id, content))
        return StoredFile(
            storage_provider="google_drive",
            original_filename=filename,
            mime_type=mime_type,
            file_size=len(content),
            checksum_sha256=sha256_hex(content),
            created_at=utc_now_iso(),
            drive_file_id=file_id,
            drive_folder_id=self.folder_id,
            pdf_path="",
        )

    def download(self, cert_row):
        file_id = cert_row["drive_file_id"]
        return next(value for _folder, current, value in self.shared["saved"] if current == file_id)

    def delete(self, cert_row):
        self.shared["deleted"].append((self.folder_id, cert_row.get("drive_file_id")))


def _oauth_environment(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_PICKER_CLIENT_ID", "picker-client.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_PICKER_CLIENT_SECRET", "synthetic-client-secret")
    monkeypatch.setenv("GOOGLE_PICKER_API_KEY", "synthetic-picker-key")
    monkeypatch.setenv(
        "GOOGLE_DRIVE_OAUTH_REDIRECT_URI",
        "https://admin-api.test/integrations/google-drive/oauth/callback",
    )
    monkeypatch.setenv("ADMIN_FRONTEND_URL", "http://localhost:5173")
    monkeypatch.setenv("GOOGLE_DRIVE_UPLOAD_PRINCIPAL_EMAIL", "worker@example.test")
    monkeypatch.setenv("GOOGLE_DRIVE_PUBLIC_READER_EMAIL", "reader@example.test")


def _begin_and_complete_oauth(client, monkeypatch, service: FakeDriveService | None = None):
    _oauth_environment(monkeypatch)
    service = service or FakeDriveService()
    monkeypatch.setattr(drive_integration, "_user_drive_service", lambda _token: service)
    monkeypatch.setattr(
        drive_integration,
        "_post_form",
        lambda _url, _values: {
            "access_token": "synthetic-short-lived-token",
            "scope": drive_integration.DRIVE_FILE_SCOPE,
            "expires_in": 3600,
        },
    )
    started = client.post("/integrations/google-drive/oauth/start")
    assert started.status_code == 200, started.text
    query = parse_qs(urlsplit(started.json()["authorization_url"]).query)
    state = query["state"][0]
    callback = client.get(
        "/integrations/google-drive/oauth/callback",
        params={"state": state, "code": "synthetic-authorization-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 303, callback.text
    return state, service


def _xlsx(rows: list[dict]) -> bytes:
    output = io.BytesIO()
    pd.DataFrame(rows).to_excel(output, index=False)
    return output.getvalue()


def _grant(client, event_to_folder: dict[str, str]) -> None:
    user_id = int(client.get("/auth/me").json()["id"])
    for event, folder_id in event_to_folder.items():
        db.upsert_google_drive_folder_grant(
            {
                "user_id": user_id,
                "folder_id": folder_id,
                "folder_id_hash": hashlib.sha256(folder_id.encode()).hexdigest(),
                "folder_name": event or "Sem evento",
                "can_add_children": 1,
            }
        )


def _start_batch(client, rows: list[dict], destinations: dict[str, str], key: str):
    return client.post(
        "/emission-batches",
        files={"file": ("lote.xlsx", _xlsx(rows), XLSX_MIME)},
        data={
            "texto_padrao": BODY,
            "certificate_type": "listener",
            "drive_folders_json": json.dumps(destinations),
        },
        headers={"Idempotency-Key": key},
    )


def _install_recording_storage(client) -> FolderRecordingStorage:
    storage = FolderRecordingStorage()
    service = client.app.state.certificate_service
    service._storage = storage
    service.generator = FakeGenerator()
    return storage


def test_oauth_state_callback_is_one_time_and_picker_token_is_not_cached(
    client, auth_headers, monkeypatch
):
    state, _service = _begin_and_complete_oauth(client, monkeypatch)
    status = client.get("/integrations/google-drive/status")
    assert status.json()["connected"] is True
    assert status.json()["storage_provider"] == "local"
    assert status.json()["account_email"] == "Armazenamento local do servidor"

    picker = client.get("/integrations/google-drive/picker-session")
    assert picker.status_code == 200
    assert picker.json()["access_token"] == "synthetic-short-lived-token"
    assert "no-store" in picker.headers["cache-control"]

    replay = client.get(
        "/integrations/google-drive/oauth/callback",
        params={"state": state, "code": "replayed-code"},
        follow_redirects=False,
    )
    assert replay.status_code == 400
    assert "reutilizado" in replay.json()["detail"]


def test_picker_api_key_can_be_loaded_from_secret_file(client, auth_headers, monkeypatch, tmp_path):
    _begin_and_complete_oauth(client, monkeypatch)
    api_key_file = tmp_path / "picker-api-key"
    api_key_file.write_text("synthetic-picker-key-from-file", encoding="utf-8")
    monkeypatch.delenv("GOOGLE_PICKER_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_PICKER_API_KEY_FILE", str(api_key_file))

    picker = client.get("/integrations/google-drive/picker-session")

    assert picker.status_code == 200
    assert picker.json()["api_key"] == "synthetic-picker-key-from-file"


def test_technical_drive_file_token_must_use_the_picker_oauth_client(monkeypatch):
    _oauth_environment(monkeypatch)
    monkeypatch.setenv("STORAGE_PROVIDER", "google_drive")
    monkeypatch.setenv("GOOGLE_DRIVE_AUTH_MODE", "oauth_user")
    monkeypatch.setattr(
        storage_config,
        "load_oauth_token_info",
        lambda: {"client_id": "legacy-client.apps.googleusercontent.com"},
    )

    with pytest.raises(HTTPException, match="outro aplicativo OAuth") as exc_info:
        drive_integration._validate_technical_oauth_client()

    assert exc_info.value.status_code == 503


def test_invalid_oauth_state_is_rejected_before_token_exchange(client, auth_headers, monkeypatch):
    _oauth_environment(monkeypatch)
    called = {"token": False}

    def exchange(*_args):
        called["token"] = True
        return {}

    monkeypatch.setattr(drive_integration, "_post_form", exchange)
    response = client.get(
        "/integrations/google-drive/oauth/callback",
        params={"state": "forged-state", "code": "forged-code"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert called["token"] is False


def test_folder_selection_validates_type_capabilities_shares_and_persists_grant(
    client, auth_headers, monkeypatch
):
    _state, service = _begin_and_complete_oauth(client, monkeypatch)
    response = client.post(
        "/integrations/google-drive/folders/select",
        json={"folder_id": "folder-picker-0001", "event": "Semana Acadêmica"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"folder_name": "Pasta oficial 2026", "ready": True}
    assert {value["role"] for value in service.permissions_created} == {"writer", "reader"}
    grant = db.get_google_drive_folder_grant(
        int(client.get("/auth/me").json()["id"]),
        hashlib.sha256(b"folder-picker-0001").hexdigest(),
    )
    assert grant and grant["folder_id"] == "folder-picker-0001"


def test_folder_selection_rejects_file_missing_permission_and_revoked_token(
    client, auth_headers, monkeypatch
):
    _begin_and_complete_oauth(client, monkeypatch, FakeDriveService(mime_type="application/pdf"))
    selected_file = client.post(
        "/integrations/google-drive/folders/select",
        json={"folder_id": "folder-picker-0002", "event": "Evento"},
    )
    assert selected_file.status_code == 422
    assert "pasta" in selected_file.json()["detail"].lower()

    monkeypatch.setattr(
        drive_integration,
        "_user_drive_service",
        lambda _token: FakeDriveService(can_add=False),
    )
    denied = client.post(
        "/integrations/google-drive/folders/select",
        json={"folder_id": "folder-picker-0003", "event": "Evento"},
    )
    assert denied.status_code == 422
    assert "adicionar" in denied.json()["detail"].lower()

    revoked = RuntimeError("revoked")
    revoked.resp = SimpleNamespace(status=401)
    monkeypatch.setattr(
        drive_integration,
        "_user_drive_service",
        lambda _token: FakeDriveService(error=revoked),
    )
    expired = client.post(
        "/integrations/google-drive/folders/select",
        json={"folder_id": "folder-picker-0004", "event": "Evento"},
    )
    assert expired.status_code == 422
    assert "permissão" in expired.json()["detail"].lower()


def test_folder_selection_rejects_malformed_folder_id_before_calling_google(
    client, auth_headers, monkeypatch
):
    _begin_and_complete_oauth(client, monkeypatch)
    called = {"google": False}

    def service(_token):
        called["google"] = True
        return FakeDriveService()

    monkeypatch.setattr(drive_integration, "_user_drive_service", service)
    response = client.post(
        "/integrations/google-drive/folders/select",
        json={"folder_id": "../id inválido", "event": "Evento"},
    )
    assert response.status_code == 422
    assert "id inválido" in response.json()["detail"].lower()
    assert called["google"] is False


def test_only_issuer_roles_can_configure_drive(client, auth_headers):
    created = client.post(
        "/admin/users",
        json={
            "name": "Auditora Sintética",
            "username": "auditora.drive",
            "role": "auditor",
            "temporary_password": "Auditoria-Sintetica-2026!",
        },
    )
    assert created.status_code == 201
    assert client.post("/auth/logout").status_code == 200
    assert (
        client.post(
            "/auth/login",
            json={"username": "auditora.drive", "password": "Auditoria-Sintetica-2026!"},
        ).status_code
        == 200
    )
    assert client.get("/integrations/google-drive/status").status_code == 403
    assert client.post("/integrations/google-drive/oauth/start").status_code == 403


def test_single_and_multiple_event_batches_store_each_pdf_in_its_frozen_folder(
    client, auth_headers, google_drive_profile
):
    storage = _install_recording_storage(client)
    destinations = {
        "Semana": "folder-event-semana",
        "Workshop": "folder-event-workshop",
        "": "folder-event-empty",
    }
    _grant(client, destinations)
    rows = [
        {"nome": "Ana", "carga_horaria": 8, "evento": "Semana"},
        {"nome": "Bia", "carga_horaria": 4, "evento": "Workshop"},
        {"nome": "Caio", "carga_horaria": 2, "evento": ""},
    ]
    response = _start_batch(client, rows, destinations, "dynamic-events-key-0001")
    assert response.status_code == 202, response.text
    finished = client.get(f"/emission-batches/{response.json()['id']}")
    assert finished.json()["status"] == "completed"
    assert storage.shared["attempted"] == [
        "folder-event-semana",
        "folder-event-workshop",
        "folder-event-empty",
    ]
    certificates, total = db.list_certificates(limit=10)
    assert total == 3
    assert {row["event_name"]: row["drive_folder_id"] for row in certificates} == {
        "Semana": "folder-event-semana",
        "Workshop": "folder-event-workshop",
        "": "folder-event-empty",
    }


def test_batch_without_every_event_destination_is_blocked(client, auth_headers, google_drive_profile):
    rows = [
        {"nome": "Ana", "carga_horaria": 8, "evento": "Semana"},
        {"nome": "Bia", "carga_horaria": 4, "evento": "Workshop"},
    ]
    destinations = {"Semana": "folder-only-semana"}
    _grant(client, destinations)
    response = _start_batch(client, rows, destinations, "missing-folder-key-0001")
    assert response.status_code == 422
    assert "todos os eventos" in response.json()["detail"]


def test_retry_and_reissue_keep_the_original_folder(client, auth_headers, google_drive_profile):
    storage = _install_recording_storage(client)
    storage.shared["fail_next"] = True
    destinations = {"Evento 2026": "folder-original-2026"}
    _grant(client, destinations)
    response = _start_batch(
        client,
        [{"nome": "Ana", "carga_horaria": 8, "evento": "Evento 2026"}],
        destinations,
        "retry-folder-key-0001",
    )
    assert response.status_code == 202, response.text
    batch_id = response.json()["id"]
    assert response.json()["certificate_type"] == "listener"
    assert client.get(f"/emission-batches/{batch_id}").json()["status"] == "failed"
    retried = client.post(f"/emission-batches/{batch_id}/retry")
    assert retried.status_code == 200, retried.text
    assert client.get(f"/emission-batches/{batch_id}").json()["status"] == "completed"
    assert storage.shared["attempted"] == ["folder-original-2026", "folder-original-2026"]

    certificate = db.list_certificates(status="ativo", limit=10)[0][0]
    assert certificate["certificate_type"] == "listener"
    storage.shared["attempted"].clear()
    client.app.state.certificate_service.reissue_certificate(certificate)
    assert storage.shared["attempted"] == ["folder-original-2026"]
    assert db.get_by_code(certificate["unique_code"])["drive_folder_id"] == "folder-original-2026"
    assert db.get_by_code(certificate["unique_code"])["certificate_type"] == "listener"


def test_disconnect_removes_only_temporary_connection_and_grants(
    client, auth_headers, monkeypatch, google_drive_profile
):
    _begin_and_complete_oauth(client, monkeypatch)
    selected = client.post(
        "/integrations/google-drive/folders/select",
        json={"folder_id": "folder-picker-0005", "event": "Evento"},
    )
    assert selected.status_code == 200
    disconnected = client.post("/integrations/google-drive/disconnect")
    assert disconnected.status_code == 200
    assert disconnected.json()["existing_certificates_unchanged"] is True
    assert client.get("/integrations/google-drive/status").json()["connected"] is False
    assert client.get("/integrations/google-drive/picker-session").status_code == 401
