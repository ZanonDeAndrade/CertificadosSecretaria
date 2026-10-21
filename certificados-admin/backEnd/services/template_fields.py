"""Template fields fed by the institutional settings, and the preview sample.

A text element whose key maps to a setting prints nothing when that setting
is empty: the renderer skips empty text. These helpers let the editor and the
batch review say so before anything is emitted, and give the editor sample
values produced by the very mapping the PDF uses.
"""

from __future__ import annotations

from certificados_backend.models import ParticipantRegistryRecord
from certificados_backend.policies import Permission, is_allowed
from certificados_backend.services import settings_service
from certificados_backend.services.runtime import build_layout_generator

# Element key → institutional setting that feeds it.
SETTING_FOR_KEY: dict[str, str] = {
    "institution_name": "institution_name",
    "issue_location": "issue_location",
    "issue_line": "issue_location",
    "signatory_name": "signatory_name",
    "signatory_title": "signatory_title",
}

SETTING_LABELS: dict[str, str] = {
    "institution_name": "Nome da instituição",
    "issue_location": "Cidade (local de emissão)",
    "signatory_name": "Nome do assinante",
    "signatory_title": "Cargo do assinante",
}

# Element keys whose value comes from the spreadsheet row or the batch. The
# name is required by the spreadsheet itself and never reaches here empty.
ROW_FIELD_LABELS: dict[str, str] = {
    "event": "Evento",
    "course": "Curso",
    "date": "Data de emissão",
    "certificate_type": "Tipo do certificado",
    "texto_certificado": "Corpo do certificado",
    "certificate_text": "Corpo do certificado",
    "authors": "Autores",
    "equipe": "Equipe",
    "work_title": "Título do trabalho",
}

_SAMPLE_BODY = (
    "participou da Semana de Inovação, promovida pelo Curso de Sistemas de "
    "Informação, realizada de 10 a 12 de junho de 2026, com carga horária "
    "total de 12 horas. A atividade contou com palestra ministrada por "
    "Maria Oliveira."
)

# Eight authors on purpose: the authors block is previewed at its tallest.
SAMPLE_AUTHORS = (
    "Joao Silva",
    "Maria Oliveira",
    "Pedro Santos",
    "Ana Costa",
    "Lucas Pereira",
    "Beatriz Lima",
    "Rafael Souza",
    "Carla Dias",
)

# Synthetic participant shown by the editor's "Dados de exemplo".
SAMPLE_PARTICIPANT = ParticipantRegistryRecord(
    nome="Joao Silva",
    email="",
    curso="Sistemas de Informação",
    livro=0,
    folha=0,
    linha=0,
    evento="Workshop de Inteligencia Artificial",
    validation_code="CERT-2026-EXEMPL",
    texto_certificado=_SAMPLE_BODY,
    certificate_text=_SAMPLE_BODY,
    data_emissao="27 de abril de 2026",
    certificate_type="Ouvinte",
    autores=SAMPLE_AUTHORS,
    equipe="Equipe Alfa",
    titulo_trabalho="Sistema de apoio à decisão para secretarias acadêmicas",
)


def text_elements(layout: dict) -> list[dict]:
    """Dynamic text elements of a layout (fixed texts and the QR carry no data)."""
    return [
        element
        for element in layout.get("elements") or []
        if isinstance(element, dict)
        and element.get("type", "text") == "text"
        and element.get("key") not in (None, "", "static", "qr")
    ]


def empty_settings(snapshot: dict) -> list[str]:
    return [setting for setting in SETTING_LABELS if not str(snapshot.get(setting) or "").strip()]


def missing_settings(layout: dict, snapshot: dict | None = None) -> list[dict]:
    """Settings the layout needs that are empty, with the element keys using them."""
    snapshot = snapshot if snapshot is not None else settings_service.certificate_snapshot()
    empty = set(empty_settings(snapshot))
    needed: dict[str, list[str]] = {}
    for element in text_elements(layout):
        key = str(element.get("key"))
        setting = SETTING_FOR_KEY.get(key)
        if setting in empty and key not in needed.setdefault(setting, []):
            needed[setting].append(key)
    return [
        {"setting": setting, "label": SETTING_LABELS[setting], "keys": keys}
        for setting, keys in needed.items()
    ]


def missing_settings_message(missing: list[dict], *, actor: dict | None) -> str:
    """Why the batch cannot be confirmed, and who can fix it."""
    labels = ", ".join(item["label"] for item in missing)
    state = "estão vazios" if len(missing) > 1 else "está vazio"
    base = f"O template ativo usa {labels}, que {state} nas Configurações da instituição."
    if actor is not None and is_allowed(actor, Permission.SETTINGS_MANAGE):
        return f"{base} Preencha em Configurações antes de emitir."
    return f"{base} Peça a um administrador para preencher em Configurações antes de emitir."


def sample_data(*, actor: dict | None = None) -> dict:
    """Values for the editor preview, computed exactly as the PDF computes them."""
    snapshot = settings_service.certificate_snapshot()
    generator = build_layout_generator(snapshot)
    return {
        "values": generator.participant_data(SAMPLE_PARTICIPANT),
        "empty_settings": [
            {"setting": setting, "label": SETTING_LABELS[setting]}
            for setting in empty_settings(snapshot)
        ],
        "can_manage_settings": bool(
            actor is not None and is_allowed(actor, Permission.SETTINGS_MANAGE)
        ),
    }
