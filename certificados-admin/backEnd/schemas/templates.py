"""Request/response models of the template text-layout endpoint.

The editor asks the backend where each text element's lines break, so the
preview wraps exactly where the PDF will. Items carry the same keys the layout
JSON uses for an element (``fontSize``, ``fontFamily``…), so the frontend can
forward its elements without translating field names.
"""

from __future__ import annotations

from typing import Any, Literal

from certificados_backend.services.template_service import MAX_IMAGE_DIMENSION
from pydantic import BaseModel, Field

MAX_TEXT_LAYOUT_ITEMS = 100
# The authored body is capped at 3000 characters before variables are resolved;
# this leaves room for the resolved values and the editor's sample data.
MAX_TEXT_LAYOUT_CHARS = 4000
MAX_TEXT_LAYOUT_FONT_SIZE = 600


class TextLayoutItemRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    key: str = Field(default="static", max_length=64)
    text: str = Field(max_length=MAX_TEXT_LAYOUT_CHARS)
    x: int = Field(ge=-MAX_IMAGE_DIMENSION, le=MAX_IMAGE_DIMENSION)
    fontSize: int = Field(ge=6, le=MAX_TEXT_LAYOUT_FONT_SIZE)
    fontFamily: str = Field(default="Times New Roman", max_length=64)
    bold: bool = False
    align: Literal["left", "center", "right"] = "left"
    width: int | None = Field(default=None, ge=1, le=MAX_IMAGE_DIMENSION)
    height: int | None = Field(default=None, ge=1, le=MAX_IMAGE_DIMENSION)

    def as_element(self) -> dict[str, Any]:
        element: dict[str, Any] = {
            "key": self.key,
            "x": self.x,
            "fontSize": self.fontSize,
            "fontFamily": self.fontFamily,
            "bold": self.bold,
            "align": self.align,
        }
        if self.width is not None:
            element["width"] = self.width
        if self.height is not None:
            element["height"] = self.height
        return element


class TextLayoutRequest(BaseModel):
    image_width: int = Field(ge=1, le=MAX_IMAGE_DIMENSION)
    items: list[TextLayoutItemRequest] = Field(max_length=MAX_TEXT_LAYOUT_ITEMS)


class TextLayoutItemResponse(BaseModel):
    id: str
    lines: list[str]
    font_size: int
    line_height: int
    text_height: int
    wrap_width: int | None
    overflow: bool
    top_offset: int


class TextLayoutResponse(BaseModel):
    items: list[TextLayoutItemResponse]


class EmptySettingResponse(BaseModel):
    setting: str
    label: str


class TemplateSampleDataResponse(BaseModel):
    """Preview values resolved like the PDF resolves them, with the gaps."""

    values: dict[str, str]
    empty_settings: list[EmptySettingResponse]
    can_manage_settings: bool
