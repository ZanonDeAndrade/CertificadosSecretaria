from __future__ import annotations

from models import Participant, ParticipantRegistryRecord

DEFAULT_LIVRO = 1
PARTICIPANTS_PER_FOLHA = 20


def enrich_with_registry(
    participants: list[Participant],
    livro: int = DEFAULT_LIVRO,
    participants_per_folha: int = PARTICIPANTS_PER_FOLHA,
) -> list[ParticipantRegistryRecord]:
    if participants_per_folha <= 0:
        raise ValueError("participants_per_folha deve ser maior que zero.")

    records: list[ParticipantRegistryRecord] = []

    for index, participant in enumerate(participants, start=1):
        folha = ((index - 1) // participants_per_folha) + 1
        linha = ((index - 1) % participants_per_folha) + 1

        records.append(
            ParticipantRegistryRecord(
                nome=participant.nome,
                email=participant.email,
                curso=participant.curso,
                livro=livro,
                folha=folha,
                linha=linha,
                referencia_registro="",
                texto_certificado=participant.texto_certificado,
                certificate_text=participant.certificate_text or participant.texto_certificado,
                data_emissao=participant.data_emissao,
            )
        )

    return records
