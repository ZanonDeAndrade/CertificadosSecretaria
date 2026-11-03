"""Group the template versions that exist into models (``certificate_templates``).

Before models existed, every edit in the editor created a loose version named
"Cópia de vN". Migration 0014 (and the legacy development database on first
start) files those versions under models with these rules, agreed with the
secretariat:

1. Versions of one type with an automatic name ("Cópia de vN", "Nova versão",
   "Padrão", none) and that type's active version form one model: the main
   model of the type. "Cópia de vN" follows its chain: it joins the model of
   version N when N exists and has the same type.
2. The current revision of a model is its active version; without one, the
   newest. Emissions do not change.
3. Versions newer than the active one are split off into a separate draft
   model, so "Editar" on the active model opens the layout being issued.
4. An inactive version with a name of its own becomes a model of its own.
5. A model takes the name of its newest version with a name of its own;
   otherwise "Modelo genérico" or "Modelo <type>". Names are made unique.

Nothing is deleted or renamed at the version level: every version keeps its
number, name and layout, and appears in its model's history.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .certificate_types import certificate_type_label

_COPY_RE = re.compile(r"^c[oó]pia de v(\d+)$", re.IGNORECASE)
_AUTO_NAMES = frozenset({"", "nova versão", "nova versao", "padrão", "padrao"})
GENERIC_MODEL_NAME = "Modelo genérico"


@dataclass(frozen=True)
class VersionRow:
    id: int
    version_number: int
    name: str | None
    certificate_type: str | None
    is_active: bool


@dataclass
class TemplateGroup:
    """One model to create: its versions (ascending) and the current one."""

    name: str
    certificate_type: str | None
    version_ids: list[int] = field(default_factory=list)
    current_version_id: int = 0


def copied_from(name: str | None) -> int | None:
    """Version number a "Cópia de vN" name points at, or None."""
    match = _COPY_RE.match((name or "").strip())
    return int(match.group(1)) if match else None


def is_automatic_name(name: str | None) -> bool:
    clean = (name or "").strip().lower()
    return clean in _AUTO_NAMES or copied_from(clean) is not None


def default_model_name(certificate_type: str | None) -> str:
    if not certificate_type:
        return GENERIC_MODEL_NAME
    return f"Modelo {certificate_type_label(certificate_type)}"


def _unique_names(groups: list[TemplateGroup]) -> None:
    seen: dict[str, int] = {}
    for group in groups:
        base = group.name
        count = seen.get(base, 0)
        seen[base] = count + 1
        if count:
            group.name = f"{base} ({count + 1})"


def group_versions(rows: list[VersionRow]) -> list[TemplateGroup]:
    """Assign every version to a model. Deterministic; pure."""
    ordered = sorted(rows, key=lambda row: row.version_number)
    by_number = {row.version_number: row for row in ordered}
    groups: list[TemplateGroup] = []
    assignment: dict[int, int] = {}  # version id -> group index
    main_group: dict[str | None, int] = {}  # type -> index of the type's main model

    def new_group(certificate_type: str | None) -> int:
        groups.append(TemplateGroup(name="", certificate_type=certificate_type))
        return len(groups) - 1

    # The active version of a type anchors the type's main model, even when it
    # has a name of its own: older automatic versions join it (rule 1).
    for row in ordered:
        if row.is_active and row.certificate_type not in main_group:
            main_group[row.certificate_type] = new_group(row.certificate_type)

    for row in ordered:
        source_number = copied_from(row.name)
        source = by_number.get(source_number) if source_number is not None else None
        index: int | None = None
        if source is not None and source.certificate_type == row.certificate_type:
            index = assignment.get(source.id)
        if index is None:
            if row.is_active or is_automatic_name(row.name):
                index = main_group.get(row.certificate_type)
                if index is None:
                    index = new_group(row.certificate_type)
                    main_group[row.certificate_type] = index
            else:
                index = new_group(row.certificate_type)
        assignment[row.id] = index
        groups[index].version_ids.append(row.id)

    # Rule 3: whatever is newer than the active version is a separate draft.
    by_id = {row.id: row for row in ordered}
    for group in list(groups):
        active = [vid for vid in group.version_ids if by_id[vid].is_active]
        if not active:
            continue
        active_number = by_id[active[0]].version_number
        newer = [vid for vid in group.version_ids if by_id[vid].version_number > active_number]
        if not newer:
            continue
        group.version_ids = [vid for vid in group.version_ids if vid not in newer]
        groups.append(
            TemplateGroup(name="", certificate_type=group.certificate_type, version_ids=newer)
        )

    for group in groups:
        rows_in_group = [by_id[vid] for vid in group.version_ids]
        active_rows = [row for row in rows_in_group if row.is_active]
        current = (
            active_rows[0]
            if active_rows
            else max(rows_in_group, key=lambda row: row.version_number)
        )
        group.current_version_id = current.id
        named = [row for row in rows_in_group if not is_automatic_name(row.name)]
        if named:
            group.name = (max(named, key=lambda row: row.version_number).name or "").strip()
        elif active_rows:
            group.name = default_model_name(group.certificate_type)
        else:
            # A draft split from the active model, or a chain that was never
            # activated: its newest name ("Cópia de vN") says where it came from.
            newest = max(rows_in_group, key=lambda row: row.version_number)
            group.name = (newest.name or "").strip() or default_model_name(group.certificate_type)

    _unique_names(groups)
    return groups
