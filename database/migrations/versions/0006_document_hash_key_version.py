"""version document HMAC keys without invalidating existing certificates

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-13

Existing hashes were all produced by the original DOCUMENT_HASH_SECRET and are
therefore labelled ``v1``.  The hash bytes are not changed: this migration is
safe even when the original document plaintext has already been minimized.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "certificates",
        sa.Column("participant_document_hash_key_id", sa.String(32), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE certificates "
            "SET participant_document_hash_key_id = 'v1' "
            "WHERE participant_document_hash IS NOT NULL "
            "AND participant_document_hash_key_id IS NULL"
        )
    )


def downgrade() -> None:
    # Downgrade removes only version metadata; the HMAC itself is unchanged.
    op.drop_column("certificates", "participant_document_hash_key_id")
