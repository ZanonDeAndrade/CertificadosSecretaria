from __future__ import annotations

import unicodedata

# Canonical list of valid courses. This is the single source of truth for
# both upload validation and the /courses endpoint consumed by the frontend.
COURSES: list[str] = [
    "Sistemas de Informação",
    "Direito",
    "Ontopsicologia",
    "Contabilidade",
    "Pedagogia",
    "Gastronomia",
    "Administração",
    "Hotelaria",
]


def normalize_course_name(course: str) -> str:
    """Stable, lowercase ASCII key from an arbitrary course name.

    "Engenharia Civil" -> "engenharia_civil"; "Ciências Contábeis" ->
    "ciencias_contabeis". Used by the spreadsheet validator to match course
    synonyms against :data:`COURSES`.
    """
    nfkd = unicodedata.normalize("NFKD", course.strip())
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    return "_".join(ascii_only.lower().split())
