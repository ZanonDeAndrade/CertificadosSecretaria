"""Single global certificate template with an immutable version history.

Rules:
  - There is ONE global template; every edit creates a new immutable version.
  - Exactly one version is ``active`` at a time; activation is explicit.
  - The background image lives in durable DB storage (never APPDATA/local JSON);
    ``layout_json`` is the frozen snapshot of dimensions + elements.
  - Each certificate records ``template_version_id`` + a ``template_snapshot`` so
    a reissue reproduces the original faithfully.

There are NO per-course templates and NO per-batch template selection.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import sys
from io import BytesIO
from pathlib import Path

for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "database" / "db.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

from database import db  # noqa: E402

MAX_BACKGROUND_BYTES = 10 * 1024 * 1024  # 10 MB
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPG_MAGIC = b"\xff\xd8\xff"
_SERVING_RE = re.compile(r"^/templates/versions/(\d+)/background$")


class TemplateError(Exception):
    """Invalid template payload (bad/missing background, etc.)."""


# Upload/abuse limits.
MAX_IMAGE_PIXELS = 40_000_000  # 40 MP — guards against decompression bombs
MAX_IMAGE_DIMENSION = 12_000   # max width/height in px
MAX_LAYOUT_ELEMENTS = 200
MAX_TOTAL_DATA_URL_BYTES = 15 * 1024 * 1024


# ── Image helpers ───────────────────────────────────────────────────────────────

def _validate_image(content: bytes) -> None:
    """Validate a template image: format, size, real decodability, and pixel/
    dimension limits (rejecting decompression bombs)."""
    from PIL import Image  # local import keeps module light

    if not content:
        raise TemplateError("Imagem de fundo vazia.")
    if len(content) > MAX_BACKGROUND_BYTES:
        raise TemplateError("Imagem de fundo excede o limite de 10 MB.")
    if content[:8] != _PNG_MAGIC and content[:3] != _JPG_MAGIC:
        raise TemplateError("Imagem de fundo inválida (apenas PNG ou JPG).")

    # Cap pixels so PIL refuses huge/bomb images instead of exhausting memory.
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        # verify() detects truncated/corrupt files (consumes the image object).
        with Image.open(BytesIO(content)) as probe:
            probe.verify()
        with Image.open(BytesIO(content)) as img:
            width, height = img.size
    except TemplateError:
        raise
    except Exception as exc:  # PIL DecompressionBombError / UnidentifiedImageError / ...
        raise TemplateError("Imagem de fundo inválida ou perigosa.") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    if width <= 0 or height <= 0:
        raise TemplateError("Imagem de fundo com dimensões inválidas.")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise TemplateError(
            f"Imagem de fundo grande demais (máx. {MAX_IMAGE_DIMENSION}px por lado)."
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise TemplateError("Imagem de fundo excede o limite de pixels.")


def _enforce_layout_limits(layout: dict) -> None:
    """Cap element count and the total size of embedded data URLs in a layout."""
    elements = layout.get("elements") or []
    if not isinstance(elements, list):
        raise TemplateError("Lista de elementos do template inválida.")
    if len(elements) > MAX_LAYOUT_ELEMENTS:
        raise TemplateError(f"Template excede o limite de {MAX_LAYOUT_ELEMENTS} elementos.")
    total_data_url = 0
    for field_value in [layout.get("background")] + [
        el.get("src") for el in elements if isinstance(el, dict)
    ]:
        if isinstance(field_value, str) and field_value.startswith("data:image"):
            total_data_url += len(field_value)
    if total_data_url > MAX_TOTAL_DATA_URL_BYTES:
        raise TemplateError("Template excede o tamanho total permitido de imagens embutidas.")


def _mime_for(content: bytes) -> str:
    return "image/png" if content[:8] == _PNG_MAGIC else "image/jpeg"


def _decode_data_url(data_url: str) -> bytes:
    _, _, encoded = data_url.partition(",")
    if not encoded:
        raise TemplateError("Data URL de imagem sem conteúdo.")
    try:
        return base64.b64decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise TemplateError("Data URL de imagem inválida.") from exc


def _read_image_size(content: bytes) -> tuple[int, int]:
    from PIL import Image  # local import keeps module light

    with Image.open(BytesIO(content)) as img:
        return int(img.width), int(img.height)


def background_serving_path(version_id: int) -> str:
    return f"/templates/versions/{version_id}/background"


def _resolve_background(bg_field: str) -> tuple[bytes, str]:
    """Return ``(bytes, mime)`` from a data URL or an existing version's image."""
    bg_field = (bg_field or "").strip()
    if bg_field.startswith("data:image"):
        content = _decode_data_url(bg_field)
        _validate_image(content)
        return content, _mime_for(content)
    match = _SERVING_RE.match(bg_field)
    if match:
        existing = db.get_template_background(int(match.group(1)))
        if existing and existing[0]:
            return existing[0], existing[1]
    raise TemplateError("Imagem de fundo do template ausente ou inválida.")


# ── Serialization ───────────────────────────────────────────────────────────────

