"""template_versions + certificate snapshot columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-19

Introduces the single global template with an immutable version history
(``template_versions``) and records, on each certificate, which version produced
it (``template_version_id``) plus a frozen ``template_snapshot`` of the layout —
so a reissue reproduces the original certificate faithfully.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "template_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255)),
        sa.Column("layout_json", sa.Text(), nullable=False),
        sa.Column("image_width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("background_image", sa.LargeBinary()),
        sa.Column("background_mime_type", sa.String(length=128), nullable=False, server_default="image/png"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("activated_by", sa.Integer()),
        sa.UniqueConstraint("version_number", name="uq_template_versions_version_number"),
    )
    op.create_index("idx_template_versions_is_active", "template_versions", ["is_active"])

    op.add_column("certificates", sa.Column("template_version_id", sa.Integer()))
    op.add_column("certificates", sa.Column("template_snapshot", sa.Text()))


def downgrade() -> None:
    op.drop_column("certificates", "template_snapshot")
    op.drop_column("certificates", "template_version_id")
    op.drop_index("idx_template_versions_is_active", table_name="template_versions")
    op.drop_table("template_versions")
