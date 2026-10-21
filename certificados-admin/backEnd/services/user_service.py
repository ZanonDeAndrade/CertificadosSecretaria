"""Transactional administrative-user and password lifecycle service."""

from __future__ import annotations

import json

from certificados_backend import auth
from certificados_backend.services.audit_service import sanitize_details
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from database import db
from database.models import AdminUser
from database.repositories import (
    AdminUserRepository,
    AuditLogRepository,
    AuthSessionRepository,
)


class UserServiceError(ValueError):
    status_code = 400


class UserNotFound(UserServiceError):
    status_code = 404


class UserConflict(UserServiceError):
    status_code = 409


class UserForbidden(UserServiceError):
    status_code = 403


def _require_admin(actor: dict) -> None:
    if actor.get("role") != "admin" or not actor.get("is_active", 1):
        raise UserForbidden("Somente administradores podem gerir usuários.")


def _name(value: str) -> str:
    clean = " ".join(value.strip().split())
    if len(clean) < 2 or len(clean) > 255:
        raise UserServiceError("O nome deve ter entre 2 e 255 caracteres.")
    if any(ord(character) < 32 for character in clean):
        raise UserServiceError("O nome não pode conter caracteres de controle.")
    return clean


def _username(value: str) -> str:
    try:
        return auth.validate_username(value)
    except ValueError as exc:
        raise UserServiceError(str(exc)) from exc


def serialize(user: dict) -> dict:
    """Strict allowlist: password material never crosses the service boundary."""
    return {
        "id": int(user["id"]),
        "name": user.get("name") or user.get("username") or "",
        "username": user.get("username") or "",
        "role": user.get("role") or "",
        "is_active": bool(user.get("is_active")),
        "must_change_password": bool(user.get("must_change_password")),
        "password_changed_at": user.get("password_changed_at"),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
    }


def _audit(
    session,
    action: str,
    *,
    actor: dict,
    target_id: int,
    details: dict | None = None,
) -> None:
    clean = sanitize_details(details)
    AuditLogRepository(session).insert(
        action=action,
        actor_id=actor.get("id"),
        actor_username=actor.get("username"),
        target_type="admin_user",
        target_id=str(target_id),
        details=json.dumps(clean, ensure_ascii=False, sort_keys=True) if clean else None,
    )


def list_users(actor: dict) -> list[dict]:
    _require_admin(actor)
    return [serialize(user) for user in db.list_admin_users()]


def create_user(payload: dict, *, actor: dict) -> dict:
    _require_admin(actor)
    name = _name(payload["name"])
    username = _username(payload["username"])
    role = payload.get("role") or "secretaria"
    if role not in auth.VALID_ROLES:
        raise UserServiceError("Perfil inválido.")
    try:
        auth.validate_new_password(payload["temporary_password"], username=username)
    except ValueError as exc:
        raise UserServiceError(str(exc)) from exc
    password_hash = auth.hash_password(payload["temporary_password"])

    try:
        with db._session() as session:  # one transaction: account + audit
            repository = AdminUserRepository(session)
            user_id = repository.create(
                username,
                password_hash,
                role,
                name=name,
                must_change_password=True,
                created_by=actor["id"],
            )
            if user_id is None:
                raise UserConflict("Já existe um usuário com este login.")
            _audit(
                session,
                "user_created",
                actor=actor,
                target_id=user_id,
                details={"role": role, "is_active": True},
            )
    except IntegrityError as exc:
        raise UserConflict("Já existe um usuário com este login.") from exc
    created = db.get_admin_user_by_id(user_id)
    if not created:  # pragma: no cover - transaction contract
        raise RuntimeError("Usuário criado não pôde ser relido.")
    return serialize(created)


def _locked_target(session, user_id: int) -> AdminUser:
    target = session.execute(
        select(AdminUser).where(AdminUser.id == user_id).with_for_update()
    ).scalar_one_or_none()
    if target is None:
        raise UserNotFound("Usuário não encontrado.")
    return target


def _lock_active_admins(session) -> list[int]:
    return list(
        session.execute(
            select(AdminUser.id)
            .where(AdminUser.role == "admin", AdminUser.is_active == 1)
            .with_for_update()
        ).scalars()
    )


