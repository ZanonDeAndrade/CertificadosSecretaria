"""Tests for certificate_service normalisation helpers and text utilities."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure backEnd/ is on the path so bare imports resolve.
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pytest

from models import CertificateFormData
from services.certificate_service import _normalize_form_data, _normalize_date_text


# ---------------------------------------------------------------------------
# _normalize_date_text
# ---------------------------------------------------------------------------

class TestNormalizeDateText:
    def test_passthrough_for_already_extenso(self):
        assert _normalize_date_text("24 de marco de 2026") == "24 de marco de 2026"

    def test_converts_dd_mm_yyyy(self):
        assert _normalize_date_text("24/03/2026") == "24 de março de 2026"

    def test_converts_dd_mm_yyyy_dashes(self):
        assert _normalize_date_text("24-03-2026") == "24 de março de 2026"

    def test_converts_yyyy_mm_dd(self):
        assert _normalize_date_text("2026-03-24") == "24 de março de 2026"

    def test_interval_format(self):
        result = _normalize_date_text("20 a 25/10/2025")
        assert result == "20 a 25 de outubro de 2025"

    def test_strips_extra_whitespace(self):
        assert _normalize_date_text("  24/03/2026  ") == "24 de março de 2026"

    def test_empty_returns_empty(self):
        assert _normalize_date_text("") == ""


# ---------------------------------------------------------------------------
# _normalize_form_data
# ---------------------------------------------------------------------------

class TestNormalizeFormData:
    def _make(self, texto: str = "participou do evento.", data: str = "24 de marco de 2026") -> CertificateFormData:
        return CertificateFormData(texto_certificado=texto, data_emissao=data)

    def test_valid_data_passes_through(self):
        result = _normalize_form_data(self._make())
        assert result.texto_certificado == "participou do evento."
        assert result.data_emissao == "24 de marco de 2026"

    def test_strips_surrounding_whitespace_from_text(self):
        result = _normalize_form_data(self._make(texto="  participou do evento.  "))
        assert result.texto_certificado == "participou do evento."

    def test_normalises_crlf_line_endings(self):
        result = _normalize_form_data(self._make(texto="linha um\r\nlinha dois"))
        assert result.texto_certificado == "linha um\nlinha dois"

    def test_normalises_cr_line_endings(self):
        result = _normalize_form_data(self._make(texto="linha um\rlinha dois"))
        assert result.texto_certificado == "linha um\nlinha dois"

    def test_converts_date_numeric_format(self):
        result = _normalize_form_data(self._make(data="24/03/2026"))
        assert result.data_emissao == "24 de março de 2026"

    def test_raises_when_texto_empty(self):
        with pytest.raises(ValueError, match="texto_certificado"):
            _normalize_form_data(self._make(texto="   "))

    def test_raises_when_data_emissao_empty(self):
        with pytest.raises(ValueError, match="data_emissao"):
            _normalize_form_data(self._make(data="   "))

    def test_accented_text_preserved(self):
        texto = "participou da Comissão Organizadora da Semana Acadêmica."
        result = _normalize_form_data(self._make(texto=texto))
        assert result.texto_certificado == texto
