"""Per-work certificates: the template they require and their automatic body.

A per-work type (``per_work_authors``) issues one certificate per work, valid
for every author listed on it. Such a certificate highlights no participant:
the body names the work and the event, and the authors block lists who wrote
it. These rules follow the type's traits, never its label text.
"""

from __future__ import annotations

from typing import Iterable

from certificados_backend.services.certificate_text import (
    CertificateTextError,
    body_template_variables,
)
from certificados_backend.services.spreadsheet import SpreadsheetRow

from database.certificate_types import certificate_type_label, is_per_work_type

AUTHORS_KEY = "authors"
NAME_KEY = "name"
BODY_KEYS = frozenset({"texto_certificado", "certificate_text"})

# ``{{nome}}`` is the first author only: on a certificate valid for every
# author it would single one of them out.
EXCLUDED_BODY_VARIABLES = frozenset({"nome"})

# Shown on the emission screen; the workload clause appears only when filled.
AUTOMATIC_BODY_DESCRIPTION = (
    'Certificamos que o trabalho "{{titulo_trabalho}}" foi apresentado no evento '
    "{{evento}}, com carga horária de {{carga_horaria}} horas."
)


def automatic_body(row: SpreadsheetRow) -> str:
    """Body of a per-work certificate whose batch brings no text of its own."""
    text = (
        f'Certificamos que o trabalho "{row.titulo_trabalho}" foi apresentado no evento '
        f"{row.evento}"
    )
    if row.carga_horaria is not None:
        text += f", com carga horária de {row.carga_horaria} horas"
    return text + "."


def check_body_variables(template: str, certificate_type: str | None) -> None:
    """Refuse variables that make no sense on a certificate shared by authors."""
    if not is_per_work_type(certificate_type):
        return
    used = sorted(body_template_variables(template) & EXCLUDED_BODY_VARIABLES)
    if used:
        label = certificate_type_label(certificate_type)
        raise CertificateTextError(
            f"O texto de {label} não pode usar {{{{nome}}}}: o certificado vale para "
            "todos os autores do trabalho e {{nome}} imprimiria só o primeiro. Os autores "
            "aparecem no bloco Autores do template; apague {{nome}} do texto."
        )


def _text_keys(layout: dict) -> set[str]:
    return {
        str(element.get("key"))
        for element in layout.get("elements") or []
        if isinstance(element, dict) and element.get("type", "text") == "text"
    }


# Problem code → (what is wrong, how to fix it in the editor).
_PROBLEMS: dict[str, tuple[str, str]] = {
    "name": ("tem o elemento Nome do participante", "remova o elemento Nome"),
    "authors": ("não tem o bloco Autores", "adicione o bloco Autores acima do QR Code"),
    "body": ("não tem o elemento Corpo", "adicione o elemento Corpo"),
}


def layout_problems(layout: dict) -> list[str]:
    """Codes of what keeps a layout from serving a per-work type."""
    keys = _text_keys(layout)
    problems: list[str] = []
    if NAME_KEY in keys:
        problems.append("name")
    if AUTHORS_KEY not in keys:
        problems.append("authors")
    if not keys & BODY_KEYS:
        problems.append("body")
    return problems


def _joined(parts: Iterable[str]) -> str:
    items = list(parts)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]


def template_problem(
    version: dict | None, certificate_type: str | None, *, can_manage: bool
) -> str | None:
    """Why a per-work batch cannot use its active template, and how to fix it.

    ``None`` when the type is not per-work or its template is fit. A per-work
    type never falls back to the generic template, so a missing version of the
    type is a problem too.
    """
    if not is_per_work_type(certificate_type):
        return None
    label = certificate_type_label(certificate_type)
    if version is None:
        reason = (
            f"Não há template ativo do tipo {label}. Este tipo não usa o template "
            "genérico, porque o certificado vale para todos os autores e não destaca "
            "nenhum nome."
        )
        if can_manage:
            return (
                f"{reason} Em Template, use “Editar (nova versão)”, escolha o tipo {label} "
                "(o editor monta o ponto de partida sem o nome e com o bloco Autores), "
                "ajuste, salve e ative a versão."
            )
        return (
            f"{reason} Peça a um administrador para criar e ativar uma versão do tipo "
            f"{label} em Template."
        )

    problems = layout_problems(version.get("layout") or {})
    if not problems:
        return None
    what = _joined(_PROBLEMS[code][0] for code in problems)
    reason = f"O template ativo do tipo {label} {what}."
    if not can_manage:
        return f"{reason} Peça a um administrador para corrigir o template em Template."
    steps = _joined(_PROBLEMS[code][1] for code in problems)
    return (
        f"{reason} Em Template, use “Editar como nova” nessa versão, {steps}, "
        "salve e ative a nova versão."
    )
