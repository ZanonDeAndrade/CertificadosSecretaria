"""Tests for the spreadsheet model: column normalisation, validation, business key."""

from __future__ import annotations

import pandas as pd
import pytest
from certificados_backend.services import spreadsheet
from certificados_backend.services.spreadsheet import SpreadsheetError, compute_business_key

EMAIL = "ana.souza@exemplo.com"


def _xlsx(tmp_path, rows, name="in.xlsx"):
    path = tmp_path / name
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


def test_valid_row_with_synonym_headers(tmp_path):
    path = _xlsx(
        tmp_path,
        [
            {
                "Nome Completo": "Ana Souza",
                "E-mail": " Ana.Souza@Exemplo.com ",
                "Curso": "Direito",
                "Evento": "Semana Jurídica",
                "Carga Horária": "40h",
                "Data de Emissão": "10/06/2026",
            }
        ],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 1
    row = report.valid[0]
    assert row.nome == "Ana Souza"
    # Normalised: lower case, no surrounding spaces.
    assert row.email == EMAIL
    assert row.emails == (EMAIL,)
    assert row.curso == "Direito"
    assert row.evento == "Semana Jurídica"  # evento != curso
    assert row.carga_horaria == 40  # structured int
    assert row.data_emissao == "10 de junho de 2026"


def test_registro_academico_header_populates_private_confirmation_field(tmp_path):
    path = _xlsx(
        tmp_path,
        [{"nome": "Ana Souza", "email": EMAIL, "registro_academico": "RA-2026-42"}],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 1
    assert report.valid[0].documento == "RA-2026-42"


def test_event_is_not_course(tmp_path):
    path = _xlsx(
        tmp_path,
        [
            {
                "nome": "X",
                "email": EMAIL,
                "curso": "Pedagogia",
                "evento": "Congresso",
                "carga_horaria": 8,
                "data_emissao": "01/02/2026",
            }
        ],
    )
    report = spreadsheet.read_and_validate(path)
    row = report.valid[0]
    assert row.curso == "Pedagogia"
    assert row.evento == "Congresso"


def test_unknown_course_is_kept_not_rejected(tmp_path):
    # curso is optional now: an unknown course is kept (raw), not rejected.
    path = _xlsx(
        tmp_path,
        [{"nome": "X", "email": EMAIL, "curso": "Curso Inexistente", "carga_horaria": 8}],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 1
    assert report.invalid_count == 0
    assert report.valid[0].curso == "Curso Inexistente"


def test_invalid_workload_is_rejected_but_bad_date_is_lenient(tmp_path):
    path = _xlsx(
        tmp_path,
        [{"nome": "X", "email": EMAIL, "carga_horaria": "abc", "data_emissao": "32/13/2026"}],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 0
    errors = report.invalid[0].errors
    assert any("carga_horaria" in e for e in errors)
    # The unparseable date is optional now → it never blocks the row.
    assert not any("data_emissao" in e for e in errors)


def test_only_name_and_email_are_required(tmp_path):
    # A minimal sheet (just name + e-mail) is valid; the rest, workload
    # included, is empty.
    path = _xlsx(tmp_path, [{"nome": "Ana", "email": EMAIL}])
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 1
    row = report.valid[0]
    assert row.nome == "Ana" and row.email == EMAIL
    assert row.carga_horaria is None
    assert row.curso == "" and row.evento == "" and row.data_emissao == ""


def test_missing_name_or_email_is_invalid(tmp_path):
    path = _xlsx(
        tmp_path,
        [
            {"nome": "", "email": EMAIL, "carga_horaria": 10},  # missing name
            {"nome": "Bia", "email": "", "carga_horaria": 10},  # missing e-mail
            {"nome": "Caio", "email": EMAIL, "carga_horaria": ""},  # blank workload is fine
        ],
    )
    report = spreadsheet.read_and_validate(path)
    assert [row.errors for row in report.invalid] == [
        ["nome é obrigatório"],
        ["email é obrigatório"],
    ]
    assert [row.nome for row in report.valid] == ["Caio"]
    assert report.valid[0].carga_horaria is None


@pytest.mark.parametrize("value", ["ana@", "ana@dominio", "ana exemplo.com", "@exemplo.com"])
def test_invalid_email_is_rejected(tmp_path, value):
    path = _xlsx(tmp_path, [{"nome": "Ana", "email": value}])
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 0
    assert report.invalid[0].errors == ["email inválido"]


def test_email_is_normalised_to_lower_case_without_spaces(tmp_path):
    path = _xlsx(tmp_path, [{"nome": "Ana", "email": " Ana. Souza @Exemplo.COM "}])
    report = spreadsheet.read_and_validate(path)
    assert report.valid[0].email == "ana.souza@exemplo.com"


def test_extra_unknown_columns_are_ignored(tmp_path):
    path = _xlsx(
        tmp_path,
        [{"nome": "Ana", "email": EMAIL, "carga_horaria": 8, "departamento": "RH", "obs": "vip"}],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 1
    assert report.valid[0].nome == "Ana"


def test_missing_required_column_raises(tmp_path):
    # No email column at all → whole-file error naming it.
    path = _xlsx(tmp_path, [{"nome": "X", "curso": "Direito", "carga_horaria": 8}])
    with pytest.raises(SpreadsheetError, match="ausentes na planilha: email$"):
        spreadsheet.read_and_validate(path)
    # No carga_horaria column is fine now.
    report = spreadsheet.read_and_validate(_xlsx(tmp_path, [{"nome": "X", "email": EMAIL}]))
    assert report.valid_count == 1


def test_default_data_emissao_fallback(tmp_path):
    # No data_emissao column, but a default is provided → valid.
    path = _xlsx(
        tmp_path,
        [{"nome": "X", "email": EMAIL, "curso": "Direito", "evento": "E", "carga_horaria": 10}],
    )
    report = spreadsheet.read_and_validate(path, default_data_emissao="05/05/2026")
    assert report.valid_count == 1
    assert report.valid[0].data_emissao == "5 de maio de 2026"


def test_max_rows_enforced(tmp_path):
    rows = [
        {
            "nome": f"P{i}",
            "email": f"p{i}@exemplo.com",
            "curso": "Direito",
            "evento": "E",
            "carga_horaria": 8,
            "data_emissao": "01/02/2026",
        }
        for i in range(5)
    ]
    path = _xlsx(tmp_path, rows)
    with pytest.raises(SpreadsheetError):
        spreadsheet.read_and_validate(path, max_rows=3)


def test_blank_rows_are_skipped(tmp_path):
    path = _xlsx(
        tmp_path,
        [
            {
                "nome": "Ana",
                "email": EMAIL,
                "curso": "Direito",
                "evento": "E",
                "carga_horaria": 8,
                "data_emissao": "01/02/2026",
            },
            {
                "nome": "",
                "email": "",
                "curso": "",
                "evento": "",
                "carga_horaria": "",
                "data_emissao": "",
            },
        ],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.total == 1


def test_business_key_is_stable_distinct_and_ignores_the_email(tmp_path):
    path = _xlsx(
        tmp_path,
        [
            {
                "nome": "Ana Souza",
                "email": EMAIL,
                "curso": "Direito",
                "evento": "Sem. Jur",
                "carga_horaria": 40,
                "data_emissao": "10/06/2026",
            },
            {
                "nome": "Ana Souza",
                "email": EMAIL,
                "curso": "Direito",
                "evento": "Outro Evento",
                "carga_horaria": 40,
                "data_emissao": "10/06/2026",
            },
            {
                "nome": "Ana Souza",
                "email": "outro.endereco@exemplo.com",
                "curso": "Direito",
                "evento": "Sem. Jur",
                "carga_horaria": 40,
                "data_emissao": "10/06/2026",
            },
        ],
    )
    report = spreadsheet.read_and_validate(path)
    k1 = compute_business_key(report.valid[0])
    k2 = compute_business_key(report.valid[1])
    k3 = compute_business_key(report.valid[2])
    assert k1 != k2  # different event → different key
    # Stable: recomputing yields the same value.
    assert compute_business_key(report.valid[0]) == k1
    # The e-mail is not part of the key: an old spreadsheet re-sent with the
    # e-mail column added still does not duplicate certificates.
    assert k3 == k1
