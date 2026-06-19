"""Brazilian Portuguese date formatting/validation (single source of truth).

Used by both the spreadsheet validator and the certificate service so that
month names are spelled consistently and **with accents** (e.g. "março").
"""
from __future__ import annotations

import re
from datetime import date, datetime

MONTHS = (
    "",
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

# Matches an already-"por extenso" date, e.g. "24 de março de 2026" or
# "20 a 25 de outubro de 2025" (month letters may or may not carry accents).
_EXTENSO_RE = re.compile(
    r"\d{1,2}( a \d{1,2})? de [a-zà-ÿç]+ de \d{4}", re.IGNORECASE
)
_INTERVAL_RE = re.compile(
    r"(\d{1,2})\s*(?:a|-|ate|até)\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})", re.IGNORECASE
)
_NUMERIC_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")


def format_extenso(value: date) -> str:
    """Format a date as 'D de mês de AAAA' (pt-BR, accented)."""
    return f"{value.day} de {MONTHS[value.month]} de {value.year}"


def normalize_date(value: str) -> str | None:
    """Validate and normalise a date to 'por extenso'. Returns None if invalid.

    Accepts dd/mm/aaaa, dd-mm-aaaa, aaaa-mm-dd, an interval "dd a dd/mm/aaaa",
    or an already-extenso string.
    """
    s = " ".join(str(value).strip().split())
    if not s:
        return None

    interval = _INTERVAL_RE.fullmatch(s)
    if interval:
        d1, d2, mo, year = (int(interval.group(i)) for i in range(1, 5))
        try:
            date(year, mo, d1)
            date(year, mo, d2)
        except ValueError:
            return None
        return f"{d1} a {d2} de {MONTHS[mo]} de {year}"

    for fmt in _NUMERIC_FORMATS:
        try:
            return format_extenso(datetime.strptime(s, fmt).date())
        except ValueError:
            continue

    if _EXTENSO_RE.fullmatch(s):
        return s
    return None


def normalize_date_text(value: str) -> str:
    """Lenient normaliser: returns the normalised date or the cleaned input.

    Used on free-text form fields where we don't want to hard-reject.
    """
    s = " ".join(str(value).strip().split())
    if not s:
        return s
    normalized = normalize_date(s)
    return normalized if normalized is not None else s
