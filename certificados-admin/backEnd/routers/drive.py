from __future__ import annotations

from certificados_backend.policies import Permission, require_permission
from certificados_backend.schemas.drive import (
    DriveConnectionStatus,
    DriveDisconnectResponse,
    DriveFolderSelectionRequest,
    DriveFolderSelectionResponse,
    DriveOAuthStartResponse,
    DrivePickerSessionResponse,
)
from certificados_backend.services import drive_integration
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/integrations/google-drive", tags=["google-drive"])


@router.get("/status", response_model=DriveConnectionStatus)
def status(
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    return drive_integration.connection_status(current)


@router.post("/oauth/start", response_model=DriveOAuthStartResponse)
def oauth_start(
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    return drive_integration.begin_oauth(current)


@router.get("/oauth/callback", include_in_schema=False)
def oauth_callback(
    state: str = Query(default="", max_length=512),
    code: str = Query(default="", max_length=4096),
    error: str = Query(default="", max_length=128),
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> RedirectResponse:
    if error:
        drive_integration.cancel_oauth(current, state=state)
        return RedirectResponse(
            drive_integration.frontend_return_url(connected=False),
            status_code=303,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
    drive_integration.complete_oauth(current, state=state, code=code)
    return RedirectResponse(
        drive_integration.frontend_return_url(connected=True),
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get("/picker-session", response_model=DrivePickerSessionResponse)
def picker_session(
    response: Response,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    return drive_integration.picker_session(current)


@router.post("/folders/select", response_model=DriveFolderSelectionResponse)
def select_folder(
    values: DriveFolderSelectionRequest,
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    return drive_integration.select_folder(
        current,
        folder_id=values.folder_id,
        event=values.event.strip(),
    )


@router.post("/disconnect", response_model=DriveDisconnectResponse)
def disconnect(
    current: dict = Depends(require_permission(Permission.CERTIFICATES_ISSUE)),
) -> dict:
    drive_integration.disconnect(current)
    return {"disconnected": True, "existing_certificates_unchanged": True}
