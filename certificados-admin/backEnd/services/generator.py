from __future__ import annotations

import base64
import binascii
import logging
import platform
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, cast

from certificados_backend.models import ParticipantRegistryRecord
from certificados_backend.utils.file_utils import ensure_directory
from certificados_backend.utils.text_utils import (
    calculate_centered_x,
    get_text_size,
    wrap_hard_breaks,
    wrap_text,
    wrap_text_para,
)
from PIL import Image, ImageDraw, ImageFont

from database.certificate_types import MAX_WORK_AUTHORS
from storage_service.filenames import build_certificate_filename, certificate_holder

_SYSTEM = platform.system()
_WINDOWS_FONTS = Path("C:/Windows/Fonts")
_LINUX_FONTS = Path("/usr/share/fonts")
_RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
_RESAMPLE_NEAREST = Image.Resampling.NEAREST

LOGGER = logging.getLogger("certificados.generator")

TEXT_COLOR = "#000000"

# Visual-template element keys that hold the (potentially long) certificate body
# authored by the secretaria. These are word-wrapped and may span many lines.
_BODY_TEXT_KEYS = {"texto_certificado", "certificate_text"}

# A text element may carry an explicit box: ``width`` is the wrap limit and
# ``height`` the area reserved for it, both in pixels of the original art. Both
# are optional — a layout without them renders exactly as it did before these
# fields existed, which is what every template saved earlier relies on.
TEXT_BOX_MIN_SIZE = 20


@dataclass(slots=True, frozen=True)
class TextBoxLayout:
    """Where a text element's lines land.

    Computed once and shared by the PDF renderer, the editor preview endpoint
    and the batch pre-check, so all three agree on line breaks and heights.
    """

    lines: list[str]
    font: ImageFont.FreeTypeFont
    #: Effective size — the participant name shrinks to fit its box.
    font_size: int
    #: Distance between the tops of two consecutive lines.
    line_height: int
    #: Height occupied from the top of the first line to the bottom of the last.
    text_height: int
    #: Width the lines were wrapped to; ``None`` when the text is drawn as-is.
    wrap_width: int | None
    #: Explicit box height when the element has one.
    height: int | None
    #: True when the text is taller than its explicit box. Never clips.
    overflow: bool
    #: Legacy name centring: the first line starts at ``y - top_offset``.
    top_offset: int


def box_size(element: dict[str, Any], key: str) -> int | None:
    """Explicit ``width``/``height``/``maxWidth`` of an element, if positive."""
    value = element.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value > 0 else None


def _aligned_x(align: str, anchor_x: int, text_width: int) -> int:
    if align == "center":
        return anchor_x - text_width // 2
    if align == "right":
        return anchor_x - text_width
    return anchor_x


def _pillow_multiline_pitch(draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont) -> int:
    """Line pitch Pillow itself uses when ``draw.text`` receives line breaks."""
    return int(draw.textbbox((0, 0), "A", font=font)[3]) + 4


def measuring_draw() -> ImageDraw.ImageDraw:
    """A throwaway drawing context: text metrics do not depend on the image."""
    return ImageDraw.Draw(Image.new("RGB", (1, 1)))


# A full participant name is a business value, not decorative text. When it has
# a first name plus two or more surname tokens, keep the first surname beside
# the given name and move the remaining surname tokens to the next line. This
# matches the secretaria's reading order and prevents long names from being
# clipped at the certificate edges.
_MULTILINE_NAME_SCALE = 0.78
_SURNAME_PARTICLES = frozenset({"da", "das", "de", "do", "dos", "e"})

# ── Font sizes as fraction of image HEIGHT (scale with any template) ──────────
# Calibrated for a 3508×2480 px (A4 @ 300 dpi) template.
# For a 2480 px tall image these produce approximately:
#   name ≈ 119 px  |  preamble ≈ 55 px  |  body ≈ 60 px
#   date ≈ 50 px   |  signatory ≈ 45 px |  registry ≈ 32 px
PREAMBLE_SIZE_RATIO = 0.023
NAME_SIZE_RATIO = 0.048
MIN_NAME_SIZE_RATIO = 0.026
BODY_SIZE_RATIO = 0.028
MIN_BODY_SIZE_RATIO = 0.018
DATE_SIZE_RATIO = 0.020
SIGNATORY_SIZE_RATIO = 0.018
META_SIZE_RATIO = 0.013
BODY_LINE_SPACING_RATIO = 0.009

