from __future__ import annotations

from datetime import date

from certificados_backend.policies import Permission, require_permission
from certificados_backend.schemas.audit import AuditCategoriesResponse, AuditPageResponse
from certificados_backend.services import audit_service
from fastapi import APIRouter, Depends, HTTPException, Query

router = APIRouter(prefix="/admin/audit", tags=["audit"])


@router.get("/categories", response_model=AuditCategoriesResponse)
def categories(
    _: dict = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict:
    return {
        "categories": {
            name: list(actions) for name, actions in audit_service.CATEGORY_ACTIONS.items()
        }
    }


@router.get("", response_model=AuditPageResponse, operation_id="list_audit_events")
def list_events(
    category: str | None = None,
    action: str | None = Query(default=None, max_length=64),
    actor: str | None = Query(default=None, max_length=150),
    target_type: str | None = Query(default=None, max_length=64),
    target_id: str | None = Query(default=None, max_length=200),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict:
    if category and category not in audit_service.CATEGORY_ACTIONS:
        raise HTTPException(status_code=422, detail="Categoria de auditoria inválida.")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="Período de auditoria inválido.")
    return audit_service.list_page(
        category=category,
        action=action,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
