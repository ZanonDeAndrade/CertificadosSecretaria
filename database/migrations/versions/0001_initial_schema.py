"""initial schema (certificates, admin_users, audit_log)

Revision ID: 0001
Revises:
Create Date: 2026-06-19

Mirrors database/models.py. The ``certificates`` table stores only metadata —
never the PDF bytes. The definitive file lives in Google Drive (drive_file_id).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("unique_code", sa.String(length=64), nullable=False),
        sa.Column("participant_name", sa.String(length=255), nullable=False),
        sa.Column("participant_email", sa.String(length=255)),
        sa.Column("participant_document", sa.String(length=64)),
        sa.Column("course_name", sa.String(length=255)),
        sa.Column("event_name", sa.String(length=255), nullable=False),
        sa.Column("workload_hours", sa.Integer()),
        sa.Column("issue_date", sa.String(length=64), nullable=False),
        sa.Column("start_date", sa.String(length=64)),
        sa.Column("end_date", sa.String(length=64)),
        sa.Column("certificate_text", sa.Text()),
        sa.Column("storage_provider", sa.String(length=32), nullable=False, server_default="local"),
        sa.Column("drive_file_id", sa.String(length=255)),
        sa.Column("drive_folder_id", sa.String(length=255)),
        sa.Column("original_filename", sa.String(length=255)),
        sa.Column("mime_type", sa.String(length=128), nullable=False, server_default="application/pdf"),
        sa.Column("file_size", sa.Integer()),
        sa.Column("checksum_sha256", sa.String(length=64)),
        sa.Column("pdf_path", sa.Text()),
        sa.Column("template_used", sa.String(length=128)),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ativo"),
        sa.Column("business_key", sa.String(length=64)),
        sa.Column("issued_by", sa.Integer()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.Integer()),
        sa.Column("revoke_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("unique_code", name="uq_certificates_unique_code"),
    )
    op.create_index("idx_certificates_participant_name", "certificates", ["participant_name"])
    op.create_index("idx_certificates_event_name", "certificates", ["event_name"])
    op.create_index("idx_certificates_course_name", "certificates", ["course_name"])
    op.create_index("idx_certificates_status", "certificates", ["status"])
    op.create_index(
        "idx_certificates_business_key", "certificates", ["business_key"], unique=True
    )

    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="secretaria"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("username", name="uq_admin_users_username"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.Integer()),
        sa.Column("actor_username", sa.String(length=150)),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64)),
        sa.Column("target_id", sa.Text()),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("admin_users")
    op.drop_index("idx_certificates_business_key", table_name="certificates")
    op.drop_index("idx_certificates_status", table_name="certificates")
    op.drop_index("idx_certificates_course_name", table_name="certificates")
    op.drop_index("idx_certificates_event_name", table_name="certificates")
    op.drop_index("idx_certificates_participant_name", table_name="certificates")
    op.drop_table("certificates")
