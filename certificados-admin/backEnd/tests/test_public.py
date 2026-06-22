"""Tests for the public area (certificados-consulta): verify, search, download.

Loads the consulta FastAPI app against a temporary database and asserts the
public projection never leaks sensitive fields or Drive links.
"""
from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient

CODE = "CERT-2026-PUB001"


def _seed_certificate(
    db,
    tmp_path,
    *,
    status="ativo",
    name="João Público",
    code=CODE,
    include_private_storage=False,
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
                "participant_document": "99999999999",
                "drive_file_id": "private-drive-id" if include_private_storage else None,
                "drive_folder_id": "private-folder-id" if include_private_storage else None,
                "original_filename": (
                    "private/path/certificate.pdf" if include_private_storage else "j.pdf"
                ),
                "storage_provider": "local",
                "status": status,
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
    storage_service.reset_storage_cache()
    db.init_db()

    path = _REPO_ROOT / "certificados-consulta" / "app.py"
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
    monkeypatch.setenv(
        "PUBLIC_VALIDATION_BASE_URL", "https://certificados.example.edu///"
    )
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
    assert response.headers["cache-control"] == "no-store"


def test_internal_lifecycle_state_is_not_public(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, status="pending")
    assert client.get(f"/validar/{CODE}").status_code == 404
    assert client.get(f"/public/verify/{CODE}").json() == {"valid": False}


def test_public_search_is_paginated_and_sanitized(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)

    body = client.get("/public/search", params={"nome": "João"}).json()
    assert body["total"] == 1
    assert body["page"] == 1
    item = body["items"][0]
    assert "unique_code" not in item
    assert item["download_challenge"]
    assert "participant_email" not in item
    assert "participant_document" not in item
    assert "participant_document_hash" not in item
    assert "/download" not in str(item)


def test_public_search_empty_term(public):
    client, _, _ = public
    response = client.get("/public/search", params={"nome": ""})
    assert response.status_code == 400


def test_public_download_requires_code_and_streams_pdf(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    resp = client.get(f"/public/certificates/{CODE}/download")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    assert resp.headers["content-type"] == "application/pdf"


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

    api = client.get("/public/search", params={"nome": "joao d'avila"})
    assert api.status_code == 200
    assert api.json()["total"] == 1
    html = client.get("/", params={"nome": "joao d'avila"}).text
    assert "João D&#39;Ávila" in html
    assert CODE not in html
    assert "/public/certificates/CERT-" not in html
    assert "Documento ou matrícula" not in html
    assert "Baixar PDF" in html


@pytest.mark.parametrize("term", ["%", "_", "\\", "ab"])
def test_short_or_wildcard_only_terms_cannot_enumerate(public, term):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    response = client.get("/public/search", params={"nome": term})
    assert response.status_code == 400


def test_sql_wildcards_are_literal_and_do_not_list_everything(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    response = client.get("/public/search", params={"nome": "Joã%"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_extreme_page_is_bounded(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    body = client.get("/public/search", params={"nome": "João", "page": 999999}).json()
    assert body["page"] == 100
    assert body["items"] == []


def test_name_download_does_not_require_document_and_never_reveals_it(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    item = client.get("/public/search", params={"nome": "João"}).json()["items"][0]
    form = {"nome": "João Público", "challenge": item["download_challenge"]}

    valid = client.post("/public/certificates/download-by-name", data=form)
    assert valid.status_code == 200
    assert valid.content.startswith(b"%PDF")
    stored = db.get_by_code(CODE)
    assert stored["participant_document"] is None
    assert stored["participant_document_hash"]


def test_name_download_rejects_missing_or_unknown_challenge(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path)
    missing_challenge = client.post(
        "/public/certificates/download-by-name",
        data={"nome": "João Público"},
    )
    wrong_challenge = client.post(
        "/public/certificates/download-by-name",
        data={"nome": "João Público", "challenge": "x" * 43},
    )
    assert (missing_challenge.status_code, missing_challenge.json()) == (
        wrong_challenge.status_code,
        wrong_challenge.json(),
    )


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
    assert client.get("/public/search", params={"nome": "Maria"}).status_code == 200

    monkeypatch.setenv("PUBLIC_RATE_LIMIT_REQUESTS", "2")
    path = _REPO_ROOT / "certificados-consulta" / "app.py"
    spec = importlib.util.spec_from_file_location(f"consulta_worker_{uuid.uuid4().hex}", path)
    second_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(second_module)
    second_worker = TestClient(second_module.app)

    assert second_worker.get("/public/search", params={"nome": "Maria"}).status_code == 200
    response = second_worker.get("/public/search", params={"nome": "Maria"})
    assert response.status_code == 429
    assert response.headers["retry-after"]
    html = second_worker.get("/")
    assert html.status_code == 429
    assert 'role="alert"' in html.text


def test_forwarded_for_is_accepted_only_from_configured_proxy(public, monkeypatch):
    client, _, _ = public
    module = client.app.state.consulta_module
    from starlette.requests import Request

    def request(peer):
        return Request({
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"198.51.100.20, 10.0.0.2")],
            "client": (peer, 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        })

    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    assert module.resolve_client_ip(request("10.0.0.1")) == "10.0.0.1"
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    assert module.resolve_client_ip(request("10.0.0.1")) == "198.51.100.20"


def test_all_name_search_responses_exclude_private_values(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, include_private_storage=True)
    responses = [
        client.get("/public/search", params={"nome": "João"}),
        client.get("/", params={"nome": "João"}),
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
