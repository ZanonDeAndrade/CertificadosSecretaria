"""OAuth-user credential tests for the Google Drive backend."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _path in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from storage_service import config  # noqa: E402
from storage_service.base import StorageConfigError  # noqa: E402
from storage_service.google_drive import GoogleDriveStorage  # noqa: E402


def _token_info() -> dict:
    return {
        "token": "access-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id.apps.googleusercontent.com",
        "client_secret": "client-secret",
        "scopes": ["https://www.googleapis.com/auth/drive.file"],
    }


def test_oauth_token_loads_from_file(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps(_token_info()), encoding="utf-8")
    monkeypatch.delenv("GOOGLE_OAUTH_TOKEN_JSON_BASE64", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", str(token_file))

    assert config.load_oauth_token_info()["refresh_token"] == "refresh-token"


def test_oauth_token_loads_from_base64(monkeypatch):
    encoded = base64.b64encode(json.dumps(_token_info()).encode()).decode()
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_JSON_BASE64", encoded)
    monkeypatch.delenv("GOOGLE_OAUTH_TOKEN_FILE", raising=False)

    assert config.load_oauth_token_info()["client_id"].endswith("googleusercontent.com")


def test_oauth_token_rejects_missing_refresh_token(monkeypatch, tmp_path):
    info = _token_info()
    info.pop("refresh_token")
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps(info), encoding="utf-8")
    monkeypatch.delenv("GOOGLE_OAUTH_TOKEN_JSON_BASE64", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", str(token_file))

    with pytest.raises(StorageConfigError, match="refresh_token"):
        config.load_oauth_token_info()


def test_production_validation_accepts_oauth_user(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps(_token_info()), encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("STORAGE_PROVIDER", "google_drive")
    monkeypatch.setenv("GOOGLE_DRIVE_AUTH_MODE", "oauth_user")
    monkeypatch.setenv("GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID", "folder-id")
    monkeypatch.delenv("GOOGLE_OAUTH_TOKEN_JSON_BASE64", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", str(token_file))

    config.validate_production_storage()


def test_drive_client_selects_oauth_credentials(monkeypatch):
    marker_credentials = object()
    marker_service = object()
    monkeypatch.setenv("GOOGLE_DRIVE_AUTH_MODE", "oauth_user")
    monkeypatch.setattr(
        GoogleDriveStorage,
        "_build_oauth_credentials",
        staticmethod(lambda: marker_credentials),
    )

    import googleapiclient.discovery

    def fake_build(api, version, *, credentials, cache_discovery):
        assert (api, version) == ("drive", "v3")
        assert credentials is marker_credentials
        assert cache_discovery is False
        return marker_service

    monkeypatch.setattr(googleapiclient.discovery, "build", fake_build)
    storage = GoogleDriveStorage(folder_id="folder-id")

    assert storage.service is marker_service
