"""Administrative rename/delete contracts for immutable template versions."""

from __future__ import annotations

import base64
from io import BytesIO

from certificados_backend.services import template_service


def _layout() -> dict:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (200, 120), "white").save(buffer, "PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {
        "background": f"data:image/png;base64,{encoded}",
        "image_width": 200,
        "image_height": 120,
        "elements": [],
    }


def test_activation_and_rename_work_through_admin_api(client, auth_headers):
    version = template_service.create_version(name="Rascunho", layout=_layout())

    activated = client.post(f"/templates/versions/{version['id']}/activate")
    assert activated.status_code == 200, activated.text
    assert activated.json()["is_active"] is True

    renamed = client.patch(
        f"/templates/versions/{version['id']}", json={"name": "Modelo institucional 2026"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Modelo institucional 2026"
    assert renamed.json()["layout"] == version["layout"]


def test_delete_allows_only_inactive_unreferenced_version(client, auth_headers):
    from database import db

    unused = template_service.create_version(name="Descartável", layout=_layout())
    deleted = client.delete(f"/templates/versions/{unused['id']}")
    assert deleted.status_code == 200, deleted.text
    assert db.get_template_version(unused["id"]) is None

    active = template_service.get_active_version()
    assert active is not None
    blocked = client.delete(f"/templates/versions/{active['id']}")
    assert blocked.status_code == 409
    assert "ativa" in blocked.json()["detail"]


def test_delete_preserves_version_referenced_by_certificate(client, auth_headers):
    from database import db

    referenced = template_service.create_version(name="Histórica", layout=_layout())
    db.insert_certificates(
        [
            {
                "unique_code": "CERT-2026-HIST01",
                "participant_name": "Pessoa Sintética",
                "event_name": "Evento Sintético",
                "issue_date": "15 de agosto de 2026",
                "template_version_id": referenced["id"],
                "template_snapshot": "{}",
            }
        ]
    )

    blocked = client.delete(f"/templates/versions/{referenced['id']}")
    assert blocked.status_code == 409
    assert "certificados emitidos" in blocked.json()["detail"]
    assert db.get_template_version(referenced["id"]) is not None


def test_rename_rejects_blank_name(client, auth_headers):
    active = template_service.get_active_version()
    assert active is not None
    response = client.patch(f"/templates/versions/{active['id']}", json={"name": "   "})
    assert response.status_code == 400
    assert response.json()["detail"] == "Informe um nome para a versão."