def _layout_with_background(version: dict) -> dict:
    layout = json.loads(version["layout_json"])
    layout["background"] = background_serving_path(version["id"])
    layout["image_width"] = version["image_width"]
    layout["image_height"] = version["image_height"]
    return layout


def serialize_version(version: dict, *, include_layout: bool = True) -> dict:
    data = {
        "id": version["id"],
        "version_number": version["version_number"],
        "name": version["name"],
        "is_active": bool(version["is_active"]),
        "image_width": version["image_width"],
        "image_height": version["image_height"],
        "background_url": background_serving_path(version["id"]),
        "created_at": version.get("created_at"),
        "created_by": version.get("created_by"),
        "activated_at": version.get("activated_at"),
    }
    if include_layout:
        data["layout"] = _layout_with_background(version)
    return data


# ── Public API ──────────────────────────────────────────────────────────────────

def list_versions() -> list[dict]:
    return [serialize_version(v, include_layout=False) for v in db.list_template_versions()]


def get_version(version_id: int) -> dict | None:
    version = db.get_template_version(version_id)
    return serialize_version(version) if version else None


def get_active_version() -> dict | None:
    version = db.get_active_template_version()
    return serialize_version(version) if version else None


def create_version(*, name: str | None, layout: dict, created_by: int | None = None) -> dict:
    """Create a new immutable version. NOT activated (activation is explicit)."""
    if not isinstance(layout, dict):
        raise TemplateError("Layout inválido.")
    _enforce_layout_limits(layout)
    content, mime = _resolve_background(str(layout.get("background") or ""))
    width = int(layout.get("image_width") or 0)
    height = int(layout.get("image_height") or 0)
    if width <= 0 or height <= 0:
        width, height = _read_image_size(content)
    clean_layout = {
        "image_width": width,
        "image_height": height,
        "elements": layout.get("elements") or [],
    }
    created = db.create_template_version(
        name=(name or "").strip() or None,
        layout_json=json.dumps(clean_layout, ensure_ascii=False),
        image_width=width,
        image_height=height,
        background_image=content,
        background_mime_type=mime,
        created_by=created_by,
    )
    return serialize_version(db.get_template_version(created["id"]))


def activate_version(version_id: int, actor: int | None = None) -> bool:
    return db.activate_template_version(version_id, actor)


def get_background_bytes(version_id: int) -> tuple[bytes, str]:
    result = db.get_template_background(version_id)
    if not result or not result[0]:
        raise TemplateError("Imagem de fundo do template não encontrada.")
    return result[0], result[1]


# ── Default seeding ─────────────────────────────────────────────────────────────

def _placeholder_png() -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (1414, 1000), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _load_default_background(default_png_path: Path) -> bytes:
    try:
        if default_png_path and Path(default_png_path).is_file():
            content = Path(default_png_path).read_bytes()
            if content:
                return content
    except OSError:
        pass
    return _placeholder_png()


def _default_layout(width: int, height: int) -> dict:
    cx = width // 2
    margin = int(width * 0.05)

    def t(key, y_ratio, size_ratio, *, static=None, bold=False, align="center", x=None):
        el = {
            "type": "text",
            "key": "static" if static is not None else key,
            "x": cx if x is None else x,
            "y": int(height * y_ratio),
            "fontSize": max(int(height * size_ratio), 8),
            "fontFamily": "Times New Roman",
            "color": "#000000",
            "align": align,
            "bold": bold,
            "italic": False,
        }
        if static is not None:
            el["staticText"] = static
        return el

    elements = [
        t("static", 0.12, 0.050, static="CERTIFICADO", bold=True),
        t("static", 0.30, 0.022, static="Certificamos, para os devidos fins, que"),
        t("name", 0.355, 0.045, bold=True),
        # Corpo do certificado: o texto padrão escrito pela secretaria é
        # interpolado por linha e renderizado aqui (quebra automática + quebras
        # digitadas). Curso, evento, carga horária e datas entram via variáveis.
        t("texto_certificado", 0.46, 0.024, align="left", x=margin),
        t("date", 0.72, 0.022),
        t("validation_code", 0.92, 0.014),
        {
            "type": "qr",
            "key": "qr",
            "x": margin,
            "y": int(height * 0.82),
            "width": int(height * 0.12),
            "height": int(height * 0.12),
        },
    ]
    return {"image_width": width, "image_height": height, "elements": elements}


def ensure_default_version(default_png_path: Path, created_by: int | None = None) -> None:
    """Seed + activate a default global template version when none exists yet."""
    if db.count_template_versions() > 0:
        return
    content = _load_default_background(default_png_path)
    try:
        width, height = _read_image_size(content)
    except Exception:  # pragma: no cover - corrupt default
        width, height = 1414, 1000
    layout = _default_layout(width, height)
    created = db.create_template_version(
        name="Padrão",
        layout_json=json.dumps(layout, ensure_ascii=False),
        image_width=width,
        image_height=height,
        background_image=content,
        background_mime_type=_mime_for(content),
        created_by=created_by,
    )
    db.activate_template_version(created["id"], created_by)
