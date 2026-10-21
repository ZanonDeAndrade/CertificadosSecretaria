"""HTTP tests for the structured admin flow: pre-validation, generation,
history, and revocation (via TestClient)."""

from __future__ import annotations

import hashlib
import io
import json
from itertools import count
from zipfile import ZipFile

import pandas as pd

from database import db
from storage_service import config as storage_config
from storage_service.filenames import content_disposition

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
_BATCH_KEYS = count(1)


def _emit(client, auth_headers, rows, *, data=TEXT, certificate_type="listener") -> dict:
    """Use the durable API and read the terminal summary after TestClient tasks."""
    headers = {
        **auth_headers,
        "Idempotency-Key": f"admin-http-test-{next(_BATCH_KEYS):06d}",
    }
    destinations = {}
    if storage_config.get_storage_provider() == "google_drive":
        user_id = int(client.get("/auth/me", headers=auth_headers).json()["id"])
        events = {
            str(row.get("evento") or "").strip()
            for row in rows
            if row.get("nome") and isinstance(row.get("carga_horaria"), (int, float))
        }
        for index, event in enumerate(sorted(events), start=1):
            folder_id = f"folder-admin-http-{index:04d}"
            db.upsert_google_drive_folder_grant(
                {
                    "user_id": user_id,
                    "folder_id": folder_id,
                    "folder_id_hash": hashlib.sha256(folder_id.encode()).hexdigest(),
                    "folder_name": event or "Sem evento",
                    "can_add_children": 1,
                }
            )
            destinations[event] = folder_id
    form = {
        **data,
        "certificate_type": certificate_type,
        "drive_folders_json": json.dumps(destinations),
    }
    response = client.post("/emission-batches", files=_files(rows), data=form, headers=headers)
    assert response.status_code == 202, response.text
    batch_id = response.json()["id"]
    batch = client.get(f"/emission-batches/{batch_id}", headers=auth_headers)
    assert batch.status_code == 200, batch.text
    payload = batch.json()
    assert payload["status"] in {"completed", "partial", "failed"}, payload
    return payload["result"] or {}


# ── Auth required ─────────────────────────────────────────────────────────────


def test_structured_routes_require_auth(client):
    # Send a valid file so the 401 (auth) is what we observe, not a 422 (body).
    assert (
        client.post("/certificates/validate-spreadsheet", files=_files([VALID])).status_code == 401
    )
    assert client.post("/certificates/generate", files=_files([VALID])).status_code == 401
    assert (
        client.post(
            "/emission-batches",
            files=_files([VALID]),
            headers={"Idempotency-Key": "unauthenticated-test"},
        ).status_code
        == 401
    )
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
    resp = client.post("/certificates/validate-spreadsheet", files=files, headers=auth_headers)
    assert resp.status_code == 400


# ── Body text (texto padrão) validation ───────────────────────────────────────


def test_generate_requires_body_text(client, auth_headers):
    # Authenticated + valid file, but NO body text → business validation 400.
    resp = client.post(
        "/emission-batches",
        files=_files([VALID]),
        data={"certificate_type": "listener"},
        headers={**auth_headers, "Idempotency-Key": "missing-body-text"},
    )
    assert resp.status_code == 400
    assert "texto" in resp.json()["detail"].lower()


def test_new_emission_requires_controlled_certificate_type(client, auth_headers):
    missing = client.post(
        "/emission-batches",
        files=_files([VALID]),
        data={"texto_padrao": BODY},
        headers={**auth_headers, "Idempotency-Key": "missing-certificate-type"},
    )
    assert missing.status_code == 422

    invalid = client.post(
        "/emission-batches",
        files=_files([VALID]),
        data={"texto_padrao": BODY, "certificate_type": "inventado"},
        headers={**auth_headers, "Idempotency-Key": "invalid-certificate-type"},
    )
    assert invalid.status_code == 422
    assert "tipo do certificado" in invalid.json()["detail"].lower()
    # Validation happens before a durable batch/job is committed or dispatched.
    assert db.list_emission_batches(limit=10)[1] == 0


