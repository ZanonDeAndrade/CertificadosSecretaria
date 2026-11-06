"""Readable certificate filenames and the download headers that carry them.

A certificate is named ``<titular>_<evento>_<ano>.pdf``: the person, the event
and the year the event started (or, failing that, the year it was issued or the
year in its code). Spaces inside the holder and the event are kept; ``_`` only
separates the parts. When the event already ends with that year ("Mostra de
Iniciação Científica 2026") the year is not repeated, and without an event the
name is ``<titular>_<ano>.pdf``.

The same rule names the stored file of a new certificate and every download
(admin panel, ZIP and public site), so a certificate issued under an older
format is also offered under this one. Only the suggested name changes; the
stored file keeps its name, bytes and hash.

Without the code in the name two files can share it: the same person twice in
one event, or two authors with the same name. Inside a ZIP and in the storage
the repeated name gets ``_2``, ``_3``… (see :func:`unique_filename` and
:func:`numbered_filenames`). A single download carries the plain name; the
browser handles repetition in the Downloads folder.

A per-work certificate (Mostra) is stored once, named after the work, and is
downloaded as one copy per author, each named after that author
(:func:`copy_filenames`). The copies are the same bytes: same code, QR and hash.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import quote

from database.certificate_types import CERTIFICATE_TYPE_LABELS, is_per_work_type

SEPARATOR = "_"
EXTENSION = ".pdf"
ZIP_EXTENSION = ".zip"
ELLIPSIS = "…"
DEFAULT_STEM = "certificado"
DEFAULT_FILENAME = DEFAULT_STEM + EXTENSION
#: Length of the whole name, extension included.
MAX_FILENAME_CHARS = 150
#: Linux caps one path component at 255 bytes and an accented letter takes two
#: in UTF-8, so a name within the character limit may still need this bound.
MAX_FILENAME_BYTES = 240
#: A long event is shortened first, down to this size, and only then the holder.
MIN_PART_CHARS = 20
#: How many ``_2``, ``_3``… variants a storage tries before giving up.
MAX_NUMBERED_NAMES = 1000

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
# A year is the first four-digit group of a date, whatever its format:
# "2026-06-10", "10/06/2026" or "10 de junho de 2026".
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_CODE_YEAR = re.compile(r"^CERT-(\d{4})-", re.IGNORECASE)
# An event that already names its year: "Semana Acadêmica 2026", "Micamf/2026".
_TRAILING_YEAR = re.compile(r"(?<!\d)(\d{4})$")


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


def year_of(value: object) -> str:
    """The four-digit year inside a date in any stored format, or ""."""
    match = _YEAR.search(str(value or ""))
    return match.group(1) if match else ""


def year_from_code(code: object) -> str:
    """The issue year a ``CERT-<ano>-XXXXXX`` code carries, or ""."""
    match = _CODE_YEAR.match(str(code or "").strip())
    return match.group(1) if match else ""


def certificate_year(cert: Mapping[str, Any]) -> str:
    """The year that names a certificate: event start, else issue, else the code's."""
    return (
        year_of(cert.get("start_date"))
        or year_of(cert.get("issue_date"))
        or year_from_code(cert.get("unique_code"))
    )


def _shorten(text: str, size: int) -> str:
    """``text`` cut to ``size`` characters, at a word when possible, ending in "…"."""
    if len(text) <= size:
        return text
    cut = text[: max(size - len(ELLIPSIS), 0)]
    boundary = cut.rfind(" ")
    if boundary >= size // 2:
        cut = cut[:boundary]
    cut = cut.rstrip(" .-" + SEPARATOR)
    return f"{cut}{ELLIPSIS}" if cut else ""


def _ends_with_year(event: str, year: str) -> bool:
    match = _TRAILING_YEAR.search(event)
    return bool(year) and match is not None and match.group(1) == year


