from __future__ import annotations

from certificados_backend import auth
from certificados_backend.policies import permission_names
from certificados_backend.schemas.auth import (
    AuthUserResponse,
    ChangeOwnPasswordRequest,
    LoginRequest,
    LoginResponse,
    PasswordChangedResponse,
    SessionsRevokedResponse,
)
from certificados_backend.services import audit_service, user_service
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from database import db

router = APIRouter(prefix="/auth", tags=["authentication"])


def _user_response(user: dict) -> dict:
    return {
        "id": int(user["id"]),
        "name": user.get("name") or user.get("username") or "",
        "username": user.get("username") or "",
        "role": user.get("role") or "",
        "permissions": permission_names(user.get("role"), user),
        "must_change_password": bool(user.get("must_change_password")),
    }


def _delete_cookie(response: JSONResponse) -> None:
    response.delete_cookie(
        key=auth.COOKIE_NAME,
        path="/",
        secure=auth.cookie_secure(),
        httponly=True,
        samesite=auth.cookie_samesite(),
    )


@router.post("/login", response_model=LoginResponse, operation_id="login")
async def login(request: Request, payload: LoginRequest) -> JSONResponse:
    try:
        user, token = await auth.login_with_throttling(payload.username, payload.password, request)
    except auth.LoginRejected as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )
    response = JSONResponse(content={"user": _user_response(user)})
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=token,
        httponly=True,
        secure=auth.cookie_secure(),
        samesite=auth.cookie_samesite(),
        max_age=auth.token_ttl_minutes() * 60,
        path="/",
    )
    return response


@router.post("/logout", operation_id="logout")
async def logout(request: Request) -> JSONResponse:
    auth.revoke_request_session(request, reason="logout")
    response = JSONResponse(content={"ok": True})
    _delete_cookie(response)
    return response


@router.get("/me", response_model=AuthUserResponse, operation_id="get_current_user")
async def whoami(
    current: dict = Depends(auth.get_current_session_user),
) -> dict:
    return _user_response(current)


@router.post(
    "/change-password",
    response_model=PasswordChangedResponse,
    operation_id="change_own_password",
)
async def change_password(
    payload: ChangeOwnPasswordRequest,
    current: dict = Depends(auth.get_current_session_user),
) -> dict:
    try:
        revoked = user_service.change_own_password(
            current=current,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except user_service.UserServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok": True, "sessions_revoked": revoked}


@router.post(
    "/sessions/revoke-all",
    response_model=SessionsRevokedResponse,
    operation_id="revoke_own_sessions",
)
async def revoke_own_sessions(
    current: dict = Depends(auth.get_current_session_user),
) -> JSONResponse:
    count = db.revoke_all_auth_sessions(current["id"], "self_revoke_all")
    audit_service.record(
        "user_sessions_revoked",
        actor=current,
        target_type="admin_user",
        target_id=current["id"],
        details={"session_count": count},
    )
    response = JSONResponse(content={"revoked": count})
    _delete_cookie(response)
    return response
