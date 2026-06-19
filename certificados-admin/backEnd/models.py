from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Participant:
    nome: str
    email: str
    curso: str
    texto_certificado: str = ""
    certificate_text: str = ""
    data_emissao: str = ""


@dataclass(slots=True, frozen=True)
class ParticipantRegistryRecord:
    nome: str
    email: str
    curso: str
    livro: int
    folha: int
    linha: int
    validation_code: str = ""
    referencia_registro: str = ""
    texto_certificado: str = ""
    certificate_text: str = ""
    data_emissao: str = ""


@dataclass(slots=True, frozen=True)
class CertificateFormData:
    texto_certificado: str
    data_emissao: str
