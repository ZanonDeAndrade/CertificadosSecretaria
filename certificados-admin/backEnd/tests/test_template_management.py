"""Certificate models through the admin API: one item per model, revisions
behind it, and the guarantees issued certificates keep.

The rules under test, as agreed with the secretariat:
  - saving a model nothing depends on changes the same revision;
  - saving a model with certificates (or ever active) adds a revision, and the
    old certificate stays linked to the layout it was issued with;
  - deleting a model without certificates removes it; with certificates it is
    archived, and validation and reissue keep working;
  - the active model cannot be deleted; saving its layout needs "apply";
  - the course only files the model: the list filters by it.
"""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
from certificados_backend.services import template_service
from certificados_backend.services.runtime import build_certificate_service

from database import db

_BACKEND_DIR = Path(__file__).resolve().parent.parent
MOSTRA = "scientific_initiation"


def _png(width: int = 200, height: int = 120, color: str = "white") -> str:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _text(key: str, **extra) -> dict:
    return {
        "type": "text",
        "key": key,
        "x": 20,
        "y": 20,
        "fontSize": 18,
        "fontFamily": "Times New Roman",
        "color": "#000000",
        "align": "left",
        "bold": False,
        "italic": False,
        **extra,
    }


def _layout(elements: list[dict] | None = None, *, background: str | None = None) -> dict:
    return {
        "background": background or _png(),
        "image_width": 200,
        "image_height": 120,
        "elements": elements if elements is not None else [_text("name")],
    }


def _create(client, name: str = "Modelo A", **extra) -> dict:
    response = client.post("/templates", json={"name": name, "layout": _layout(), **extra})
    assert response.status_code == 200, response.text
    return response.json()


