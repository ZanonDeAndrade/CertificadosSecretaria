"""Spreadsheet model: flexible column reading + per-row validation.

Supported (canonical) columns — header names are normalised (lowercase, no
accents, no spaces/punctuation) and matched against a set of synonyms, so
"Carga Horária", "carga_horaria" and "CH" all resolve to ``carga_horaria``:

    nome*          email          documento/matricula
    curso*         evento*        carga_horaria*
    data_inicio    data_fim       data_emissao*   (* obrigatório)

Rules enforced here:
- ``evento`` is a distinct column (never the course).
- ``carga_horaria`` is parsed to a positive integer (structured).
- ``curso`` must match the canonical course list.
- ``data_emissao`` (per-row, or a form default) is validated.
- invalid rows never produce a certificate.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import IO

import pandas as pd

from utils.courses import COURSES
from utils.dates import normalize_date
from utils.template_store import normalize_course_name

DEFAULT_MAX_ROWS = 2000

_CANONICAL_COURSES = {normalize_course_name(c): c for c in COURSES}


# ── Column synonyms ─────────────────────────────────────────────────────────────

_COLUMN_SYNONYMS: dict[str, set[str]] = {
    "nome": {"nome", "name", "participante", "aluno", "nomecompleto"},
    "email": {"email", "e-mail", "correio", "emailaluno"},
    "documento": {"documento", "cpf", "matricula", "registro", "document", "doc", "ra"},
    "curso": {"curso", "course", "cursonome"},
    "evento": {"evento", "event", "atividade", "nomeevento"},
    "carga_horaria": {"cargahoraria", "carga", "ch", "horas", "workload", "cargahorariatotal"},
    "data_inicio": {"datainicio", "inicio", "datadeinicio", "start", "startdate"},
    "data_fim": {"datafim", "fim", "termino", "datatermino", "end", "enddate"},
    "data_emissao": {"dataemissao", "emissao", "datadeemissao", "issuedate", "dataemissaocertificado"},
}

REQUIRED_COLUMNS = ("nome", "curso", "evento", "carga_horaria")


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
    curso: str            # canonical course name
    evento: str
    carga_horaria: int
    data_emissao: str     # normalised (por extenso)
    email: str = ""
    documento: str = ""
    data_inicio: str = ""
    data_fim: str = ""


@dataclass
class InvalidRow:
    row_number: int
    data: dict
    errors: list[str]


@dataclass
class ValidationReport:
    valid: list[SpreadsheetRow] = field(default_factory=list)
    invalid: list[InvalidRow] = field(default_factory=list)

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


def compute_business_key(row: SpreadsheetRow) -> str:
    """Stable hash identifying a unique certificate (idempotency).

    Based on name + document + event + course + workload + issue date, all
    normalised, so re-uploading the same spreadsheet does not duplicate.
    """
    parts = [
        _norm_text(row.nome),
        _norm_text(row.documento),
        _norm_text(row.evento),
        _norm_text(row.curso),
        str(row.carga_horaria),
        _norm_text(row.data_emissao),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# ── Reader ──────────────────────────────────────────────────────────────────────


def read_and_validate(
    source: Path | str | IO[bytes],
    *,
    default_data_emissao: str | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> ValidationReport:
    """Read an xlsx and return a per-row validation report (nothing persisted)."""
    dataframe = pd.read_excel(source, engine="openpyxl", dtype=object)

    colmap: dict[str, object] = {}
    for column in dataframe.columns:
        canonical = _REVERSE_SYNONYMS.get(_norm_header(column))
        if canonical and canonical not in colmap:
            colmap[canonical] = column

    missing = [c for c in REQUIRED_COLUMNS if c not in colmap]
    has_emissao_default = bool((default_data_emissao or "").strip())
    if "data_emissao" not in colmap and not has_emissao_default:
        missing.append("data_emissao")
    if missing:
        raise SpreadsheetError(
            "Colunas obrigatórias ausentes na planilha: " + ", ".join(sorted(set(missing)))
        )

    if len(dataframe) > max_rows:
        raise SpreadsheetError(
            f"A planilha tem {len(dataframe)} linhas; o limite é {max_rows}."
        )

    default_emissao_norm = normalize_date(default_data_emissao) if has_emissao_default else None

    report = ValidationReport()
    for offset, (_, raw) in enumerate(dataframe.iterrows()):
        row_number = offset + 2  # +1 header, +1 to 1-based
        values = {canonical: _cell(raw[col]) for canonical, col in colmap.items()}

        if not any(values.get(c) for c in ("nome", "curso", "evento")):
            continue  # skip fully empty rows

        errors: list[str] = []

        nome = values.get("nome", "")
        if not nome:
            errors.append("nome é obrigatório")

        curso_raw = values.get("curso", "")
        curso = match_course(curso_raw) if curso_raw else None
        if not curso_raw:
            errors.append("curso é obrigatório")
        elif curso is None:
            errors.append(f"curso inválido: '{curso_raw}' não está na lista oficial")

        evento = values.get("evento", "")
        if not evento:
            errors.append("evento é obrigatório")

        carga_raw = values.get("carga_horaria", "")
        carga = parse_workload(carga_raw) if carga_raw else None
        if not carga_raw:
            errors.append("carga_horaria é obrigatória")
        elif carga is None:
            errors.append(f"carga_horaria inválida: '{carga_raw}'")

        emissao_raw = values.get("data_emissao", "")
        emissao = normalize_date(emissao_raw) if emissao_raw else default_emissao_norm
        if not emissao_raw and not default_emissao_norm:
            errors.append("data_emissao é obrigatória")
        elif emissao is None:
            errors.append(f"data_emissao inválida: '{emissao_raw}'")

        inicio = ""
        if values.get("data_inicio"):
            inicio_norm = normalize_date(values["data_inicio"])
            if inicio_norm is None:
                errors.append(f"data_inicio inválida: '{values['data_inicio']}'")
            else:
                inicio = inicio_norm

        fim = ""
        if values.get("data_fim"):
            fim_norm = normalize_date(values["data_fim"])
            if fim_norm is None:
                errors.append(f"data_fim inválida: '{values['data_fim']}'")
            else:
                fim = fim_norm

        if errors:
            report.invalid.append(InvalidRow(row_number=row_number, data=values, errors=errors))
            continue

        report.valid.append(
            SpreadsheetRow(
                row_number=row_number,
                nome=nome,
                curso=curso,  # canonical
                evento=evento,
                carga_horaria=carga,
                data_emissao=emissao,
                email=values.get("email", ""),
                documento=values.get("documento", ""),
                data_inicio=inicio,
                data_fim=fim,
            )
        )

    return report