def test_batch_persists_type_per_certificate_and_serializes_it(client, auth_headers):
    second = {**VALID, "nome": "Beatriz Souza"}
    result = _emit(
        client,
        auth_headers,
        [VALID, second],
        certificate_type="organizing_committee",
    )
    codes = [item["code"] for item in result["generated"]]
    assert len(codes) == 2
    batch_ids = set()
    for code in codes:
        stored = db.get_by_code(code)
        assert stored is not None
        assert stored["certificate_type"] == "organizing_committee"
        batch_ids.add(stored["batch_id"])
        response = client.get(f"/certificates/{code}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["certificate_type"] == "organizing_committee"
        assert response.json()["certificate_type_label"] == "Comissão Organizadora"
        metadata = client.get(f"/admin/certificates/{code}/metadata", headers=auth_headers)
        assert metadata.status_code == 200
        assert metadata.json()["certificate_type"] == "organizing_committee"
        assert metadata.json()["certificate_type_label"] == "Comissão Organizadora"

    assert len(batch_ids) == 1
    batch = db.get_emission_batch(batch_ids.pop())
    assert batch is not None
    assert batch["certificate_type"] == "organizing_committee"

    filtered = client.get(
        "/certificates?certificate_type=organizing_committee", headers=auth_headers
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2
    assert (
        client.get("/certificates?certificate_type=arbitrario", headers=auth_headers).status_code
        == 422
    )


def test_every_controlled_type_can_be_issued_and_is_part_of_idempotency(client, auth_headers):
    expected = {
        "listener": "Ouvinte",
        "speaker": "Palestrante",
        "organizing_committee": "Comissão Organizadora",
        "teams": "Equipes",
        "monitoring": "Monitoria",
        "tcc_board_professor": "Professores participantes de Banca de TCC",
        "scientific_initiation": "Mostra de Iniciação Científica",
    }
    issued_codes = []
    for value, label in expected.items():
        result = _emit(client, auth_headers, [VALID], certificate_type=value)
        assert result["generated_count"] == 1
        code = result["generated"][0]["code"]
        issued_codes.append(code)
        stored = db.get_by_code(code)
        assert stored is not None
        assert stored["certificate_type"] == value
        detail = client.get(f"/certificates/{code}", headers=auth_headers).json()
        assert detail["certificate_type_label"] == label

    # The same participant/event may legitimately receive certificates of
    # different types; the type is therefore part of the business key.
    assert len(set(issued_codes)) == len(expected)
    assert client.get("/certificates", headers=auth_headers).json()["total"] == len(expected)


def test_admin_api_serializes_legacy_certificate_without_inventing_a_type(client, auth_headers):
    db.insert_certificates(
        [
            {
                "unique_code": "CERT-2025-LEGACY",
                "participant_name": "Pessoa Legada",
                "event_name": "Evento Histórico",
                "issue_date": "2025-08-15",
                "pdf_path": "",
                "certificate_type": None,
            }
        ]
    )

    listing = client.get("/certificates", headers=auth_headers).json()
    assert listing["items"][0]["certificate_type"] is None
    assert listing["items"][0]["certificate_type_label"] == "Tipo não informado"
    detail = client.get("/certificates/CERT-2025-LEGACY", headers=auth_headers).json()
    assert detail["certificate_type"] is None
    assert detail["certificate_type_label"] == "Tipo não informado"


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
        client.post(
            "/emission-batches",
            files=_files([VALID]),
            headers={"Idempotency-Key": "auth-before-validation"},
        ).status_code
        == 401
    )
    assert (
        client.post("/certificates/validate-spreadsheet", files=_files([VALID])).status_code == 401
    )


# ── Generation + history ──────────────────────────────────────────────────────


def test_generate_then_appears_in_history(client, auth_headers):
    body = _emit(client, auth_headers, [VALID, INVALID])
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
    assert "participant_document" not in detail
    assert "drive_file_id" not in detail
    # The persisted body is the INTERPOLATED text (never the {{...}} template).
    text = detail["certificate_text"]
    assert "{{" not in text and "}}" not in text
    assert "Semana Jurídica" in text and "Direito" in text and "40" in text


def test_generation_is_idempotent_over_http(client, auth_headers):
    first = _emit(client, auth_headers, [VALID])
    assert first["generated_count"] == 1

    second = _emit(client, auth_headers, [VALID])
    assert second["generated_count"] == 0
    assert second["duplicate_count"] == 1
    assert client.get("/certificates", headers=auth_headers).json()["total"] == 1


def test_revoke_marks_certificate(client, auth_headers):
    gen = _emit(client, auth_headers, [VALID])
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
    generated = _emit(client, auth_headers, [VALID])
    code = generated["generated"][0]["code"]
    assert (
        client.post(f"/certificates/{code}/revoke", json={}, headers=auth_headers).status_code
        == 422
    )
    whitespace = client.post(
        f"/certificates/{code}/revoke", json={"reason": "     "}, headers=auth_headers
    )
    assert whitespace.status_code == 400
    assert "pelo menos 5 caracteres" in whitespace.json()["detail"]


def test_history_zip_returns_available_files_and_reports_partial_errors(client, auth_headers):
    second = {**VALID, "nome": "Bruna Souza", "evento": "Outro Evento"}
    generated = _emit(client, auth_headers, [VALID, second])["generated"]
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


def test_history_zip_rejects_oversized_code_payload(client, auth_headers):
    response = client.post(
        "/certificates/download-zip",
        json={"codes": ["x" * 129]},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_history_search_by_event(client, auth_headers):
    _emit(client, auth_headers, [VALID])
    found = client.get("/certificates?event=Jurídica", headers=auth_headers).json()
    assert found["total"] == 1
    none = client.get("/certificates?event=Inexistente", headers=auth_headers).json()
    assert none["total"] == 0


def test_history_event_filter_ignores_accents_and_case(client, auth_headers):
    _emit(
        client,
        auth_headers,
        [VALID, {**VALID, "nome": "Caio Lima", "evento": "Jornada de Inovação"}],
    )
    for term in ("juridica", "SEMANA JURÍDICA", "  semana   jur  "):
        found = client.get("/certificates", params={"event": term}, headers=auth_headers).json()
        assert [item["event_name"] for item in found["items"]] == ["Semana Jurídica"], term
    found = client.get("/certificates", params={"event": "INOVACAO"}, headers=auth_headers).json()
    assert [item["participant_name"] for item in found["items"]] == ["Caio Lima"]


def _insert(code: str, *, event: str, course: str) -> None:
    db.insert_certificates(
        [
            {
                "unique_code": code,
                "participant_name": "Pessoa Sintética",
                "event_name": event,
                "course_name": course,
                "issue_date": "2026-06-10",
                "status": "ativo",
            }
        ]
    )


def test_history_event_and_course_filters_take_wildcards_literally(client, auth_headers):
    _insert("CERT-2026-WILD01", event="Evento 100% online", course="Curso_A")
    _insert("CERT-2026-WILD02", event="Evento 1000 online", course="CursoXA")

    def codes(**params) -> list[str]:
        page = client.get("/certificates", params=params, headers=auth_headers).json()
        return sorted(item["unique_code"] for item in page["items"])

    assert codes(event="100%") == ["CERT-2026-WILD01"]
    assert codes(event="%") == ["CERT-2026-WILD01"]
    assert codes(event="Evento 10_0") == []
    assert codes(course="Curso_A") == ["CERT-2026-WILD01"]
    assert codes(course="_") == ["CERT-2026-WILD01"]
    assert codes(course="curso") == ["CERT-2026-WILD01", "CERT-2026-WILD02"]


def test_emission_stores_readable_filename_and_admin_download_uses_it(client, auth_headers):
    code = _emit(client, auth_headers, [VALID])["generated"][0]["code"]
    expected = f"Ana Souza - Semana Jurídica - {code}.pdf"

    stored = db.get_by_code(code)
    assert stored["original_filename"] == expected
    assert stored["pdf_path"] == f"pdfs/{expected}"
    assert (db.STORAGE_DIR / stored["pdf_path"]).is_file()

    response = client.get(f"/certificate-file/{code}", headers=auth_headers)
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition == content_disposition(expected)
    assert f'filename="Ana Souza - Semana Juridica - {code}.pdf"' in disposition
    assert "filename*=UTF-8''Ana%20Souza%20-%20Semana%20Jur%C3%ADdica%20-%20" in disposition


def test_certificate_issued_before_the_format_downloads_under_it_without_renaming(
    client, auth_headers
):
    code = "CERT-2025-OLD001"
    legacy_name = f"Joao_Antigo_{code}.pdf"
    (db.PDFS_DIR).mkdir(parents=True, exist_ok=True)
    (db.PDFS_DIR / legacy_name).write_bytes(b"%PDF-1.4 legado")
    db.insert_certificates(
        [
            {
                "unique_code": code,
                "participant_name": "João Antigo",
                "event_name": "Semana de Inovação",
                "issue_date": "2025-06-10",
                "pdf_path": f"pdfs/{legacy_name}",
                "original_filename": legacy_name,
                "storage_provider": "local",
                "status": "ativo",
            }
        ]
    )

    response = client.get(f"/certificate-file/{code}", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-disposition"] == content_disposition(
        f"João Antigo - Semana de Inovação - {code}.pdf"
    )
    # Only the suggested name changes: the stored file and its record stay put.
    assert db.get_by_code(code)["original_filename"] == legacy_name
    assert db.get_by_code(code)["pdf_path"] == f"pdfs/{legacy_name}"
    assert (db.PDFS_DIR / legacy_name).read_bytes() == b"%PDF-1.4 legado"


def test_history_zip_names_entries_with_holder_event_and_code(client, auth_headers):
    # The same person twice in the same event: the code keeps the names apart.
    second = {**VALID, "carga_horaria": 20}
    third = {**VALID, "nome": "Lúcia Ávila", "evento": "Jornada: Ética/Direito"}
    generated = _emit(client, auth_headers, [VALID, second, third])["generated"]
    codes = [item["code"] for item in generated]

    response = client.post(
        "/certificates/download-zip", json={"codes": codes}, headers=auth_headers
    )
    assert response.status_code == 200
    with ZipFile(io.BytesIO(response.content)) as archive:
        names = sorted(archive.namelist())
    assert names == sorted(
        [
            f"Ana Souza - Semana Jurídica - {codes[0]}.pdf",
            f"Ana Souza - Semana Jurídica - {codes[1]}.pdf",
            f"Lúcia Ávila - Jornada Ética Direito - {codes[2]}.pdf",
        ]
    )


def test_legacy_synchronous_generation_is_gone(client, auth_headers):
    response = client.post("/certificates/generate", headers=auth_headers)
    assert response.status_code == 410
    assert "/emission-batches" in response.json()["detail"]