def update_user(user_id: int, payload: dict, *, actor: dict) -> dict:
    _require_admin(actor)
    provided = {key: value for key, value in payload.items() if value is not None}
    if not provided:
        raise UserServiceError("Nada para alterar.")
    if "name" in provided:
        provided["name"] = _name(provided["name"])
    if "username" in provided:
        provided["username"] = _username(provided["username"])
    if "role" in provided and provided["role"] not in auth.VALID_ROLES:
        raise UserServiceError("Perfil inválido.")

    sessions_revoked = 0
    try:
        with db._session() as session:
            target = _locked_target(session, user_id)
            active_admin_ids = _lock_active_admins(session)
            next_role = provided.get("role", target.role)
            next_active = bool(provided.get("is_active", bool(target.is_active)))
            if target.id == int(actor["id"]) and not next_active:
                raise UserConflict("Você não pode desativar o seu próprio acesso.")
            losing_admin = target.role == "admin" and (next_role != "admin" or not next_active)
            if losing_admin and target.id in active_admin_ids and len(active_admin_ids) == 1:
                raise UserConflict(
                    "Este é o último administrador ativo. Promova outro administrador antes."
                )
            if "username" in provided:
                duplicate = session.execute(
                    select(AdminUser.id)
                    .where(func.lower(AdminUser.username) == provided["username"].lower())
                    .where(AdminUser.id != target.id)
                    .limit(1)
                ).scalar_one_or_none()
                if duplicate is not None:
                    raise UserConflict("Já existe um usuário com este login.")

            changes: dict[str, dict] = {}
            for field in ("name", "username", "role"):
                if field in provided and getattr(target, field) != provided[field]:
                    # Audit field names and role transitions, but not real names/logins.
                    changes[field] = (
                        {"from": target.role, "to": provided[field]}
                        if field == "role"
                        else {"status": "changed"}
                    )
                    setattr(target, field, provided[field])
            if "is_active" in provided and bool(target.is_active) != next_active:
                changes["is_active"] = {
                    "from": bool(target.is_active),
                    "to": next_active,
                }
                target.is_active = 1 if next_active else 0

            if not changes:
                raise UserServiceError("Nada para alterar.")
            from database.models import utcnow

            target.updated_at = utcnow()
            if any(field in changes for field in ("username", "role", "is_active")):
                sessions_revoked = AuthSessionRepository(session).revoke_all(
                    target.id,
                    "user_access_changed",
                )
            if set(changes) == {"is_active"}:
                action = "user_activated" if next_active else "user_deactivated"
            else:
                action = "user_updated"
            _audit(
                session,
                action,
                actor=actor,
                target_id=target.id,
                details={"fields": sorted(changes), **changes},
            )
    except IntegrityError as exc:
        raise UserConflict("Já existe um usuário com este login.") from exc

    updated = db.get_admin_user_by_id(user_id)
    if not updated:  # pragma: no cover
        raise UserNotFound("Usuário não encontrado.")
    return {"user": serialize(updated), "sessions_revoked": sessions_revoked}


def set_active(user_id: int, active: bool, *, actor: dict) -> dict:
    return update_user(user_id, {"is_active": active}, actor=actor)


def reset_password(user_id: int, temporary_password: str, *, actor: dict) -> dict:
    _require_admin(actor)
    with db._session() as session:
        target = _locked_target(session, user_id)
        if target.id == int(actor["id"]):
            raise UserConflict(
                "Para alterar sua própria senha, informe a senha atual em Meu perfil."
            )
        try:
            auth.validate_new_password(temporary_password, username=target.username)
        except ValueError as exc:
            raise UserServiceError(str(exc)) from exc
        target.password_hash = auth.hash_password(temporary_password)
        target.must_change_password = 1
        from database.models import utcnow

        target.password_changed_at = utcnow()
        target.updated_at = utcnow()
        revoked = AuthSessionRepository(session).revoke_all(target.id, "password_reset")
        _audit(
            session,
            "user_password_reset",
            actor=actor,
            target_id=target.id,
            details={"session_count": revoked},
        )
    updated = db.get_admin_user_by_id(user_id)
    return {"user": serialize(updated or {"id": user_id}), "sessions_revoked": revoked}


def change_own_password(
    *,
    current: dict,
    current_password: str,
    new_password: str,
) -> int:
    with db._session() as session:
        target = _locked_target(session, int(current["id"]))
        if not auth.verify_password(current_password, target.password_hash):
            raise UserServiceError("A senha atual está incorreta.")
        if auth.verify_password(new_password, target.password_hash):
            raise UserServiceError("A nova senha deve ser diferente da senha atual.")
        try:
            auth.validate_new_password(new_password, username=target.username)
        except ValueError as exc:
            raise UserServiceError(str(exc)) from exc
        target.password_hash = auth.hash_password(new_password)
        target.must_change_password = 0
        from database.models import utcnow

        target.password_changed_at = utcnow()
        target.updated_at = utcnow()
        revoked = AuthSessionRepository(session).revoke_all(
            target.id,
            "password_changed",
            exclude_session_id=current.get("session_id"),
        )
        _audit(
            session,
            "password_changed",
            actor=current,
            target_id=target.id,
            details={"session_count": revoked},
        )
    return revoked


def revoke_sessions(user_id: int, *, actor: dict) -> int:
    _require_admin(actor)
    with db._session() as session:
        target = _locked_target(session, user_id)
        revoked = AuthSessionRepository(session).revoke_all(target.id, "admin_revoke_all")
        _audit(
            session,
            "user_sessions_revoked",
            actor=actor,
            target_id=target.id,
            details={"session_count": revoked},
        )
    return revoked
