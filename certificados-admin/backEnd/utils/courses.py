"""Course names the spreadsheet validator canonicalises.

The registered course list lives in the ``courses`` table (managed in the
settings screen) and files templates. The spreadsheet keeps using this fixed
list on purpose: a participant's course is part of the duplicate key of a
certificate, so a course renamed in the settings must not change how an old
spreadsheet is read.
"""

from __future__ import annotations

from database.courses import DEFAULT_COURSES, normalize_course_key

# Canonical spellings the validator maps synonyms onto.
COURSES: list[str] = list(DEFAULT_COURSES)


def normalize_course_name(course: str) -> str:
    """Same key as the registered courses: "Ciências Contábeis" -> "ciencias_contabeis"."""
    return normalize_course_key(course)
