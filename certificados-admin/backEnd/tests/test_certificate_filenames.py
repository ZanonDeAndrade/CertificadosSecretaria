"""Readable certificate filenames: "<titular>_<evento>_<código>.pdf"."""

from __future__ import annotations

from urllib.parse import unquote

import pytest
from certificados_backend.models import ParticipantRegistryRecord
from certificados_backend.services.generator import build_pdf_filename

from database.certificate_types import CERTIFICATE_TYPE_LABELS, CertificateType
from storage_service.filenames import (
    MAX_FILENAME_BYTES,
    MAX_FILENAME_CHARS,
    SEPARATOR,
    ascii_filename,
    build_certificate_filename,
    certificate_filename,
    clean_filename_part,
    content_disposition,
)

CODE = "CERT-2026-3ETWK9"
MOSTRA = CertificateType.SCIENTIFIC_INITIATION.value


def _record(**overrides) -> ParticipantRegistryRecord:
    fields = {
        "nome": "Lisieli Rorato Dotto",
        "email": "",
        "curso": "Direito",
        "livro": 0,
        "folha": 0,
        "linha": 0,
        "evento": "Semana de Inovação",
        "validation_code": CODE,
    }
    return ParticipantRegistryRecord(**{**fields, **overrides})


def test_parts_are_joined_by_an_underscore():
    assert SEPARATOR == "_"


def test_keeps_accents_and_spaces_with_the_code_at_the_end():
    assert build_pdf_filename(_record()) == (
        "Lisieli Rorato Dotto_Semana de Inovação_CERT-2026-3ETWK9.pdf"
    )


def test_spaces_inside_the_name_and_the_event_are_kept():
    name = build_pdf_filename(_record())
    holder, event, code = name.split("_")
    assert holder == "Lisieli Rorato Dotto"
    assert event == "Semana de Inovação"
    assert code == f"{CODE}.pdf"


def test_decomposed_accents_are_composed():
    # Spreadsheets saved on macOS may carry "ç" as "c" + combining cedilla.
    decomposed = "Inovação"
    assert clean_filename_part(decomposed) == "Inovação"


@pytest.mark.parametrize("forbidden", list('/\\:*?"<>|'))
def test_removes_each_character_forbidden_on_windows_linux_or_drive(forbidden):
    name = build_certificate_filename(f"Ana{forbidden}Souza", f"Semana{forbidden}2026", CODE)
    assert name == f"Ana Souza_Semana 2026_{CODE}.pdf"


def test_removes_line_breaks_control_and_invisible_characters_and_collapses_spaces():
    holder = "  Ana\nMaria\r\n\tSouza\x00\x07 ‮gnp.exe​  "
    event = ".Semana de   Inovação."
    assert build_certificate_filename(holder, event, CODE) == (
        f"Ana Maria Souza gnp.exe_Semana de Inovação_{CODE}.pdf"
    )


def test_without_event_the_name_is_holder_and_code():
    assert build_pdf_filename(_record(evento="")) == f"Lisieli Rorato Dotto_{CODE}.pdf"
    assert build_certificate_filename("Ana", "  \n ", CODE) == f"Ana_{CODE}.pdf"


def test_long_event_is_shortened_first_and_the_code_is_never_cut():
    event = "Congresso Internacional de Inovação e Tecnologia " * 6
    name = build_certificate_filename("Lisieli Rorato Dotto", event, CODE)
    assert len(name) <= MAX_FILENAME_CHARS
    assert name.startswith("Lisieli Rorato Dotto_Congresso Internacional")
    assert name.endswith(f"…_{CODE}.pdf")


def test_holder_is_shortened_only_after_the_event_reaches_its_minimum():
    holder = "Maria " + "Aparecida da Conceição " * 8
    event = "Semana Acadêmica de Tecnologia " * 4
    name = build_certificate_filename(holder, event, CODE)
    assert len(name) <= MAX_FILENAME_CHARS
    holder_part, event_part, code_part = name.split("_")
    assert holder_part.endswith("…") and event_part.endswith("…")
    assert len(event_part) <= 20 < len(holder_part)
    assert code_part == f"{CODE}.pdf"


