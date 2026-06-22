from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ParticipantRegistryRecord:
    """Transient render record for a single certificate (not persisted)."""

    nome: str
    email: str
    curso: str
    livro: int
    folha: int
    linha: int
    # Event and course are DISTINCT fields and both travel with the record so
    # the visual template can place each independently (see generator).
    evento: str = ""
    validation_code: str = ""
    referencia_registro: str = ""
    texto_certificado: str = ""
    certificate_text: str = ""
    data_emissao: str = ""
