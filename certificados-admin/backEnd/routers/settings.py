from __future__ import annotations

from certificados_backend.policies import Permission, require_permission
from certificados_backend.schemas.settings import (
    InstitutionalSettingsResponse,
    InstitutionalSettingsUpdate,
    PublicInstitutionSettings,
)
from certificados_backend.services import settings_service
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(tags=["institutional-settings"])


@router.get(
    "/institution",
    response_model=PublicInstitutionSettings,
    operation_id="get_public_institution_settings",
)
def public_settings() -> dict:
    """Non-secret presentation data used before and after sign-in."""
    return settings_service.public_projection()


@router.get(
    "/admin/settings",
    response_model=InstitutionalSettingsResponse,
    operation_id="get_institutional_settings",
)
def get_settings(
    _: dict = Depends(require_permission(Permission.SETTINGS_READ)),
) -> dict:
    return settings_service.get()


@router.put(
    "/admin/settings",
    response_model=InstitutionalSettingsResponse,
    operation_id="update_institutional_settings",
)
def update_settings(
    payload: InstitutionalSettingsUpdate,
    current: dict = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> dict:
    try:
        return settings_service.update(payload.model_dump(), actor=current)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
