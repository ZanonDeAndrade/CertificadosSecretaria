"""Typed institutional configuration, with environment-compatible defaults."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from certificados_backend import auth
from certificados_backend.services import audit_service
from sqlalchemy.exc import IntegrityError

from database import db


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(float((os.getenv(name) or str(default)).strip()))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def environment_defaults() -> dict:
    return {
        "institution_name": (os.getenv("INSTITUTION_NAME") or "Instituição de ensino").strip(),
        "issue_location": (os.getenv("ISSUE_LOCATION") or "").strip(),
        "signatory_name": (os.getenv("SIGNATORY_NAME") or "").strip(),
        "signatory_title": (os.getenv("SIGNATORY_TITLE") or "").strip(),
        "public_url": (os.getenv("PUBLIC_VALIDATION_BASE_URL") or "").strip().rstrip("/"),
        "retention_days": _int_env("PRIVATE_DATA_RETENTION_DAYS", 0, minimum=0, maximum=36500),
        "max_batch_rows": _int_env("MAX_SPREADSHEET_ROWS", 2000, minimum=1, maximum=10000),
        "max_upload_mb": _int_env("MAX_SPREADSHEET_SIZE_MB", 10, minimum=1, maximum=100),
        "secretaria_can_revoke": 1,
        "secretaria_can_reissue": 1,
    }


def ensure_settings() -> dict:
    current = db.get_institutional_settings()
    if current:
        return current
    try:
        return db.create_institutional_settings(environment_defaults())
    except IntegrityError:
        # Another worker won the singleton insert race.
        current = db.get_institutional_settings()
        if current:
            return current
        raise


def serialize(settings: dict) -> dict:
    return {
        "id": 1,
        "institution_name": settings.get("institution_name") or "Instituição de ensino",
        "issue_location": settings.get("issue_location") or "",
        "signatory_name": settings.get("signatory_name") or "",
        "signatory_title": settings.get("signatory_title") or "",
        "public_url": settings.get("public_url") or "",
        "retention_days": int(settings.get("retention_days") or 0),
        "max_batch_rows": int(settings.get("max_batch_rows") or 2000),
        "max_upload_mb": int(settings.get("max_upload_mb") or 10),
        "secretaria_can_revoke": bool(settings.get("secretaria_can_revoke", 1)),
        "secretaria_can_reissue": bool(settings.get("secretaria_can_reissue", 1)),
        "updated_at": settings.get("updated_at"),
        "updated_by": settings.get("updated_by"),
    }


def get() -> dict:
    return serialize(ensure_settings())


def public_projection() -> dict:
    settings = get()
    return {
        "institution_name": settings["institution_name"],
        "public_url": settings["public_url"],
    }


def validate_public_url(value: str) -> str:
    clean = value.strip().rstrip("/")
    if not clean:
        return ""
    try:
        parsed = urlsplit(clean)
        parsed.port
    except ValueError as exc:
        raise ValueError("URL pública inválida.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("URL pública inválida.")
    if auth.is_production() and parsed.scheme != "https":
        raise ValueError("A URL pública deve usar HTTPS em produção.")
    return clean


def validate_runtime_settings(settings: dict | None = None) -> None:
    """Fail closed on the business configuration required to issue QR codes."""
    current = settings or get()
    public_url = validate_public_url(str(current.get("public_url") or ""))
    if auth.is_production() and not public_url:
        raise RuntimeError("A configuração institucional exige uma URL pública HTTPS.")


def update(values: dict, *, actor: dict) -> dict:
    current = get()
    clean = dict(values)
    clean["public_url"] = validate_public_url(str(clean.get("public_url") or ""))
    clean["secretaria_can_revoke"] = 1 if clean["secretaria_can_revoke"] else 0
    clean["secretaria_can_reissue"] = 1 if clean["secretaria_can_reissue"] else 0
    changed_fields = sorted(
        key
        for key, value in clean.items()
        if current.get(key) != (bool(value) if key.startswith("secretaria_can_") else value)
    )
    if not changed_fields:
        return current
    updated = db.update_institutional_settings(clean, actor_id=actor["id"])
    if not updated:
        raise RuntimeError("Configuração institucional não encontrada.")
    audit_service.record(
        "institutional_settings_updated",
        actor=actor,
        target_type="institutional_settings",
        target_id=1,
        details={"fields": changed_fields},
    )
    return serialize(updated)


def certificate_snapshot() -> dict:
    settings = get()
    return {
        "institution_name": settings["institution_name"],
        "issue_location": settings["issue_location"],
        "signatory_name": settings["signatory_name"],
        "signatory_title": settings["signatory_title"],
        "public_url": settings["public_url"],
    }
