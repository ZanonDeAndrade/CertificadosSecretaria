"""normalized event name for the history filter

Revision ID: 0013
Revises: 0012

The history filters events ignoring accents and case, like the name search.
Existing certificates are filled with the same ``normalize_name`` the
application applies when it writes a certificate, so old and new rows match
alike. Every step checks what exists first: a development SQLite database may
already have the column and index from the legacy startup migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from database.privacy import normalize_name

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

COLUMN = "event_name_normalized"
INDEX_NAME = "idx_certificates_event_name_normalized"
BATCH_SIZE = 1000

_certificates = sa.table(
    "certificates",
    sa.column("id", sa.Integer()),
    sa.column("event_name", sa.String()),
    sa.column(COLUMN, sa.String()),
)


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("certificates")}


def _indexes() -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("certificates")}


def _backfill() -> None:
    bind = op.get_bind()
    last_id = 0
    while True:
        rows = bind.execute(
            sa.select(_certificates.c.id, _certificates.c.event_name)
            .where(_certificates.c.id > last_id)
            .where(_certificates.c[COLUMN].is_(None))
            .order_by(_certificates.c.id)
            .limit(BATCH_SIZE)
        ).all()
        if not rows:
            return
        bind.execute(
            sa.update(_certificates)
            .where(_certificates.c.id == sa.bindparam("row_id"))
            .values({COLUMN: sa.bindparam("normalized")}),
            [{"row_id": row.id, "normalized": normalize_name(row.event_name)} for row in rows],
        )
        last_id = rows[-1].id


def upgrade() -> None:
    if COLUMN not in _columns():
        op.add_column("certificates", sa.Column(COLUMN, sa.String(255)))
    _backfill()
    if INDEX_NAME not in _indexes():
        op.create_index(INDEX_NAME, "certificates", [COLUMN])


def downgrade() -> None:
    if INDEX_NAME in _indexes():
        op.drop_index(INDEX_NAME, table_name="certificates")
    if COLUMN not in _columns():
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("certificates") as batch:
            batch.drop_column(COLUMN)
    else:
        op.drop_column("certificates", COLUMN)
