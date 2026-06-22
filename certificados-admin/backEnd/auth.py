"""Hardened authentication for the secretaria/admin area.

JWTs are delivered in a Secure/HttpOnly cookie, but they are not stateless:
each token carries a ``jti`` backed by ``auth_sessions``. Login throttling is
also persisted in the shared SQL database, so both controls work across
workers and deployments without process-local state.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import secrets
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

import bcrypt
import jwt
from fastapi import HTTPException, Request

from database import db  # noqa: E402

LOGGER = logging.getLogger("certificados.auth")

COOKIE_NAME = "admin_token"
JWT_ALGORITHM = "HS256"
MIN_JWT_SECRET_BYTES = 32
MIN_ESTIMATED_SECRET_ENTROPY_BITS = 128.0
VALID_ROLES = frozenset({"admin", "secretaria", "auditor"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _env(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def _is_production() -> bool:
    return (os.getenv("APP_ENV") or "").strip().lower() in ("prod", "production")


def is_production() -> bool:
    return _is_production()


def _int_env(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int((os.getenv(name) or str(default)).strip()))
    except ValueError:
        return default


def _estimated_entropy_bits(material: bytes) -> float:
    if not material:
        return 0.0
    counts = Counter(material)
    length = len(material)
    per_byte = -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )
    return per_byte * length


def validate_jwt_secret(secret: str) -> None:
    """Reject short and obviously low-entropy secrets.

    Actual entropy cannot be proven from a value after generation, so startup
    enforces at least 32 UTF-8 bytes plus a conservative diversity estimate.
    Production documentation requires generating 32 random bytes or more.
    """
    material = secret.encode("utf-8")
    if len(material) < MIN_JWT_SECRET_BYTES:
        raise RuntimeError("JWT_SECRET deve conter pelo menos 32 bytes.")
    if _estimated_entropy_bits(material) < MIN_ESTIMATED_SECRET_ENTROPY_BITS:
        raise RuntimeError(
            "JWT_SECRET possui baixa entropia aparente; gere pelo menos 32 bytes aleatórios."
        )


def _jwt_secret() -> str:
    secret = (os.getenv("JWT_SECRET") or "").strip()
    if secret:
        if _is_production():
            validate_jwt_secret(secret)
        return secret
    if _is_production():
        raise RuntimeError("APP_ENV=production exige JWT_SECRET forte.")
    global _EPHEMERAL_SECRET
    try:
        return _EPHEMERAL_SECRET
    except NameError:
        _EPHEMERAL_SECRET = secrets.token_urlsafe(48)
        LOGGER.warning("JWT_SECRET não definido; usando segredo efêmero apenas em desenvolvimento.")
        return _EPHEMERAL_SECRET


def cookie_secure() -> bool:
    explicit = (os.getenv("AUTH_COOKIE_SECURE") or "").strip().lower()
    if explicit:
        return explicit in ("1", "true", "yes")
    return _is_production()


def cookie_samesite() -> str:
    value = (os.getenv("AUTH_COOKIE_SAMESITE") or "lax").strip().lower()
    if value not in {"lax", "strict", "none"}:
        raise RuntimeError("AUTH_COOKIE_SAMESITE deve ser lax, strict ou none.")
    if value == "none" and not cookie_secure():
        raise RuntimeError("SameSite=None exige AUTH_COOKIE_SECURE=true.")
    return value


def require_production_secret() -> None:
    """Backward-compatible entry point for startup validation."""
    if not _is_production():
        return
    secret = (os.getenv("JWT_SECRET") or "").strip()
    if not secret:
        raise RuntimeError("APP_ENV=production exige JWT_SECRET definido.")
    validate_jwt_secret(secret)


def require_production_auth_config() -> None:
    if not _is_production():
        cookie_samesite()  # validate explicit dev/test configuration too
        return
    require_production_secret()
    if not cookie_secure():
        raise RuntimeError("Em produção, AUTH_COOKIE_SECURE não pode ser desativado.")
    cookie_samesite()


def token_ttl_minutes() -> int:
    raw = _env("JWT_EXPIRES_IN_MINUTES", "JWT_TTL_MINUTES")
    try:
        return max(1, int(raw))
    except ValueError:
        return 480


def session_retention_days() -> int:
    return _int_env("AUTH_SESSION_RETENTION_DAYS", 30, minimum=0)


def login_window_seconds() -> int:
    return _int_env("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 900, minimum=1)


def login_ip_threshold() -> int:
    return _int_env("LOGIN_MAX_FAILURES_PER_IP", 20, minimum=1)


def login_user_threshold() -> int:
    return _int_env("LOGIN_MAX_FAILURES_PER_USER", 8, minimum=1)


def login_lockout_seconds() -> int:
    return _int_env("LOGIN_LOCKOUT_SECONDS", 900, minimum=1)


def login_backoff_base_ms() -> int:
    return _int_env("LOGIN_BACKOFF_BASE_MS", 250, minimum=0)


def login_backoff_max_ms() -> int:
    return _int_env("LOGIN_BACKOFF_MAX_MS", 4000, minimum=0)


# ── Password hashing ─────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# Created once per process only to equalize unknown-user password checks.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(24))


def _authenticate_with_reason(username: str, password: str) -> tuple[dict | None, str]:
    user = db.get_admin_user_by_username(username.strip())
    password_hash = user["password_hash"] if user else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(password, password_hash)
    if not user or not password_ok:
        return None, "invalid_credentials"
    if not user.get("is_active", 1):
        return None, "inactive_user"
    if (user.get("role") or "") not in VALID_ROLES:
        return None, "invalid_role"
    return user, "success"


def authenticate(username: str, password: str) -> dict | None:
    """Compatibility helper; HTTP login uses the throttled async flow below."""
    return _authenticate_with_reason(username, password)[0]


# ── Persistent throttling + login audit ─────────────────────────────────────


class LoginRejected(Exception):
    def __init__(self, status_code: int, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


def _hash_identifier(kind: str, value: str) -> str:
    normalized = value.strip().casefold()
    return hashlib.sha256(f"{kind}:{normalized}".encode("utf-8")).hexdigest()


def _request_ip(request: Request) -> str:
    # Deliberately ignore spoofable forwarding headers. The reverse proxy must
    # pass the real peer address through the ASGI server's trusted-proxy config.
    return request.client.host if request.client else "unknown"


def _request_fingerprint(request: Request) -> tuple[str, str]:
    return (
        _hash_identifier("ip", _request_ip(request)),
        _hash_identifier("ua", request.headers.get("user-agent", "unknown")),
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _audit_login(
    action: str,
    *,
    username: str,
    ip_hash: str,
    reason: str,
    actor_id: int | None = None,
    session_id: str | None = None,
    failures: int | None = None,
) -> None:
    details = {"reason": reason, "ip_hash": ip_hash}
    if session_id:
        details["session_id"] = session_id
    if failures is not None:
        details["failures"] = failures
    db.insert_audit_log(
        action=action,
        actor_id=actor_id,
        actor_username=username.strip()[:150] or None,
        target_type="admin_user",
        target_id=str(actor_id) if actor_id is not None else None,
        details=json.dumps(details, sort_keys=True),
    )


async def login_with_throttling(
    username: str, password: str, request: Request
) -> tuple[dict, str]:
    now = datetime.now(timezone.utc)
    ip_hash, user_agent_hash = _request_fingerprint(request)
    user_hash = _hash_identifier("user", username)
    scope_keys = [("ip", ip_hash), ("user", user_hash)]

    rows = db.get_login_throttles(scope_keys)
    blocked = [
        _as_utc(row["blocked_until"])
        for row in rows
        if row.get("blocked_until") and _as_utc(row["blocked_until"]) > now
    ]
    if blocked:
        retry_after = max(1, math.ceil((max(blocked) - now).total_seconds()))
        _audit_login(
            "login_blocked",
            username=username,
            ip_hash=ip_hash,
            reason="temporary_lockout",
        )
        raise LoginRejected(429, "Muitas tentativas. Tente novamente mais tarde.", retry_after)

    user, reason = _authenticate_with_reason(username, password)
    if not user:
        states = db.record_login_failures(
            [
                ("ip", ip_hash, login_ip_threshold()),
                ("user", user_hash, login_user_threshold()),
            ],
            now=now,
            window_seconds=login_window_seconds(),
            lockout_seconds=login_lockout_seconds(),
        )
        failures = max(int(state["failures"]) for state in states)
        delay_ms = min(
            login_backoff_max_ms(),
            login_backoff_base_ms() * (2 ** max(0, min(failures - 1, 10))),
        )
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        newly_blocked = [state["blocked_until"] for state in states if state["blocked_until"]]
        _audit_login(
            "login_failed",
            username=username,
            ip_hash=ip_hash,
            reason=reason,
            failures=failures,
        )
        if newly_blocked:
            retry_after = max(
                1, math.ceil((max(newly_blocked) - now).total_seconds())
            )
            raise LoginRejected(
                429, "Muitas tentativas. Tente novamente mais tarde.", retry_after
            )
        raise LoginRejected(401, "Usuário ou senha inválidos.")

    # A valid login clears only this username's state. IP state remains so one
    # known credential cannot reset brute-force attempts against other users.
    db.clear_login_throttle("user", user_hash)
    token, session_id = create_session_token(
        user, ip_hash=ip_hash, user_agent_hash=user_agent_hash
    )
    _audit_login(
        "login_success",
        username=user["username"],
        ip_hash=ip_hash,
        reason="success",
        actor_id=user["id"],
        session_id=session_id,
    )
    # Successful logins are low-volume and provide a safe periodic cleanup
    # trigger in addition to startup cleanup (no process-local scheduler/state).
    cleanup_auth_state()
    return user, token


# ── JWT + revocable server-side session ─────────────────────────────────────


def create_session_token(
    user: dict, *, ip_hash: str | None = None, user_agent_hash: str | None = None
) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=token_ttl_minutes())
    session_id = secrets.token_urlsafe(32)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "jti": session_id,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    db.create_auth_session(
        session_id=session_id,
        user_id=int(user["id"]),
        expires_at=expires_at,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    return token, session_id


def create_access_token(user: dict) -> str:
    """Compatibility helper that still creates a persisted, revocable session."""
    return create_session_token(user)[0]


def decode_token(token: str, *, verify_exp: bool = True) -> dict | None:
    try:
        return jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            options={"verify_exp": verify_exp},
        )
    except jwt.PyJWTError:
        return None


def _extract_token(request: Request) -> tuple[str | None, str | None]:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token, "cookie"
    authz = request.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        return authz[len("Bearer ") :].strip() or None, "bearer"
    return None, None


async def get_current_admin(request: Request) -> dict:
    token, source = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
    try:
        user_id = int(payload["sub"])
        session_id = str(payload["jti"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Sessão inválida.")
    session = db.get_active_auth_session(session_id, datetime.now(timezone.utc))
    if not session or int(session["user_id"]) != user_id:
        raise HTTPException(status_code=401, detail="Sessão revogada ou expirada.")
    user = db.get_admin_user_by_id(user_id)
    if not user or not user.get("is_active", 1):
        raise HTTPException(status_code=401, detail="Usuário inativo ou inexistente.")
    if (user.get("role") or "") not in VALID_ROLES:
        raise HTTPException(status_code=403, detail="Papel de usuário não autorizado.")
    current = dict(user)
    current["session_id"] = session_id
    current["auth_source"] = source
    return current


def require_roles(*allowed_roles: str) -> Callable:
    allowed = frozenset(allowed_roles)
    if not allowed or not allowed.issubset(VALID_ROLES):
        raise ValueError("Conjunto de papéis inválido.")

    async def dependency(request: Request) -> dict:
        user = await get_current_admin(request)
        if user.get("role") not in allowed:
            raise HTTPException(status_code=403, detail="Permissão insuficiente.")
        return user

    return dependency


def revoke_request_session(request: Request, reason: str = "logout") -> bool:
    token, _source = _extract_token(request)
    if not token:
        return False
    payload = decode_token(token, verify_exp=False)
    if not payload or not payload.get("jti"):
        return False
    revoked = db.revoke_auth_session(str(payload["jti"]), reason)
    if revoked:
        db.insert_audit_log(
            action="logout",
            actor_id=int(payload["sub"]) if str(payload.get("sub", "")).isdigit() else None,
            actor_username=str(payload.get("username") or "")[:150] or None,
            target_type="auth_session",
            target_id=str(payload["jti"]),
            details=json.dumps({"reason": reason}),
        )
    return revoked


def cleanup_auth_state() -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    session_cutoff = now - timedelta(days=session_retention_days())
    throttle_cutoff = now - timedelta(seconds=login_window_seconds() * 2)
    return (
        db.cleanup_auth_sessions(session_cutoff),
        db.cleanup_login_throttles(throttle_cutoff),
    )


# ── Origin/Referer validation for cookie-authenticated mutations ─────────────


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    except ValueError:
        return None


def validate_mutating_request_origin(request: Request, allowed_origins: list[str]) -> None:
    if request.method.upper() in SAFE_METHODS:
        return
    has_cookie = bool(request.cookies.get(COOKIE_NAME))
    # Login creates the cookie, so it is protected even before one exists.
    if request.url.path != "/auth/login" and not has_cookie:
        return
    supplied = request.headers.get("Origin")
    if not supplied:
        supplied = request.headers.get("Referer")
    supplied_origin = _origin(supplied or "")
    normalized_allowed = {_origin(value) for value in allowed_origins}
    if not supplied_origin or supplied_origin not in normalized_allowed:
        raise HTTPException(status_code=403, detail="Origem da requisição não autorizada.")


# ── Initial user seed ────────────────────────────────────────────────────────


def seed_admin_from_env() -> None:
    username = _env("ADMIN_INITIAL_USERNAME", "ADMIN_USERNAME")
    password = os.getenv("ADMIN_INITIAL_PASSWORD") or os.getenv("ADMIN_PASSWORD") or ""
    role = _env("ADMIN_INITIAL_ROLE", "ADMIN_ROLE") or "admin"
    if not username or not password:
        return
    if role not in VALID_ROLES:
        raise RuntimeError(f"ADMIN_INITIAL_ROLE inválido: {role}.")
    if db.get_admin_user_by_username(username):
        return
    db.create_admin_user(username, hash_password(password), role)
    LOGGER.info("Usuário administrativo inicial criado a partir do ambiente: %s", username)
