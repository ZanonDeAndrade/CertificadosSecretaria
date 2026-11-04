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
    emails=None,
    authors=None,
    work_title=None,
):
    """A certificate as the worker records it. Without ``emails`` it stands for
    one issued before e-mails were recorded: only the document hash confirms it."""
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
                "emails": list(emails or []),
                "authors_json": json.dumps(list(authors)) if authors else None,
                "work_title": work_title,
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
    expected = f"João Público_Semana Acadêmica_{CODE}.pdf"
    assert resp.headers["content-disposition"] == content_disposition(expected)
    assert (
        f'filename="Joao Publico_Semana Academica_{CODE}.pdf"'
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
    assert "E-mail cadastrado" in html
    assert "Confirmar e baixar" in html
    assert "segredo@exemplo.com" not in html
    assert html_response.headers["cache-control"] == "no-store, private"


EMAIL = "pessoa.academica@exemplo.com"


def test_email_search_returns_every_certificate_of_the_person_as_holder_or_author(public):
    client, db, tmp_path = public
    _seed_certificate(
        db, tmp_path, code="CERT-2026-EM0001", name="Pessoa Acadêmica", emails=[EMAIL]
    )
    _seed_certificate(
        db,
        tmp_path,
        code="CERT-2026-EM0002",
        name="Primeira Autora",
        certificate_type="scientific_initiation",
        authors=["Primeira Autora", "Pessoa Acadêmica"],
        work_title="Horta vertical automatizada",
        emails=["primeira.autora@exemplo.com", EMAIL],
    )
    _seed_certificate(
        db, tmp_path, code="CERT-2026-OTHER1", name="Outra Pessoa", emails=["outra@exemplo.com"]
    )

    # Exact match, after the same normalisation the spreadsheet applies.
    api = client.post("/public/search/email", json={"email": "  Pessoa.Academica@EXEMPLO.com "})
    assert api.status_code == 200
    assert api.json()["total"] == 2
    assert {item["work_title"] for item in api.json()["items"]} == {
        None,
        "Horta vertical automatizada",
    }
    assert "exemplo.com" not in api.text
    assert "CERT-2026-EM0001" not in api.text
    assert "participant_document_hash" not in api.text

    page = client.post("/", data={"email": EMAIL})
    assert page.status_code == 200
    assert re.search(r"2\s+certificados encontrados", page.text)
    # The e-mail is never echoed: the confirmation asks for it again, with the name.
    assert "exemplo.com" not in page.text
    assert "Nome completo" in page.text and "Confirmar e baixar" in page.text
    assert client.post("/public/search/email", json={"email": "sem-arroba"}).status_code == 422


def test_academic_record_search_is_gone_from_the_public_site(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, document="2026007788")
    assert (
        client.post(
            "/public/search/academic-record", json={"registro_academico": "2026007788"}
        ).status_code
        == 404
    )
    page = client.post("/", data={"registro_academico": "2026007788"})
    assert page.status_code == 400
    assert "Informe o nome ou o e-mail" in page.text
    assert "2026007788" not in page.text
    assert 'name="registro_academico"' not in client.get("/").text


def test_email_search_download_confirms_with_the_email_again_and_the_full_name(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, name="João Público", emails=["joao@exemplo.com"])
    item = client.post("/public/search/email", json={"email": "joao@exemplo.com"}).json()["items"][
        0
    ]
    base = {"search_type": "email", "result_ref": item["result_ref"]}

    wrong_name = client.post(
        "/public/certificates/download-by-search",
        data={**base, "confirmacao": "joao@exemplo.com", "nome": "Outra Pessoa"},
    )
    assert wrong_name.status_code == 404
    without_name = client.post(
        "/public/certificates/download-by-search",
        data={**base, "confirmacao": "joao@exemplo.com"},
    )
    assert without_name.status_code == 404
    wrong_email = client.post(
        "/public/certificates/download-by-search",
        data={**base, "confirmacao": "outro@exemplo.com", "nome": "João Público"},
    )
    assert wrong_email.status_code == 404

    response = client.post(
        "/public/certificates/download-by-search",
        data={**base, "confirmacao": " JOAO@Exemplo.com", "nome": "joao publico"},
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_coauthor_confirms_a_work_with_the_own_name_and_email(public):
    client, db, tmp_path = public
    _seed_certificate(
        db,
        tmp_path,
        name="Primeira Autora",
        certificate_type="scientific_initiation",
        authors=["Primeira Autora", "Segundo Autor"],
        work_title="Robô seguidor de linha",
        emails=["primeira@exemplo.com", "segundo@exemplo.com"],
    )
    item = client.post("/public/search/email", json={"email": "segundo@exemplo.com"}).json()[
        "items"
    ][0]
    response = client.post(
        "/public/certificates/download-by-search",
        data={
            "search_type": "email",
            "result_ref": item["result_ref"],
            "confirmacao": "segundo@exemplo.com",
            "nome": "Segundo Autor",
        },
    )
    assert response.status_code == 200


def test_name_search_download_confirms_with_the_email_not_the_document(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, emails=["joao@exemplo.com"], document="99999999999")
    item = client.post("/public/search", json={"nome": "João"}).json()["items"][0]
    base = {"search_type": "nome", "nome": "João", "result_ref": item["result_ref"], "page": 1}

    # The certificate has an e-mail on record: the document no longer confirms it.
    by_document = client.post(
        "/public/certificates/download-by-search", data={**base, "confirmacao": "99999999999"}
    )
    assert by_document.status_code == 404
    by_email = client.post(
        "/public/certificates/download-by-search", data={**base, "confirmacao": "Joao@exemplo.com"}
    )
    assert by_email.status_code == 200
    assert by_email.content.startswith(b"%PDF")


def test_certificate_issued_before_emails_still_confirms_with_the_document(public):
    client, db, tmp_path = public
    _seed_certificate(db, tmp_path, document="2026007788")  # no e-mail hash on record
    item = client.post("/public/search", json={"nome": "João"}).json()["items"][0]
    response = client.post(
        "/public/certificates/download-by-search",
        data={
            "search_type": "nome",
            "nome": "João",
            "result_ref": item["result_ref"],
            "page": 1,
            "confirmacao": "2026007788",
        },
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_email_search_rejects_unknown_email_without_leaking_it(public):
    client, _, _ = public
    unknown = "ninguem.conhece@exemplo.com"
    response = client.post("/", data={"email": unknown})
    assert response.status_code == 200
    assert "Nenhum certificado ativo ou revogado" in response.text
    assert unknown not in response.text


def test_successful_email_confirmation_lazily_rotates_the_email_hmac(public, monkeypatch, tmp_path):
    client, db, storage_path = public
    _seed_certificate(db, storage_path, emails=["joao@exemplo.com"])
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
    certificate_id = int(db.get_by_code(CODE)["id"])
    assert [row["hash_key_id"] for row in db.certificate_email_hashes(certificate_id)] == ["v1"]

    # Found under the old key, confirmed, and moved to the active one.
    item = client.post("/public/search/email", json={"email": "joao@exemplo.com"}).json()["items"][
        0
    ]
    response = client.post(
        "/public/certificates/download-by-search",
        data={
            "search_type": "email",
            "result_ref": item["result_ref"],
            "confirmacao": "joao@exemplo.com",
            "nome": "João Público",
        },
    )
    assert response.status_code == 200
    assert [row["hash_key_id"] for row in db.certificate_email_hashes(certificate_id)] == ["v2"]
    assert (
        client.post("/public/search/email", json={"email": "joao@exemplo.com"}).json()["total"] == 1
    )


def test_public_email_search_and_confirmation_never_log_or_return_the_email(public, caplog):
    client, db, tmp_path = public
    private_email = "marcador.privado@exemplo.com"
    _seed_certificate(db, tmp_path, name="Pessoa Marcadora", emails=[private_email])
    with caplog.at_level("INFO"):
        search = client.post("/public/search/email", json={"email": private_email})
        item = search.json()["items"][0]
        page = client.post("/", data={"email": private_email})
        denied = client.post(
            "/public/certificates/download-by-search",
            data={
                "search_type": "email",
                "result_ref": item["result_ref"],
                "confirmacao": private_email,
                "nome": "Nome Errado",
            },
        )
    assert search.status_code == 200 and page.status_code == 200
    assert denied.status_code == 404
    for body in (search.text, page.text, denied.text):
        assert private_email not in body
        assert "marcador" not in body.lower()
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert private_email not in rendered_logs
    assert "marcador" not in rendered_logs.lower()


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
