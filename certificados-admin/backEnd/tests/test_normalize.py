"""Tests for certificate_service normalisation helpers and text utilities."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure backEnd/ is on the path so bare imports resolve.
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from services.certificate_service import _normalize_date_text


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