# ── Text column – left safe zone ──────────────────────────────────────────────
SIDE_MARGIN_RATIO = 0.05
BODY_WIDTH_RATIO = 0.525  # keeps clear of the right decoration while using the text area

# ── Upper block: fixed Y anchors (fraction of image height) ───────────────────
PREAMBLE_Y_RATIO = 0.32
NAME_Y_RATIO = 0.365
BODY_Y_RATIO = 0.445

# ── Lower block: anchored from BOTTOM upward ──────────────────────────────────
# Registry sits at REGISTRY_BOTTOM_Y_RATIO from the top (≈ 5 % from the bottom).
# Every other element is stacked above it.
REGISTRY_BOTTOM_Y_RATIO = 0.95  # top-left of registry text
SIG_BLOCK_GAP_RATIO = 0.012  # gap between consecutive lines in sig block
SIGNATURE_BLANK_RATIO = 0.08  # blank vertical space reserved for physical signature
DATE_BODY_GAP_RATIO = 0.03  # minimum gap between body end and date line
DATE_MIN_Y_RATIO = 0.62  # date never placed above this (when body is short)

# ── Constant strings ──────────────────────────────────────────────────────────
PREAMBLE_TEXT = "Certificamos, para os devidos fins, que"


@dataclass(slots=True, frozen=True)
class CertificateGeneratorConfig:
    template_path: Path
    regular_font_path: Path
    bold_font_path: Path
    output_dir: Path
    # Institution/signatory data — injected from the settings snapshot.
    institution_name: str = ""
    issue_location: str = ""
    signatory_name: str = ""
    signatory_title: str = ""


