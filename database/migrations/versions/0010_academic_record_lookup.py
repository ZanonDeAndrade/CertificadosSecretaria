"""index the private academic-record lookup

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

INDEX_NAME = "idx_certificates_document_hash_key"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"]: index for index in inspector.get_indexes("certificates")}
    if INDEX_NAME in existing:
        columns = list(existing[INDEX_NAME].get("column_names") or [])
        expected = ["participant_document_hash", "participant_document_hash_key_id"]
        if columns != expected:
            raise RuntimeError(f"O índice preexistente {INDEX_NAME!r} é incompatível.")
        return
    op.create_index(
        INDEX_NAME,
        "certificates",
        ["participant_document_hash", "participant_document_hash_key_id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if INDEX_NAME in {index["name"] for index in inspector.get_indexes("certificates")}:
        op.drop_index(INDEX_NAME, table_name="certificates")
