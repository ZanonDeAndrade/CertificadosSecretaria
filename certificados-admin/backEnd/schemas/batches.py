from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class PreviewRowResponse(BaseModel):
    row_number: int
    nome: str
    curso: str
    evento: str
    carga_horaria: int
    data_emissao: str
    data_inicio: str
    data_fim: str


class InvalidRowResponse(BaseModel):
    row_number: int
    errors: list[str]
    data: dict[str, Any] | None = None


class EventGroupResponse(BaseModel):
    key: str
    label: str
    count: int


class SpreadsheetPreviewResponse(BaseModel):
    total: int
    valid_count: int
    invalid_count: int
    valid: list[PreviewRowResponse]
    invalid: list[InvalidRowResponse]
    events: list[EventGroupResponse]
    resolved_text_preview: str | None = None


class EmissionBatchResponse(BaseModel):
    id: str
    status: Literal["queued", "processing", "completed", "partial", "failed", "cancelled"]
    total_rows: int
    valid_count: int
    invalid_count: int
    processed_count: int
    generated_count: int
    duplicate_count: int
    failed_count: int
    certificate_type: str | None = None
    certificate_type_label: str
    progress_percent: int
    attempt_count: int = 0
    max_attempts: int = 3
    result: dict[str, Any] | None = None
    invalid_report: list[InvalidRowResponse]
    error_message: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None


class EmissionBatchPageResponse(BaseModel):
    items: list[EmissionBatchResponse]
    total: int
    limit: int
    offset: int
