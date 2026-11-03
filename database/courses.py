"""Courses as a registered list.

Templates may be filed under a course, and the settings screen manages the
list, so the same spelling is used everywhere instead of free text. The
normalised key keeps "Sistemas de Informação" and "sistemas de informacao" from
becoming two courses. The spreadsheet validator uses the same normalisation to
canonicalise the participant's course, but it never writes to this table.
"""

from __future__ import annotations

import unicodedata

# Seeded by migration 0014 and by the development database on first start.
DEFAULT_COURSES: tuple[str, ...] = (
    "Sistemas de Informação",
    "Direito",
    "Ontopsicologia",
    "Contabilidade",
    "Pedagogia",
    "Gastronomia",
    "Administração",
    "Hotelaria",
)

MAX_COURSE_NAME_LENGTH = 255


def normalize_course_key(course: str) -> str:
    """Stable, lowercase ASCII key from an arbitrary course name.

    "Engenharia Civil" -> "engenharia_civil"; "Ciências Contábeis" ->
    "ciencias_contabeis".
    """
    nfkd = unicodedata.normalize("NFKD", course.strip())
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    return "_".join(ascii_only.lower().split())
