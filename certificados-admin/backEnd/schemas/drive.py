from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DriveConnectionStatus(BaseModel):
    connected: bool
    account_email: str | None = None
    expires_at: datetime | None = None
    storage_provider: str = "google_drive"


class DriveOAuthStartResponse(BaseModel):
    authorization_url: str


class DrivePickerSessionResponse(BaseModel):
    access_token: str
    api_key: str
    app_id: str | None = None
    expires_at: datetime


class DriveFolderSelectionRequest(BaseModel):
    folder_id: str = Field(min_length=10, max_length=255)
    event: str = Field(default="", max_length=255)


class DriveFolderSelectionResponse(BaseModel):
    folder_name: str
    ready: bool


class DriveDisconnectResponse(BaseModel):
    disconnected: bool
    existing_certificates_unchanged: bool
