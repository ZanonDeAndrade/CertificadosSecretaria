"""The model workbook download must be a complete, self-delimiting response.

A browser only finishes a download when it knows where the body ends. The
workbook used to go out as a chunked stream without ``Content-Length``; the
download then depended on the terminating chunk surviving every proxy on the
way, and Chrome could keep it as ``.crdownload`` for good. These contracts
pin the response shape so that cannot come back unnoticed.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import load_workbook

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.parametrize("params", [{}, {"certificate_type": "scientific_initiation"}])
def test_spreadsheet_template_is_one_complete_response(client, auth_headers, params):
    response = client.get("/certificates/spreadsheet-template", params=params)

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX
    assert response.headers["content-disposition"] == (
        'attachment; filename="modelo-certificados.xlsx"'
    )
    # Declared length, no chunked framing: the end of the file is explicit.
    assert response.headers["content-length"] == str(len(response.content))
    assert "transfer-encoding" not in response.headers
    assert len(response.content) > 0

    workbook = load_workbook(BytesIO(response.content))
    assert workbook.sheetnames == ["certificados", "Instruções"]


def test_spreadsheet_template_is_never_cached(client, auth_headers):
    response = client.get("/certificates/spreadsheet-template")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"


def test_spreadsheet_template_requires_login(client):
    response = client.get("/certificates/spreadsheet-template")
    assert response.status_code == 401
