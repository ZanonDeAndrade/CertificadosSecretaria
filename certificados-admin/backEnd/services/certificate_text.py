"""Secretaria-authored certificate body: validation + safe interpolation.

The body is the ONLY free text the secretaria writes for a whole batch — it is
the *corpo* of the certificate (the template still controls title, preamble,
highlighted name, date, signature, QR code and validation code).

Interpolation is intentionally minimal and safe:
  - a fixed allowlist of ``{{variavel}}`` tokens is permitted;
  - substitution is literal token replacement — never ``str.format``, ``eval``
    or any HTML/templating engine;
  - unknown or malformed variables are rejected with a clear message.
"""
from __future__ import annotations

import re
from typing import Mapping

# Hard cap on the body length (characters, after trimming the outer whitespace).
MAX_BODY_LENGTH = 3000

# The only variables the secretaria may use in the body text. They mirror the
# REQUIRED spreadsheet columns (name + workload) — every other piece of info is
# written literally in the body text, so no other variable is offered.
ALLOWED_VARIABLES: tuple[str, ...] = (
    "nome",
    "carga_horaria",
)

# A well-formed token: {{ name }} with optional inner spaces.
_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class CertificateTextError(ValueError):
    """Raised when the body template is missing, too long, or has bad variables."""


def _allowed_hint() -> str:
    return ", ".join("{{%s}}" % name for name in ALLOWED_VARIABLES)


def validate_body_template(raw: str | None) -> str:
    """Validate the secretaria's body template and return the trimmed text.

    Rules (business validation, applied AFTER authentication):
      - required (non-empty after trimming the outer whitespace);
      - only the outer whitespace is trimmed (inner line breaks are preserved);
      - at most ``MAX_BODY_LENGTH`` characters;
      - every ``{{var}}`` must be in :data:`ALLOWED_VARIABLES`;
      - no malformed braces (e.g. ``{{x``, ``{nome}``, ``{{}}``).
    """
    text = (raw or "").strip()
    if not text:
        raise CertificateTextError("Informe o texto padrão do certificado.")
    if len(text) > MAX_BODY_LENGTH:
        raise CertificateTextError(
            f"O texto padrão excede o limite de {MAX_BODY_LENGTH} caracteres."
        )

    # Every well-formed token must be an allowed variable.
    for name in _TOKEN_RE.findall(text):
        if name not in ALLOWED_VARIABLES:
            raise CertificateTextError(
                f"Variável desconhecida: {{{{{name}}}}}. Use apenas: {_allowed_hint()}."
            )

    # Remove every well-formed token; any brace left over is malformed.
    residue = _TOKEN_RE.sub("", text)
    if "{" in residue or "}" in residue:
        raise CertificateTextError(
            "Há chaves malformadas no texto. Use exatamente o formato {{variavel}} "
            f"com uma das variáveis: {_allowed_hint()}."
        )
    return text


def render_certificate_body(template: str, values: Mapping[str, str]) -> str:
    """Interpolate the allowed variables with literal replacement (no format/eval).

    ``template`` is assumed already validated by :func:`validate_body_template`.
    Unknown tokens (should not occur after validation) are left untouched.
    """

    def _replace(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name in ALLOWED_VARIABLES:
            return str(values.get(name, ""))
        return match.group(0)

    return _TOKEN_RE.sub(_replace, template)
