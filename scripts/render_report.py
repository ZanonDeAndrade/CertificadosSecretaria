#!/usr/bin/env python3
"""Render the final Markdown report to self-contained print-oriented HTML.

The renderer intentionally supports only the Markdown constructs used by the
project report.  It has no network dependency and escapes source text before
adding markup.  PDF conversion is performed separately by LibreOffice or a
headless browser so the generated binary can be visually reviewed.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


def _inline(value: str) -> str:
    escaped = html.escape(value, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r"\[([^]]+)]\(([^)]+)\)",
        lambda match: f'<a href="{html.escape(match.group(2), quote=True)}">{match.group(1)}</a>',
        escaped,
    )
    return escaped


def _table(lines: list[str]) -> str:
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    header, *body = rows
    body = body[1:]  # separator row
    out = ["<table><thead><tr>"]
    out.extend(f"<th>{_inline(cell)}</th>" for cell in header)
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>")
        out.extend(f"<td>{_inline(cell)}</td>" for cell in row)
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def markdown_to_html(source: str, *, base: Path) -> str:
    lines = source.splitlines()
    blocks: list[str] = []
    paragraph: list[str] = []
    index = 0
    in_code = False
    code_lines: list[str] = []
    list_kind: str | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append(f"<p>{_inline(' '.join(part.strip() for part in paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            blocks.append(f"</{list_kind}>")
            list_kind = None

    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            flush_paragraph()
            close_list()
            if in_code:
                blocks.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if not line.strip():
            flush_paragraph()
            close_list()
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        image_match = re.match(r"^!\[([^]]*)]\(([^)]+)\)$", line.strip())
        if image_match:
            flush_paragraph()
            close_list()
            target = (base / image_match.group(2)).resolve().as_uri()
            caption = html.escape(image_match.group(1))
            blocks.append(
                f'<figure><img src="{target}" alt="{caption}"><figcaption>{caption}</figcaption></figure>'
            )
            index += 1
            continue
        if (
            line.lstrip().startswith("|")
            and index + 1 < len(lines)
            and re.match(r"^\s*\|?\s*:?-+", lines[index + 1])
        ):
            flush_paragraph()
            close_list()
            table_lines = [line]
            index += 1
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            blocks.append(_table(table_lines))
            continue
        unordered = re.match(r"^\s*-\s+(.+)$", line)
        ordered = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            desired = "ul" if unordered else "ol"
            if list_kind != desired:
                close_list()
                blocks.append(f"<{desired}>")
                list_kind = desired
            item = (unordered or ordered).group(1)  # type: ignore[union-attr]
            blocks.append(f"<li>{_inline(item)}</li>")
            index += 1
            continue
        if line.startswith("> "):
            flush_paragraph()
            close_list()
            blocks.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
            index += 1
            continue
        paragraph.append(line)
        index += 1

    flush_paragraph()
    close_list()
    if in_code:
        blocks.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    return "\n".join(blocks)


STYLE = """
@page { size: A4; margin: 18mm 16mm 18mm 18mm; }
html { font-family: 'Liberation Sans', Arial, sans-serif; color: #17212b; }
body { max-width: 180mm; margin: 0 auto; font-size: 10.5pt; line-height: 1.45; }
h1 { color: #123b52; font-size: 24pt; border-bottom: 2px solid #2d718f; padding-bottom: 6mm; }
h2 { color: #174f69; font-size: 16pt; margin-top: 9mm; page-break-after: avoid; }
h3 { color: #1d607d; font-size: 12.5pt; margin-top: 6mm; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #135f85; text-decoration: none; }
code { font-family: 'Liberation Mono', monospace; background: #eef3f5; padding: 0.4mm 1mm; }
pre { white-space: pre-wrap; background: #eef3f5; border-left: 3px solid #2d718f; padding: 3mm; font-size: 8.5pt; page-break-inside: avoid; }
table { width: 100%; border-collapse: collapse; font-size: 8.7pt; margin: 4mm 0 6mm; }
th { background: #174f69; color: white; text-align: left; }
th, td { border: 1px solid #aab9c1; padding: 2mm; vertical-align: top; }
tr { page-break-inside: avoid; }
figure { margin: 6mm 0 8mm; page-break-inside: avoid; text-align: center; }
img { max-width: 100%; max-height: 220mm; object-fit: contain; border: 1px solid #b9c5cb; }
figcaption { color: #526673; font-size: 8.5pt; margin-top: 2mm; }
blockquote { border-left: 3px solid #d19b3a; margin: 4mm 0; padding: 2mm 4mm; background: #fff8e8; }
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    body = markdown_to_html(source.read_text("utf-8"), base=source.parent)
    document = (
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        f"<title>Relatório técnico final</title><style>{STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )
    args.output.write_text(document, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
