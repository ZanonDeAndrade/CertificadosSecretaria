from __future__ import annotations

import base64
import binascii
import platform
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from models import ParticipantRegistryRecord
from utils.file_utils import ensure_directory, sanitize_filename
from utils.text_utils import (
    calculate_centered_x,
    get_text_size,
    wrap_hard_breaks,
    wrap_text,
    wrap_text_para,
)

_SYSTEM = platform.system()
_WINDOWS_FONTS = Path("C:/Windows/Fonts")
_LINUX_FONTS = Path("/usr/share/fonts")
_RESAMPLE_LANCZOS = (
    Image.Resampling.LANCZOS
    if hasattr(Image, "Resampling")
    else Image.LANCZOS
)

TEXT_COLOR     = "#000000"

# Visual-template element keys that hold the (potentially long) certificate body
# authored by the secretaria. These are word-wrapped and may span many lines.
_BODY_TEXT_KEYS = {"texto_certificado", "certificate_text"}

# ── Font sizes as fraction of image HEIGHT (scale with any template) ──────────
# Calibrated for a 3508×2480 px (A4 @ 300 dpi) template.
# For a 2480 px tall image these produce approximately:
#   name ≈ 119 px  |  preamble ≈ 55 px  |  body ≈ 60 px
#   date ≈ 50 px   |  signatory ≈ 45 px |  registry ≈ 32 px
PREAMBLE_SIZE_RATIO  = 0.023
NAME_SIZE_RATIO      = 0.048
MIN_NAME_SIZE_RATIO  = 0.026
BODY_SIZE_RATIO      = 0.028
MIN_BODY_SIZE_RATIO  = 0.018
DATE_SIZE_RATIO      = 0.020
SIGNATORY_SIZE_RATIO = 0.018
META_SIZE_RATIO      = 0.013
BODY_LINE_SPACING_RATIO = 0.009

# ── Text column – left safe zone ──────────────────────────────────────────────
SIDE_MARGIN_RATIO = 0.05
BODY_WIDTH_RATIO  = 0.525      # keeps clear of the right decoration while using the text area

# ── Upper block: fixed Y anchors (fraction of image height) ───────────────────
PREAMBLE_Y_RATIO = 0.32
NAME_Y_RATIO     = 0.365
BODY_Y_RATIO     = 0.445

# ── Lower block: anchored from BOTTOM upward ──────────────────────────────────
# Registry sits at REGISTRY_BOTTOM_Y_RATIO from the top (≈ 5 % from the bottom).
# Every other element is stacked above it.
REGISTRY_BOTTOM_Y_RATIO  = 0.95   # top-left of registry text
SIG_BLOCK_GAP_RATIO      = 0.012  # gap between consecutive lines in sig block
SIGNATURE_BLANK_RATIO    = 0.08   # blank vertical space reserved for physical signature
DATE_BODY_GAP_RATIO      = 0.03   # minimum gap between body end and date line
DATE_MIN_Y_RATIO         = 0.62   # date never placed above this (when body is short)

# ── Constant strings ──────────────────────────────────────────────────────────
PREAMBLE_TEXT = "Certificamos, para os devidos fins, que"


@dataclass(slots=True, frozen=True)
class CertificateGeneratorConfig:
    template_path: Path
    regular_font_path: Path
    bold_font_path: Path
    output_dir: Path
    # Institution/signatory data — configured via environment (no hardcoding).
    issue_location: str = ""
    signatory_name: str = ""
    signatory_title: str = ""


def build_pdf_filename(participant: ParticipantRegistryRecord) -> str:
    """Build a unique PDF filename: "<nome>_<codigo>.pdf".

    Including the validation code guarantees two participants with the same name
    don't overwrite each other's file (and ties the file to its DB row)."""
    stem = sanitize_filename(participant.nome)
    if participant.validation_code:
        stem = f"{stem}_{participant.validation_code}"
    return f"{stem}.pdf"


def _image_to_pdf_bytes(image: Image.Image) -> bytes:
    """Render a composed PIL image to in-memory PDF bytes (A4 @ 300 dpi)."""
    buffer = BytesIO()
    image.convert("RGB").save(buffer, "PDF", resolution=300.0)
    return buffer.getvalue()


def make_qr_image(data: str, size_px: int) -> Image.Image:
    """Return a square QR-code image (RGBA) encoding ``data``."""
    import qrcode  # local import; lib listed in requirements

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
    if image.size != (size_px, size_px):
        image = image.resize((size_px, size_px), Image.NEAREST)
    return image


