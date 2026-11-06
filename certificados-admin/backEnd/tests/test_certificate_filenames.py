"""Readable certificate filenames: "<titular>_<evento>_<ano>.pdf"."""

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
    certificate_year,
    certificate_zip_filename,
    clean_filename_part,
    content_disposition,
    copy_filenames,
    numbered_filename,
    numbered_filenames,
    unique_filename,
)

CODE = "CERT-2026-3ETWK9"
YEAR = "2026"
MOSTRA = CertificateType.SCIENTIFIC_INITIATION.value
AUTHORS = ("Pessoa Exemplo Alfa", "Pessoa Exemplo Beta", "Pessoa Exemplo Gama")


def _record(**overrides) -> ParticipantRegistryRecord:
    fields = {
        "nome": "Pessoa Exemplo Titular",
        "email": "",
        "curso": "Direito",
        "livro": 0,
        "folha": 0,
        "linha": 0,
        "evento": "Semana de Inovação",
        "validation_code": CODE,
        "data_emissao": "10 de junho de 2026",
    }
    return ParticipantRegistryRecord(**{**fields, **overrides})


def _row(**overrides) -> dict:
    row = {
        "participant_name": "Pessoa Exemplo Titular",
        "event_name": "Semana de Inovação",
        "unique_code": CODE,
        "start_date": "2026-05-04",
        "issue_date": "2026-06-10",
        "certificate_type": "listener",
    }
    return {**row, **overrides}


def _work(**overrides) -> dict:
    work = {
        "participant_name": AUTHORS[0],
        "work_title": "Horta vertical automatizada",
        "certificate_type": MOSTRA,
        "event_name": "Micamf",
    }
    return _row(**{**work, **overrides})


# ── Format ────────────────────────────────────────────────────────────────────


def test_parts_are_joined_by_an_underscore():
    assert SEPARATOR == "_"


def test_name_is_holder_event_and_year_without_the_code():
    assert certificate_filename(_row()) == "Pessoa Exemplo Titular_Semana de Inovação_2026.pdf"
    assert CODE not in certificate_filename(_row())


def test_spaces_inside_the_name_and_the_event_are_kept():
    holder, event, year = certificate_filename(_row()).split("_")
    assert holder == "Pessoa Exemplo Titular"
    assert event == "Semana de Inovação"
    assert year == "2026.pdf"


def test_without_event_the_name_is_holder_and_year():
    assert certificate_filename(_row(event_name=None)) == "Pessoa Exemplo Titular_2026.pdf"
    assert build_certificate_filename("Ana", "  \n ", YEAR) == "Ana_2026.pdf"


def test_an_event_that_already_ends_with_the_year_does_not_repeat_it():
    row = _row(event_name="Mostra de Iniciação Científica 2026")
    assert certificate_filename(row) == (
        "Pessoa Exemplo Titular_Mostra de Iniciação Científica 2026.pdf"
    )
    # Another year inside the event is not the certificate's year: both stay.
    assert certificate_filename(_row(event_name="Turma 1999")) == (
        "Pessoa Exemplo Titular_Turma 1999_2026.pdf"
    )
    # Digits glued to the year are a number, not a year.
    assert certificate_filename(_row(event_name="Sala 12026")) == (
        "Pessoa Exemplo Titular_Sala 12026_2026.pdf"
    )


def test_year_comes_from_the_event_start_then_the_issue_date_then_the_code():
    assert certificate_year(_row()) == "2026"
    assert certificate_year(_row(start_date="2025-11-30", issue_date="2026-02-01")) == "2025"
    assert certificate_year(_row(start_date=None)) == "2026"
    assert certificate_year(_row(start_date="", issue_date="10 de junho de 2024")) == "2024"
    assert certificate_year(_row(start_date=None, issue_date=None)) == "2026"
    assert certificate_year({"unique_code": "CERT-2023-ABCDEF"}) == "2023"
    assert certificate_year({"unique_code": "sem-ano"}) == ""
    assert certificate_filename(_row(start_date=None, issue_date=None, unique_code="x")) == (
        "Pessoa Exemplo Titular_Semana de Inovação.pdf"
    )


def test_decomposed_accents_are_composed():
    # Spreadsheets saved on macOS may carry "ç" as "c" + combining cedilla.
    decomposed = "Inovação"
    assert clean_filename_part(decomposed) == "Inovação"


@pytest.mark.parametrize("forbidden", list('/\\:*?"<>|'))
def test_removes_each_character_forbidden_on_windows_linux_or_drive(forbidden):
    name = build_certificate_filename(f"Ana{forbidden}Souza", f"Semana{forbidden}Jurídica", YEAR)
    assert name == "Ana Souza_Semana Jurídica_2026.pdf"