def test_a_shortened_part_never_ends_in_the_separator():
    event = "Semana_" * 40
    name = build_certificate_filename("Ana", event, CODE)
    assert len(name) <= MAX_FILENAME_CHARS
    assert "_…" not in name
    assert name.endswith(f"…_{CODE}.pdf")


def test_name_also_respects_the_byte_limit_of_linux():
    name = build_certificate_filename("漢" * 120, "字" * 120, CODE)
    assert len(name.encode("utf-8")) <= MAX_FILENAME_BYTES
    assert name.endswith(f"_{CODE}.pdf")


def test_same_person_twice_in_the_same_event_gets_two_names():
    first = build_pdf_filename(_record(validation_code="CERT-2026-AAAAAA"))
    second = build_pdf_filename(_record(validation_code="CERT-2026-BBBBBB"))
    assert first != second
    assert first.removesuffix("CERT-2026-AAAAAA.pdf") == second.removesuffix("CERT-2026-BBBBBB.pdf")


def test_mostra_uses_the_work_title_and_falls_back_to_the_first_author():
    row = {
        "participant_name": "Pessoa Exemplo Alfa",
        "work_title": "Horta vertical automatizada",
        "certificate_type": MOSTRA,
        "event_name": "Mostra Científica",
        "unique_code": CODE,
    }
    assert certificate_filename(row) == (
        f"Horta vertical automatizada_Mostra Científica_{CODE}.pdf"
    )
    assert certificate_filename({**row, "work_title": None}) == (
        f"Pessoa Exemplo Alfa_Mostra Científica_{CODE}.pdf"
    )


def test_render_record_with_the_mostra_label_matches_the_persisted_row():
    # The render record carries the type LABEL; the database row, its value.
    label = CERTIFICATE_TYPE_LABELS[CertificateType.SCIENTIFIC_INITIATION]
    record = _record(
        nome="Pessoa Exemplo Alfa",
        titulo_trabalho="Horta vertical automatizada",
        certificate_type=label,
        autores=("Pessoa Exemplo Alfa", "Pessoa Exemplo Beta"),
    )
    row = {
        "participant_name": "Pessoa Exemplo Alfa",
        "work_title": "Horta vertical automatizada",
        "certificate_type": MOSTRA,
        "event_name": "Semana de Inovação",
        "unique_code": CODE,
    }
    assert build_pdf_filename(record) == certificate_filename(row)
    assert build_pdf_filename(record).startswith("Horta vertical automatizada_")


def test_work_title_is_ignored_for_types_that_are_not_per_work():
    record = _record(titulo_trabalho="Trabalho qualquer", certificate_type="Palestrante")
    assert build_pdf_filename(record).startswith("Lisieli Rorato Dotto_")


def test_ascii_fallback_is_pure_ascii():
    name = "Lisieli Ørsted Dotto_Semana de Inovação…_CERT-2026-3ETWK9.pdf"
    fallback = ascii_filename(name)
    assert fallback.isascii()
    assert fallback == "Lisieli _rsted Dotto_Semana de Inovacao..._CERT-2026-3ETWK9.pdf"


def test_ascii_fallback_collapses_underscores_around_untranslatable_text():
    # Characters without an ASCII form become "_" and runs collapse, so a part
    # made only of them folds into the separator in the fallback name; the
    # exact UTF-8 name still travels in filename*.
    name = f"漢字_Semana de Inovação_{CODE}.pdf"
    assert ascii_filename(name) == f"_Semana de Inovacao_{CODE}.pdf"
    assert unquote(content_disposition(name).split("filename*=UTF-8''", 1)[1]) == name


def test_content_disposition_carries_ascii_and_utf8_names():
    name = f"Lisieli Rorato Dotto_Semana de Inovação_{CODE}.pdf"
    header = content_disposition(name)
    assert header.isascii()
    assert header.startswith(
        f'attachment; filename="Lisieli Rorato Dotto_Semana de Inovacao_{CODE}.pdf"; '
    )
    encoded = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == name
    assert "Lisieli%20Rorato%20Dotto_Semana%20de%20Inova%C3%A7%C3%A3o_" in encoded
    assert content_disposition(name, "inline").startswith("inline; ")
