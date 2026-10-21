"""Tests for the public area (certificados-consulta): verify, search, download.

Loads the consulta FastAPI app against a temporary database and asserts the
public projection never leaks sensitive fields or Drive links.
"""

from __future__ import annotations

import importlib.util
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[3]
CODE = "CERT-2026-PUB001"


def _seed_certificate(
    db,
    tmp_path,
    *,
    status="ativo",
    name="João Público",
    code=CODE,
    include_private_storage=False,
    document="99999999999",
    certificate_type=None,
):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir(parents=True, exist_ok=True)
    (pdfs / "j.pdf").write_bytes(b"%PDF-1.4 test certificate")
    db.insert_certificates(
        [
            {
                "unique_code": code,
                "participant_name": name,
                "event_name": "Semana Acadêmica",
                "course_name": "Direito",
                "workload_hours": 40,
                "issue_date": "10 de junho de 2026",
                "pdf_path": "pdfs/j.pdf",
                "participant_email": "segredo@exemplo.com",
                "participant_document": document,
                "drive_file_id": "private-drive-id" if include_private_storage else None,
                "drive_folder_id": "private-folder-id" if include_private_storage else None,
                "original_filename": (
                    "private/path/certificate.pdf" if include_private_storage else "j.pdf"
                ),
                "storage_provider": "local",
                "status": status,
                "certificate_type": certificate_type,
            }
        ]
    )


