"""HTTP tests for the structured admin flow: pre-validation, generation,
history, and revocation (via TestClient)."""
from __future__ import annotations

import io

import pandas as pd

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(rows) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def _files(rows):
    return {"file": ("participantes.xlsx", _xlsx(rows), XLSX_MIME)}


VALID = {
    "nome": "Ana Souza",
    "curso": "Direito",
    "evento": "Semana Jurídica",
    "carga_horaria": 40,
    "data_emissao": "10/06/2026",
}
INVALID = {
    "nome": "Bruno",
    "curso": "Curso Inexistente",
    "evento": "X",
    "carga_horaria": 8,
    "data_emissao": "10/06/2026",
}


# ── Auth required ─────────────────────────────────────────────────────────────


def test_structured_routes_require_auth(client):
    # Send a valid file so the 401 (auth) is what we observe, not a 422 (body).
    assert (
        client.post("/certificates/validate-spreadsheet", files=_files([VALID])).status_code
        == 401
    )
    assert client.post("/certificates/generate", files=_files([VALID])).status_code == 401
    assert client.get("/certificates").status_code == 401


# ── Pre-validation ────────────────────────────────────────────────────────────


def test_validate_spreadsheet_preview(client, auth_headers):
    resp = client.post(
        "/certificates/validate-spreadsheet",
        files=_files([VALID, INVALID]),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["valid_count"] == 1
    assert body["invalid_count"] == 1
    assert body["valid"][0]["evento"] == "Semana Jurídica"
    # Nothing was persisted.
    assert client.get("/certificates", headers=auth_headers).json()["total"] == 0


def test_validate_rejects_non_xlsx(client, auth_headers):
    files = {"file": ("data.csv", b"nome,curso\n", "text/csv")}
    resp = client.post(
        "/certificates/validate-spreadsheet", files=files, headers=auth_headers
    )
    assert resp.status_code == 400


# ── Generation + history ──────────────────────────────────────────────────────


def test_generate_then_appears_in_history(client, auth_headers):
    resp = client.post(
        "/certificates/generate", files=_files([VALID, INVALID]), headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["generated_count"] == 1
    assert body["invalid_count"] == 1
    code = body["generated"][0]["code"]

    listing = client.get("/certificates", headers=auth_headers).json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["unique_code"] == code
    assert item["event_name"] == "Semana Jurídica"  # evento, not course
    assert item["course_name"] == "Direito"
    assert item["status"] == "ativo"

    detail = client.get(f"/certificates/{code}", headers=auth_headers).json()
    assert detail["workload_hours"] == 40
    assert detail["certificate_text"]


def test_generation_is_idempotent_over_http(client, auth_headers):
    first = client.post(
        "/certificates/generate", files=_files([VALID]), headers=auth_headers
    ).json()
    assert first["generated_count"] == 1

    second = client.post(
        "/certificates/generate", files=_files([VALID]), headers=auth_headers
    ).json()
    assert second["generated_count"] == 0
    assert second["duplicate_count"] == 1
    assert client.get("/certificates", headers=auth_headers).json()["total"] == 1


def test_revoke_marks_certificate(client, auth_headers):
    gen = client.post(
        "/certificates/generate", files=_files([VALID]), headers=auth_headers
    ).json()
    code = gen["generated"][0]["code"]

    resp = client.post(
        f"/certificates/{code}/revoke",
        json={"reason": "emitido por engano"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "revogado"

    # Filter by status.
    revoked = client.get("/certificates?status=revogado", headers=auth_headers).json()
    assert revoked["total"] == 1
    # Admin file stream is blocked for revoked (410).
    assert client.get(f"/certificate-file/{code}", headers=auth_headers).status_code == 410


def test_history_search_by_event(client, auth_headers):
    client.post("/certificates/generate", files=_files([VALID]), headers=auth_headers)
    found = client.get("/certificates?event=Jurídica", headers=auth_headers).json()
    assert found["total"] == 1
    none = client.get("/certificates?event=Inexistente", headers=auth_headers).json()
    assert none["total"] == 0
