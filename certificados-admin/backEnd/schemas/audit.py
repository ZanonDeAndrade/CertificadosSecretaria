from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    id: int
    action: str
    actor_id: int | None = None
    actor_username: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime | None = None


class AuditPageResponse(BaseModel):
    items: list[AuditEntryResponse]
    total: int
    limit: int
    offset: int


class AuditCategoriesResponse(BaseModel):
    categories: dict[str, list[str]]