class CertificateGenerator:
    def __init__(self, config: CertificateGeneratorConfig) -> None:
        self.config = config
        ensure_directory(self.config.output_dir)

    def generate(
        self,
        participant: ParticipantRegistryRecord,
        template_path: Path | None = None,
        qr_url: str | None = None,
    ) -> Path:
        """Compose and write a PDF to ``output_dir`` (kept for compatibility)."""
        image = self._compose_default_image(participant, template_path, qr_url)
        output_path = self.config.output_dir / build_pdf_filename(participant)
        image.convert("RGB").save(output_path, "PDF", resolution=300.0)
        return output_path

    def render_pdf_bytes_default(
        self,
        participant: ParticipantRegistryRecord,
        template_path: Path | None = None,
        qr_url: str | None = None,
    ) -> bytes:
        """Compose the default-layout certificate and return PDF bytes."""
        image = self._compose_default_image(participant, template_path, qr_url)
        return _image_to_pdf_bytes(image)

    def _compose_default_image(
        self,
        participant: ParticipantRegistryRecord,
        template_path: Path | None = None,
        qr_url: str | None = None,
    ) -> Image.Image:
        base_image = self._load_base_image(template_path)
        draw = ImageDraw.Draw(base_image)
        width, height = base_image.size
        col_w    = int(width  * BODY_WIDTH_RATIO)
        origin_x = int(width  * SIDE_MARGIN_RATIO)

        # ── Compute all sizes from image height ───────────────────────────────
        preamble_sz  = max(int(height * PREAMBLE_SIZE_RATIO),  8)
        name_sz      = max(int(height * NAME_SIZE_RATIO),     16)
        min_name_sz  = max(int(height * MIN_NAME_SIZE_RATIO), 12)
        body_sz      = max(int(height * BODY_SIZE_RATIO),     10)
        min_body_sz  = max(int(height * MIN_BODY_SIZE_RATIO),  8)
        date_sz      = max(int(height * DATE_SIZE_RATIO),      8)
        sig_sz       = max(int(height * SIGNATORY_SIZE_RATIO), 8)
        meta_sz      = max(int(height * META_SIZE_RATIO),      6)
        line_spacing = max(int(height * BODY_LINE_SPACING_RATIO), 4)

        # ── Compute lower-block Y positions (bottom-up) ───────────────────────
        sig_gap      = int(height * SIG_BLOCK_GAP_RATIO)
        sig_blank    = int(height * SIGNATURE_BLANK_RATIO)

        registry_y   = int(height * REGISTRY_BOTTOM_Y_RATIO)
        sig_title_y  = registry_y   - sig_gap - sig_sz
        sig_name_y   = sig_title_y  - sig_gap - sig_sz
        date_y       = max(
            sig_name_y - sig_blank - date_sz,
            int(height * DATE_MIN_Y_RATIO),
        )

        # ── Available vertical space for body text ────────────────────────────
        body_start_y    = int(height * BODY_Y_RATIO)
        body_gap        = int(height * DATE_BODY_GAP_RATIO)
        max_body_bottom = date_y - body_gap

        # ── Load fonts ────────────────────────────────────────────────────────
        preamble_font = self._load_font(self.config.regular_font_path, preamble_sz)
        name_font     = self._fit_font_to_width(
            draw, participant.nome, self.config.bold_font_path,
            name_sz, min_name_sz, col_w,
        )
        body_font, body_lines = self._fit_body_to_space(
            draw, participant.texto_certificado,
            self.config.regular_font_path, col_w,
            body_sz, min_body_sz, line_spacing,
            max_body_bottom - body_start_y,
        )
        date_font = self._load_font(self.config.regular_font_path, date_sz)
        sig_font  = self._load_font(self.config.regular_font_path, sig_sz)
        meta_font = self._load_font(self.config.regular_font_path, meta_sz)

        # ── Draw upper block ──────────────────────────────────────────────────
        self._draw_centered(draw, PREAMBLE_TEXT, int(height * PREAMBLE_Y_RATIO),
                            col_w, origin_x, preamble_font)
        self._draw_centered(draw, participant.nome, int(height * NAME_Y_RATIO),
                            col_w, origin_x, name_font)
        self._draw_body(draw, participant.texto_certificado, body_start_y,
                        col_w, origin_x, body_font, line_spacing)

        # ── Draw lower block ──────────────────────────────────────────────────
        location = self.config.issue_location.strip()
        if location:
            issue_text = f"{location}, {participant.data_emissao}."
        else:
            issue_text = f"{participant.data_emissao}." if participant.data_emissao else ""
        if issue_text:
            self._draw_centered(draw, issue_text, date_y, col_w, origin_x, date_font)
        if self.config.signatory_name.strip():
            self._draw_centered(
                draw, self.config.signatory_name.strip(), sig_name_y, col_w, origin_x, sig_font
            )
        if self.config.signatory_title.strip():
            self._draw_centered(
                draw, self.config.signatory_title.strip(), sig_title_y, col_w, origin_x, sig_font
            )
        self._draw_registry(draw, registry_y, col_w, origin_x, participant, meta_font)

        # QR code (validação pública) — canto inferior esquerdo, fora da coluna
        # de texto/assinatura. O código textual continua visível à direita.
        if qr_url:
            self._draw_qr(base_image, qr_url, origin_x, registry_y, height)

        return base_image

    def _draw_qr(
        self,
        base_image: Image.Image,
        qr_url: str,
        origin_x: int,
        registry_y: int,
        height: int,
    ) -> None:
        try:
            qr_size = max(int(height * 0.12), 96)
            qr_img = make_qr_image(qr_url, qr_size)
            qr_y = max(registry_y - qr_size, 0)
            base_image.alpha_composite(qr_img, dest=(origin_x, qr_y))
        except Exception:  # pragma: no cover - QR is best-effort, never breaks gen
            pass

    # ── Drawing helpers ───────────────────────────────────────────────────────

    def _draw_centered(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        y: int,
        col_w: int,
        origin_x: int,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        x = calculate_centered_x(draw, text, font, col_w, origin_x)
        draw.text((x, y), text, fill=TEXT_COLOR, font=font)

    def _draw_body(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        start_y: int,
        col_w: int,
        origin_x: int,
        font: ImageFont.FreeTypeFont,
        line_spacing: int,
    ) -> None:
        """Draw body text with full justification.

        Every line is stretched to fill col_w exactly, except the last line of
        each paragraph (which is left-aligned, as per typographic convention).
        Single-word lines are also left-aligned to avoid extreme spacing.
        """
        lines_with_flags = wrap_text_para(draw, text, font, col_w)
        line_h = get_text_size(draw, "Ag", font)[1] + line_spacing
        y = start_y

        for line, is_para_end in lines_with_flags:
            words = line.split()

            # Last line of paragraph, empty lines, or single-word lines: left-align
            if is_para_end or len(words) <= 1 or not line.strip():
                draw.text((origin_x, y), line, fill=TEXT_COLOR, font=font)
            else:
                # Full justification: distribute extra space evenly between words
                word_widths = [get_text_size(draw, w, font)[0] for w in words]
                total_word_w = sum(word_widths)
                gap = (col_w - total_word_w) / (len(words) - 1)
                x = float(origin_x)
                for word, ww in zip(words, word_widths):
                    draw.text((int(x), y), word, fill=TEXT_COLOR, font=font)
                    x += ww + gap

            y += line_h

    def _draw_registry(
        self,
        draw: ImageDraw.ImageDraw,
        y: int,
        col_w: int,
        origin_x: int,
        participant: ParticipantRegistryRecord,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        text = f"C\u00f3digo de valida\u00e7\u00e3o: {participant.validation_code}"
        tw, _ = get_text_size(draw, text, font)
        x = origin_x + max(col_w - tw, 0)
        draw.text((x, y), text, fill=TEXT_COLOR, font=font)

    # ── Font fitting ──────────────────────────────────────────────────────────

    def _fit_font_to_width(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font_path: Path,
        initial_size: int,
        min_size: int,
        max_width: int,
    ) -> ImageFont.FreeTypeFont:
        size = initial_size
        font = self._load_font(font_path, size)
        while size > min_size and get_text_size(draw, text, font)[0] > max_width:
            size -= 2
            font = self._load_font(font_path, size)
        return font

    def _fit_body_to_space(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font_path: Path,
        col_w: int,
        initial_size: int,
        min_size: int,
        line_spacing: int,
        available_height: int,
    ) -> tuple[ImageFont.FreeTypeFont, list[str]]:
        """Shrink font until all wrapped lines fit inside available_height."""
        size = initial_size
        font = self._load_font(font_path, size)
        lines = wrap_text(draw, text, font, col_w)

        while size > min_size:
            line_h = get_text_size(draw, "Ag", font)[1] + line_spacing
            if len(lines) * line_h <= max(available_height, line_h):
                break
            size -= 2
            font  = self._load_font(font_path, size)
            lines = wrap_text(draw, text, font, col_w)

        return font, lines

    # ── Internal utilities ────────────────────────────────────────────────────

    # ── Visual template generation ────────────────────────────────────────────

    def render_pdf_bytes_visual(
        self,
        participant: ParticipantRegistryRecord,
        layout: dict[str, Any],
        *,
        qr_url: str | None = None,
        background_bytes: bytes | None = None,
    ) -> bytes:
        """Compose a visual-template certificate and return PDF bytes.

        The background is provided as raw bytes (durable DB-stored template
        image) — the generator never reads template assets from disk.
        """
        image = self._compose_visual_image(
            participant, layout, qr_url=qr_url, background_bytes=background_bytes
        )
        return _image_to_pdf_bytes(image)

    def _compose_visual_image(
        self,
        participant: ParticipantRegistryRecord,
        layout: dict[str, Any],
        *,
        qr_url: str | None = None,
        background_bytes: bytes | None = None,
    ) -> Image.Image:
        """Render a certificate image using a visual template layout dict."""
        image = self._open_background_bytes(background_bytes)
        draw = ImageDraw.Draw(image)

        participant_data = self._participant_data(participant)

        for element in layout.get("elements", []):
            element_type = element.get("type", "text")
            if element_type == "image":
                self._draw_visual_image(image, element)
                continue
            if element_type == "qr" or element.get("key") == "qr":
                if qr_url:
                    self._draw_visual_qr(image, element, qr_url)
                continue
            if element_type != "text":
                continue

            key: str = element.get("key", "")
            if key == "static":
                text = element.get("staticText", "")
            else:
                text = participant_data.get(key, f"[{key}]")

            if not text:
                continue

            font_size = max(int(element.get("fontSize", 24)), 6)
            font_family: str = element.get("fontFamily", "Times New Roman")
            bold: bool = bool(element.get("bold", False))
            color: str = element.get("color", "#000000")
            align: str = element.get("align", "left")
            anchor_x = int(element.get("x", 0))
            anchor_y = int(element.get("y", 0))

            font = self._resolve_visual_font(font_family, font_size, bold)

            # The body text can be long: wrap it, respect typed line breaks, keep
            # it inside the certificate, and honour the configured alignment.
            if key in _BODY_TEXT_KEYS:
                self._draw_text_block(
                    draw, image, text, font,
                    color=color, align=align,
                    anchor_x=anchor_x, anchor_y=anchor_y,
                    font_size=font_size, element=element,
                )
                continue

            tw, _ = get_text_size(draw, text, font)

            if align == "center":
                draw_x = anchor_x - tw // 2
            elif align == "right":
                draw_x = anchor_x - tw
            else:
                draw_x = anchor_x

            draw.text((draw_x, anchor_y), text, fill=color, font=font)

        return image

    def _wrap_bound(self, align: str, anchor_x: int, image_width: int, margin: int) -> int:
        """Max line width that keeps the text inside the page for an alignment.

        - left  → grows right: room from the anchor to the right margin;
        - right → grows left:  room from the anchor to the left margin;
        - center→ grows both ways: symmetric room around the anchor.
        """
        if align == "center":
            return max(2 * (min(anchor_x, image_width - anchor_x) - margin), 1)
        if align == "right":
            return max(anchor_x - margin, 1)
        return max(image_width - anchor_x - margin, 1)

    def _draw_text_block(
        self,
        draw: ImageDraw.ImageDraw,
        image: Image.Image,
        text: str,
        font: ImageFont.FreeTypeFont,
        *,
        color: str,
        align: str,
        anchor_x: int,
        anchor_y: int,
        font_size: int,
        element: dict[str, Any],
    ) -> None:
        """Render a (possibly long) body text: word-wrap + typed line breaks,
        alignment, and a width limit so it never leaves the certificate."""
        image_width = image.size[0]
        margin = max(int(image_width * 0.04), 8)
        bound = self._wrap_bound(align, anchor_x, image_width, margin)

        explicit = element.get("width") or element.get("maxWidth")
        if isinstance(explicit, (int, float)) and explicit > 0:
            wrap_w = max(1, min(int(explicit), bound))
        else:
            wrap_w = bound

        line_spacing = max(int(font_size * 0.3), 2)
        line_h = get_text_size(draw, "Ag", font)[1] + line_spacing

        y = anchor_y
        for line in wrap_hard_breaks(draw, text, font, wrap_w):
            if line:
                lw, _ = get_text_size(draw, line, font)
                if align == "center":
                    draw_x = anchor_x - lw // 2
                elif align == "right":
                    draw_x = anchor_x - lw
                else:
                    draw_x = anchor_x
                draw.text((draw_x, y), line, fill=color, font=font)
            y += line_h

    def _participant_data(self, participant: ParticipantRegistryRecord) -> dict[str, str]:
        """Map template keys to certificate values.

        ``event`` and ``course`` are DISTINCT fields (bug fix: ``event`` used to
        receive the course)."""
        return {
            "name": participant.nome,
            "event": participant.evento,
            "course": participant.curso,
            "date": participant.data_emissao,
            "validation_code": participant.validation_code,
            "texto_certificado": participant.texto_certificado,
            "certificate_text": participant.certificate_text or participant.texto_certificado,
        }

    def _open_background_bytes(self, background_bytes: bytes | None) -> Image.Image:
        if not background_bytes:
            raise ValueError(
                "Template sem imagem de fundo (background_bytes ausente)."
            )
        return Image.open(BytesIO(background_bytes)).convert("RGBA")

    def _draw_visual_image(self, base_image: Image.Image, element: dict[str, Any]) -> None:
        source = str(element.get("src", "")).strip()
        if not source:
            return

        try:
            overlay = self._load_visual_element_image(source)
        except Exception:
            return

        target_width = max(int(element.get("width", overlay.width)), 1)
        target_height = max(int(element.get("height", overlay.height)), 1)
        if overlay.width != target_width or overlay.height != target_height:
            overlay = overlay.resize((target_width, target_height), _RESAMPLE_LANCZOS)

        try:
            opacity = float(element.get("opacity", 1.0))
        except (TypeError, ValueError):
            opacity = 1.0
        opacity = max(0.0, min(opacity, 1.0))

        if opacity < 1.0:
            alpha = overlay.getchannel("A").point(lambda p: int(p * opacity))
            overlay.putalpha(alpha)

        x = int(element.get("x", 0))
        y = int(element.get("y", 0))
        base_image.alpha_composite(overlay, dest=(x, y))

    def _draw_visual_qr(
        self, base_image: Image.Image, element: dict[str, Any], qr_url: str
    ) -> None:
        try:
            size = max(int(element.get("width", element.get("height", 160))), 32)
            qr_img = make_qr_image(qr_url, size)
            x = int(element.get("x", 0))
            y = int(element.get("y", 0))
            base_image.alpha_composite(qr_img, dest=(x, y))
        except Exception:  # pragma: no cover - best effort
            pass

    def _load_visual_element_image(self, source: str) -> Image.Image:
        # Element (overlay) images are embedded as data URLs in the immutable
        # layout snapshot — durable and self-contained, no disk/asset lookup.
        if source.startswith("data:image"):
            _, _, encoded = source.partition(",")
            if not encoded:
                raise ValueError("Data URL de imagem sem payload.")
            try:
                raw = base64.b64decode(encoded)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("Imagem em Data URL invalida.") from exc
            return Image.open(BytesIO(raw)).convert("RGBA")

        raise ValueError("Tipo de origem de imagem nao suportado no template visual.")

    def _resolve_visual_font(
        self, family: str, size: int, bold: bool
    ) -> ImageFont.FreeTypeFont:
        fonts_dir = self.config.regular_font_path.parent
        _FONT_MAP: dict[str, dict[bool, Path]] = {
            "Times New Roman": {
                False: fonts_dir / "times.ttf",
                True: fonts_dir / "timesbd.ttf",
            },
            "Arial": {
                False: _WINDOWS_FONTS / "arial.ttf",
                True: _WINDOWS_FONTS / "arialbd.ttf",
            },
            "Georgia": {
                False: _WINDOWS_FONTS / "georgia.ttf",
                True: _WINDOWS_FONTS / "georgiab.ttf",
            },
            "Verdana": {
                False: _WINDOWS_FONTS / "verdana.ttf",
                True: _WINDOWS_FONTS / "verdanab.ttf",
            },
            "Courier New": {
                False: _WINDOWS_FONTS / "cour.ttf",
                True: _WINDOWS_FONTS / "courbd.ttf",
            },
        }
        candidates = _FONT_MAP.get(family, {})
        for try_bold in (bold, False):
            path = candidates.get(try_bold)
            if path and path.exists():
                return ImageFont.truetype(str(path), size=size)
        # Fallback to backend Times New Roman
        fallback = self.config.bold_font_path if bold else self.config.regular_font_path
        if fallback.exists():
            return ImageFont.truetype(str(fallback), size=size)
        return ImageFont.load_default()

    def _load_base_image(self, override: Path | None = None) -> Image.Image:
        path = override if override is not None else self.config.template_path
        if not path.exists():
            raise FileNotFoundError(
                f"Template do certificado nao encontrado: {path}"
            )
        return Image.open(path).convert("RGBA")

    def _load_font(self, font_path: Path, size: int) -> ImageFont.FreeTypeFont:
        if not font_path.exists():
            raise FileNotFoundError(f"Fonte nao encontrada: {font_path}")
        return ImageFont.truetype(str(font_path), size=size)
