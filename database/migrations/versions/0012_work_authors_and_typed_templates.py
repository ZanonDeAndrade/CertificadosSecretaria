"""per-work certificates (authors, team, work title) and templates per type

Revision ID: 0012
Revises: 0011

Certificates gain the authors of a work, the team and the work title. Template
versions gain an optional certificate type: the version active today keeps a
NULL type and becomes the generic one, so emissions do not change. The old
"single active version" unique index is replaced by one active version per
type, enforced through ``active_type_key`` (set only while active).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TYPE_VALUES = (
    "listener",
    "speaker",
    "organizing_committee",
    "teams",
    "monitoring",
    "tcc_board_professor",
    "scientific_initiation",
)
TYPE_CHECK_SQL = "certificate_type IS NULL OR certificate_type IN ({})".format(
    ", ".join(f"'{value}'" for value in TYPE_VALUES)
)
GENERIC_KEY = "__generic__"
OLD_INDEX = "uq_template_versions_single_active"
NEW_INDEX = "uq_template_versions_active_type_key"
TYPE_CHECK = "ck_template_versions_certificate_type"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def _checks(table: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)
        if constraint.get("name")
    }


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    certificate_columns = _columns("certificates")
    for name, column in (
        ("authors_json", sa.Column("authors_json", sa.Text())),
        ("authors_search", sa.Column("authors_search", sa.Text())),
        ("team_name", sa.Column("team_name", sa.String(255))),
        ("work_title", sa.Column("work_title", sa.String(255))),
    ):
        if name not in certificate_columns:
            op.add_column("certificates", column)

    version_columns = _columns("template_versions")
    if "certificate_type" not in version_columns:
        op.add_column("template_versions", sa.Column("certificate_type", sa.String(32)))
    if "active_type_key" not in version_columns:
        op.add_column("template_versions", sa.Column("active_type_key", sa.String(40)))

    if TYPE_CHECK not in _checks("template_versions"):
        if _is_sqlite():
            with op.batch_alter_table("template_versions") as batch:
                batch.create_check_constraint(TYPE_CHECK, TYPE_CHECK_SQL)
        else:
            op.create_check_constraint(TYPE_CHECK, "template_versions", TYPE_CHECK_SQL)

    # The active version becomes the generic one: nothing changes for batches.
    op.execute(
        sa.text(
            "UPDATE template_versions SET active_type_key = :key "
            "WHERE is_active = 1 AND active_type_key IS NULL"
        ).bindparams(key=GENERIC_KEY)
    )

    indexes = _indexes("template_versions")
    if OLD_INDEX in indexes:
        op.drop_index(OLD_INDEX, table_name="template_versions")
    if NEW_INDEX not in indexes:
        op.create_index(NEW_INDEX, "template_versions", ["active_type_key"], unique=True)


def downgrade() -> None:
    indexes = _indexes("template_versions")
    if NEW_INDEX in indexes:
        op.drop_index(NEW_INDEX, table_name="template_versions")
    # Only the generic active version survives as "the" active version.
    op.execute(
        sa.text("UPDATE template_versions SET is_active = 0 WHERE certificate_type IS NOT NULL")
    )
    if OLD_INDEX not in indexes:
        op.create_index(
            OLD_INDEX,
            "template_versions",
            ["is_active"],
            unique=True,
            sqlite_where=sa.text("is_active = 1"),
            postgresql_where=sa.text("is_active = 1"),
        )

    if _is_sqlite():
        with op.batch_alter_table("template_versions") as batch:
            batch.drop_constraint(TYPE_CHECK, type_="check")
            batch.drop_column("active_type_key")
            batch.drop_column("certificate_type")
        with op.batch_alter_table("certificates") as batch:
            batch.drop_column("work_title")
            batch.drop_column("team_name")
            batch.drop_column("authors_search")
            batch.drop_column("authors_json")
    else:
        op.drop_constraint(TYPE_CHECK, "template_versions", type_="check")
        op.drop_column("template_versions", "active_type_key")
        op.drop_column("template_versions", "certificate_type")
        op.drop_column("certificates", "work_title")
        op.drop_column("certificates", "team_name")
        op.drop_column("certificates", "authors_search")
        op.drop_column("certificates", "authors_json")