@pytest.fixture
def public(tmp_path, monkeypatch):
    import storage_service
    from database import db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "certificates.db")
    monkeypatch.setattr(db, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(db, "PDFS_DIR", tmp_path / "pdfs")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("DOCUMENT_HASH_SECRET", "T8v!mZ2#qL9@pR4$xN7&cB1*eK6-wY3+")
    monkeypatch.setenv("DOCUMENT_HASH_ACTIVE_KEY_ID", "v1")
    monkeypatch.delenv("DOCUMENT_HASH_KEYRING_FILE", raising=False)
    storage_service.reset_storage_cache()
    db.init_db()

    path = _REPO_ROOT / "certificados_consulta" / "app.py"
    spec = importlib.util.spec_from_file_location(f"consulta_{uuid.uuid4().hex}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    client = TestClient(module.app)
    client.app.state.consulta_module = module
    yield client, db, tmp_path
    storage_service.reset_storage_cache()


def test_verify_valid_certificate_is_sanitized(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)

    resp = client.get(f"/public/verify/{CODE}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["revoked"] is False
    cert = body["certificate"]
    assert cert["participant_name"] == "João Público"
    assert cert["event_name"] == "Semana Acadêmica"
    assert cert["certificate_type"] is None
    assert cert["certificate_type_label"] == "Tipo não informado"
    # No sensitive/internal fields leak.
    for forbidden in (
        "participant_email",
        "participant_document",
        "participant_document_hash",
        "drive_file_id",
        "pdf_path",
        "id",
    ):
        assert forbidden not in cert


def test_public_pages_use_amf_brand_and_packaged_logo(public):
    client, _, _ = public
    page = client.get("/")
    assert page.status_code == 200
    assert "Certificados Faculdade AMF" in page.text
    assert 'src="/static/logo-amf.jpg"' in page.text

    logo = client.get("/static/logo-amf.jpg")
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/jpeg"


def test_public_api_and_pages_show_persisted_certificate_type(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, certificate_type="scientific_initiation")

    cert = client.get(f"/public/verify/{CODE}").json()["certificate"]
    assert cert["certificate_type"] == "scientific_initiation"
    assert cert["certificate_type_label"] == "Mostra de Iniciação Científica"
    assert "Mostra de Iniciação Científica" in client.get(f"/validar/{CODE}").text
    assert (
        "Mostra de Iniciação Científica"
        in client.post("/public/search", json={"nome": "João Público"}).text
    )


def test_verify_unknown_code(public):
    client, _, _ = public
    assert client.get("/public/verify/CERT-2026-NOPE").json() == {"valid": False}


def test_verify_revoked_is_flagged(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, status="revogado")
    body = client.get(f"/public/verify/{CODE}").json()
    assert body["valid"] is True
    assert body["revoked"] is True
    assert body["status"] == "revogado"


def test_validation_url_matches_existing_html_route(public, monkeypatch):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    monkeypatch.setenv("PUBLIC_VALIDATION_BASE_URL", "https://certificados.example.edu///")
    from storage_service import config as storage_config

    url = storage_config.build_public_validation_url(CODE)
    assert url == f"https://certificados.example.edu/validar/{CODE}"
    response = client.get(urlsplit(url).path)
    assert response.status_code == 200
    assert "Certificado válido" in response.text


def test_validation_page_active_is_accessible_sanitized_and_downloadable(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, include_private_storage=True)

    response = client.get(f"/validar/{CODE}")
    assert response.status_code == 200
    assert 'role="status"' in response.text
    assert "Certificado válido" in response.text
    assert f"/public/certificates/{CODE}/download" in response.text
    assert "João Público" in response.text
    for private_value in (
        "segredo@exemplo.com",
        "99999999999",
        "private-drive-id",
        "private-folder-id",
        "private/path/certificate.pdf",
    ):
        assert private_value not in response.text


def test_validation_page_revoked_has_no_download(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, status="revogado")

    response = client.get(f"/validar/{CODE}")
    assert response.status_code == 200
    assert 'role="alert"' in response.text
    assert "Certificado revogado" in response.text
    assert f"/public/certificates/{CODE}/download" not in response.text


def test_validation_page_unknown_is_accessible_404(public):
    client, _, _ = public
    response = client.get("/validar/CERT-2026-NOPE")
    assert response.status_code == 404
    assert 'role="alert"' in response.text
    assert "Certificado inexistente" in response.text


def test_validation_page_security_headers(public):
    client, _, _ = public
    response = client.get("/validar/CERT-2026-NOPE")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store, private"


def test_internal_lifecycle_state_is_not_public(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, status="pending")
    assert client.get(f"/validar/{CODE}").status_code == 404
    assert client.get(f"/public/verify/{CODE}").json() == {"valid": False}


def test_public_search_is_paginated_and_sanitized(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)

    response = client.post("/public/search", json={"nome": "João"})
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    item = body["items"][0]
    assert "unique_code" not in item
    assert "download_challenge" not in item
    assert len(item["result_ref"]) == 64
    assert item["participant_name"] != "João Público"
    assert "participant_email" not in item
    assert "participant_document" not in item
    assert "participant_document_hash" not in item
    assert "/download" not in str(item)
    assert response.headers["cache-control"] == "no-store, private"


def test_public_search_empty_term(public):
    client, _, _ = public
    response = client.post("/public/search", json={"nome": ""})
    assert response.status_code == 422


def test_sensitive_name_search_is_not_available_by_get(public):
    client, _, _ = public
    response = client.get("/public/search", params={"nome": "João"})
    assert response.status_code == 405
    assert response.headers["cache-control"] == "no-store, private"


def test_public_download_requires_code_and_streams_pdf(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    resp = client.get(f"/public/certificates/{CODE}/download")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["cache-control"] == "no-store, private"


def test_public_download_names_file_with_holder_event_and_code(public):
    from storage_service.filenames import content_disposition

    client, db, tmp_path = public
    # Seeded with a pre-format stored name ("j.pdf"): the download still offers
    # the readable name, and the stored record is left untouched.
    _seed_certificate(db, tmp_path)
    resp = client.get(f"/public/certificates/{CODE}/download")
    assert resp.status_code == 200
    expected = f"João Público - Semana Acadêmica - {CODE}.pdf"
    assert resp.headers["content-disposition"] == content_disposition(expected)
    assert (
        f'filename="Joao Publico - Semana Academica - {CODE}.pdf"'
        in (resp.headers["content-disposition"])
    )
    assert db.get_by_code(CODE)["original_filename"] == "j.pdf"


def test_code_validation_responses_are_not_cached(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    api = client.get(f"/public/verify/{CODE}")
    landing = client.get("/", params={"codigo": CODE})
    assert api.headers["cache-control"] == "no-store, private"
    assert landing.headers["cache-control"] == "no-store, private"


def test_public_download_revoked_returns_410(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, status="revogado")
    assert client.get(f"/public/certificates/{CODE}/download").status_code == 410


def test_public_download_unknown_returns_404(public):
    client, _, _ = public
    assert client.get("/public/certificates/CERT-2026-NOPE/download").status_code == 404


def test_name_search_is_accent_insensitive_and_html_offers_download(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, name="João D'Ávila")

    api = client.post("/public/search", json={"nome": "joao d'avila"})
    assert api.status_code == 200
    assert api.json()["total"] == 1
    html_response = client.post("/", data={"nome": "joao d'avila"})
    html = html_response.text
    assert "J••• D•••" in html
    assert CODE not in html
    assert "/public/certificates/CERT-" not in html
    assert "Registro Acadêmico (RA)" in html
    assert "Confirmar e baixar" in html
    assert html_response.headers["cache-control"] == "no-store, private"


def test_academic_record_search_returns_every_related_certificate(public):
    client, db, tmp_path = public
    academic_record = "RA-2026-0042"
    _seed_certificate(
        db,
        tmp_path,
        code="CERT-2026-RA0001",
        name="Pessoa Acadêmica",
        document=academic_record,
    )
    _seed_certificate(
        db,
        tmp_path,
        code="CERT-2026-RA0002",
        name="Pessoa Acadêmica",
        document=academic_record,
    )
    _seed_certificate(
        db,
        tmp_path,
        code="CERT-2026-OTHER1",
        name="Outra Pessoa",
        document="RA-OUTRO",
    )

    api = client.post(
        "/public/search/academic-record",
        json={"registro_academico": academic_record},
    )
    assert api.status_code == 200
    assert api.json()["total"] == 2
    assert len(api.json()["items"]) == 2
    assert academic_record not in api.text
    assert "CERT-2026-RA0001" not in api.text

    page = client.post("/", data={"registro_academico": academic_record})
    assert page.status_code == 200
    assert re.search(r"2\s+certificados encontrados", page.text)
    assert "Registro Acadêmico (RA)" in page.text
    assert academic_record not in page.text


def test_academic_record_search_can_confirm_and_download_selected_certificate(public):
    client, db, tmp_path = public
    academic_record = "2026007788"
    _seed_certificate(db, tmp_path, document=academic_record)
    item = client.post(
        "/public/search/academic-record",
        json={"registro_academico": academic_record},
    ).json()["items"][0]

    response = client.post(
        "/public/certificates/download-by-search",
        data={
            "search_type": "ra",
            "result_ref": item["result_ref"],
            "registro_academico": academic_record,
        },
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_academic_record_search_rejects_unknown_ra_without_leaking_it(public):
    client, _, _ = public
    unknown = "RA-NAO-EXISTE-999"
    response = client.post("/", data={"registro_academico": unknown})
    assert response.status_code == 200
    assert "Nenhum certificado ativo ou revogado" in response.text
    assert unknown not in response.text


@pytest.mark.parametrize("term", ["%", "_", "\\", "ab"])
def test_short_or_wildcard_only_terms_cannot_enumerate(public, term):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    response = client.post("/public/search", json={"nome": term})
    assert response.status_code == 400


def test_sql_wildcards_are_literal_and_do_not_list_everything(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    response = client.post("/public/search", json={"nome": "Joã%"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_extreme_page_is_bounded(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    response = client.post("/public/search", json={"nome": "João", "page": 999999})
    assert response.status_code == 422


def test_name_download_requires_correct_document_and_never_persists_it(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    item = client.post("/public/search", json={"nome": "João"}).json()["items"][0]
    without_document = client.post(
        "/public/certificates/download-by-name",
        data={"nome": "João", "result_ref": item["result_ref"]},
    )
    assert without_document.status_code == 404
    form = {
        "nome": "João",
        "result_ref": item["result_ref"],
        "documento": "999.999.999-99",
    }

    valid = client.post("/public/certificates/download-by-name", data=form)
    assert valid.status_code == 200
    assert valid.content.startswith(b"%PDF")
    stored = db.get_by_code(CODE)
    assert stored["participant_document"] is None
    assert stored["participant_document_hash"]
    assert stored["participant_document_hash_key_id"] == "v1"
    assert valid.headers["cache-control"] == "no-store, private"


def test_old_challenge_and_wrong_document_fail_with_generic_response(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    item = client.post("/public/search", json={"nome": "João"}).json()["items"][0]
    legacy_challenge = client.post(
        "/public/certificates/download-by-name",
        data={"nome": "João", "challenge": "x" * 43},
    )
    wrong_document = client.post(
        "/public/certificates/download-by-name",
        data={
            "nome": "João",
            "result_ref": item["result_ref"],
            "documento": "11111111111",
        },
    )
    assert (legacy_challenge.status_code, legacy_challenge.json()) == (
        wrong_document.status_code,
        wrong_document.json(),
    )


def test_certificate_without_document_cannot_be_downloaded_by_name(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, document=None)
    item = client.post("/public/search", json={"nome": "João"}).json()["items"][0]
    response = client.post(
        "/public/certificates/download-by-name",
        data={
            "nome": "João",
            "result_ref": item["result_ref"],
            "documento": "99999999999",
        },
    )
    assert response.status_code == 404
    assert "procure a secretaria" in response.json()["detail"].lower()


def test_successful_confirmation_lazily_rotates_document_hmac(public, monkeypatch, tmp_path):
    client, db, storage_path = public
    _seed_certificate(db, storage_path)
    keyring = tmp_path / "keyring.json"
    keyring.write_text(
        json.dumps(
            {
                "v1": "T8v!mZ2#qL9@pR4$xN7&cB1*eK6-wY3+",
                "v2": "Current-Key-For-Tests-0987654321!Bb",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCUMENT_HASH_KEYRING_FILE", str(keyring))
    monkeypatch.setenv("DOCUMENT_HASH_ACTIVE_KEY_ID", "v2")
    item = client.post("/public/search", json={"nome": "João"}).json()["items"][0]
    response = client.post(
        "/public/certificates/download-by-name",
        data={
            "nome": "João",
            "result_ref": item["result_ref"],
            "documento": "99999999999",
        },
    )
    assert response.status_code == 200
    stored = db.get_by_code(CODE)
    assert stored["participant_document"] is None
    assert stored["participant_document_hash_key_id"] == "v2"


def test_public_confirmation_does_not_log_name_or_document(public, caplog):
    client, db, tmp_path = public
    private_name = "Pessoa Marcadora Privada"
    private_document = "74185296300"
    _seed_certificate(db, tmp_path, name=private_name, document=private_document)
    item = client.post("/public/search", json={"nome": "Pessoa Marcadora"}).json()["items"][0]
    with caplog.at_level("INFO"):
        response = client.post(
            "/public/certificates/download-by-name",
            data={
                "nome": "Pessoa Marcadora",
                "result_ref": item["result_ref"],
                "documento": "00000000000",
            },
        )
    assert response.status_code == 404
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert private_name not in rendered_logs
    assert private_document not in rendered_logs
    assert "00000000000" not in rendered_logs


def test_client_request_id_cannot_inject_pii_into_logs(public, caplog):
    client, _, _ = public
    marker = "Pessoa Privada 74185296300"
    with caplog.at_level("INFO"):
        response = client.get("/health", headers={"X-Request-ID": marker})
    assert response.status_code == 200
    assert marker not in response.headers["x-request-id"]
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert marker not in rendered_logs


def test_legacy_download_is_rate_limited_redirect_without_bypass(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    response = client.get(f"/certificado/{CODE}/download", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"].endswith(f"/public/certificates/{CODE}/download")


def test_public_rate_limit_is_shared_between_app_instances_and_returns_429(public, monkeypatch):
    client, _, _ = public
    module = client.app.state.consulta_module
    module.PUBLIC_RATE_LIMIT_REQUESTS = 2
    assert client.get("/health").status_code == 200  # health is intentionally unmetered
    module.PUBLIC_NAME_RATE_LIMIT_REQUESTS = 100
    assert client.post("/public/search", json={"nome": "Maria"}).status_code == 200

    monkeypatch.setenv("PUBLIC_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("PUBLIC_NAME_RATE_LIMIT_REQUESTS", "100")
    path = _REPO_ROOT / "certificados_consulta" / "app.py"
    spec = importlib.util.spec_from_file_location(f"consulta_worker_{uuid.uuid4().hex}", path)
    second_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(second_module)
    second_worker = TestClient(second_module.app)

    assert second_worker.post("/public/search", json={"nome": "Maria"}).status_code == 200
    response = second_worker.post("/public/search", json={"nome": "Maria"})
    assert response.status_code == 429
    assert response.headers["retry-after"]
    html = second_worker.get("/")
    assert html.status_code == 429
    assert 'role="alert"' in html.text


def test_confirmation_identity_rate_limit_is_shared_between_workers(public, monkeypatch):
    client, db, tmp_path = public
    module = client.app.state.consulta_module
    module.PUBLIC_RATE_LIMIT_REQUESTS = 100
    module.PUBLIC_CONFIRM_RATE_LIMIT_REQUESTS = 1
    _seed_certificate(db, tmp_path)
    item = client.post("/public/search", json={"nome": "João"}).json()["items"][0]
    form = {
        "nome": "João",
        "result_ref": item["result_ref"],
        "documento": "11111111111",
    }
    assert client.post("/public/certificates/download-by-name", data=form).status_code == 404

    monkeypatch.setenv("PUBLIC_RATE_LIMIT_REQUESTS", "100")
    monkeypatch.setenv("PUBLIC_CONFIRM_RATE_LIMIT_REQUESTS", "1")
    path = _REPO_ROOT / "certificados_consulta" / "app.py"
    spec = importlib.util.spec_from_file_location(
        f"consulta_confirm_worker_{uuid.uuid4().hex}", path
    )
    second_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(second_module)
    second_worker = TestClient(second_module.app)

    response = second_worker.post("/public/certificates/download-by-name", data=form)
    assert response.status_code == 429
    assert response.headers["retry-after"]


def test_forwarded_for_is_accepted_only_from_configured_proxy(public, monkeypatch):
    client, _, _ = public
    module = client.app.state.consulta_module
    from starlette.requests import Request

    def request(peer):
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [(b"x-forwarded-for", b"198.51.100.20, 10.0.0.2")],
                "client": (peer, 1234),
                "server": ("testserver", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )

    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    assert module.resolve_client_ip(request("10.0.0.1")) == "10.0.0.1"
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    assert module.resolve_client_ip(request("10.0.0.1")) == "198.51.100.20"


def test_all_name_search_responses_exclude_private_values(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, include_private_storage=True)
    responses = [
        client.post("/public/search", json={"nome": "João"}),
        client.post("/", data={"nome": "João"}),
    ]
    for response in responses:
        body = response.text
        for private in (
            CODE,
            "segredo@exemplo.com",
            "99999999999",
            "private-drive-id",
            "private-folder-id",
            "private/path/certificate.pdf",
        ):
            assert private not in body
