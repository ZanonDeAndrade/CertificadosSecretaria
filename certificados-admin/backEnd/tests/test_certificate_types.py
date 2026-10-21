from __future__ import annotations

import pytest

from database.certificate_types import (
    CERTIFICATE_TYPE_LABELS,
    CertificateType,
    certificate_type_label,
    parse_certificate_type,
)


def test_all_controlled_certificate_types_have_the_required_labels():
    expected = {
        "listener": "Ouvinte",
        "speaker": "Palestrante",
        "organizing_committee": "Comissão Organizadora",
        "teams": "Equipes",
        "monitoring": "Monitoria",
        "tcc_board_professor": "Professores participantes de Banca de TCC",
        "scientific_initiation": "Mostra de Iniciação Científica",
    }
    assert {item.value: CERTIFICATE_TYPE_LABELS[item] for item in CertificateType} == expected
    for item in CertificateType:
        assert parse_certificate_type(item.value) is item
        assert certificate_type_label(item.value) == expected[item.value]


def test_type_parser_rejects_missing_and_arbitrary_values():
    with pytest.raises(ValueError, match="Selecione"):
        parse_certificate_type(None)
    with pytest.raises(ValueError, match="inválido"):
        parse_certificate_type("inventado")


def test_legacy_type_has_an_explicit_non_invented_label():
    assert certificate_type_label(None) == "Tipo não informado"
