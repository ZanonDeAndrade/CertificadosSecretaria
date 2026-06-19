from __future__ import annotations

import re
import unicodedata
from pathlib import Path

DEFAULT_FILENAME = "certificado"


def sanitize_filename(value: str, replacement: str = "_") -> str:
    normalized = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", replacement, normalized).strip("._-")
    sanitized = re.sub(rf"{re.escape(replacement)}+", replacement, sanitized)
    return sanitized or DEFAULT_FILENAME


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
