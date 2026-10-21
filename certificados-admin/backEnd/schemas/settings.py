from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PublicInstitutionSettings(BaseModel):
    institution_name: str
    public_url: str


class InstitutionalSettingsResponse(PublicInstitutionSettings):
    id: int = 1
    issue_location: str
    signatory_name: str
    signatory_title: str
    retention_days: int
    max_batch_rows: int
    max_upload_mb: int
    secretaria_can_revoke: bool
    secretaria_can_reissue: bool
    updated_at: datetime | None = None
    updated_by: int | None = None

    model_config = ConfigDict(from_attributes=True)


class InstitutionalSettingsUpdate(BaseModel):
    institution_name: str = Field(min_length=2, max_length=255)
    issue_location: str = Field(default="", max_length=255)
    signatory_name: str = Field(default="", max_length=255)
    signatory_title: str = Field(default="", max_length=255)
    public_url: str = Field(default="", max_length=2048)
    retention_days: int = Field(ge=0, le=36500)
    max_batch_rows: int = Field(ge=1, le=10000)
    max_upload_mb: int = Field(ge=1, le=100)
    secretaria_can_revoke: bool = True
    secretaria_can_reissue: bool = True

    @field_validator(
        "institution_name",
        "issue_location",
        "signatory_name",
        "signatory_title",
        "public_url",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()
