"""Tests for the spreadsheet model: column normalisation, validation, business key."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from services import spreadsheet
from services.spreadsheet import SpreadsheetError, compute_business_key


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
    assert row.curso == "Direito"
    assert row.evento == "Semana Jurídica"  # evento != curso
    assert row.carga_horaria == 40  # structured int
    assert row.data_emissao == "10 de junho de 2026"


def test_event_is_not_course(tmp_path):
    path = _xlsx(
        tmp_path,
        [{"nome": "X", "curso": "Pedagogia", "evento": "Congresso", "carga_horaria": 8,
          "data_emissao": "01/02/2026"}],
    )
    report = spreadsheet.read_and_validate(path)
    row = report.valid[0]
    assert row.curso == "Pedagogia"
    assert row.evento == "Congresso"


def test_unknown_course_is_kept_not_rejected(tmp_path):
    # curso is optional now: an unknown course is kept (raw), not rejected.
    path = _xlsx(
        tmp_path,
        [{"nome": "X", "curso": "Curso Inexistente", "carga_horaria": 8}],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 1
    assert report.invalid_count == 0
    assert report.valid[0].curso == "Curso Inexistente"


def test_invalid_workload_is_rejected_but_bad_date_is_lenient(tmp_path):
    path = _xlsx(
        tmp_path,
        [{"nome": "X", "carga_horaria": "abc", "data_emissao": "32/13/2026"}],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 0
    errors = report.invalid[0].errors
    assert any("carga_horaria" in e for e in errors)
    # The unparseable date is optional now → it never blocks the row.
    assert not any("data_emissao" in e for e in errors)


def test_only_name_and_workload_are_required(tmp_path):
    # A minimal sheet (just name + workload) is valid; the rest is empty.
    path = _xlsx(tmp_path, [{"nome": "Ana", "carga_horaria": "20h"}])
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 1
    row = report.valid[0]
    assert row.nome == "Ana" and row.carga_horaria == 20
    assert row.curso == "" and row.evento == "" and row.data_emissao == ""


def test_missing_name_or_workload_is_invalid(tmp_path):
    path = _xlsx(
        tmp_path,
        [
            {"nome": "", "carga_horaria": 10},     # missing name
            {"nome": "Bia", "carga_horaria": ""},  # missing workload
        ],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 0
    assert report.invalid_count == 2


def test_extra_unknown_columns_are_ignored(tmp_path):
    path = _xlsx(
        tmp_path,
        [{"nome": "Ana", "carga_horaria": 8, "departamento": "RH", "obs": "vip"}],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.valid_count == 1
    assert report.valid[0].nome == "Ana"


def test_missing_required_column_raises(tmp_path):
    # No carga_horaria column at all → whole-file error.
    path = _xlsx(tmp_path, [{"nome": "X", "curso": "Direito"}])
    with pytest.raises(SpreadsheetError):
        spreadsheet.read_and_validate(path)


def test_default_data_emissao_fallback(tmp_path):
    # No data_emissao column, but a default is provided → valid.
    path = _xlsx(
        tmp_path,
        [{"nome": "X", "curso": "Direito", "evento": "E", "carga_horaria": 10}],
    )
    report = spreadsheet.read_and_validate(path, default_data_emissao="05/05/2026")
    assert report.valid_count == 1
    assert report.valid[0].data_emissao == "5 de maio de 2026"


def test_max_rows_enforced(tmp_path):
    rows = [
        {"nome": f"P{i}", "curso": "Direito", "evento": "E", "carga_horaria": 8,
         "data_emissao": "01/02/2026"}
        for i in range(5)
    ]
    path = _xlsx(tmp_path, rows)
    with pytest.raises(SpreadsheetError):
        spreadsheet.read_and_validate(path, max_rows=3)


def test_blank_rows_are_skipped(tmp_path):
    path = _xlsx(
        tmp_path,
        [
            {"nome": "Ana", "curso": "Direito", "evento": "E", "carga_horaria": 8,
             "data_emissao": "01/02/2026"},
            {"nome": "", "curso": "", "evento": "", "carga_horaria": "", "data_emissao": ""},
        ],
    )
    report = spreadsheet.read_and_validate(path)
    assert report.total == 1


def test_business_key_is_stable_and_distinct(tmp_path):
    path = _xlsx(
        tmp_path,
        [
            {"nome": "Ana Souza", "curso": "Direito", "evento": "Sem. Jur",
             "carga_horaria": 40, "data_emissao": "10/06/2026"},
            {"nome": "Ana Souza", "curso": "Direito", "evento": "Outro Evento",
             "carga_horaria": 40, "data_emissao": "10/06/2026"},
        ],
    )
    report = spreadsheet.read_and_validate(path)
    k1 = compute_business_key(report.valid[0])
    k2 = compute_business_key(report.valid[1])
    assert k1 != k2  # different event → different key
    # Stable: recomputing yields the same value.
    assert compute_business_key(report.valid[0]) == k1