def _save(client, template: dict, **changes) -> dict:
    response = client.put(
        f"/templates/{template['id']}", json={"revision": template["revision"], **changes}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _issue_with(template: dict, code: str) -> dict:
    """A synthetic certificate issued with the model's current revision."""
    db.insert_certificates(
        [
            {
                "unique_code": code,
                "participant_name": "Pessoa Exemplo Alfa",
                "event_name": "Evento Sintético",
                "issue_date": "2026-08-15",
                "template_used": f"v{template['version_number']}",
                "template_version_id": template["current_version_id"],
                "template_snapshot": json.dumps(template["layout"]),
                "institutional_snapshot": json.dumps(
                    {
                        "institution_name": "Instituição",
                        "issue_location": "Cidade",
                        "signatory_name": "Assinante",
                        "signatory_title": "Cargo",
                        "public_url": "https://certificados.example.test",
                    }
                ),
            }
        ]
    )
    cert = db.get_by_code(code)
    assert cert is not None
    return cert


def _course_id(client, name: str) -> int:
    courses = client.get("/courses").json()
    return next(course["id"] for course in courses if course["name"] == name)


# ── Saving ────────────────────────────────────────────────────────────────────


def test_saving_a_model_without_certificates_changes_the_same_revision(client, auth_headers):
    template = _create(client, "Rascunho")
    before = db.get_template_version(template["current_version_id"])
    assert before is not None

    saved = _save(client, template, layout=_layout([_text("event", x=40)]))

    assert saved["outcome"] == "updated"
    assert saved["current_version_id"] == template["current_version_id"]
    assert saved["version_number"] == template["version_number"]
    assert saved["revision"] == template["revision"] + 1
    after = db.get_template_version(template["current_version_id"])
    assert after is not None
    assert json.loads(after["layout_json"])["elements"][0]["key"] == "event"
    assert len(client.get(f"/templates/{template['id']}/history").json()) == 1


def test_saving_a_model_with_certificates_adds_a_revision_and_keeps_the_old_layout(
    client, auth_headers
):
    template = _create(client, "Em uso")
    cert = _issue_with(template, "CERT-2026-MODEL1")
    original_version = template["current_version_id"]

    saved = _save(client, template, layout=_layout([_text("event", x=40)]))

    assert saved["outcome"] == "revised"
    assert saved["current_version_id"] != original_version
    assert saved["version_number"] == template["version_number"] + 1
    # Same item in the list, two revisions in its history.
    assert [item["id"] for item in client.get("/templates").json()].count(template["id"]) == 1
    history = client.get(f"/templates/{template['id']}/history").json()
    assert [entry["id"] for entry in history] == [saved["current_version_id"], original_version]
    assert history[0]["is_current"] is True and history[1]["is_current"] is False
    # The certificate still points at the layout it was issued with.
    stored = db.get_by_code(cert["unique_code"])
    assert stored is not None
    assert stored["template_version_id"] == original_version
    untouched = db.get_template_version(original_version)
    assert untouched is not None
    assert json.loads(untouched["layout_json"])["elements"][0]["key"] == "name"


def test_a_model_that_was_ever_active_also_gains_a_revision(client, auth_headers):
    template = _create(client, "Já ativo", certificate_type=MOSTRA)
    # Fit for the Mostra, so it can be activated, then another one takes over.
    template = _save(
        client,
        template,
        layout=_layout([_text("texto_certificado"), _text("authors", anchorY="bottom")]),
    )
    assert client.post(f"/templates/{template['id']}/activate").status_code == 200
    other = _create(client, "Outro Mostra", certificate_type=MOSTRA)
    other = _save(
        client,
        other,
        layout=_layout([_text("texto_certificado"), _text("authors", anchorY="bottom")]),
    )
    assert client.post(f"/templates/{other['id']}/activate").status_code == 200

    current = client.get(f"/templates/{template['id']}").json()
    assert current["is_active"] is False and current["ever_activated"] is True
    saved = _save(client, current, layout=_layout([_text("texto_certificado", x=50)]))
    assert saved["outcome"] == "revised"
    assert saved["current_version_id"] != current["current_version_id"]


def test_name_and_course_change_without_a_new_revision(client, auth_headers):
    template = _create(client, "Antes")
    _issue_with(template, "CERT-2026-MODEL2")
    direito = _course_id(client, "Direito")

    saved = _save(client, template, name="Depois", course_id=direito)

    assert saved["outcome"] == "unchanged"
    assert saved["name"] == "Depois"
    assert saved["course_id"] == direito and saved["course_name"] == "Direito"
    assert saved["current_version_id"] == template["current_version_id"]


def test_saving_the_active_model_requires_the_apply_confirmation(client, auth_headers):
    active = next(item for item in client.get("/templates").json() if item["is_active"])
    detail = client.get(f"/templates/{active['id']}").json()
    new_layout = _layout([_text("event", x=55)], background=detail["layout"]["background"])

    refused = client.put(
        f"/templates/{active['id']}", json={"revision": detail["revision"], "layout": new_layout}
    )
    assert refused.status_code == 409
    assert "aplicar" in refused.json()["detail"].lower()
    # Nothing changed.
    assert client.get(f"/templates/{active['id']}").json()["revision"] == detail["revision"]

    applied = client.put(
        f"/templates/{active['id']}",
        json={"revision": detail["revision"], "layout": new_layout, "apply": True},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["outcome"] == "applied"
    assert body["is_active"] is True
    assert body["current_version_id"] != detail["current_version_id"]
    # The next emissions use the new revision; the old one is history.
    assert template_service.get_active_version()["id"] == body["current_version_id"]
    history = client.get(f"/templates/{active['id']}/history").json()
    assert history[1]["id"] == detail["current_version_id"] and history[1]["is_active"] is False


def test_a_stale_editor_is_refused_instead_of_overwriting(client, auth_headers):
    template = _create(client, "Concorrente")
    first = _save(client, template, name="Primeira pessoa")
    assert first["revision"] == template["revision"] + 1

    second = client.put(
        f"/templates/{template['id']}",
        json={"revision": template["revision"], "name": "Segunda pessoa"},
    )
    assert second.status_code == 409
    assert "alterado por outra pessoa" in second.json()["detail"]
    assert client.get(f"/templates/{template['id']}").json()["name"] == "Primeira pessoa"


def test_the_type_locks_once_the_model_issued_or_was_active(client, auth_headers):
    template = _create(client, "Tipo livre")
    changed = _save(client, template, certificate_type="listener")
    assert changed["certificate_type"] == "listener" and changed["type_locked"] is False

    _issue_with(changed, "CERT-2026-MODEL3")
    locked = client.get(f"/templates/{template['id']}").json()
    assert locked["type_locked"] is True
    refused = client.put(
        f"/templates/{template['id']}",
        json={"revision": locked["revision"], "certificate_type": "speaker"},
    )
    assert refused.status_code == 409
    assert "Duplique" in refused.json()["detail"]


def test_applying_an_unfit_mostra_layout_is_refused(client, auth_headers):
    template = _create(client, "Mostra", certificate_type=MOSTRA)
    # Activation itself refuses a layout that would block the Mostra emission.
    blocked = client.post(f"/templates/{template['id']}/activate")
    assert blocked.status_code == 400
    assert "bloquearia a emissão" in blocked.json()["detail"]

    fit = _save(
        client,
        template,
        layout=_layout([_text("texto_certificado"), _text("authors", anchorY="bottom")]),
    )
    assert client.post(f"/templates/{template['id']}/activate").status_code == 200
    current = client.get(f"/templates/{template['id']}").json()
    assert current["is_active"] is True
    refused = client.put(
        f"/templates/{template['id']}",
        json={"revision": current["revision"], "layout": _layout([_text("name")]), "apply": True},
    )
    assert refused.status_code == 400
    assert "Nome do participante" in refused.json()["detail"]
    assert template_service.get_active_version(MOSTRA)["id"] == fit["current_version_id"]


# ── Duplicating, deleting, archiving, restoring ───────────────────────────────


def test_duplicate_creates_an_inactive_copy_with_the_same_type_and_course(client, auth_headers):
    direito = _course_id(client, "Direito")
    source = _create(client, "Original", certificate_type="listener", course_id=direito)
    source = _save(client, source, layout=_layout([_text("event", x=70)]))

    response = client.post(f"/templates/{source['id']}/duplicate")
    assert response.status_code == 200, response.text
    copy = response.json()

    assert copy["id"] != source["id"]
    assert copy["name"] == "Cópia de Original"
    assert copy["is_active"] is False
    assert copy["certificate_type"] == "listener" and copy["course_id"] == direito
    assert copy["layout"]["elements"] == source["layout"]["elements"]
    assert copy["current_version_id"] != source["current_version_id"]
    assert copy["edits_in_place"] is True


def test_duplicate_from_history_copies_an_older_revision(client, auth_headers):
    template = _create(client, "Com histórico")
    _issue_with(template, "CERT-2026-MODEL4")
    newer = _save(client, template, layout=_layout([_text("event", x=40)]))
    old_version = template["current_version_id"]
    assert newer["current_version_id"] != old_version

    response = client.post(
        f"/templates/{template['id']}/duplicate",
        json={"version_id": old_version, "name": "Resgate"},
    )
    assert response.status_code == 200, response.text
    copy = response.json()
    assert copy["name"] == "Resgate"
    assert copy["layout"]["elements"][0]["key"] == "name"

    foreign = client.post(f"/templates/{copy['id']}/duplicate", json={"version_id": old_version})
    assert foreign.status_code == 404


def test_delete_removes_a_model_without_certificates(client, auth_headers):
    template = _create(client, "Descartável")
    version_id = template["current_version_id"]

    response = client.delete(f"/templates/{template['id']}")
    assert response.status_code == 200, response.text
    assert response.json() == {"outcome": "deleted", "template_id": template["id"]}
    assert client.get(f"/templates/{template['id']}").status_code == 404
    assert db.get_template_version(version_id) is None


def test_delete_archives_a_model_with_certificates_and_everything_keeps_working(
    client, auth_headers, monkeypatch, tmp_path
):
    template = _create(client, "Histórico")
    cert = _issue_with(template, "CERT-2026-MODEL5")

    response = client.delete(f"/templates/{template['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "archived"

    # Gone from the list, still in the database, visible with the filter.
    assert template["id"] not in [item["id"] for item in client.get("/templates").json()]
    archived = client.get("/templates", params={"include_archived": "true"}).json()
    row = next(item for item in archived if item["id"] == template["id"])
    assert row["is_archived"] is True and row["certificate_count"] == 1
    assert db.get_template_version(template["current_version_id"]) is not None

    # Public validation and the reissue keep working on the archived model.
    public = client.get(f"/certificates/{cert['unique_code']}")
    assert public.status_code == 200
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    service = build_certificate_service()
    service.reissue_certificate(db.get_by_code(cert["unique_code"]), reissued_by=1)
    reissued = db.get_by_code(cert["unique_code"])
    assert reissued is not None
    assert reissued["template_version_id"] == template["current_version_id"]
    assert reissued["reissue_count"] == 1

    # Archived models cannot be edited or activated until restored.
    edit = client.put(f"/templates/{template['id']}", json={"name": "x"})
    assert edit.status_code == 409
    assert client.post(f"/templates/{template['id']}/activate").status_code == 409

    restored = client.post(f"/templates/{template['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["is_archived"] is False
    assert template["id"] in [item["id"] for item in client.get("/templates").json()]


def test_the_active_model_cannot_be_deleted_or_archived(client, auth_headers):
    active = next(item for item in client.get("/templates").json() if item["is_active"])
    _create(client, "Outro")  # so the "only model" rule is not what refuses

    response = client.delete(f"/templates/{active['id']}")
    assert response.status_code == 409
    assert "ativo" in response.json()["detail"]
    assert client.get(f"/templates/{active['id']}").json()["is_archived"] is False


def test_the_only_model_cannot_be_deleted(client, auth_headers):
    # The default model is active; make a second one active so the first is
    # inactive and alone would be deletable but for the rule.
    other = _create(client, "Único candidato")
    assert client.post(f"/templates/{other['id']}/activate").status_code == 200
    default = next(item for item in client.get("/templates").json() if not item["is_active"])
    assert client.delete(f"/templates/{default['id']}").status_code == 200

    # Now "other" is the only model and active: refused as active first.
    assert client.delete(f"/templates/{other['id']}").status_code == 409


def test_delete_waits_for_a_running_batch_when_the_model_was_active(client, auth_headers):
    template = _create(client, "Foi ativo")
    assert client.post(f"/templates/{template['id']}/activate").status_code == 200
    successor = _create(client, "Sucessor")
    assert client.post(f"/templates/{successor['id']}/activate").status_code == 200
    db.create_emission_batch(
        {
            "id": "batch-em-andamento",
            "idempotency_key": "chave-sintetica",
            "request_sha256": "a" * 64,
            "status": "processing",
            "total_rows": 1,
            "valid_count": 1,
            "created_by": 1,
        }
    )

    response = client.delete(f"/templates/{template['id']}")
    assert response.status_code == 409
    assert "lote em andamento" in response.json()["detail"]


# ── Listing and courses ───────────────────────────────────────────────────────


def test_list_filters_by_course_type_name_and_archived(client, auth_headers):
    direito = _course_id(client, "Direito")
    pedagogia = _course_id(client, "Pedagogia")
    a = _create(client, "Direito Ouvinte", certificate_type="listener", course_id=direito)
    b = _create(client, "Pedagogia Palestrante", certificate_type="speaker", course_id=pedagogia)
    c = _create(client, "Genérico para todos")

    by_course = client.get("/templates", params={"course_id": direito}).json()
    assert [item["id"] for item in by_course] == [a["id"]]
    without_course = client.get("/templates", params={"without_course": "true"}).json()
    assert c["id"] in [item["id"] for item in without_course]
    assert a["id"] not in [item["id"] for item in without_course]

    by_type = client.get("/templates", params={"certificate_type": "speaker"}).json()
    assert [item["id"] for item in by_type] == [b["id"]]
    generic = client.get("/templates", params={"certificate_type": "__generic__"}).json()
    assert c["id"] in [item["id"] for item in generic] and a["id"] not in [
        item["id"] for item in generic
    ]
    assert client.get("/templates", params={"certificate_type": "nope"}).status_code == 400

    by_name = client.get("/templates", params={"q": "pedagog"}).json()
    assert [item["id"] for item in by_name] == [b["id"]]

    # Active first.
    listed = client.get("/templates").json()
    assert listed[0]["is_active"] is True
    assert all(item["is_active"] is False for item in listed[1:])


def test_unknown_course_is_refused(client, auth_headers):
    response = client.post("/templates", json={"name": "x", "layout": _layout(), "course_id": 9999})
    assert response.status_code == 400
    assert "Curso não encontrado" in response.json()["detail"]


def test_courses_are_seeded_managed_and_deduplicated(client, auth_headers):
    courses = client.get("/courses").json()
    names = [course["name"] for course in courses]
    assert "Sistemas de Informação" in names and len(names) == 8

    created = client.post("/courses", json={"name": "  Engenharia   de Software "})
    assert created.status_code == 200, created.text
    assert created.json()["name"] == "Engenharia de Software"
    duplicate = client.post("/courses", json={"name": "engenharia de software"})
    assert duplicate.status_code == 409

    course_id = created.json()["id"]
    updated = client.patch(f"/courses/{course_id}", json={"is_active": False})
    assert updated.status_code == 200 and updated.json()["is_active"] is False
    active_only = client.get("/courses", params={"include_inactive": "false"}).json()
    assert course_id not in [course["id"] for course in active_only]

    renamed = client.patch(f"/courses/{course_id}", json={"name": "Direito"})
    assert renamed.status_code == 409


def test_template_mutations_are_audited(client, auth_headers):
    template = _create(client, "Auditado")
    _save(client, template, name="Auditado 2")
    client.post(f"/templates/{template['id']}/duplicate")
    client.delete(f"/templates/{template['id']}")

    page = client.get("/admin/audit", params={"category": "template"})
    assert page.status_code == 200, page.text
    actions = [row["action"] for row in page.json()["items"]]
    for expected in (
        "template_created",
        "template_saved",
        "template_duplicated",
        "template_deleted",
    ):
        assert expected in actions, actions


@pytest.mark.parametrize("role", ["secretaria", "auditor"])
def test_models_are_read_only_without_the_manage_permission(client, auth_headers, role):
    from certificados_backend import auth
    from fastapi.testclient import TestClient

    db.create_admin_user(f"{role}.teste", auth.hash_password("Senha-Sintetica-2!"), role)
    other = TestClient(client.app, base_url=str(client.base_url), headers=client.headers)
    login = other.post(
        "/auth/login", json={"username": f"{role}.teste", "password": "Senha-Sintetica-2!"}
    )
    assert login.status_code == 200, login.text
    assert other.post("/templates", json={"name": "x", "layout": _layout()}).status_code == 403
    assert other.delete("/templates/1").status_code == 403
