"""Readable certificate filenames and the download headers that carry them.

A new certificate is stored as ``<titular> - <evento> - <código>.pdf`` so the
secretaria can find it by name in the event's Drive folder or on disk. The code
always closes the name and is never shortened: it keeps the name unique for the
same person twice in one event and for two people with the same name.

Downloads (admin panel, ZIP and public site) are named by the same rule, so a
certificate issued before this format existed is also offered under it. Only the
suggested name changes; the stored file keeps its name, bytes and hash.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping
from urllib.parse import quote

from database.certificate_types import CERTIFICATE_TYPE_LABELS, is_per_work_type

SEPARATOR = " - "
EXTENSION = ".pdf"
ELLIPSIS = "…"
DEFAULT_FILENAME = "certificado.pdf"
#: Length of the whole name, extension included.
MAX_FILENAME_CHARS = 150
#: Linux caps one path component at 255 bytes and an accented letter takes two
#: in UTF-8, so a name within the character limit may still need this bound.
MAX_FILENAME_BYTES = 240
#: A long event is shortened first, down to this size, and only then the holder.
MIN_PART_CHARS = 20

# Not allowed in a name on Windows, Linux or Google Drive.
_FORBIDDEN = frozenset('/\\:*?"<>|')
# Line breaks and control characters become a space so words do not merge.
_AS_SPACE = frozenset({"Cc", "Zl", "Zp"})
# Invisible format characters (e.g. the ones that reverse the text direction
# and can disguise an extension) and lone surrogates are dropped.
_DROPPED = frozenset({"Cf", "Cs"})
_PER_WORK_LABELS = frozenset(
    label for value, label in CERTIFICATE_TYPE_LABELS.items() if is_per_work_type(value)
)


def clean_filename_part(value: object) -> str:
    """``value`` made safe for a filename, keeping accents and spaces.

    Forbidden characters, line breaks and control characters become spaces,
    runs of spaces collapse and leading/trailing spaces and dots are removed
    (Windows rejects a trailing dot; a leading one hides the file on Linux).
    """
    characters = []
    for char in unicodedata.normalize("NFC", str(value or "")):
        category = unicodedata.category(char)
        if category in _DROPPED:
            continue
        characters.append(" " if char in _FORBIDDEN or category in _AS_SPACE else char)
    return " ".join("".join(characters).split()).strip(" .")


def _is_per_work(certificate_type: object) -> bool:
    # Persisted rows carry the type value; render records carry its label.
    return is_per_work_type(certificate_type) or str(certificate_type or "") in _PER_WORK_LABELS


def certificate_holder(name: object, work_title: object, certificate_type: object) -> str:
    """Who the file is named after.

    The participant, or the work title on a per-work certificate (Mostra). A
    work without a title falls back to ``name``, which there is the first author.
    """
    if _is_per_work(certificate_type) and clean_filename_part(work_title):
        return str(work_title)
    return str(name or "")


def _shorten(text: str, size: int) -> str:
    """``text`` cut to ``size`` characters, at a word when possible, ending in "…"."""
    if len(text) <= size:
        return text
    cut = text[: max(size - len(ELLIPSIS), 0)]
    boundary = cut.rfind(" ")
    if boundary >= size // 2:
        cut = cut[:boundary]
    cut = cut.rstrip(" .-")
    return f"{cut}{ELLIPSIS}" if cut else ""


def _compose(*parts: str) -> str:
    return SEPARATOR.join(part for part in parts if part) + EXTENSION


def _fits(filename: str) -> bool:
    return (
        len(filename) <= MAX_FILENAME_CHARS and len(filename.encode("utf-8")) <= MAX_FILENAME_BYTES
    )


def build_certificate_filename(holder: object, event: object, code: object) -> str:
    """``<titular> - <evento> - <código>.pdf`` within the length limits.

    Without an event the name is ``<titular> - <código>.pdf``. A name that is
    too long loses characters from the event first, then from the holder; the
    code is never cut.
    """
    holder_text = clean_filename_part(holder)
    event_text = clean_filename_part(event)
    code_text = clean_filename_part(code)
    if not (holder_text or event_text or code_text):
        return DEFAULT_FILENAME
    holder_size = min(len(holder_text), MAX_FILENAME_CHARS)
    event_size = min(len(event_text), MAX_FILENAME_CHARS)
    while True:
        filename = _compose(
            _shorten(holder_text, holder_size), _shorten(event_text, event_size), code_text
        )
        if _fits(filename) or holder_size == event_size == 0:
            return filename
        if event_size > MIN_PART_CHARS:
            event_size -= 1
        elif holder_size > MIN_PART_CHARS:
            holder_size -= 1
        elif event_size:
            event_size -= 1
        else:
            holder_size -= 1


def certificate_filename(cert: Mapping[str, Any]) -> str:
    """Name of a persisted certificate row, for storage and for downloads."""
    holder = certificate_holder(
        cert.get("participant_name"), cert.get("work_title"), cert.get("certificate_type")
    )
    return build_certificate_filename(holder, cert.get("event_name"), cert.get("unique_code"))


def ascii_filename(filename: str) -> str:
    """ASCII-only rendering of ``filename`` for clients that ignore ``filename*``."""
    text = unicodedata.normalize("NFKD", filename.replace(ELLIPSIS, "..."))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = "".join(char if " " <= char <= "~" and char not in '"\\' else "_" for char in text)
    text = " ".join(re.sub(r"_+", "_", text).split())
    return text or DEFAULT_FILENAME


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    """RFC 6266 header: an ASCII ``filename`` plus the exact UTF-8 ``filename*``."""
    return (
        f'{disposition}; filename="{ascii_filename(filename)}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
