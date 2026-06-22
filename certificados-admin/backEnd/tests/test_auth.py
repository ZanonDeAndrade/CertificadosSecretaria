"""Security contracts for authentication, sessions, throttling, CORS and CSRF."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient

ADMIN_USER = "secretaria"
ADMIN_PASS = "senha-super-secreta"
ALLOWED_ORIGIN = "http://localhost:5173"
TEST_SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef"


@pytest.fixture
def client(tmp_path, monkeypatch):
    import storage_service
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "certificates.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)
    monkeypatch.setenv("ADMIN_INITIAL_ROLE", "admin")
    monkeypatch.setenv("FRONTEND_ADMIN_URL", ALLOWED_ORIGIN)
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("LOGIN_BACKOFF_BASE_MS", "0")
    monkeypatch.setenv("LOGIN_BACKOFF_MAX_MS", "0")

    storage_service.reset_storage_cache()
    import main

    result = TestClient(
        main.create_app(),
        base_url="https://admin-api.test",
        headers={"Origin": ALLOWED_ORIGIN},
    )
    yield result
    storage_service.reset_storage_cache()


def _login(client: TestClient, username=ADMIN_USER, password=ADMIN_PASS) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    assert "access_token" not in response.json()
    return response.cookies["admin_token"]


def _new_client(client: TestClient) -> TestClient:
    return TestClient(
        client.app,
        base_url="https://admin-api.test",
        headers={"Origin": ALLOWED_ORIGIN},
    )


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_admin_has_no_public_validation_route(client):
    assert client.get("/validate/CERT-2026-UNKNOWN").status_code == 404


def test_login_sets_hardened_cookie_without_returning_jwt(client):
    response = client.post(
        "/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert response.status_code == 200
    assert response.json()["user"]["username"] == ADMIN_USER
    assert "access_token" not in response.json()
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


def test_invalid_and_unknown_credentials_are_generic(client):
    wrong = client.post(
        "/auth/login", json={"username": ADMIN_USER, "password": "errada"}
    )
    unknown = client.post(
        "/auth/login", json={"username": "ninguem", "password": "errada"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_audits_success_and_failure_without_password(client):
    from database import db

    password_marker = "NEVER-LOG-THIS-PASSWORD"
    client.post("/auth/login", json={"username": ADMIN_USER, "password": password_marker})
    _login(client)

    failed = db.list_audit_logs("login_failed")
    success = db.list_audit_logs("login_success")
    assert failed and success
    assert password_marker not in failed[0]["details"]
    assert "ip_hash" in failed[0]["details"]


def test_brute_force_returns_429_and_temporary_lockout(client, monkeypatch):
    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_USER", "3")
    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_IP", "100")
    monkeypatch.setenv("LOGIN_LOCKOUT_SECONDS", "60")

    statuses = [
        client.post(
            "/auth/login", json={"username": ADMIN_USER, "password": f"wrong-{index}"}
        ).status_code
        for index in range(3)
    ]
    assert statuses == [401, 401, 429]
    blocked = client.post(
        "/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


def test_combined_ip_limit_applies_across_usernames(client, monkeypatch):
    import main

    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_USER", "100")
    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_IP", "2")
    first = client.post("/auth/login", json={"username": "user-a", "password": "x"})
    # A second app instance simulates another worker sharing the same database.
    other_worker = TestClient(
        main.create_app(),
        base_url="https://admin-api.test",
        headers={"Origin": ALLOWED_ORIGIN},
    )
    second = other_worker.post(
        "/auth/login", json={"username": "user-b", "password": "x"}
    )
    assert first.status_code == 401
    assert second.status_code == 429
    assert client.post(
        "/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    ).status_code == 429


def test_failed_login_uses_progressive_async_delay(client, monkeypatch):
    import auth

    calls = []

    async def fake_sleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(auth.asyncio, "sleep", fake_sleep)
    monkeypatch.setenv("LOGIN_BACKOFF_BASE_MS", "100")
    monkeypatch.setenv("LOGIN_BACKOFF_MAX_MS", "1000")
    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_USER", "20")
    client.post("/auth/login", json={"username": ADMIN_USER, "password": "wrong-1"})
    client.post("/auth/login", json={"username": ADMIN_USER, "password": "wrong-2"})
    assert calls == [0.1, 0.2]


def test_me_accepts_cookie_and_bearer(client):
    token = _login(client)
    assert client.get("/auth/me").status_code == 200
    bearer_client = _new_client(client)
    assert bearer_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200


def test_logout_revokes_server_session_and_copied_token(client):
    token = _login(client)
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401
    assert _new_client(client).get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 401


def test_expired_server_session_is_rejected_and_cleaned(client, monkeypatch):
    import auth
    from database import db

    token = _login(client)
    session_id = auth.decode_token(token)["jti"]
    expired = datetime.now(timezone.utc) - timedelta(days=2)
    assert db.set_auth_session_expiry(session_id, expired)
    assert client.get("/auth/me").status_code == 401
    monkeypatch.setenv("AUTH_SESSION_RETENTION_DAYS", "0")
    deleted_sessions, _ = auth.cleanup_auth_state()
    assert deleted_sessions >= 1


def test_explicitly_revoked_session_is_rejected(client):
    import auth
    from database import db

    token = _login(client)
    session_id = auth.decode_token(token)["jti"]
    assert db.revoke_auth_session(session_id, "test")
    assert client.get("/auth/me").status_code == 401


def test_revoke_all_sessions_invalidates_current_cookie(client):
    _login(client)
    response = client.post("/auth/sessions/revoke-all")
    assert response.status_code == 200
    assert response.json()["revoked"] >= 1
    assert client.get("/auth/me").status_code == 401


def test_admin_can_revoke_all_sessions_for_another_user(client):
    import auth
    from database import db

    target_id = db.create_admin_user(
        "operador", auth.hash_password("operator-password"), "secretaria"
    )
    target = _new_client(client)
    _login(target, "operador", "operator-password")
    _login(client)
    response = client.post(f"/auth/users/{target_id}/sessions/revoke-all")
    assert response.status_code == 200
    assert response.json()["revoked"] >= 1
    assert target.get("/auth/me").status_code == 401


def test_inactive_user_cannot_login_or_keep_session(client):
    from database import db

    token = _login(client)
    user = db.get_admin_user_by_username(ADMIN_USER)
    assert db.set_admin_user_active(user["id"], False)
    assert _new_client(client).get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 401
    response = _new_client(client).post(
        "/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert response.status_code == 401


def test_role_authorization_denies_auditor_mutation(client):
    import auth
    from database import db

    user_id = db.create_admin_user("auditor", auth.hash_password("audit-password"), "auditor")
    assert user_id
    auditor = _new_client(client)
    _login(auditor, "auditor", "audit-password")
    response = auditor.post(
        "/templates/versions",
        json={"name": "forbidden", "layout": {}},
    )
    assert response.status_code == 403


def test_cookie_mutations_require_allowed_origin_or_referer(client):
    assert client.post(
        "/auth/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
        headers={"Origin": "https://evil.example"},
    ).status_code == 403
    assert client.post(
        "/auth/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
        headers={"Origin": "", "Referer": f"{ALLOWED_ORIGIN}/login"},
    ).status_code == 200
    assert client.post(
        "/auth/logout", headers={"Origin": "https://evil.example"}
    ).status_code == 403


def test_cors_allows_only_configured_origin(client):
    allowed = client.options(
        "/auth/login",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ALLOWED_ORIGIN

    denied = client.options(
        "/auth/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in denied.headers


def test_production_rejects_missing_or_weak_auth_configuration(monkeypatch):
    import auth

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        auth.require_production_auth_config()

    monkeypatch.setenv("JWT_SECRET", "a" * 64)
    with pytest.raises(RuntimeError):
        auth.require_production_auth_config()

    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    auth.require_production_auth_config()

    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    with pytest.raises(RuntimeError):
        auth.require_production_auth_config()


def test_application_startup_calls_fail_closed_auth_validation(monkeypatch):
    import main
    from database import config as database_config
    from storage_service import config as storage_config

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(database_config, "require_production_database", lambda: None)
    monkeypatch.setattr(storage_config, "validate_production_storage", lambda: None)
    monkeypatch.setattr(
        storage_config, "validate_production_public_validation_url", lambda: None
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        main.validate_startup_config()


def test_cors_is_fail_closed_in_production(monkeypatch):
    import main

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ADMIN_FRONTEND_URL", raising=False)
    monkeypatch.delenv("FRONTEND_ADMIN_URL", raising=False)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    with pytest.raises(RuntimeError):
        main.resolve_allowed_origins()

    monkeypatch.setenv("ADMIN_FRONTEND_URL", "http://admin.example.edu")
    with pytest.raises(RuntimeError):
        main.resolve_allowed_origins()

    monkeypatch.setenv("ADMIN_FRONTEND_URL", "https://admin.example.edu")
    assert main.resolve_allowed_origins() == ["https://admin.example.edu"]


def test_admin_route_requires_authentication(client):
    assert client.get("/certificate-file/CERT-2026-NOPE").status_code == 401
    assert client.get("/admin/certificates/CERT-2026-NOPE/metadata").status_code == 401
