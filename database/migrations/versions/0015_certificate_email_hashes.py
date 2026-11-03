"""keyed e-mail hashes per certificate, for the public search and confirmation

Revision ID: 0015
Revises: 0014

Every certificate issued from now on records a keyed HMAC of each e-mail on
its spreadsheet row: the holder's (position 1) and, on a per-work
certificate, one per author. The public site finds certificates by exact
e-mail and confirms a download with it, the way the academic record did.
Certificates already issued are untouched: they keep their document hash and
get no e-mail rows. A development SQLite database may already have the table
from the ORM startup, so every step checks first.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

TABLE = "certificate_email_hashes"
FOREIGN_KEY = "fk_certificate_email_hashes_certificate_id"
HASH_INDEX = "idx_certificate_email_hashes_hash_key"
CERTIFICATE_INDEX = "idx_certificate_email_hashes_certificate"
POSITION_INDEX = "uq_certificate_email_hashes_position"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if TABLE not in _tables():
        op.create_table(
            TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "certificate_id",
                sa.Integer(),
                sa.ForeignKey("certificates.id", ondelete="CASCADE", name=FOREIGN_KEY),
                nullable=False,
            ),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("email_hash", sa.String(length=64), nullable=False),
            sa.Column("hash_key_id", sa.String(length=32), nullable=False),
        )
    existing = _indexes(TABLE)
    if HASH_INDEX not in existing:
        op.create_index(HASH_INDEX, TABLE, ["email_hash", "hash_key_id"])
    if CERTIFICATE_INDEX not in existing:
        op.create_index(CERTIFICATE_INDEX, TABLE, ["certificate_id"])
    if POSITION_INDEX not in existing:
        op.create_index(POSITION_INDEX, TABLE, ["certificate_id", "position"], unique=True)


def downgrade() -> None:
    if TABLE in _tables():
        op.drop_table(TABLE)
