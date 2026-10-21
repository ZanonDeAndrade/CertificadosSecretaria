from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PreviewRowResponse(BaseModel):
    row_number: int
    nome: str
    curso: str
    evento: str
    carga_horaria: int | None
    data_emissao: str
    data_inicio: str
    data_fim: str
    autores: list[str] = Field(default_factory=list)
    equipe: str = ""
    titulo_trabalho: str = ""


class InvalidRowResponse(BaseModel):
    row_number: int
    errors: list[str]
    data: dict[str, Any] | None = None


class EventGroupResponse(BaseModel):
    key: str
    label: str
    count: int


class LayoutWarningRowResponse(BaseModel):
    row_number: int
    nome: str


class LayoutWarningResponse(BaseModel):
    """A sized text box of the active template that some participants overflow."""

    key: str
    label: str
    height: int
    row_count: int
    rows: list[LayoutWarningRowResponse]
    applies_to_all: bool = False
    checked_rows: int
    truncated: bool = False


class MissingSettingResponse(BaseModel):
    """An empty institutional setting that the active template prints."""

    setting: str
    label: str
    keys: list[str]


class EmptyFieldResponse(BaseModel):
    """A template field that is blank for some rows (the certificate omits it)."""

    key: str
    label: str
    row_count: int
    rows: list[LayoutWarningRowResponse]
    checked_rows: int
    truncated: bool = False


class BodyVariableResponse(BaseModel):
    """A variable the certificate body text accepts, as ``{{name}}``."""

    name: str
    token: str
    label: str


class BodyVariablesResponse(BaseModel):
    variables: list[BodyVariableResponse]


class SpreadsheetPreviewResponse(BaseModel):
    total: int
    valid_count: int
    invalid_count: int
    valid: list[PreviewRowResponse]
    invalid: list[InvalidRowResponse]
    events: list[EventGroupResponse]
    resolved_text_preview: str | None = None
    #: File-level notes, such as author columns beyond the supported eight.
    warnings: list[str] = Field(default_factory=list)
    layout_warnings: list[LayoutWarningResponse] = Field(default_factory=list)
    #: Blocks confirmation: the fix is in the institutional settings.
    missing_settings: list[MissingSettingResponse] = Field(default_factory=list)
    missing_settings_message: str | None = None
    #: Warns only: those rows print without the field.
    empty_fields: list[EmptyFieldResponse] = Field(default_factory=list)
    can_manage_settings: bool = False


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