def test_removes_line_breaks_control_and_invisible_characters_and_collapses_spaces():
    holder = "  Ana\nMaria\r\n\tSouza\x00\x07 ‮gnp.exe​  "
    event = ".Semana de   Inovação."
    assert build_certificate_filename(holder, event, YEAR) == (
        "Ana Maria Souza gnp.exe_Semana de Inovação_2026.pdf"
    )


# ── Length limits ─────────────────────────────────────────────────────────────


def test_long_event_is_shortened_first_and_the_year_is_never_cut():
    event = "Congresso Internacional de Inovação e Tecnologia " * 6
    name = build_certificate_filename("Pessoa Exemplo Titular", event, YEAR)
    assert len(name) <= MAX_FILENAME_CHARS
    assert name.startswith("Pessoa Exemplo Titular_Congresso Internacional")
    assert name.endswith("…_2026.pdf")


def test_the_year_returns_when_the_event_that_carried_it_is_shortened():
    event = "Mostra de Iniciação Científica e Tecnológica " * 5 + "2026"
    name = build_certificate_filename("Ana", event, YEAR)
    assert len(name) <= MAX_FILENAME_CHARS
    assert name.endswith("…_2026.pdf")


def test_holder_is_shortened_only_after_the_event_reaches_its_minimum():
    holder = "Maria " + "Aparecida da Conceição " * 8
    event = "Semana Acadêmica de Tecnologia " * 4
    name = build_certificate_filename(holder, event, YEAR)
    assert len(name) <= MAX_FILENAME_CHARS
    holder_part, event_part, year_part = name.split("_")
    assert holder_part.endswith("…") and event_part.endswith("…")
    assert len(event_part) <= 20 < len(holder_part)
    assert year_part == "2026.pdf"


def test_a_shortened_part_never_ends_in_the_separator():
    event = "Semana_" * 40
    name = build_certificate_filename("Ana", event, YEAR)
    assert len(name) <= MAX_FILENAME_CHARS
    assert "_…" not in name
    assert name.endswith("…_2026.pdf")


def test_name_also_respects_the_byte_limit_of_linux():
    name = build_certificate_filename("漢" * 120, "字" * 120, YEAR)
    assert len(name.encode("utf-8")) <= MAX_FILENAME_BYTES
    assert name.endswith("_2026.pdf")


# ── Repeated names ────────────────────────────────────────────────────────────


def test_same_person_twice_in_the_same_event_gets_the_same_name():
    first = certificate_filename(_row(unique_code="CERT-2026-AAAAAA"))
    second = certificate_filename(_row(unique_code="CERT-2026-BBBBBB"))
    assert first == second == "Pessoa Exemplo Titular_Semana de Inovação_2026.pdf"


def test_numbered_variants_go_before_the_extension():
    assert numbered_filename("Ana_Evento_2026.pdf", 2) == "Ana_Evento_2026_2.pdf"
    assert numbered_filename("Trabalho_Evento_2026.zip", 3) == "Trabalho_Evento_2026_3.zip"
    assert numbered_filename("sem-extensao", 2) == "sem-extensao_2"
    assert list(numbered_filenames("a.pdf", limit=3)) == ["a.pdf", "a_2.pdf", "a_3.pdf"]


def test_unique_filename_adds_2_3_and_ignores_case():
    used: set[str] = set()
    assert unique_filename("Ana_Evento_2026.pdf", used) == "Ana_Evento_2026.pdf"
    assert unique_filename("ana_evento_2026.pdf", used) == "ana_evento_2026_2.pdf"
    assert unique_filename("Ana_Evento_2026.pdf", used) == "Ana_Evento_2026_3.pdf"
    assert unique_filename("Outro_Evento_2026.pdf", used) == "Outro_Evento_2026.pdf"


# ── Per-work certificates (Mostra) ────────────────────────────────────────────


def test_mostra_file_is_named_after_the_work_and_falls_back_to_the_first_author():
    assert certificate_filename(_work()) == "Horta vertical automatizada_Micamf_2026.pdf"
    assert certificate_filename(_work(work_title=None)) == "Pessoa Exemplo Alfa_Micamf_2026.pdf"


def test_a_copy_for_one_author_is_named_after_that_author():
    assert certificate_filename(_work(), author=AUTHORS[1]) == (
        "Pessoa Exemplo Beta_Micamf_2026.pdf"
    )
    # A blank author keeps the work title.
    assert certificate_filename(_work(), author="  ") == certificate_filename(_work())


