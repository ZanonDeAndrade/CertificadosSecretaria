"""The e-mail on the spreadsheet: required, validated, hashed, never shown.

Ordinary types require ``nome`` and ``email``; the Mostra requires one e-mail
per author. The workload is optional everywhere, except that a body text
printing ``{{carga_horaria}}`` refuses the rows without one. Every e-mail of
a row ends up as a keyed hash on the certificate and nowhere else.
"""

from __future__ import annotations

import io
from io import BytesIO
from itertools import count

import pandas as pd
from openpyxl import load_workbook

from database import db

MOSTRA = "scientific_initiation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_KEYS = count(1)
PRIVATE_EMAIL = "marcador.privado@exemplo.com"


def _xlsx(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return buffer.getvalue()


def _files(rows: list[dict]) -> dict:
    return {"file": ("lote.xlsx", _xlsx(rows), XLSX_MIME)}


def _text(text: str | None, certificate_type: str) -> str:
    """An ordinary batch needs a body; the Mostra may leave it blank (automatic)."""
    if text is not None:
        return text
    return "" if certificate_type == MOSTRA else "participou do evento."


def _preview(
    client, rows: list[dict], *, text: str | None = None, certificate_type: str = "listener"
):
    return client.post(
        "/certificates/validate-spreadsheet",
        files=_files(rows),
        data={"texto_padrao": _text(text, certificate_type), "certificate_type": certificate_type},
    )


def _issue(
    client, rows: list[dict], *, text: str | None = None, certificate_type: str = "listener"
) -> dict:
    """Start a batch; in tests it runs to the end before the response returns."""
    response = client.post(
        "/emission-batches",
        files=_files(rows),
        data={
            "texto_padrao": _text(text, certificate_type),
            "certificate_type": certificate_type,
            "drive_folders_json": "{}",
        },
        headers={"Idempotency-Key": f"email-contract-{next(_KEYS):06d}"},
    )
    assert response.status_code == 202, response.text
    return response.json()


def _work(*authors: str, **extra) -> dict:
    row: dict = {}
    for index, name in enumerate(authors, start=1):
        row[f"autor{index}"] = name
        row[f"email{index}"] = f"autor{index}@exemplo.com"
    row.update(evento="Mostra 2026", titulo_trabalho="Horta vertical automatizada")
    row.update(extra)
    return row


# ── Validation ────────────────────────────────────────────────────────────────


def test_name_and_email_are_enough_and_the_workload_may_be_blank(client, auth_headers):
    preview = _preview(client, [{"nome": "Ana Souza", "email": "Ana.Souza@Exemplo.com"}])
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["valid_count"] == 1 and body["invalid"] == []
    assert body["valid"][0]["carga_horaria"] is None
    # The preview carries no e-mail, normalised or not.
    assert "exemplo.com" not in preview.text


def test_spreadsheet_without_an_email_column_is_refused(client, auth_headers):
    preview = _preview(client, [{"nome": "Ana Souza", "carga_horaria": 8}])
    assert preview.status_code == 400
    assert preview.json()["detail"] == "Colunas obrigatórias ausentes na planilha: email"


def test_blank_or_invalid_email_invalidates_the_row(client, auth_headers):
    preview = _preview(
        client,
        [
            {"nome": "Ana", "email": ""},
            {"nome": "Bia", "email": "bia@exemplo"},
            {"nome": "Caio", "email": "caio@exemplo.com"},
        ],
    )
    body = preview.json()
    assert [row["errors"] for row in body["invalid"]] == [
        ["email é obrigatório"],
        ["email inválido"],
    ]
    assert [row["nome"] for row in body["valid"]] == ["Caio"]


def test_text_using_the_workload_refuses_rows_without_it(client, auth_headers):
    rows = [
        {"nome": "Ana", "email": "ana@exemplo.com", "carga_horaria": 8},
        {"nome": "Bia", "email": "bia@exemplo.com", "carga_horaria": ""},
    ]
    preview = _preview(client, rows, text="participou com {{carga_horaria}} horas.")
    body = preview.json()
    assert body["valid_count"] == 1 and body["invalid_count"] == 1
    assert body["invalid"][0]["row_number"] == 3
    assert body["invalid"][0]["errors"] == [
        "carga_horaria vazia, mas o texto do certificado usa {{carga_horaria}}"
    ]
    # Not a warning any more: the row is out.
    assert body["empty_fields"] == []

    # Without the variable the same row is fine and the text has no gap.
    free = _preview(client, rows, text="participou do evento.")
    assert free.json()["invalid"] == []

    # The API keeps the row out of the batch too.
    batch = _issue(client, rows, text="participou com {{carga_horaria}} horas.")
    assert batch["invalid_count"] == 1
    names = {item["participant_name"] for item in client.get("/certificates").json()["items"]}
    assert names == {"Ana"}


def test_mostra_requires_one_email_per_author(client, auth_headers, mostra_template):
    authors = ("Pessoa Exemplo Alfa", "Pessoa Exemplo Beta", "Pessoa Exemplo Gama")
    preview = _preview(
        client,
        [
            _work(*authors),
            {**_work(*authors), "email2": ""},
            {**_work(authors[0]), "email3": "sem.autor@exemplo.com"},
            {**_work(*authors), "email3": "gama@exemplo"},
        ],
        certificate_type=MOSTRA,
    )
    body = preview.json()
    assert body["valid_count"] == 1
    assert [row["errors"] for row in body["invalid"]] == [
        ["email2 é obrigatório (autor2)"],
        ["email3 preenchido sem autor3"],
        ["email3 inválido"],
    ]
    # ``email`` stands in for ``email1`` only when the numbered column is absent.
    only_email = _preview(
        client,
        [{"autor1": authors[0], "email": "alfa@exemplo.com", **_work()}],
        certificate_type=MOSTRA,
    )
    assert only_email.json()["invalid"] == []
    missing = _preview(client, [{"autor1": authors[0], **_work()}], certificate_type=MOSTRA)
    assert missing.status_code == 400
    assert "email1" in missing.json()["detail"]


# ── The model workbook ────────────────────────────────────────────────────────


def test_model_workbooks_require_the_email_and_explain_it(client, auth_headers):
    ordinary = load_workbook(BytesIO(client.get("/certificates/spreadsheet-template").content))
    headers = [cell.value for cell in ordinary["certificados"][1]]
    assert headers[:3] == ["nome", "email", "carga_horaria"]
    guide = list(ordinary["Instruções"].iter_rows(values_only=True))
    assert any(line[0] and "consulta pública" in str(line[0]) for line in guide)
    table = guide[guide.index(("Coluna", "Obrigatória", "O que preencher", "Exemplo")) + 1 :]
    assert {line[0] for line in table if line[1] == "Sim"} == {"nome", "email"}

    mostra = load_workbook(
        BytesIO(
            client.get(
                "/certificates/spreadsheet-template", params={"certificate_type": MOSTRA}
            ).content
        )
    )
    headers = [cell.value for cell in mostra["certificados"][1]]
    assert headers[:4] == ["autor1", "email1", "autor2", "email2"]
    guide = list(mostra["Instruções"].iter_rows(values_only=True))
    assert any(
        line[0] and "e-mail na coluna email de mesmo número" in str(line[0]) for line in guide
    )


# ── What the certificate keeps ────────────────────────────────────────────────


def test_issued_certificate_keeps_only_keyed_hashes_of_every_email(
    client, auth_headers, mostra_template
):
    _issue(client, [{"nome": "Ana Souza", "email": f" {PRIVATE_EMAIL.upper()} "}])
    authors = ("Pessoa Exemplo Alfa", "Pessoa Exemplo Beta", "Pessoa Exemplo Gama")
    _issue(client, [_work(*authors)], certificate_type=MOSTRA)

    from database.privacy import email_hash

    items = {item["participant_name"]: item for item in client.get("/certificates").json()["items"]}
    ordinary = db.get_by_code(items["Ana Souza"]["unique_code"])
    rows = db.certificate_email_hashes(int(ordinary["id"]))
    assert [(row["position"], row["hash_key_id"]) for row in rows] == [(1, "v1")]
    # Hashed after normalisation, under the active key, never the plain text.
    assert rows[0]["email_hash"] == email_hash(PRIVATE_EMAIL)
    assert PRIVATE_EMAIL not in str(rows)
    # The holder's plain e-mail stays on the record for the secretariat, as before.
    assert ordinary["participant_email"] == PRIVATE_EMAIL

    work = db.get_by_code(items[authors[0]]["unique_code"])
    hashes = db.certificate_email_hashes(int(work["id"]))
    assert [row["position"] for row in hashes] == [1, 2, 3]
    assert [row["email_hash"] for row in hashes] == [
        email_hash(f"autor{index}@exemplo.com") for index in (1, 2, 3)
    ]
    # Co-authors' e-mails exist only as hashes.
    assert "autor2@exemplo.com" not in str(work)


def test_email_never_reaches_audit_logs_batch_results_or_error_reports(
    client, auth_headers, caplog
):
    rows = [
        {"nome": "Pessoa Marcadora", "email": PRIVATE_EMAIL},
        {"nome": "", "email": PRIVATE_EMAIL},
    ]
    with caplog.at_level("INFO"):
        preview = _preview(client, rows)
        batch = _issue(client, rows)
        status = client.get(f"/emission-batches/{batch.get('batch_id') or batch['id']}")
    assert status.status_code == 200
    audit = client.get("/admin/audit")
    assert audit.status_code == 200
    for body in (preview.text, str(batch), status.text, audit.text):
        assert PRIVATE_EMAIL not in body
        assert "marcador.privado" not in body
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert PRIVATE_EMAIL not in rendered_logs
    assert "marcador.privado" not in rendered_logs
