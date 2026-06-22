"""public search privacy, normalized names and distributed rate limits

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("certificates", sa.Column("participant_name_normalized", sa.String(255)))
    op.add_column("certificates", sa.Column("participant_document_hash", sa.String(64)))
    op.create_index("idx_certificates_name_normalized", "certificates", ["participant_name_normalized"])
    op.create_index(
        "idx_certificates_name_normalized_status",
        "certificates",
        ["participant_name_normalized", "status"],
    )
    op.create_table(
        "public_rate_limits",
        sa.Column("bucket_key", sa.String(64), primary_key=True),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_public_rate_limits_updated_at", "public_rate_limits", ["updated_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute(
            "CREATE INDEX idx_certificates_name_normalized_trgm "
            "ON certificates USING gin (participant_name_normalized gin_trgm_ops)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_certificates_name_normalized_trgm")
    op.drop_index("idx_public_rate_limits_updated_at", table_name="public_rate_limits")
    op.drop_table("public_rate_limits")
    op.drop_index("idx_certificates_name_normalized_status", table_name="certificates")
    op.drop_index("idx_certificates_name_normalized", table_name="certificates")
    op.drop_column("certificates", "participant_document_hash")
    op.drop_column("certificates", "participant_name_normalized")
