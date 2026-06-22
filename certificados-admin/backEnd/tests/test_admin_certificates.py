"""HTTP tests for the structured admin flow: pre-validation, generation,
history, and revocation (via TestClient)."""
from __future__ import annotations

import io
from zipfile import ZipFile

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
    # Invalid because the workload is not a number (only nome + carga are required).
    "nome": "Bruno",
    "curso": "Direito",
    "evento": "X",
    "carga_horaria": "abc",
    "data_emissao": "10/06/2026",
}

# Secretaria-authored body text (the new required field) + the form payload.
BODY = (
    "participou da Semana Jurídica, promovida pelo Curso de Direito, "
    "com carga horária total de {{carga_horaria}} horas."
)
TEXT = {"texto_padrao": BODY}


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
        data=TEXT,
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["valid_count"] == 1
    assert body["invalid_count"] == 1
    assert body["valid"][0]["evento"] == "Semana Jurídica"
    # The preview interpolates the body for the first valid row (no {{...}} left).
    preview = body["resolved_text_preview"]
    assert preview and "{{" not in preview
    assert "Semana Jurídica" in preview and "Direito" in preview and "40" in preview
    # Nothing was persisted.
    assert client.get("/certificates", headers=auth_headers).json()["total"] == 0


def test_validate_rejects_non_xlsx(client, auth_headers):
    files = {"file": ("data.csv", b"nome,curso\n", "text/csv")}
    resp = client.post(
        "/certificates/validate-spreadsheet", files=files, headers=auth_headers
    )
    assert resp.status_code == 400


# ── Body text (texto padrão) validation ───────────────────────────────────────


def test_generate_requires_body_text(client, auth_headers):
    # Authenticated + valid file, but NO body text → business validation 400.
    resp = client.post(
        "/certificates/generate", files=_files([VALID]), headers=auth_headers
    )
    assert resp.status_code == 400
    assert "texto" in resp.json()["detail"].lower()


def test_validate_rejects_unknown_variable(client, auth_headers):
    resp = client.post(
        "/certificates/validate-spreadsheet",
        files=_files([VALID]),
        data={"texto_padrao": "participou de {{palestrante}}."},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "palestrante" in resp.json()["detail"].lower()


def test_auth_is_checked_before_body_text_validation(client):
    # No auth + no body text → 401 (auth first), NOT 400 (text validation).
    assert (
        client.post("/certificates/generate", files=_files([VALID])).status_code == 401
    )
    assert (
        client.post(
            "/certificates/validate-spreadsheet", files=_files([VALID])
        ).status_code
        == 401
    )


# ── Generation + history ──────────────────────────────────────────────────────


def test_generate_then_appears_in_history(client, auth_headers):
    resp = client.post(
        "/certificates/generate",
        files=_files([VALID, INVALID]),
        data=TEXT,
        headers=auth_headers,
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
    # The persisted body is the INTERPOLATED text (never the {{...}} template).
    text = detail["certificate_text"]
    assert "{{" not in text and "}}" not in text
    assert "Semana Jurídica" in text and "Direito" in text and "40" in text


def test_generation_is_idempotent_over_http(client, auth_headers):
    first = client.post(
        "/certificates/generate", files=_files([VALID]), data=TEXT, headers=auth_headers
    ).json()
    assert first["generated_count"] == 1

    second = client.post(
        "/certificates/generate", files=_files([VALID]), data=TEXT, headers=auth_headers
    ).json()
    assert second["generated_count"] == 0
    assert second["duplicate_count"] == 1
    assert client.get("/certificates", headers=auth_headers).json()["total"] == 1


def test_revoke_marks_certificate(client, auth_headers):
    gen = client.post(
        "/certificates/generate", files=_files([VALID]), data=TEXT, headers=auth_headers
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


def test_revoke_requires_valid_reason(client, auth_headers):
    generated = client.post(
        "/certificates/generate", files=_files([VALID]), data=TEXT, headers=auth_headers
    ).json()
    code = generated["generated"][0]["code"]
    assert client.post(
        f"/certificates/{code}/revoke", json={}, headers=auth_headers
    ).status_code == 422
    whitespace = client.post(
        f"/certificates/{code}/revoke", json={"reason": "     "}, headers=auth_headers
    )
    assert whitespace.status_code == 400
    assert "pelo menos 5 caracteres" in whitespace.json()["detail"]


def test_history_zip_returns_available_files_and_reports_partial_errors(client, auth_headers):
    second = {**VALID, "nome": "Bruna Souza", "evento": "Outro Evento"}
    generated = client.post(
        "/certificates/generate",
        files=_files([VALID, second]),
        data=TEXT,
        headers=auth_headers,
    ).json()["generated"]
    active_code = generated[0]["code"]
    revoked_code = generated[1]["code"]
    client.post(
        f"/certificates/{revoked_code}/revoke",
        json={"reason": "emissão duplicada"},
        headers=auth_headers,
    )

    listing = client.get("/certificates", headers=auth_headers).json()["items"]
    availability = {item["unique_code"]: item["download_available"] for item in listing}
    assert availability[active_code] is True
    assert availability[revoked_code] is False

    response = client.post(
        "/certificates/download-zip",
        json={"codes": [active_code, revoked_code]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert revoked_code in response.headers["x-skipped-certificates"]
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert "_erros-download.txt" in archive.namelist()
        assert any(name.endswith(".pdf") for name in archive.namelist())


def test_history_search_by_event(client, auth_headers):
    client.post(
        "/certificates/generate", files=_files([VALID]), data=TEXT, headers=auth_headers
    )
    found = client.get("/certificates?event=Jurídica", headers=auth_headers).json()
    assert found["total"] == 1
    none = client.get("/certificates?event=Inexistente", headers=auth_headers).json()
    assert none["total"] == 0
