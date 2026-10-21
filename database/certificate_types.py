"""Controlled certificate-type domain shared by persistence and APIs."""

from __future__ import annotations

from dataclasses import dataclass
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

# Upper bound of authors a per-work certificate carries (``autor1``..``autor8``).
MAX_WORK_AUTHORS = 8


@dataclass(frozen=True, slots=True)
class CertificateTypeTraits:
    """Behaviour a type opts into. Code consults these, never the label text."""

    #: One certificate per work, valid for every author listed on it: the first
    #: author is the holder, the others travel with the certificate.
    per_work_authors: bool = False
    #: Workload may be left blank on the spreadsheet.
    optional_workload: bool = False


CERTIFICATE_TYPE_TRAITS: dict[CertificateType, CertificateTypeTraits] = {
    CertificateType.SCIENTIFIC_INITIATION: CertificateTypeTraits(
        per_work_authors=True, optional_workload=True
    ),
}
_DEFAULT_TRAITS = CertificateTypeTraits()


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


def certificate_type_traits(value: object) -> CertificateTypeTraits:
    """Traits of a type value; unknown or missing types get the defaults."""
    try:
        parsed = parse_certificate_type(value, required=False)
    except ValueError:
        return _DEFAULT_TRAITS
    return CERTIFICATE_TYPE_TRAITS.get(parsed, _DEFAULT_TRAITS) if parsed else _DEFAULT_TRAITS


def is_per_work_type(value: object) -> bool:
    return certificate_type_traits(value).per_work_authors