def build_pdf_filename(participant: ParticipantRegistryRecord) -> str:
    """Build a unique PDF filename: "<titular> - <evento> - <codigo>.pdf".

    The validation code closes the name, so two participants with the same name
    (or one participant twice in an event) never overwrite each other's file.
    Rules live in :mod:`storage_service.filenames`, shared with the downloads."""
    holder = certificate_holder(
        participant.nome, participant.titulo_trabalho, participant.certificate_type
    )
    return build_certificate_filename(holder, participant.evento, participant.validation_code)


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
        image = image.resize((size_px, size_px), _RESAMPLE_NEAREST)
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
        col_w = int(width * BODY_WIDTH_RATIO)
        origin_x = int(width * SIDE_MARGIN_RATIO)

        # ── Compute all sizes from image height ───────────────────────────────
        preamble_sz = max(int(height * PREAMBLE_SIZE_RATIO), 8)
        name_sz = max(int(height * NAME_SIZE_RATIO), 16)
        min_name_sz = max(int(height * MIN_NAME_SIZE_RATIO), 12)
        body_sz = max(int(height * BODY_SIZE_RATIO), 10)
        min_body_sz = max(int(height * MIN_BODY_SIZE_RATIO), 8)
        date_sz = max(int(height * DATE_SIZE_RATIO), 8)
        sig_sz = max(int(height * SIGNATORY_SIZE_RATIO), 8)
        meta_sz = max(int(height * META_SIZE_RATIO), 6)
        line_spacing = max(int(height * BODY_LINE_SPACING_RATIO), 4)

        # ── Compute lower-block Y positions (bottom-up) ───────────────────────
        sig_gap = int(height * SIG_BLOCK_GAP_RATIO)
        sig_blank = int(height * SIGNATURE_BLANK_RATIO)

        registry_y = int(height * REGISTRY_BOTTOM_Y_RATIO)
        sig_title_y = registry_y - sig_gap - sig_sz
        sig_name_y = sig_title_y - sig_gap - sig_sz
        date_y = max(
            sig_name_y - sig_blank - date_sz,
            int(height * DATE_MIN_Y_RATIO),
        )

        # ── Available vertical space for body text ────────────────────────────
        body_start_y = int(height * BODY_Y_RATIO)
        body_gap = int(height * DATE_BODY_GAP_RATIO)
        max_body_bottom = date_y - body_gap

        # ── Load fonts ────────────────────────────────────────────────────────
        preamble_font = self._load_font(self.config.regular_font_path, preamble_sz)
        name_font, name_lines = self._fit_name_to_width(
            draw,
            participant.nome,
            lambda size: self._load_font(self.config.bold_font_path, size),
            name_sz,
            min_name_sz,
            col_w,
        )
        body_font, body_lines = self._fit_body_to_space(
            draw,
            participant.texto_certificado,
            self.config.regular_font_path,
            col_w,
            body_sz,
            min_body_sz,
            line_spacing,
            max_body_bottom - body_start_y,
        )
        date_font = self._load_font(self.config.regular_font_path, date_sz)
        sig_font = self._load_font(self.config.regular_font_path, sig_sz)
        meta_font = self._load_font(self.config.regular_font_path, meta_sz)

        # ── Draw upper block ──────────────────────────────────────────────────
        self._draw_centered(
            draw, PREAMBLE_TEXT, int(height * PREAMBLE_Y_RATIO), col_w, origin_x, preamble_font
        )
        self._draw_centered_lines(
            draw,
            name_lines,
            int(height * NAME_Y_RATIO),
            col_w,
            origin_x,
            name_font,
        )
        self._draw_body(
            draw,
            participant.texto_certificado,
            body_start_y,
            col_w,
            origin_x,
            body_font,
            line_spacing,
        )

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

    def _draw_centered_lines(
        self,
        draw: ImageDraw.ImageDraw,
        lines: list[str],
        center_y: int,
        col_w: int,
        origin_x: int,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        """Draw one or more centered name lines around the configured Y anchor."""
        line_spacing = max(int(getattr(font, "size", 12) * 0.12), 2)
        line_h = max(get_text_size(draw, "Ag", font)[1], 1) + line_spacing
        y = center_y - ((len(lines) - 1) * line_h) // 2
        for line in lines:
            self._draw_centered(draw, line, y, col_w, origin_x, font)
            y += line_h

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

    def _fit_name_to_width(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font_factory: Callable[[int], ImageFont.FreeTypeFont],
        initial_size: int,
        min_size: int,
        max_width: int,
    ) -> tuple[ImageFont.FreeTypeFont, list[str]]:
        """Fit a participant name without clipping, preferring two surname lines.

        For ``Arthur Zanon de Andrade`` the preferred result is
        ``["Arthur Zanon", "de Andrade"]``. Short names remain on one line at
        their configured size. Pathological long tokens are finally wrapped at
        the minimum size, so no text can leave the page.
        """
        clean_text = " ".join(str(text).split())
        words = clean_text.split()
        surname_groups: list[str] = []
        index = 1
        while index < len(words):
            group: list[str] = []
            while index < len(words) - 1 and words[index].casefold() in _SURNAME_PARTICLES:
                group.append(words[index])
                index += 1
            group.append(words[index])
            index += 1
            surname_groups.append(" ".join(group))

        multiline = len(surname_groups) >= 2
        preferred_lines = (
            [f"{words[0]} {surname_groups[0]}", " ".join(surname_groups[1:])]
            if multiline
            else [clean_text]
        )

        size = (
            max(int(initial_size * _MULTILINE_NAME_SCALE), min_size) if multiline else initial_size
        )
        size = max(size, min_size)
        font = font_factory(size)
        while size > min_size and any(
            get_text_size(draw, line, font)[0] > max_width for line in preferred_lines
        ):
            size = max(size - 2, min_size)
            font = font_factory(size)

        if any(get_text_size(draw, line, font)[0] > max_width for line in preferred_lines):
            fitted_lines: list[str] = []
            for line in preferred_lines:
                fitted_lines.extend(wrap_hard_breaks(draw, line, font, max_width))
            preferred_lines = fitted_lines

        return font, preferred_lines

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
            font = self._load_font(font_path, size)
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

            color: str = element.get("color", "#000000")
            align: str = element.get("align", "left")
            anchor_x = int(element.get("x", 0))
            anchor_y = int(element.get("y", 0))

            box = self.layout_text_box(draw, image.size[0], text, element)
            if box.overflow:
                # Never clip: the certificate is still complete. The editor and
                # the batch pre-check surface this before emission; here it is
                # only recorded (sizes only, never the participant's text).
                LOGGER.warning(
                    "Texto do elemento '%s' excede a caixa: %d px de %d px em %d linha(s).",
                    key,
                    box.text_height,
                    box.height,
                    len(box.lines),
                )
            self._draw_text_box(
                draw,
                box,
                text=text,
                color=color,
                align=align,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                anchor_bottom=element.get("anchorY") == "bottom",
            )

        return image

    def layout_text_box(
        self,
        draw: ImageDraw.ImageDraw,
        image_width: int,
        text: str,
        element: dict[str, Any],
    ) -> TextBoxLayout:
        """Decide the lines, effective font and height of a text element.

        Three regimes, chosen to keep every pre-existing template identical:

        - ``name``: shrinks to fit and wraps at its box (or the page bound).
          Without a box the lines are centred on Y, as they always were; with a
          box they grow downward from Y like every other boxed text.
        - body keys, or any text with an explicit ``width``: word-wrapped at
          ``min(width, bound)`` honouring typed line breaks.
        - everything else: drawn in one call, exactly as before; Pillow lays
          out typed line breaks itself.
        """
        key = str(element.get("key", ""))
        font_size = max(int(element.get("fontSize", 24)), 6)
        font_family = str(element.get("fontFamily", "Times New Roman"))
        bold = bool(element.get("bold", False))
        align = str(element.get("align", "left"))
        anchor_x = int(element.get("x", 0))

        margin = max(int(image_width * 0.04), 8)
        bound = self._wrap_bound(align, anchor_x, image_width, margin)
        box_width = box_size(element, "width")
        # ``maxWidth`` is a legacy hint still honoured for the name and body.
        explicit_width = box_width or box_size(element, "maxWidth")
        box_height = box_size(element, "height")
        wrap_width: int | None = max(1, min(explicit_width, bound)) if explicit_width else bound
        font = self._resolve_visual_font(font_family, font_size, bold)

        if key == "name":
            min_size = max(int(font_size * 0.5), 8)
            font, lines = self._fit_name_to_width(
                draw,
                text,
                lambda size: self._resolve_visual_font(font_family, size, bold),
                font_size,
                min_size,
                wrap_width or bound,
            )
            effective_size = int(getattr(font, "size", font_size))
            line_spacing = max(int(effective_size * 0.12), 2)
            line_height = max(get_text_size(draw, "Ag", font)[1], 1) + line_spacing
            top_offset = 0 if box_width else ((len(lines) - 1) * line_height) // 2
        elif key in _BODY_TEXT_KEYS or box_width:
            lines = wrap_hard_breaks(draw, text, font, wrap_width or bound)
            effective_size = font_size
            line_spacing = max(int(font_size * 0.3), 2)
            line_height = get_text_size(draw, "Ag", font)[1] + line_spacing
            top_offset = 0
        else:
            lines = str(text).split("\n")
            effective_size = font_size
            wrap_width = None
            line_height = _pillow_multiline_pitch(draw, font)
            top_offset = 0

        glyph_height = max(get_text_size(draw, "Ag", font)[1], 1)
        text_height = max(len(lines) - 1, 0) * line_height + glyph_height
        return TextBoxLayout(
            lines=lines,
            font=font,
            font_size=effective_size,
            line_height=line_height,
            text_height=text_height,
            wrap_width=wrap_width,
            height=box_height,
            overflow=box_height is not None and text_height > box_height,
            top_offset=top_offset,
        )

    def _draw_text_box(
        self,
        draw: ImageDraw.ImageDraw,
        box: TextBoxLayout,
        *,
        text: str,
        color: str,
        align: str,
        anchor_x: int,
        anchor_y: int,
        anchor_bottom: bool = False,
    ) -> None:
        """Draw a laid-out text element. X is the alignment anchor, never a box edge.

        With ``anchor_bottom`` Y is the base of the text: the block keeps its
        base in place and grows upward as it gains lines.
        """
        font = box.font
        top = anchor_y - box.text_height if anchor_bottom else anchor_y
        if box.wrap_width is None:
            text_width, _ = get_text_size(draw, text, font)
            draw.text((_aligned_x(align, anchor_x, text_width), top), text, fill=color, font=font)
            return

        y = top - box.top_offset
        for line in box.lines:
            if line:
                line_width, _ = get_text_size(draw, line, font)
                draw.text((_aligned_x(align, anchor_x, line_width), y), line, fill=color, font=font)
            y += box.line_height

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

    def participant_data(self, participant: ParticipantRegistryRecord) -> dict[str, str]:
        """Values every template key resolves to; previews and pre-checks use it too."""
        return self._participant_data(participant)

    def _participant_data(self, participant: ParticipantRegistryRecord) -> dict[str, str]:
        """Map template keys to certificate values.

        ``event`` and ``course`` are DISTINCT fields (bug fix: ``event`` used to
        receive the course). Institutional values come from the immutable batch
        snapshot held by this generator, never from text embedded in the layout.
        """
        issue_location = self.config.issue_location.strip()
        issue_date = participant.data_emissao.strip()
        authors = [str(name).strip() for name in participant.autores if str(name).strip()]
        authors = authors[:MAX_WORK_AUTHORS]
        if issue_location and issue_date:
            issue_line = f"{issue_location}, {issue_date}."
        elif issue_location:
            issue_line = issue_location
        elif issue_date:
            issue_line = f"{issue_date}."
        else:
            issue_line = ""

        return {
            "name": participant.nome,
            "event": participant.evento,
            "course": participant.curso,
            "date": participant.data_emissao,
            "institution_name": self.config.institution_name.strip(),
            "issue_location": issue_location,
            "issue_line": issue_line,
            "signatory_name": self.config.signatory_name.strip(),
            "signatory_title": self.config.signatory_title.strip(),
            "validation_code": participant.validation_code,
            "texto_certificado": participant.texto_certificado,
            "certificate_text": participant.certificate_text or participant.texto_certificado,
            "certificate_type": participant.certificate_type,
            "equipe": participant.equipe,
            "work_title": participant.titulo_trabalho,
            # Per-work certificates: one key per author plus the numbered block
            # ("Autor 1: …"), which lists only the authors present.
            **{
                f"autor{index}": (authors[index - 1] if index <= len(authors) else "")
                for index in range(1, MAX_WORK_AUTHORS + 1)
            },
            "authors": "\n".join(
                f"Autor {index}: {name}" for index, name in enumerate(authors, start=1)
            ),
        }

    def _open_background_bytes(self, background_bytes: bytes | None) -> Image.Image:
        if not background_bytes:
            raise ValueError("Template sem imagem de fundo (background_bytes ausente).")
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

    def _resolve_visual_font(self, family: str, size: int, bold: bool) -> ImageFont.FreeTypeFont:
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
        return cast(ImageFont.FreeTypeFont, ImageFont.load_default())

    def _load_base_image(self, override: Path | None = None) -> Image.Image:
        path = override if override is not None else self.config.template_path
        if not path.exists():
            raise FileNotFoundError(f"Template do certificado nao encontrado: {path}")
        return Image.open(path).convert("RGBA")

    def _load_font(self, font_path: Path, size: int) -> ImageFont.FreeTypeFont:
        if not font_path.exists():
            raise FileNotFoundError(f"Fonte nao encontrada: {font_path}")
        return ImageFont.truetype(str(font_path), size=size)
