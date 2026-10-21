"""Privacy-minimised, queryable audit trail service."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from typing import Any

from database import db

CATEGORY_ACTIONS: dict[str, tuple[str, ...]] = {
    "login": ("login_success", "login_failed", "login_blocked", "logout"),
    "emission": ("batch_created", "emission_completed", "generate", "generation_failed"),
    "duplicate": ("certificate_duplicate",),
    "revocation": ("certificate_revoked", "revoke"),
    "reissue": ("certificate_reissued", "reissue", "reissue_failed"),
    "download": ("certificate_downloaded", "certificates_downloaded", "download_zip"),
    "template": (
        "template_version_created",
        "template_version_activated",
        "template_version_renamed",
        "template_version_deleted",
        "template_version_create",
        "template_version_activate",
    ),
    "users": (
        "user_created",
        "user_updated",
        "user_activated",
        "user_deactivated",
        "user_password_reset",
        "password_changed",
        "user_sessions_revoked",
        "sessions_revoke_all",
        "admin_user_update",
    ),
    "integrity": (
        "integrity_incident",
        "reconcile_active_without_file",
        "reconcile_compensation_error",
    ),
    "settings": ("institutional_settings_updated",),
    "google_drive": (
        "google_drive_connected",
        "google_drive_folder_selected",
        "google_drive_folder_changed",
        "google_drive_disconnected",
    ),
}

# Only operational metadata may become visible in the audit API. Values such as
# password/token/document/e-mail/certificate body are deliberately impossible
# to persist through this service.
_SAFE_KEYS = frozenset(
    {
        "reason",
        "count",
        "revoked",
        "generated",
        "duplicates",
        "invalid",
        "failed",
        "total_rows",
        "processed",
        "status",
        "from",
        "to",
        "role",
        "is_active",
        "fields",
        "batch_id",
        "version_id",
        "version_number",
        "session_count",
        "integrity_status",
        "request_id",
        "failures",
        "scope",
        "event",
        "folder_ref",
        "destination_count",
        "existing_certificates_unchanged",
    }
)
_FORBIDDEN_FRAGMENTS = (
    "password",
    "senha",
    "token",
    "secret",
    "document",
    "cpf",
    "email",
    "certificate_text",
    "content",
)


def _clean_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 2:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (list, tuple)):
        return [_clean_value(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, dict):
        return {
            str(key): _clean_value(item, depth=depth + 1)
            for key, item in list(value.items())[:30]
            if str(key) in _SAFE_KEYS
            and not any(fragment in str(key).casefold() for fragment in _FORBIDDEN_FRAGMENTS)
        }
    return str(value)[:500]


def sanitize_details(details: dict[str, Any] | None) -> dict[str, Any] | None:
    if not details:
        return None
    cleaned = {
        key: _clean_value(value)
        for key, value in details.items()
        if key in _SAFE_KEYS
        and not any(fragment in key.casefold() for fragment in _FORBIDDEN_FRAGMENTS)
    }
    return cleaned or None


def record(
    action: str,
    *,
    actor: dict | None = None,
    actor_id: int | None = None,
    actor_username: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    clean = sanitize_details(details)
    db.insert_audit_log(
        action=action[:64],
        actor_id=actor.get("id") if actor else actor_id,
        actor_username=(actor.get("username") if actor else actor_username),
        target_type=(target_type or "")[:64] or None,
        target_id=str(target_id)[:500] if target_id is not None else None,
        details=json.dumps(clean, ensure_ascii=False, sort_keys=True) if clean else None,
    )


def parse_details(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return sanitize_details(parsed if isinstance(parsed, dict) else None)


def serialize(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "action": entry.get("action"),
        "actor_id": entry.get("actor_id"),
        "actor_username": entry.get("actor_username"),
        "target_type": entry.get("target_type"),
        "target_id": entry.get("target_id"),
        "details": parse_details(entry.get("details")),
        "created_at": entry.get("created_at"),
    }


def _day_start(value: date | None) -> datetime | None:
    return datetime.combine(value, time.min, tzinfo=timezone.utc) if value else None


def _day_end(value: date | None) -> datetime | None:
    return datetime.combine(value, time.max, tzinfo=timezone.utc) if value else None


def list_page(
    *,
    category: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    actions = CATEGORY_ACTIONS.get(category or "")
    rows, total = db.list_audit_logs_page(
        action=action,
        actions=actions,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        date_from=_day_start(date_from),
        date_to=_day_end(date_to),
        limit=limit,
        offset=offset,
    )
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "limit": max(1, min(int(limit), 200)),
        "offset": max(0, int(offset)),
    }
