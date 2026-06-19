from __future__ import annotations

import json
import os
import threading
import unicodedata
import uuid
from pathlib import Path


def _resolve_app_data_dir() -> Path:
    """Return a writable persistent directory for app data."""
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "CertificadosApp"
    # Fallback for non-Windows or missing APPDATA
    return Path.home() / ".CertificadosApp"


APP_DATA_DIR = _resolve_app_data_dir()
TEMPLATES_DIR = APP_DATA_DIR / "templates"
TEMPLATES_JSON = APP_DATA_DIR / "templates.json"

MAX_TEMPLATE_BYTES = 5 * 1024 * 1024  # 5 MB

_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Directory bootstrap
# ---------------------------------------------------------------------------


def ensure_app_dirs() -> None:
    """Create all required directories if they do not exist."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Course name normalisation
# ---------------------------------------------------------------------------


def normalize_course_name(course: str) -> str:
    """
    Produce a stable, lowercase ASCII key from an arbitrary course name.

    "Engenharia Civil" -> "engenharia_civil"
    "Ciências Contábeis" -> "ciencias_contabeis"
    """
    stripped = course.strip()
    # Unicode decomposition + drop non-ASCII characters
    nfkd = unicodedata.normalize("NFKD", stripped)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    # Collapse whitespace and replace with underscores
    return "_".join(ascii_only.lower().split())


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------


def load_templates() -> dict[str, str]:
    """
    Return the stored course→relative-path mapping.

    Returns an empty dict when the file is absent, empty, or corrupt
    so that callers can always rely on getting a valid dict.
    """
    if not TEMPLATES_JSON.exists():
        return {}
    try:
        raw = TEMPLATES_JSON.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        # Keep only clean string pairs to guard against manual edits
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    except (json.JSONDecodeError, OSError):
        return {}


def save_templates(data: dict[str, str]) -> None:
    """
    Persist the templates mapping to JSON.

    Uses a write-then-replace strategy so a crash mid-write never
    leaves a corrupt templates.json.  Protected by a threading lock
    for concurrent FastAPI workers.
    """
    ensure_app_dirs()
    tmp_path = TEMPLATES_JSON.with_suffix(".tmp")
    with _write_lock:
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Atomic rename (on the same filesystem this is a single syscall)
        tmp_path.replace(TEMPLATES_JSON)


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------


def get_template_for_course(course: str, default: Path) -> Path:
    """
    Return the stored template path for *course*, or *default* if none exists.

    Falls back to *default* when:
    - The course has no entry in templates.json
    - The recorded file no longer exists on disk
    """
    key = normalize_course_name(course)
    templates = load_templates()
    relative = templates.get(key)
    if relative:
        candidate = APP_DATA_DIR / relative
        if candidate.exists():
            return candidate
    return default


# ---------------------------------------------------------------------------
# Template registration
# ---------------------------------------------------------------------------


def register_template(course_name: str, file_bytes: bytes, ext: str = ".png") -> str:
    """
    Store a PNG or JPG template for *course_name* and update templates.json.

    - Validates content length (enforced before calling, but double-checked here)
    - Deletes the previous file for the same course to avoid orphaned files
    - Uses a UUID filename to prevent path-traversal and collisions

    Returns the relative path stored in templates.json (e.g. "templates/abc123.png").
    """
    if len(file_bytes) > MAX_TEMPLATE_BYTES:
        raise ValueError("Arquivo excede o tamanho maximo de 5 MB.")

    ensure_app_dirs()
    key = normalize_course_name(course_name)
    templates = load_templates()

    # Remove the previous file for this course if it exists
    old_relative = templates.get(key)
    if old_relative:
        old_path = APP_DATA_DIR / old_relative
        try:
            old_path.unlink(missing_ok=True)
        except OSError:
            pass  # Non-critical: old file removal is best-effort

    # Save new file under a UUID name inside TEMPLATES_DIR
    safe_ext = ext if ext in (".png", ".jpg") else ".png"
    filename = f"{uuid.uuid4().hex}{safe_ext}"
    dest = TEMPLATES_DIR / filename
    dest.write_bytes(file_bytes)

    relative = f"templates/{filename}"
    templates[key] = relative
    save_templates(templates)
    return relative
