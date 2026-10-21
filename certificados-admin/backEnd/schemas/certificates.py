from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field


class ResponsibleUser(BaseModel):
    id: int
    name: str | None = None
    username: str | None = None


class CertificateResponse(BaseModel):
    unique_code: str
    participant_name: str
    course_name: str | None = None
    event_name: str | None = None
    certificate_type: str | None = None
    certificate_type_label: str
    workload_hours: int | None = None
    # Per-work certificates: every author (the first is participant_name).
    authors: list[str] = []
    team_name: str | None = None
    work_title: str | None = None
    issue_date: str | None = None
    issue_date_iso: str | None = None
    status: str
    download_available: bool
    integrity_status: str
    integrity_blocked: bool
    storage_provider: str | None = None
    template_used: str | None = None
    template_version_id: int | None = None
    issued_by: ResponsibleUser | None = None
    batch_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Detail-only fields. Auditor projections deliberately return null for
    # participant contact/body fields.
    participant_email: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    file_size: int | None = None
    certificate_text: str | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    reissue_count: int = 0
    reissued_at: datetime | None = None
    reissued_by: ResponsibleUser | None = None


class CertificatePageResponse(BaseModel):
    items: list[CertificateResponse]
    total: int
    limit: int
    offset: int


class RevokeCertificateRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class DownloadCertificatesRequest(BaseModel):
    codes: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        min_length=1, max_length=200
    )
