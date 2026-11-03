"""E-mails for test spreadsheets: the contract requires one per person.

Most tests are about something else (templates, folders, idempotency…) and
build their rows without an e-mail. ``with_emails`` fills a synthetic one so
those tests keep describing their own subject; the e-mail contract itself is
exercised by ``test_spreadsheet.py`` and ``test_email_contract.py``.
"""

from __future__ import annotations

import re
import unicodedata

_AUTHOR_RE = re.compile(r"(?:co)?aut(?:h)?or0*(\d+)")
_NAME_HEADERS = {"nome", "name", "participante", "aluno", "nomecompleto"}


def _norm(header: object) -> str:
    text = unicodedata.normalize("NFKD", str(header)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", text.lower())


def with_emails(rows: list[dict]) -> list[dict]:
    """Copies of ``rows`` with a synthetic e-mail wherever the row brings none.

    Ordinary rows get ``email``; per-work rows get ``email<n>`` for every
    filled ``autor<n>``. A key already present, even blank, is left alone, so
    a test can still state what a missing or invalid e-mail does.
    """
    filled: list[dict] = []
    for row in rows:
        copy = dict(row)
        author_numbers = [
            int(match.group(1))
            for key in copy
            if (match := _AUTHOR_RE.fullmatch(_norm(key))) and str(copy[key] or "").strip()
        ]
        has_email = any(_norm(key).startswith("email") for key in copy)
        if author_numbers:
            for number in author_numbers:
                copy.setdefault(f"email{number}", f"autor{number}@exemplo.com")
        elif not has_email and any(_norm(key) in _NAME_HEADERS for key in copy):
            copy["email"] = "pessoa.sintetica@exemplo.com"
        filled.append(copy)
    return filled