def test_copies_are_one_per_author_for_1_3_and_8_authors():
    one = copy_filenames(_work(), AUTHORS[:1])
    assert one == ["Pessoa Exemplo Alfa_Micamf_2026.pdf"]
    three = copy_filenames(_work(), AUTHORS)
    assert three == [f"{author}_Micamf_2026.pdf" for author in AUTHORS]
    eight = [f"Pessoa Exemplo {index}" for index in range(1, 9)]
    assert copy_filenames(_work(), eight) == [f"{author}_Micamf_2026.pdf" for author in eight]


def test_copies_keep_homonymous_authors_apart_only_through_unique_filename():
    names = copy_filenames(_work(), ("Ana Lima", "Ana Lima", "Beto Reis"))
    assert names == [
        "Ana Lima_Micamf_2026.pdf",
        "Ana Lima_Micamf_2026.pdf",
        "Beto Reis_Micamf_2026.pdf",
    ]
    used: set[str] = set()
    assert [unique_filename(name, used) for name in names] == [
        "Ana Lima_Micamf_2026.pdf",
        "Ana Lima_Micamf_2026_2.pdf",
        "Beto Reis_Micamf_2026.pdf",
    ]


def test_an_ordinary_certificate_or_a_work_without_authors_yields_one_copy():
    assert copy_filenames(_row(), ()) == ["Pessoa Exemplo Titular_Semana de Inovação_2026.pdf"]
    # Authors are only meaningful on a per-work type.
    assert copy_filenames(_row(), AUTHORS) == ["Pessoa Exemplo Titular_Semana de Inovação_2026.pdf"]
    assert copy_filenames(_work(), ()) == ["Horta vertical automatizada_Micamf_2026.pdf"]


def test_zip_of_a_work_is_named_after_the_work_event_and_year():
    assert certificate_zip_filename(_work()) == "Horta vertical automatizada_Micamf_2026.zip"
    assert certificate_zip_filename(_work(event_name="Mostra 2026")) == (
        "Horta vertical automatizada_Mostra 2026.zip"
    )


# ── Render record (generator) ─────────────────────────────────────────────────


def test_render_record_is_named_like_the_persisted_row():
    assert build_pdf_filename(_record()) == "Pessoa Exemplo Titular_Semana de Inovação_2026.pdf"
    assert build_pdf_filename(_record(evento="")) == "Pessoa Exemplo Titular_2026.pdf"
    # Without an issue date the code's year stands in.
    assert build_pdf_filename(_record(data_emissao="", validation_code="CERT-2024-AAAAAA")) == (
        "Pessoa Exemplo Titular_Semana de Inovação_2024.pdf"
    )


def test_render_record_with_the_mostra_label_matches_the_persisted_row():
    # The render record carries the type LABEL; the database row, its value.
    label = CERTIFICATE_TYPE_LABELS[CertificateType.SCIENTIFIC_INITIATION]
    record = _record(
        nome=AUTHORS[0],
        titulo_trabalho="Horta vertical automatizada",
        certificate_type=label,
        autores=AUTHORS[:2],
    )
    row = _work(event_name="Semana de Inovação", start_date=None)
    assert build_pdf_filename(record) == certificate_filename(row)
    assert build_pdf_filename(record).startswith("Horta vertical automatizada_")


def test_work_title_is_ignored_for_types_that_are_not_per_work():
    record = _record(titulo_trabalho="Trabalho qualquer", certificate_type="Palestrante")
    assert build_pdf_filename(record).startswith("Pessoa Exemplo Titular_")


# ── Content-Disposition ───────────────────────────────────────────────────────


def test_ascii_fallback_is_pure_ascii():
    name = "Pessoa Ørsted Titular_Semana de Inovação…_2026.pdf"
    fallback = ascii_filename(name)
    assert fallback.isascii()
    assert fallback == "Pessoa _rsted Titular_Semana de Inovacao..._2026.pdf"


def test_ascii_fallback_collapses_underscores_around_untranslatable_text():
    # Characters without an ASCII form become "_" and runs collapse, so a part
    # made only of them folds into the separator in the fallback name; the
    # exact UTF-8 name still travels in filename*.
    name = "漢字_Semana de Inovação_2026.pdf"
    assert ascii_filename(name) == "_Semana de Inovacao_2026.pdf"
    assert unquote(content_disposition(name).split("filename*=UTF-8''", 1)[1]) == name


def test_content_disposition_carries_ascii_and_utf8_names():
    name = "Pessoa Exemplo Titular_Semana de Inovação_2026.pdf"
    header = content_disposition(name)
    assert header.isascii()
    assert header.startswith(
        'attachment; filename="Pessoa Exemplo Titular_Semana de Inovacao_2026.pdf"; '
    )
    encoded = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == name
    assert "Pessoa%20Exemplo%20Titular_Semana%20de%20Inova%C3%A7%C3%A3o_2026.pdf" in encoded
    assert content_disposition(name, "inline").startswith("inline; ")
