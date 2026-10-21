from __future__ import annotations

from certificados_backend.policies import Permission, require_permission
from certificados_backend.schemas.auth import SessionsRevokedResponse
from certificados_backend.schemas.users import (
    CreateUserRequest,
    ResetPasswordRequest,
    UpdateUserRequest,
    UserListResponse,
    UserMutationResponse,
    UserResponse,
)
from certificados_backend.services import user_service
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/admin/users", tags=["users"])
legacy_router = APIRouter(prefix="/auth/users", tags=["users"])


def _handle(call):
    try:
        return call()
    except user_service.UserServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("", response_model=UserListResponse, operation_id="list_users")
def list_users(
    current: dict = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict:
    items = _handle(lambda: user_service.list_users(current))
    return {"items": items, "total": len(items)}


@router.post(
    "",
    response_model=UserResponse,
    status_code=201,
    operation_id="create_user",
)
def create_user(
    payload: CreateUserRequest,
    current: dict = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict:
    return _handle(lambda: user_service.create_user(payload.model_dump(), actor=current))


@router.patch(
    "/{user_id}",
    response_model=UserMutationResponse,
    operation_id="update_user",
)
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    current: dict = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict:
    return _handle(
        lambda: user_service.update_user(
            user_id, payload.model_dump(exclude_unset=True), actor=current
        )
    )


@router.post(
    "/{user_id}/activate",
    response_model=UserMutationResponse,
    operation_id="activate_user",
)
def activate_user(
    user_id: int,
    current: dict = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict:
    return _handle(lambda: user_service.set_active(user_id, True, actor=current))


@router.post(
    "/{user_id}/deactivate",
    response_model=UserMutationResponse,
    operation_id="deactivate_user",
)
def deactivate_user(
    user_id: int,
    current: dict = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict:
    return _handle(lambda: user_service.set_active(user_id, False, actor=current))


@router.post(
    "/{user_id}/reset-password",
    response_model=UserMutationResponse,
    operation_id="reset_user_password",
)
def reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    current: dict = Depends(require_permission(Permission.USERS_MANAGE)),
) -> dict:
    return _handle(
        lambda: user_service.reset_password(user_id, payload.temporary_password, actor=current)
    )


def _revoke_sessions(user_id: int, current: dict) -> dict:
    revoked = _handle(lambda: user_service.revoke_sessions(user_id, actor=current))
    return {"revoked": revoked}


@router.post(
    "/{user_id}/sessions/revoke-all",
    response_model=SessionsRevokedResponse,
    operation_id="revoke_user_sessions",
)
def revoke_sessions(
    user_id: int,
    current: dict = Depends(require_permission(Permission.SESSIONS_MANAGE)),
) -> dict:
    return _revoke_sessions(user_id, current)


@legacy_router.post(
    "/{user_id}/sessions/revoke-all",
    response_model=SessionsRevokedResponse,
    deprecated=True,
    include_in_schema=False,
)
def legacy_revoke_sessions(
    user_id: int,
    current: dict = Depends(require_permission(Permission.SESSIONS_MANAGE)),
) -> dict:
    return _revoke_sessions(user_id, current)
