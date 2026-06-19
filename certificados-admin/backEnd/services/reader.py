from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import IO

import pandas as pd

from models import Participant

EXPECTED_COLUMNS = (
    "nome",
    "email",
    "curso",
)
REQUIRED_FIELDS = ("nome", "email", "curso")


def read_participants(excel_source: Path | str | IO[bytes]) -> list[Participant]:
    if isinstance(excel_source, Path) and not excel_source.exists():
        raise FileNotFoundError(f"Arquivo Excel nao encontrado: {excel_source}")

    dataframe = pd.read_excel(excel_source, engine="openpyxl")
    dataframe.columns = [_normalize_column_name(column) for column in dataframe.columns]

    missing_columns = sorted(set(EXPECTED_COLUMNS) - set(dataframe.columns))
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"Colunas obrigatorias ausentes no Excel: {missing}")

    participants: list[Participant] = []

    for row_number, row in enumerate(
        dataframe.loc[:, EXPECTED_COLUMNS].itertuples(index=False, name=None),
        start=2,
    ):
        row_data = dict(zip(EXPECTED_COLUMNS, row, strict=True))
        normalized_data = {key: _normalize_cell_value(value) for key, value in row_data.items()}

        if all(not normalized_data[column] for column in EXPECTED_COLUMNS):
            continue

        missing_fields = [field for field in REQUIRED_FIELDS if not normalized_data[field]]
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise ValueError(
                f"Linha {row_number} do Excel possui campos obrigatorios vazios: {missing}"
            )

        participants.append(Participant(**normalized_data))

    return participants


def _normalize_column_name(column_name: object) -> str:
    return str(column_name).strip().lower().replace(" ", "_")


def _normalize_cell_value(value: object) -> str:
    if pd.isna(value):
        return ""

    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().strftime("%d/%m/%Y")

    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")

    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()
