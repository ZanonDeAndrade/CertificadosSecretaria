"""Spreadsheet model: flexible column reading + per-row validation.

Supported (canonical) columns — header names are normalised (lowercase, no
accents, no spaces/punctuation) and matched against a set of synonyms, so
"Carga Horária", "carga_horaria" and "CH" all resolve to ``carga_horaria``:

    nome*          carga_horaria*  (* obrigatório)
    curso          evento          data_emissao
    data_inicio    data_fim        email   registro_academico

Rules enforced here:
- Only ``nome`` and ``carga_horaria`` are REQUIRED. Everything else is optional
  and is meant to be written by the secretary in the certificate body text.
- ``carga_horaria`` is parsed to a positive integer (structured).
- Optional fields never block a row: ``curso`` is canonicalised when it matches
  the official list (kept as-is otherwise), dates are normalised when parseable,
  and unknown/extra columns are ignored.
- ``evento`` is a distinct column (never the course).
- Per-work types require ``autor1``, ``evento`` and ``titulo_trabalho``; the
  workload is optional.
- A cell still holding an example text of the model workbook ("Equipe
  (opcional)", ...) invalidates its row: it would print on the certificate.
- invalid rows (missing name or workload) never produce a certificate.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import IO

import pandas as pd
from certificados_backend.utils.courses import COURSES, normalize_course_name
from certificados_backend.utils.dates import normalize_date

from database.certificate_types import MAX_WORK_AUTHORS, certificate_type_traits

DEFAULT_MAX_ROWS = 2000
DEFAULT_MAX_COLS = 50
DEFAULT_MAX_CELL_LEN = 2000
DEFAULT_MAX_SECONDS = 20.0
# Decompression-bomb guards (a ~10 MB xlsx must not expand to hundreds of MB).
_MAX_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200

_CANONICAL_COURSES = {normalize_course_name(c): c for c in COURSES}


# ── Column synonyms ─────────────────────────────────────────────────────────────

_COLUMN_SYNONYMS: dict[str, set[str]] = {
    "nome": {"nome", "name", "participante", "aluno", "nomecompleto"},
    "email": {"email", "e-mail", "correio", "emailaluno"},
    "documento": {
        "registroacademico",
        "ra",
        # Cabeçalhos legados continuam aceitos para planilhas já existentes.
        "documento",
        "cpf",
        "matricula",
        "registro",
        "document",
        "doc",
    },
    "curso": {"curso", "course", "cursonome"},
    "evento": {"evento", "event", "atividade", "nomeevento"},
    "carga_horaria": {"cargahoraria", "carga", "ch", "horas", "workload", "cargahorariatotal"},
    "data_inicio": {"datainicio", "inicio", "datadeinicio", "start", "startdate"},
    "data_fim": {"datafim", "fim", "termino", "datatermino", "end", "enddate"},
    "data_emissao": {
        "dataemissao",
        "emissao",
        "datadeemissao",
        "issuedate",
        "dataemissaocertificado",
    },
    "equipe": {"equipe", "team", "nomeequipe", "nomedaequipe", "grupo"},
    "titulo_trabalho": {
        "titulotrabalho",
        "titulodotrabalho",
        "titulo",
        "trabalho",
        "title",
        "worktitle",
    },
    # Per-work certificates: "Autor 1", "autor_1", "Autor01" all map to autor1.
    **{
        f"autor{index}": {f"autor{index}", f"autor0{index}", f"author{index}", f"coautor{index}"}
        for index in range(1, MAX_WORK_AUTHORS + 1)
    },
}

REQUIRED_COLUMNS = ("nome", "carga_horaria")
# Per-work certificates name the work and its event; the workload may be blank.
PER_WORK_REQUIRED_COLUMNS = ("autor1", "evento", "titulo_trabalho")

# Texts the example row of earlier model workbooks carried. Those models are
# still in circulation, and a cell left unchanged would print on the
# certificate, so such a cell invalidates its row. Today's model has no
# example row: its "Instruções" sheet explains each column instead.
TEMPLATE_EXAMPLE_TEXTS = (
    "Nome completo",
    "Nome do primeiro autor",
    "Segundo autor (opcional)",
    "Nome da mostra",
    "Curso (opcional)",
    "Evento (opcional)",
    "Equipe (opcional)",
    "Título do trabalho (opcional)",
)
# The model's instructions sheet is never read as data.
INSTRUCTIONS_SHEET_TITLE = "Instruções"
_AUTHOR_HEADER_RE = re.compile(r"^(?:co)?aut(?:h)?or0*(\d+)$")


def _norm_header(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", s.lower())


# normalised synonym -> canonical field
_REVERSE_SYNONYMS: dict[str, str] = {}
for _canonical, _syns in _COLUMN_SYNONYMS.items():
    _REVERSE_SYNONYMS[_norm_header(_canonical)] = _canonical
    for _s in _syns:
        _REVERSE_SYNONYMS[_norm_header(_s)] = _canonical


# ── Value objects ───────────────────────────────────────────────────────────────


class SpreadsheetError(Exception):
    """Raised for whole-file problems (missing columns, too many rows, etc.)."""


@dataclass(frozen=True)
class SpreadsheetRow:
    row_number: int
    nome: str
    # ``None`` only for types whose workload is optional (per-work certificates).
    carga_horaria: int | None
    # Optional fields — written by the secretary in the body text when absent.
    curso: str = ""  # canonical course name when matched, else raw
    evento: str = ""
    data_emissao: str = ""  # normalised (por extenso) when parseable
    email: str = ""
    documento: str = ""
    data_inicio: str = ""
    data_fim: str = ""
    # Per-work certificates: the authors in order, blanks already dropped.
    # ``nome`` is the first author, the certificate's holder.
    autores: tuple[str, ...] = ()
    equipe: str = ""
    titulo_trabalho: str = ""


@dataclass
class InvalidRow:
    row_number: int
    data: dict
    errors: list[str]


@dataclass
class ValidationReport:
    valid: list[SpreadsheetRow] = field(default_factory=list)
    invalid: list[InvalidRow] = field(default_factory=list)
    #: File-level notes that do not invalidate rows (e.g. ignored columns).
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.valid) + len(self.invalid)

    @property
    def valid_count(self) -> int:
        return len(self.valid)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid)


# ── Cell + field helpers ────────────────────────────────────────────────────────


def _cell(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().strftime("%d/%m/%Y")
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_workload(value: str) -> int | None:
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    hours = int(match.group())
    return hours if hours > 0 else None


def match_course(value: str) -> str | None:
    """Return the canonical course name, or None if not in the list."""
    return _CANONICAL_COURSES.get(normalize_course_name(value))


# ── Business key (idempotency) ──────────────────────────────────────────────────


def _norm_text(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().split())


def compute_business_key(
    row: SpreadsheetRow,
    body: str | None = None,
    certificate_type: str | None = None,
) -> str:
    """Stable hash identifying a unique certificate (idempotency).

    Based on name + document + event + course + workload + issue date, all
    normalised, so re-uploading the same spreadsheet does not duplicate.

    When a ``body`` (the resolved, secretaria-authored certificate text) is
    provided, its normalised form is folded into the key so that the SAME row
    with a DIFFERENT text is treated as a new emission, while the SAME row with
    the SAME text remains a duplicate. Callers that pass no body keep the
    historical key (backwards compatible).
    """
    parts = [
        _norm_text(row.nome),
        _norm_text(row.documento),
        _norm_text(row.evento),
        _norm_text(row.curso),
        str(row.carga_horaria),
        _norm_text(row.data_emissao),
    ]
    if body is not None:
        parts.append(_norm_text(body))
    if certificate_type is not None:
        parts.append(_norm_text(certificate_type))
    # Per-work data joins the key only when present, so historical keys of
    # ordinary certificates are unchanged while two works that share a first
    # author are still told apart.
    if row.autores:
        parts.append("autores=" + "/".join(_norm_text(name) for name in row.autores))
    if row.equipe:
        parts.append("equipe=" + _norm_text(row.equipe))
    if row.titulo_trabalho:
        parts.append("titulo=" + _norm_text(row.titulo_trabalho))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


_EXAMPLE_TEXTS_NORM = frozenset(_norm_text(text) for text in TEMPLATE_EXAMPLE_TEXTS)


def example_text_errors(values: dict[str, str]) -> list[str]:
    """Cells of a row that still hold an example text of the model workbook."""
    return [
        f'{column} contém o texto de exemplo do modelo ("{value}"); '
        "substitua pelo dado real ou apague"
        for column, value in values.items()
        if value and _norm_text(value) in _EXAMPLE_TEXTS_NORM
    ]


# ── Reader ──────────────────────────────────────────────────────────────────────


def _materialize_bytes(source: Path | str | IO[bytes]) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    pos = source.tell() if hasattr(source, "tell") else None
    data = source.read()
    if pos is not None and hasattr(source, "seek"):
        source.seek(pos)
    return data


def enforce_xlsx_limits(
    data: bytes,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cols: int = DEFAULT_MAX_COLS,
    max_cell_len: int = DEFAULT_MAX_CELL_LEN,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> str:
    """Validate the REAL .xlsx structure and enforce hard limits BEFORE the
    spreadsheet is fully loaded into pandas — guarding against malformed files,
    decompression bombs, and oversized rows/columns/cells/processing time.

    Returns the title of the data sheet: the first one that is not the model's
    instructions sheet. The limits apply to that sheet, the one pandas reads.
    """
    # 1) Real OOXML/ZIP structure + decompression-bomb guard (no XML parsed yet).
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SpreadsheetError("Arquivo .xlsx inválido (não é um pacote Office/ZIP).") from exc
    names = set(archive.namelist())
    if "[Content_Types].xml" not in names or not any(n.startswith("xl/") for n in names):
        raise SpreadsheetError("Arquivo .xlsx inválido (estrutura OOXML ausente).")
    total_uncompressed = 0
    for info in archive.infolist():
        total_uncompressed += info.file_size
        if (
            info.compress_size > 0
            and (info.file_size / info.compress_size) > _MAX_COMPRESSION_RATIO
        ):
            raise SpreadsheetError("Planilha rejeitada (possível bomba de descompressão).")
    if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
        raise SpreadsheetError("Planilha rejeitada: conteúdo descomprimido excede o limite.")

    # 2) Streaming row/col/cell/time limits via openpyxl read_only (low memory).
    import openpyxl

    started = time.monotonic()
    workbook = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
    try:
        sheets = workbook.worksheets
        instructions = _norm_header(INSTRUCTIONS_SHEET_TITLE)
        worksheet = next(
            (sheet for sheet in sheets if _norm_header(sheet.title) != instructions),
            sheets[0] if sheets else None,
        )
        if worksheet is None:
            raise SpreadsheetError("Planilha sem aba ativa.")
        row_count = 0
        for row in worksheet.iter_rows(values_only=True):
            row_count += 1
            if row_count > max_rows + 1:  # +1 for the header row
                raise SpreadsheetError(f"A planilha excede o limite de {max_rows} linhas.")
            if len(row) > max_cols:
                raise SpreadsheetError(f"A planilha excede o limite de {max_cols} colunas.")
            for cell in row:
                if isinstance(cell, str) and len(cell) > max_cell_len:
                    raise SpreadsheetError(
                        f"Uma célula excede o limite de {max_cell_len} caracteres."
                    )
            if time.monotonic() - started > max_seconds:
                raise SpreadsheetError("Tempo de processamento da planilha excedido.")
        return str(worksheet.title)
    finally:
        workbook.close()


def read_and_validate(
    source: Path | str | IO[bytes],
    *,
    default_data_emissao: str | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cols: int = DEFAULT_MAX_COLS,
    max_cell_len: int = DEFAULT_MAX_CELL_LEN,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    certificate_type: str | None = None,
) -> ValidationReport:
    """Read an xlsx and return a per-row validation report (nothing persisted).

    ``certificate_type`` selects the column contract: per-work types take the
    authors columns (``autor1`` required, ``nome`` standing in for it only when
    ``autor1`` is absent), require the event and the work title, and may leave
    the workload blank.
    """
    traits = certificate_type_traits(certificate_type)
    per_work = traits.per_work_authors
    data = _materialize_bytes(source)
    sheet_name = enforce_xlsx_limits(
        data,
        max_rows=max_rows,
        max_cols=max_cols,
        max_cell_len=max_cell_len,
        max_seconds=max_seconds,
    )
    dataframe = pd.read_excel(BytesIO(data), sheet_name=sheet_name, engine="openpyxl", dtype=object)

    colmap: dict[str, object] = {}
    for column in dataframe.columns:
        canonical = _REVERSE_SYNONYMS.get(_norm_header(column))
        if canonical and canonical not in colmap:
            colmap[canonical] = column

    report = ValidationReport()
    if per_work:
        if "autor1" not in colmap and "nome" in colmap:
            colmap["autor1"] = colmap.pop("nome")
        ignored = sorted(
            str(column)
            for column in dataframe.columns
            if (match := _AUTHOR_HEADER_RE.match(_norm_header(column)))
            and int(match.group(1)) > MAX_WORK_AUTHORS
        )
        if ignored:
            report.warnings.append(
                "Colunas ignoradas: "
                + ", ".join(ignored)
                + f". Um trabalho tem no máximo {MAX_WORK_AUTHORS} autores."
            )
    required = PER_WORK_REQUIRED_COLUMNS if per_work else REQUIRED_COLUMNS
    missing = [c for c in required if c not in colmap]
    if missing:
        raise SpreadsheetError(
            "Colunas obrigatórias ausentes na planilha: " + ", ".join(sorted(set(missing)))
        )
    has_emissao_default = bool((default_data_emissao or "").strip())

    if len(dataframe) > max_rows:
        raise SpreadsheetError(f"A planilha tem {len(dataframe)} linhas; o limite é {max_rows}.")

    default_emissao_norm = normalize_date(default_data_emissao) if has_emissao_default else None

    author_columns = [f"autor{index}" for index in range(1, MAX_WORK_AUTHORS + 1)]
    for offset, (_, raw) in enumerate(dataframe.iterrows()):
        row_number = offset + 2  # +1 header, +1 to 1-based
        values = {canonical: _cell(raw[col]) for canonical, col in colmap.items()}

        # Blank cells between authors are dropped; the rest keep their order.
        autores = tuple(values.get(column, "") for column in author_columns if values.get(column))
        if per_work:
            if not autores and not values.get("carga_horaria"):
                continue  # skip fully empty rows
        elif not values.get("nome") and not values.get("carga_horaria"):
            continue  # skip fully empty rows

        errors: list[str] = example_text_errors(values)

        # ── Required: name (or first author) + workload ───────────────────────
        if per_work:
            nome = autores[0] if autores else ""
            if not nome:
                errors.append("autor1 é obrigatório")
            # The certificate names the work and the event it was presented at.
            if not values.get("titulo_trabalho"):
                errors.append("titulo_trabalho é obrigatório")
            if not values.get("evento"):
                errors.append("evento é obrigatório")
        else:
            nome = values.get("nome", "")
            if not nome:
                errors.append("nome é obrigatório")

        carga_raw = values.get("carga_horaria", "")
        carga = parse_workload(carga_raw) if carga_raw else None
        if not carga_raw:
            if not traits.optional_workload:
                errors.append("carga_horaria é obrigatória")
        elif carga is None:
            errors.append(f"carga_horaria inválida: '{carga_raw}'")

        # ── Optional: never block a row; normalise when possible ──────────────
        # ``curso`` is canonicalised when it matches the official list, else the
        # raw value is kept. Dates are normalised when parseable, else kept raw.
        curso_raw = values.get("curso", "")
        curso = (match_course(curso_raw) or curso_raw).strip() if curso_raw else ""
        evento = values.get("evento", "")

        emissao_raw = values.get("data_emissao", "")
        if emissao_raw:
            emissao = normalize_date(emissao_raw) or emissao_raw
        else:
            emissao = default_emissao_norm or ""

        inicio_raw = values.get("data_inicio", "")
        inicio = (normalize_date(inicio_raw) or inicio_raw) if inicio_raw else ""

        fim_raw = values.get("data_fim", "")
        fim = (normalize_date(fim_raw) or fim_raw) if fim_raw else ""

        if errors:
            report.invalid.append(InvalidRow(row_number=row_number, data=values, errors=errors))
            continue

        report.valid.append(
            SpreadsheetRow(
                row_number=row_number,
                nome=nome,
                carga_horaria=carga,
                curso=curso,
                evento=evento,
                data_emissao=emissao,
                email=values.get("email", ""),
                documento=values.get("documento", ""),
                data_inicio=inicio,
                data_fim=fim,
                autores=autores if per_work else (),
                equipe=values.get("equipe", ""),
                titulo_trabalho=values.get("titulo_trabalho", ""),
            )
        )

    return report
