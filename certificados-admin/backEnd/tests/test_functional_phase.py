"""Product-phase contracts: users, formal RBAC, audit, settings and batches."""

from __future__ import annotations

import hashlib
import io
import json

import pandas as pd
from certificados_backend.policies import Permission, matrix_contract

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BODY = "participou da atividade, com {{carga_horaria}} horas."
ADMIN_PASSWORD = "Senha-Sintetica-1!"


def _xlsx(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return buffer.getvalue()


def _files(rows: list[dict]) -> dict:
    return {"file": ("lote.xlsx", _xlsx(rows), XLSX_MIME)}


def _batch_data(client, *events: str) -> dict[str, str]:
    """Create the already-validated Picker grants required by the batch contract."""
    from database import db

    actor_id = int(client.get("/auth/me").json()["id"])
    destinations: dict[str, str] = {}
    for index, event in enumerate(events, start=1):
        folder_id = f"folder-functional-{index:04d}"
        db.upsert_google_drive_folder_grant(
            {
                "user_id": actor_id,
                "folder_id": folder_id,
                "folder_id_hash": hashlib.sha256(folder_id.encode()).hexdigest(),
                "folder_name": f"Pasta funcional {index}",
                "can_add_children": 1,
            }
        )
        destinations[event] = folder_id
    return {
        "texto_padrao": BODY,
        "certificate_type": "listener",
        "drive_folders_json": json.dumps(destinations),
    }


def _login(client, username: str, password: str):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def _create_user(client, *, username="operador", role="secretaria", password=None):
    temporary = password or "Temporaria-Forte-2026!"
    response = client.post(
        "/admin/users",
        json={
            "name": "Operador de Teste",
            "username": username,
            "role": role,
            "temporary_password": temporary,
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), temporary


def test_formal_permission_matrix_is_fail_closed_and_exact(monkeypatch):
    from certificados_backend.policies import permissions_for_role

    contract = matrix_contract()
    assert set(contract["admin"]) == {permission.value for permission in Permission}
    assert set(contract["secretaria"]) == {
        "dashboard.read",
        "certificates.read",
        "certificates.issue",
        "certificates.download",
        "certificates.revoke",
        "certificates.reissue",
    }
    assert set(contract["auditor"]) == {"certificates.read", "audit.read"}
    assert permissions_for_role("root") == frozenset()
    assert permissions_for_role(None) == frozenset()


def test_user_lifecycle_never_returns_password_material(client, auth_headers):
    created, temporary = _create_user(client)
    assert created["must_change_password"] is True
    assert created["role"] == "secretaria"
    assert "password_hash" not in json.dumps(created).lower()
    assert temporary not in json.dumps(created)

    listing = client.get("/admin/users")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    serialized = json.dumps(listing.json()).lower()
    assert "password_hash" not in serialized
    assert temporary.lower() not in serialized

    changed = client.patch(
        f"/admin/users/{created['id']}",
        json={"name": "Novo Nome", "username": "novo.login", "role": "auditor"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["user"]["name"] == "Novo Nome"
    assert changed.json()["user"]["username"] == "novo.login"
    assert changed.json()["user"]["role"] == "auditor"
    assert "hash" not in json.dumps(changed.json()).lower()

    inactive = client.post(f"/admin/users/{created['id']}/deactivate")
    assert inactive.status_code == 200
    assert inactive.json()["user"]["is_active"] is False
    active = client.post(f"/admin/users/{created['id']}/activate")
    assert active.status_code == 200
    assert active.json()["user"]["is_active"] is True

    reset = client.post(
        f"/admin/users/{created['id']}/reset-password",
        json={"temporary_password": "Outra-Temporaria-2026!"},
    )
    assert reset.status_code == 200
    assert reset.json()["user"]["must_change_password"] is True
    assert "Outra-Temporaria-2026!" not in reset.text
    revoked = client.post(f"/admin/users/{created['id']}/sessions/revoke-all")
    assert revoked.status_code == 200
    assert isinstance(revoked.json()["revoked"], int)


def test_temporary_password_blocks_business_until_secure_self_change(client, auth_headers):
    created, temporary = _create_user(client, username="primeiro.acesso")
    user = _login(client, "primeiro.acesso", temporary)
    assert user["must_change_password"] is True
    denied = client.get("/certificates")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "password_change_required"

    wrong = client.post(
        "/auth/change-password",
        json={
            "current_password": "Senha-Atual-Incorreta!",
            "new_password": "Permanente-Forte-2026!",
        },
    )
    assert wrong.status_code == 400
    assert client.get("/auth/me").json()["must_change_password"] is True

    changed = client.post(
        "/auth/change-password",
        json={"current_password": temporary, "new_password": "Permanente-Forte-2026!"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["ok"] is True
    assert client.get("/auth/me").json()["must_change_password"] is False
    assert client.get("/certificates").status_code == 200


def test_self_deactivation_and_last_admin_removal_are_refused(client, auth_headers):
    me = client.get("/auth/me").json()
    self_deactivate = client.post(f"/admin/users/{me['id']}/deactivate")
    assert self_deactivate.status_code == 409
    assert "próprio" in self_deactivate.json()["detail"].lower()

    self_reset = client.post(
        f"/admin/users/{me['id']}/reset-password",
        json={"temporary_password": "Nao-Contorna-Senha-Atual-2026!"},
    )
    assert self_reset.status_code == 409
    assert "senha atual" in self_reset.json()["detail"].lower()

    last_admin = client.patch(f"/admin/users/{me['id']}", json={"role": "secretaria"})
    assert last_admin.status_code == 409
    assert "último administrador" in last_admin.json()["detail"].lower()


def test_non_admin_cannot_elevate_privilege_or_manage_users(client, auth_headers):
    _, temporary = _create_user(client, username="sem.privilegio")
    _login(client, "sem.privilegio", temporary)
    # Complete first-login flow so the denial is RBAC, not password state.
    assert (
        client.post(
            "/auth/change-password",
            json={"current_password": temporary, "new_password": "Permanente-Segura-2026!"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/admin/users",
            json={
                "name": "Admin Indevido",
                "username": "indevido",
                "role": "admin",
                "temporary_password": "Temporaria-Indevida-2026!",
            },
        ).status_code
        == 403
    )


def test_auditor_is_read_only_and_secretaria_has_operational_matrix(client, auth_headers):
    _, auditor_password = _create_user(
        client, username="auditor.teste", role="auditor", password="Auditoria-Forte-2026!"
    )
    _login(client, "auditor.teste", auditor_password)
    client.post(
        "/auth/change-password",
        json={"current_password": auditor_password, "new_password": "Auditoria-Permanente-2026!"},
    )
    me = client.get("/auth/me").json()
    assert set(me["permissions"]) == {"audit.read", "certificates.read"}
    assert client.get("/certificates").status_code == 200
    assert client.get("/admin/audit").status_code == 200
    assert client.get("/admin/stats").status_code == 403
    assert (
        client.post(
            "/emission-batches",
            headers={"Idempotency-Key": "auditor-cannot-issue-certificates"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/certificates/CERT-NAO-EXISTE/revoke", json={"reason": "sem autorização"}
        ).status_code
        == 403
    )
    assert (
        client.post("/certificates/download-zip", json={"codes": ["CERT-NAO-EXISTE"]}).status_code
        == 403
    )
    assert client.get("/templates/versions").status_code == 403
    assert client.get("/admin/users").status_code == 403


def test_institutional_policy_dynamically_removes_secretaria_actions(client, auth_headers):
    update = client.put(
        "/admin/settings",
        json={
            "institution_name": "Instituição Teste",
            "issue_location": "Cidade Teste",
            "signatory_name": "Assinante Teste",
            "signatory_title": "Cargo Teste",
            "public_url": "https://certificados.example.test",
            "retention_days": 365,
            "max_batch_rows": 100,
            "max_upload_mb": 5,
            "secretaria_can_revoke": False,
            "secretaria_can_reissue": False,
        },
    )
    assert update.status_code == 200, update.text
    assert "password_hash" not in json.dumps(update.json()).lower()
    public = client.get("/institution").json()
    assert public == {
        "institution_name": "Instituição Teste",
        "public_url": "https://certificados.example.test",
    }

    _, temporary = _create_user(client, username="secretaria.regra")
    _login(client, "secretaria.regra", temporary)
    client.post(
        "/auth/change-password",
        json={"current_password": temporary, "new_password": "Secretaria-Permanente-2026!"},
    )
    permissions = set(client.get("/auth/me").json()["permissions"])
    assert "certificates.issue" in permissions
    assert "certificates.download" in permissions
    assert "certificates.revoke" not in permissions
    assert "certificates.reissue" not in permissions
    assert (
        client.post(
            "/certificates/qualquer/revoke", json={"reason": "regra institucional"}
        ).status_code
        == 403
    )


def test_idempotent_batch_persists_progress_result_and_history_link(client, auth_headers):
    row = {
        "nome": "Pessoa do Lote",
        "curso": "Direito",
        "evento": "Evento de Produto",
        "carga_horaria": 8,
        "data_emissao": "10/06/2026",
    }
    key = "functional-batch-key-0001"
    first = client.post(
        "/emission-batches",
        files=_files([row]),
        data=_batch_data(client, "Evento de Produto"),
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 202, first.text
    batch_id = first.json()["id"]
    finished = client.get(f"/emission-batches/{batch_id}")
    assert finished.status_code == 200
    payload = finished.json()
    assert payload["status"] == "completed"
    assert payload["progress_percent"] == 100
    assert payload["processed_count"] == payload["valid_count"] == 1
    assert payload["result"]["batch_id"] == batch_id
    assert payload["generated_count"] == 1

    repeated = client.post(
        "/emission-batches",
        files=_files([row]),
        data=_batch_data(client, "Evento de Produto"),
        headers={"Idempotency-Key": key},
    )
    assert repeated.status_code == 202
    assert repeated.json()["id"] == batch_id
    assert client.get(f"/emission-batches/by-idempotency-key/{key}").json()["id"] == batch_id

    history = client.get(f"/certificates?batch_id={batch_id}").json()
    assert history["total"] == 1
    assert history["items"][0]["batch_id"] == batch_id
    assert client.get("/certificates").json()["total"] == 1

    conflict_row = {**row, "nome": "Outra Pessoa"}
    conflict = client.post(
        "/emission-batches",
        files=_files([conflict_row]),
        data=_batch_data(client, "Evento de Produto"),
        headers={"Idempotency-Key": key},
    )
    assert conflict.status_code == 409


def test_all_invalid_batch_finishes_with_privacy_minimized_error_report(client, auth_headers):
    key = "functional-invalid-key-01"
    response = client.post(
        "/emission-batches",
        files=_files(
            [
                {
                    "nome": "Participante Inválido",
                    "carga_horaria": "não-numérica",
                    "email": "nao-deve-voltar@example.test",
                    "documento": "12345678900",
                }
            ]
        ),
        data={
            "texto_padrao": BODY,
            "certificate_type": "listener",
            "drive_folders_json": "{}",
        },
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["invalid_count"] == 1
    assert payload["result"]["invalid_count"] == 1
    serialized = json.dumps(payload).lower()
    assert "example.test" not in serialized
    assert "12345678900" not in serialized
    assert "documento" not in serialized


def test_audit_is_paginated_filterable_and_privacy_minimized(client, auth_headers):
    _create_user(client, username="auditado")
    page = client.get("/admin/audit?category=users&limit=1&offset=0")
    assert page.status_code == 200
    payload = page.json()
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["total"] >= 1
    assert len(payload["items"]) == 1
    text = json.dumps(payload).lower()
    for forbidden in (
        "password_hash",
        "temporary_password",
        "token",
        "documento",
        "certificate_text",
    ):
        assert forbidden not in text
    assert client.get("/admin/audit?category=unknown").status_code == 422
    assert client.get("/admin/audit?date_from=2026-12-31&date_to=2026-01-01").status_code == 422


def test_revoke_reason_is_not_duplicated_into_audit(client, auth_headers):
    row = {
        "nome": "Pessoa Revogável",
        "curso": "Direito",
        "carga_horaria": 8,
        "data_emissao": "10/06/2026",
    }
    response = client.post(
        "/emission-batches",
        files=_files([row]),
        data=_batch_data(client, ""),
        headers={"Idempotency-Key": "test-only-key-0001"},
    )
    assert response.status_code == 202
    code = client.get(f"/emission-batches/{response.json()['id']}").json()["result"]["generated"][
        0
    ]["code"]
    sensitive_reason = "Correção solicitada para pessoa@example.test"
    revoked = client.post(f"/certificates/{code}/revoke", json={"reason": sensitive_reason})
    assert revoked.status_code == 200
    assert revoked.json()["revoke_reason"] == sensitive_reason

    audit = client.get(f"/admin/audit?action=certificate_revoked&target_id={code}").json()
    serialized = json.dumps(audit).lower()
    assert "pessoa@example.test" not in serialized
    assert audit["items"][0]["details"]["reason"] == "provided"


def test_openapi_describes_new_contract_without_password_hash(client):
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    payload = schema.json()
    required_paths = {
        "/admin/users",
        "/admin/users/{user_id}/reset-password",
        "/admin/audit",
        "/admin/settings",
        "/emission-batches",
        "/emission-batches/{batch_id}",
        "/certificates/{code}/reissue",
    }
    assert required_paths.issubset(payload["paths"])
    assert payload["info"]["version"] == "2.1.0"
    assert "password_hash" not in json.dumps(payload)
