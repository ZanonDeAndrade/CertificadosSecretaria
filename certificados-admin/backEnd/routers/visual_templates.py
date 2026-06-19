from __future__ import annotations

import sys
from pathlib import Path as _Path

_BACKEND_DIR = str(_Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from services.visual_template_store import (
    create_visual_template,
    delete_visual_template,
    get_visual_template,
    list_visual_templates,
    save_background_image,
    update_visual_template,
)

LOGGER = logging.getLogger("certificados.visual_templates")

router = APIRouter(prefix="/visual-templates", tags=["Visual Templates"])

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPG_MAGIC = b"\xff\xd8\xff"
_MAX_BG_BYTES = 10 * 1024 * 1024  # 10 MB


# ── Pydantic models ───────────────────────────────────────────────────────────

class CreateTemplateRequest(BaseModel):
    name: str
    layout: dict[str, Any]


class UpdateTemplateRequest(BaseModel):
    name: str | None = None
    layout: dict[str, Any] | None = None


class BackgroundUploadResponse(BaseModel):
    background_url: str
    image_width: int
    image_height: int


# ── Background upload ─────────────────────────────────────────────────────────

@router.post("/background", response_model=BackgroundUploadResponse)
async def upload_background(file: UploadFile = File(...)) -> BackgroundUploadResponse:
    filename = (file.filename or "").strip().lower()
    if not any(filename.endswith(ext) for ext in (".png", ".jpg", ".jpeg")):
        raise HTTPException(400, "Apenas PNG ou JPG são aceitos como background.")

    content = await file.read()
    await file.close()

    if not content:
        raise HTTPException(400, "Arquivo vazio.")
    if len(content) > _MAX_BG_BYTES:
        raise HTTPException(400, "Arquivo excede o limite de 10 MB.")
    if content[:8] != _PNG_MAGIC and content[:3] != _JPG_MAGIC:
        raise HTTPException(400, "Conteúdo inválido — não é PNG ou JPG.")

    ext = ".png" if content[:8] == _PNG_MAGIC else ".jpg"
    try:
        url, width, height = save_background_image(content, ext)
    except Exception as exc:
        LOGGER.exception("Erro ao salvar background: %s", exc)
        raise HTTPException(500, "Não foi possível salvar o background.") from exc

    return BackgroundUploadResponse(background_url=url, image_width=width, image_height=height)


# ── Template CRUD ─────────────────────────────────────────────────────────────

@router.get("")
async def list_templates() -> list[dict]:
    return list_visual_templates()


@router.post("")
async def create_template(body: CreateTemplateRequest) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "O nome do template não pode ser vazio.")
    return create_visual_template(name=body.name.strip(), layout=body.layout)


@router.get("/{template_id}")
async def get_template(template_id: str) -> dict:
    tmpl = get_visual_template(template_id)
    if not tmpl:
        raise HTTPException(404, "Template não encontrado.")
    return tmpl


@router.put("/{template_id}")
async def update_template(template_id: str, body: UpdateTemplateRequest) -> dict:
    tmpl = update_visual_template(template_id, name=body.name, layout=body.layout)
    if not tmpl:
        raise HTTPException(404, "Template não encontrado.")
    return tmpl


@router.delete("/{template_id}")
async def delete_template_route(template_id: str) -> dict:
    if not delete_visual_template(template_id):
        raise HTTPException(404, "Template não encontrado.")
    return {"deleted": True}
