"""Authentication for the secretaria (admin) area.

- Passwords are hashed with **bcrypt**.
- Sessions use a signed **JWT** delivered via an HttpOnly cookie (the dependency
  also accepts an ``Authorization: Bearer`` header for API clients/tests).
- The initial admin user can be seeded from ``ADMIN_USERNAME`` /
  ``ADMIN_PASSWORD`` env vars, or created with ``create_admin.py``.

Secrets come exclusively from environment variables.
"""
from __future__ import annotations

import logging
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make the shared `database` package importable regardless of CWD.
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


def _jwt_secret() -> str:
    secret = (os.getenv("JWT_SECRET") or "").strip()
    if secret:
        return secret
    # Dev fallback: a per-process random secret. Tokens won't survive a restart.
    global _EPHEMERAL_SECRET
    try:
        return _EPHEMERAL_SECRET
    except NameError:
        _EPHEMERAL_SECRET = secrets.token_urlsafe(48)
        LOGGER.warning(
            "JWT_SECRET não definido — usando segredo efêmero (defina JWT_SECRET em produção)."
        )
        return _EPHEMERAL_SECRET


def _env(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def token_ttl_minutes() -> int:
    raw = _env("JWT_EXPIRES_IN_MINUTES", "JWT_TTL_MINUTES")  # new name, legacy alias
    try:
        return max(5, int(raw))
    except ValueError:
        return 480  # 8 hours


def cookie_secure() -> bool:
    """Whether the auth cookie should be marked Secure (HTTPS-only).

    Explicit ``AUTH_COOKIE_SECURE`` wins; otherwise defaults to secure when
    ``APP_ENV`` indicates production.
    """
    explicit = (os.getenv("AUTH_COOKIE_SECURE") or "").strip().lower()
    if explicit:
        return explicit in ("1", "true", "yes")
    return (os.getenv("APP_ENV") or "").strip().lower() in ("prod", "production")


# ── Password hashing ──────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────


def create_access_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user.get("role", "secretaria"),
        "iat": now,
        "exp": now + timedelta(minutes=token_ttl_minutes()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ── FastAPI dependency ─────────────────────────────────────────────────────────


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token
    authz = request.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        return authz[len("Bearer ") :].strip() or None
    return None


async def get_current_admin(request: Request) -> dict:
    """Dependency that returns the authenticated admin user or raises 401."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
    try:
        user = db.get_admin_user_by_id(int(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Sessão inválida.")
    if not user or not user.get("is_active", 1):
        raise HTTPException(status_code=401, detail="Usuário inativo ou inexistente.")
    return user


# ── Seeding ─────────────────────────────────────────────────────────────────────


def authenticate(username: str, password: str) -> dict | None:
    """Return the user dict on valid credentials, else None."""
    user = db.get_admin_user_by_username(username.strip())
    if not user or not user.get("is_active", 1):
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def seed_admin_from_env() -> None:
    """Create the initial admin from ADMIN_INITIAL_USERNAME/PASSWORD if missing.

    Legacy aliases ADMIN_USERNAME/ADMIN_PASSWORD are still accepted.
    """
    username = _env("ADMIN_INITIAL_USERNAME", "ADMIN_USERNAME")
    password = os.getenv("ADMIN_INITIAL_PASSWORD") or os.getenv("ADMIN_PASSWORD") or ""
    if not username or not password:
        return
    if db.get_admin_user_by_username(username):
        return
    db.create_admin_user(username, hash_password(password))
    LOGGER.info("Usuário admin inicial criado a partir do ambiente: %s", username)
