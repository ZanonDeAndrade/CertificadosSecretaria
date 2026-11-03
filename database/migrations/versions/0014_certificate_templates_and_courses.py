"""certificate models, registered courses and the version foreign key

Revision ID: 0014
Revises: 0013

The template screen shows one item per model instead of one per version.
This migration creates ``certificate_templates`` and files every existing
version under a model (see ``database.template_grouping``), creates the
``courses`` list seeded with the institution's courses, and protects
``certificates.template_version_id`` with a foreign key.

Nothing about an issued certificate changes. On PostgreSQL the foreign key is
created ``NOT VALID``: existing rows are not checked, so a certificate that
pointed at a version deleted in the past cannot stop the deploy; new rows and
deletions of referenced versions are enforced from now on. On SQLite (dev and
tests) the key is created only when no such orphan exists.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

from database.courses import DEFAULT_COURSES, normalize_course_key
from database.template_grouping import VersionRow, group_versions

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

LOGGER = logging.getLogger("alembic.runtime.migration")

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
VERSION_FK = "fk_template_versions_template_id"
CERTIFICATE_FK = "fk_certificates_template_version_id"


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def _foreign_keys(table: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_foreign_keys(table)
        if constraint.get("name")
    }


def _create_courses() -> None:
    if "courses" not in _tables():
        op.create_table(
            "courses",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("normalized_key", sa.String(255), nullable=False),
            sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("normalized_key", name="uq_courses_normalized_key"),
        )
    courses = sa.table(
        "courses",
        sa.column("name", sa.String()),
        sa.column("normalized_key", sa.String()),
        sa.column("is_active", sa.Integer()),
    )
    bind = op.get_bind()
    existing = set(bind.execute(sa.select(courses.c.normalized_key)).scalars())
    for name in DEFAULT_COURSES:
        key = normalize_course_key(name)
        if key in existing:
            continue
        bind.execute(sa.insert(courses).values(name=name, normalized_key=key, is_active=1))
        existing.add(key)


def _create_templates_table() -> None:
    if "certificate_templates" in _tables():
        return
    op.create_table(
        "certificate_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("certificate_type", sa.String(32)),
        sa.Column(
            "course_id",
            sa.Integer(),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.Integer()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by", sa.Integer()),
        sa.CheckConstraint(TYPE_CHECK_SQL, name="ck_certificate_templates_certificate_type"),
    )
    op.create_index("idx_certificate_templates_course_id", "certificate_templates", ["course_id"])
    op.create_index(
        "idx_certificate_templates_certificate_type", "certificate_templates", ["certificate_type"]
    )
    op.create_index(
        "idx_certificate_templates_archived_at", "certificate_templates", ["archived_at"]
    )


def _add_template_id_column() -> None:
    if "template_id" in _columns("template_versions"):
        return
    column = sa.Column(
        "template_id",
        sa.Integer(),
        sa.ForeignKey("certificate_templates.id", ondelete="RESTRICT", name=VERSION_FK),
        nullable=True,
    )
    if _is_sqlite():
        with op.batch_alter_table("template_versions") as batch:
            batch.add_column(column)
    else:
        op.add_column("template_versions", column)
    if "idx_template_versions_template_id" not in _indexes("template_versions"):
        op.create_index("idx_template_versions_template_id", "template_versions", ["template_id"])


def _file_versions_under_models() -> None:
    """Create one model per group of versions and point the versions at it."""
    bind = op.get_bind()
    versions = sa.table(
        "template_versions",
        sa.column("id", sa.Integer()),
        sa.column("version_number", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("certificate_type", sa.String()),
        sa.column("is_active", sa.Integer()),
        sa.column("template_id", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("created_by", sa.Integer()),
    )
    templates = sa.table(
        "certificate_templates",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("certificate_type", sa.String()),
        sa.column("revision", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("created_by", sa.Integer()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    rows = bind.execute(
        sa.select(
            versions.c.id,
            versions.c.version_number,
            versions.c.name,
            versions.c.certificate_type,
            versions.c.is_active,
            versions.c.created_at,
            versions.c.created_by,
        ).where(versions.c.template_id.is_(None))
    ).all()
    if not rows:
        return
    meta = {row.id: row for row in rows}
    groups = group_versions(
        [
            VersionRow(
                id=int(row.id),
                version_number=int(row.version_number),
                name=row.name,
                certificate_type=row.certificate_type,
                is_active=bool(row.is_active),
            )
            for row in rows
        ]
    )
    for group in groups:
        first = meta[group.version_ids[0]]
        newest = meta[group.version_ids[-1]]
        template_id = bind.execute(
            sa.insert(templates)
            .values(
                name=group.name[:255],
                certificate_type=group.certificate_type,
                revision=len(group.version_ids),
                created_at=first.created_at,
                created_by=first.created_by,
                updated_at=newest.created_at,
            )
            .returning(templates.c.id)
        ).scalar_one()
        bind.execute(
            sa.update(versions)
            .where(versions.c.id.in_(group.version_ids))
            .values(template_id=template_id)
        )


def _require_template_id() -> None:
    if _is_sqlite():
        with op.batch_alter_table("template_versions") as batch:
            batch.alter_column("template_id", existing_type=sa.Integer(), nullable=False)
    else:
        op.alter_column("template_versions", "template_id", nullable=False)


def _orphan_certificates() -> int:
    bind = op.get_bind()
    return int(
        bind.execute(
            sa.text(
                "SELECT count(*) FROM certificates c "
                "WHERE c.template_version_id IS NOT NULL AND NOT EXISTS "
                "(SELECT 1 FROM template_versions v WHERE v.id = c.template_version_id)"
            )
        ).scalar_one()
    )


def _protect_certificate_versions() -> None:
    if CERTIFICATE_FK in _foreign_keys("certificates"):
        return
    if _is_sqlite():
        orphans = _orphan_certificates()
        if orphans:
            LOGGER.warning(
                "0014: %d certificado(s) apontam para versões inexistentes; a chave "
                "estrangeira não foi criada neste banco SQLite.",
                orphans,
            )
            return
        with op.batch_alter_table("certificates") as batch:
            batch.create_foreign_key(
                CERTIFICATE_FK,
                "template_versions",
                ["template_version_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        return
    # NOT VALID: existing rows are not scanned, so a historical orphan never
    # stops the deploy; the key still guards every new row and every deletion.
    op.execute(
        sa.text(
            f"ALTER TABLE certificates ADD CONSTRAINT {CERTIFICATE_FK} "
            "FOREIGN KEY (template_version_id) REFERENCES template_versions (id) "
            "ON DELETE RESTRICT NOT VALID"
        )
    )


def upgrade() -> None:
    _create_courses()
    _create_templates_table()
    _add_template_id_column()
    _file_versions_under_models()
    _require_template_id()
    _protect_certificate_versions()


def downgrade() -> None:
    if CERTIFICATE_FK in _foreign_keys("certificates"):
        if _is_sqlite():
            with op.batch_alter_table("certificates") as batch:
                batch.drop_constraint(CERTIFICATE_FK, type_="foreignkey")
        else:
            op.drop_constraint(CERTIFICATE_FK, "certificates", type_="foreignkey")

    if "template_id" in _columns("template_versions"):
        if "idx_template_versions_template_id" in _indexes("template_versions"):
            op.drop_index("idx_template_versions_template_id", table_name="template_versions")
        if _is_sqlite():
            with op.batch_alter_table("template_versions") as batch:
                batch.drop_constraint(VERSION_FK, type_="foreignkey")
                batch.drop_column("template_id")
        else:
            op.drop_constraint(VERSION_FK, "template_versions", type_="foreignkey")
            op.drop_column("template_versions", "template_id")

    tables = _tables()
    if "certificate_templates" in tables:
        op.drop_table("certificate_templates")
    if "courses" in tables:
        op.drop_table("courses")
