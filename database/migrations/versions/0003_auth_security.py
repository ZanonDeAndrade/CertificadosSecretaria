"""revocable sessions and persistent login throttling

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.String(length=64)),
        sa.Column("ip_hash", sa.String(length=64)),
        sa.Column("user_agent_hash", sa.String(length=64)),
    )
    op.create_index("idx_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("idx_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_index("idx_auth_sessions_revoked_at", "auth_sessions", ["revoked_at"])

    op.create_table(
        "login_throttles",
        sa.Column("scope_type", sa.String(length=16), primary_key=True),
        sa.Column("scope_key", sa.String(length=64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True)),
        sa.Column("blocked_until", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_login_throttles_blocked_until", "login_throttles", ["blocked_until"]
    )
    op.create_index(
        "idx_login_throttles_updated_at", "login_throttles", ["updated_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_login_throttles_updated_at", table_name="login_throttles")
    op.drop_index("idx_login_throttles_blocked_until", table_name="login_throttles")
    op.drop_table("login_throttles")
    op.drop_index("idx_auth_sessions_revoked_at", table_name="auth_sessions")
    op.drop_index("idx_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("idx_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
