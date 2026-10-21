"""Controlled certificate-type domain shared by persistence and APIs."""

from __future__ import annotations

from enum import StrEnum


class CertificateType(StrEnum):
    LISTENER = "listener"
    SPEAKER = "speaker"
    ORGANIZING_COMMITTEE = "organizing_committee"
    TEAMS = "teams"
    MONITORING = "monitoring"
    TCC_BOARD_PROFESSOR = "tcc_board_professor"
    SCIENTIFIC_INITIATION = "scientific_initiation"


CERTIFICATE_TYPE_LABELS: dict[CertificateType, str] = {
    CertificateType.LISTENER: "Ouvinte",
    CertificateType.SPEAKER: "Palestrante",
    CertificateType.ORGANIZING_COMMITTEE: "Comissão Organizadora",
    CertificateType.TEAMS: "Equipes",
    CertificateType.MONITORING: "Monitoria",
    CertificateType.TCC_BOARD_PROFESSOR: "Professores participantes de Banca de TCC",
    CertificateType.SCIENTIFIC_INITIATION: "Mostra de Iniciação Científica",
}
CERTIFICATE_TYPE_VALUES = tuple(item.value for item in CertificateType)
LEGACY_CERTIFICATE_TYPE_LABEL = "Tipo não informado"


def parse_certificate_type(value: object, *, required: bool = True) -> CertificateType | None:
    """Return a controlled type, rejecting missing/unknown payload values."""
    normalized = str(value or "").strip()
    if not normalized:
        if required:
            raise ValueError("Selecione o tipo do certificado.")
        return None
    try:
        return CertificateType(normalized)
    except ValueError as exc:
        raise ValueError("Tipo do certificado inválido.") from exc


def certificate_type_label(value: object) -> str:
    parsed = parse_certificate_type(value, required=False)
    return CERTIFICATE_TYPE_LABELS[parsed] if parsed else LEGACY_CERTIFICATE_TYPE_LABEL
