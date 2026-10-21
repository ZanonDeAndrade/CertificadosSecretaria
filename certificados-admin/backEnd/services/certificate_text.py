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

# The only variables the secretaria may use in the body text, with the label of
# each one. This is the single list: the emission screen receives it from the
# API (``GET /certificates/body-variables``) to build its insert buttons, and
# the batch review uses the labels to report rows where a variable is blank.
BODY_VARIABLES: tuple[tuple[str, str], ...] = (
    ("nome", "Nome"),
    ("carga_horaria", "Carga horária"),
    ("certificate_type", "Tipo do certificado"),
    ("evento", "Evento"),
    ("equipe", "Equipe"),
    ("titulo_trabalho", "Título do trabalho"),
)
ALLOWED_VARIABLES: tuple[str, ...] = tuple(name for name, _label in BODY_VARIABLES)
BODY_VARIABLE_LABELS: dict[str, str] = dict(BODY_VARIABLES)

# A well-formed token: {{ name }} with optional inner spaces.
_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# Text pasted from editors carries characters that print as nothing or as an
# odd gap: zero-width spaces/joiners, the BOM, soft hyphens and the no-break
# space family. They are normalised away so the certificate reads as typed.
_INVISIBLE_CHARS = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_SPACE_CHARS = dict.fromkeys(
    map(ord, "             　"),
    " ",
)


def normalize_body_text(raw: str | None) -> str:
    """Drop invisible characters and turn special spaces into plain ones."""
    return (raw or "").translate(_INVISIBLE_CHARS).translate(_SPACE_CHARS)


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
    text = normalize_body_text(raw).strip()
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


def body_template_variables(template: str) -> set[str]:
    """Allowed variables a (validated) body template actually uses."""
    return {name for name in _TOKEN_RE.findall(template) if name in ALLOWED_VARIABLES}


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
