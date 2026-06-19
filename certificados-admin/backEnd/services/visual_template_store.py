from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_STORE_PATH = _BACKEND_DIR / "visual_templates.json"
BACKGROUNDS_DIR = _BACKEND_DIR / "visual_template_backgrounds"

# Guards read-modify-write cycles on the JSON store across FastAPI workers
# within a process (prevents lost updates / corruption).
_write_lock = threading.Lock()


def ensure_dirs() -> None:
    BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)


# ── JSON store helpers ────────────────────────────────────────────────────────

def _read() -> list[dict[str, Any]]:
    if not _STORE_PATH.exists():
        return []
    return json.loads(_STORE_PATH.read_text("utf-8") or "[]")


def _write(records: list[dict[str, Any]]) -> None:
    """Atomic write: serialise to a temp file then replace (no partial writes).

    Callers performing a read-modify-write hold ``_write_lock`` around the whole
    cycle (see create/update/delete).
    """
    payload = json.dumps(records, ensure_ascii=False, indent=2)
    tmp_path = _STORE_PATH.with_suffix(".tmp")
    tmp_path.write_text(payload, "utf-8")
    tmp_path.replace(_STORE_PATH)  # atomic rename on the same filesystem


# ── Public CRUD ───────────────────────────────────────────────────────────────

def list_visual_templates() -> list[dict[str, Any]]:
    return _read()


def get_visual_template(template_id: str) -> dict[str, Any] | None:
    return next((t for t in _read() if t["id"] == template_id), None)


def create_visual_template(name: str, layout: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "layout": layout,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _write_lock:  # whole read-modify-write under the lock
        records = _read()
        records.append(record)
        _write(records)
    return record


def update_visual_template(
    template_id: str,
    name: str | None = None,
    layout: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    with _write_lock:
        records = _read()
        for i, t in enumerate(records):
            if t["id"] == template_id:
                if name is not None:
                    records[i]["name"] = name
                if layout is not None:
                    records[i]["layout"] = layout
                records[i]["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write(records)
                return records[i]
    return None


def delete_visual_template(template_id: str) -> bool:
    with _write_lock:
        records = _read()
        filtered = [t for t in records if t["id"] != template_id]
        if len(filtered) == len(records):
            return False
        _write(filtered)
    return True


# ── Background image persistence ──────────────────────────────────────────────

def save_background_image(content: bytes, ext: str) -> tuple[str, int, int]:
    """
    Persist background image and return (relative_url, width, height).
    """
    from PIL import Image  # local import to keep module lightweight

    ensure_dirs()
    img = Image.open(BytesIO(content))
    width, height = img.size

    filename = f"{uuid.uuid4()}{ext}"
    (BACKGROUNDS_DIR / filename).write_bytes(content)

    return f"/visual-template-backgrounds/{filename}", width, height


def resolve_background_path(background_url: str) -> Path:
    """Convert a stored background URL to the local filesystem path."""
    return BACKGROUNDS_DIR / Path(background_url).name
