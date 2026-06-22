from __future__ import annotations

from PIL import ImageDraw, ImageFont


def get_text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def calculate_centered_x(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    container_width: int,
    origin_x: int = 0,
) -> int:
    text_width, _ = get_text_size(draw, text, font)
    return origin_x + max((container_width - text_width) // 2, 0)


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap text into lines that fit within max_width. Returns plain strings."""
    paragraphs = _split_paragraphs(text)
    lines: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            lines.append("")
            continue
        lines.extend(_wrap_paragraph(draw, paragraph, font, max_width))
    return lines


def wrap_text_para(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[tuple[str, bool]]:
    """Wrap text and return (line, is_paragraph_end) pairs.

    is_paragraph_end is True for the last line of each paragraph — these lines
    should be left-aligned rather than fully justified.
    """
    paragraphs = _split_paragraphs(text)
    result: list[tuple[str, bool]] = []
    for paragraph in paragraphs:
        if not paragraph:
            result.append(("", True))
            continue
        para_lines = _wrap_paragraph(draw, paragraph, font, max_width)
        for i, line in enumerate(para_lines):
            result.append((line, i == len(para_lines) - 1))
    return result


def wrap_hard_breaks(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap text honouring EXPLICIT line breaks typed by the user.

    Every ``\\n`` is treated as a hard break (the secretaria's typed line breaks
    are respected), and each segment is then word-wrapped to ``max_width`` so a
    long body never leaves the certificate. Blank lines are preserved.
    """
    lines: list[str] = []
    for segment in str(text).split("\n"):
        stripped = segment.strip()
        if not stripped:
            lines.append("")
            continue
        lines.extend(_wrap_paragraph(draw, stripped, font, max(max_width, 1)))
    return lines


# ── Internal helpers ──────────────────────────────────────────────────────────

def _split_paragraphs(text: str) -> list[str]:
    """Treat copied line breaks as spaces and blank lines as paragraph breaks."""
    stripped = text.strip()
    if not stripped:
        return [""]

    paragraphs: list[str] = []
    current_paragraph: list[str] = []

    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line:
            if current_paragraph:
                paragraphs.append(" ".join(current_paragraph))
                current_paragraph = []
            continue
        current_paragraph.append(line)

    if current_paragraph:
        paragraphs.append(" ".join(current_paragraph))

    return paragraphs or [""]


def _wrap_paragraph(
    draw: ImageDraw.ImageDraw,
    paragraph: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Wrap a single paragraph (no newlines) into lines."""
    words = paragraph.split()
    if not words:
        return []

    lines: list[str] = []
    current_line = words[0]

    for word in words[1:]:
        candidate = f"{current_line} {word}"
        if get_text_size(draw, candidate, font)[0] <= max_width:
            current_line = candidate
        else:
            lines.extend(_split_long_line(draw, current_line, font, max_width))
            current_line = word

    lines.extend(_split_long_line(draw, current_line, font, max_width))
    return lines


def _split_long_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    if get_text_size(draw, text, font)[0] <= max_width:
        return [text]

    fragments: list[str] = []
    current_fragment = ""

    for character in text:
        candidate = f"{current_fragment}{character}"
        if get_text_size(draw, candidate, font)[0] <= max_width or not current_fragment:
            current_fragment = candidate
        else:
            fragments.append(current_fragment.rstrip())
            current_fragment = character.lstrip()

    if current_fragment:
        fragments.append(current_fragment.rstrip())

    return fragments
