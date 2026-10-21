"""Single backend authority for role and institutional permission policy."""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

from certificados_backend import auth
from fastapi import HTTPException, Request

from database import db


class Permission(StrEnum):
    DASHBOARD_READ = "dashboard.read"
    CERTIFICATES_READ = "certificates.read"
    CERTIFICATES_ISSUE = "certificates.issue"
    CERTIFICATES_DOWNLOAD = "certificates.download"
    CERTIFICATES_REVOKE = "certificates.revoke"
    CERTIFICATES_REISSUE = "certificates.reissue"
    TEMPLATES_READ = "templates.read"
    TEMPLATES_MANAGE = "templates.manage"
    USERS_MANAGE = "users.manage"
    SESSIONS_MANAGE = "sessions.manage"
    AUDIT_READ = "audit.read"
    SETTINGS_READ = "settings.read"
    SETTINGS_MANAGE = "settings.manage"


_ALL = frozenset(Permission)
_MATRIX: dict[str, frozenset[Permission]] = {
    "admin": _ALL,
    "secretaria": frozenset(
        {
            Permission.DASHBOARD_READ,
            Permission.CERTIFICATES_READ,
            Permission.CERTIFICATES_ISSUE,
            Permission.CERTIFICATES_DOWNLOAD,
            Permission.CERTIFICATES_REVOKE,
            Permission.CERTIFICATES_REISSUE,
        }
    ),
    "auditor": frozenset(
        {
            Permission.CERTIFICATES_READ,
            Permission.AUDIT_READ,
        }
    ),
}


def base_permissions_for_role(role: str | None) -> frozenset[Permission]:
    """Return the formal, configuration-independent role contract."""
    return _MATRIX.get(role or "", frozenset())


def permissions_for_role(role: str | None, settings: dict | None = None) -> frozenset[Permission]:
    """Return effective permissions, failing closed for unknown roles."""
    permissions = base_permissions_for_role(role)
    if role != "secretaria":
        return permissions
    settings = settings or db.get_institutional_settings() or {}
    if not bool(settings.get("secretaria_can_revoke", 1)):
        permissions = permissions - {Permission.CERTIFICATES_REVOKE}
    if not bool(settings.get("secretaria_can_reissue", 1)):
        permissions = permissions - {Permission.CERTIFICATES_REISSUE}
    return permissions


def permission_names(role: str | None, settings: dict | None = None) -> list[str]:
    return sorted(permission.value for permission in permissions_for_role(role, settings))


def is_allowed(user: dict, permission: Permission) -> bool:
    return permission in permissions_for_role(user.get("role"), user)


def require_permission(permission: Permission) -> Callable:
    """FastAPI dependency that always evaluates the current DB-backed policy."""

    def dependency(request: Request) -> dict:
        user = auth.get_current_admin(request)
        if not is_allowed(user, permission):
            raise HTTPException(
                status_code=403,
                detail="Seu perfil não permite realizar esta ação.",
            )
        return user

    return dependency


def matrix_contract() -> dict[str, list[str]]:
    """Machine-readable formal matrix used by tests/OpenAPI documentation."""
    return {
        role: sorted(permission.value for permission in base_permissions_for_role(role))
        for role in sorted(_MATRIX)
    }