def _compose(holder: str, event: str, year: str, extension: str) -> str:
    # The year is left out only while the (possibly shortened) event still ends
    # with it; a shortened event ends with "…", so the year comes back.
    parts = [holder, event, "" if _ends_with_year(event, year) else year]
    return SEPARATOR.join(part for part in parts if part) + extension


def _fits(filename: str) -> bool:
    return (
        len(filename) <= MAX_FILENAME_CHARS and len(filename.encode("utf-8")) <= MAX_FILENAME_BYTES
    )


def build_certificate_filename(
    holder: object, event: object, year: object, *, extension: str = EXTENSION
) -> str:
    """``<titular>_<evento>_<ano><extension>`` within the length limits.

    Without an event the name is ``<titular>_<ano>``; an event that already
    ends with the year does not repeat it. A name that is too long loses
    characters from the event first, then from the holder; the year is never cut.
    """
    holder_text = clean_filename_part(holder)
    event_text = clean_filename_part(event)
    year_text = clean_filename_part(year)
    if not (holder_text or event_text or year_text):
        return DEFAULT_STEM + extension
    holder_size = min(len(holder_text), MAX_FILENAME_CHARS)
    event_size = min(len(event_text), MAX_FILENAME_CHARS)
    while True:
        filename = _compose(
            _shorten(holder_text, holder_size),
            _shorten(event_text, event_size),
            year_text,
            extension,
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


def certificate_filename(cert: Mapping[str, Any], *, author: object = None) -> str:
    """Name of a persisted certificate row, for storage and for downloads.

    ``author`` names one copy of a per-work certificate after that author
    instead of the work.
    """
    holder = (
        str(author)
        if clean_filename_part(author)
        else certificate_holder(
            cert.get("participant_name"), cert.get("work_title"), cert.get("certificate_type")
        )
    )
    return build_certificate_filename(holder, cert.get("event_name"), certificate_year(cert))


def certificate_zip_filename(cert: Mapping[str, Any]) -> str:
    """``<trabalho>_<evento>_<ano>.zip``: the copies of one per-work certificate."""
    holder = certificate_holder(
        cert.get("participant_name"), cert.get("work_title"), cert.get("certificate_type")
    )
    return build_certificate_filename(
        holder, cert.get("event_name"), certificate_year(cert), extension=ZIP_EXTENSION
    )


def copy_filenames(cert: Mapping[str, Any], authors: Sequence[str]) -> list[str]:
    """The files a download of ``cert`` delivers: one per author, else one.

    A per-work certificate yields one name per author, in order; an ordinary
    certificate (or a per-work row issued before authors were stored) yields
    its own name. Repeated names are returned as they are; the caller makes
    them unique inside an archive with :func:`unique_filename`.
    """
    names = [author for author in authors if clean_filename_part(author)]
    if _is_per_work(cert.get("certificate_type")) and names:
        return [certificate_filename(cert, author=author) for author in names]
    return [certificate_filename(cert)]


def numbered_filename(filename: str, number: int) -> str:
    """``<stem>_<number><extension>``: the second, third… file of one name."""
    stem, dot, extension = filename.rpartition(".")
    if not dot or not stem:
        return f"{filename}{SEPARATOR}{number}"
    return f"{stem}{SEPARATOR}{number}.{extension}"


def numbered_filenames(filename: str, limit: int = MAX_NUMBERED_NAMES) -> Iterator[str]:
    """``filename`` itself, then its ``_2``, ``_3``… variants, up to ``limit`` names."""
    yield filename
    for number in range(2, limit + 1):
        yield numbered_filename(filename, number)


def unique_filename(filename: str, used: set[str]) -> str:
    """``filename``, or its first ``_2``, ``_3``… variant not yet in ``used``.

    Names compare case-insensitively, as a Windows or macOS folder does.
    ``used`` is updated with the chosen name.
    """
    chosen = next(
        candidate
        for candidate in numbered_filenames(filename, limit=max(len(used) + 2, 2))
        if candidate.casefold() not in used
    )
    used.add(chosen.casefold())
    return chosen


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
