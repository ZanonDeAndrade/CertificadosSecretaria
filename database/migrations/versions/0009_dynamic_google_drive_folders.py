"""dynamic Google Drive folders selected through OAuth and Picker

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _require_columns(table_name: str, required: set[str]) -> None:
    columns = {column["name"] for column in _inspector().get_columns(table_name)}
    missing = sorted(required - columns)
    if missing:
        raise RuntimeError(
            f"A tabela preexistente {table_name!r} é incompatível; "
            f"colunas ausentes: {', '.join(missing)}."
        )


def _ensure_index(name: str, table_name: str, columns: list[str]) -> None:
    existing = {index["name"]: index for index in _inspector().get_indexes(table_name)}
    if name in existing:
        if list(existing[name].get("column_names") or []) != columns:
            raise RuntimeError(f"O índice preexistente {name!r} possui definição incompatível.")
        return
    op.create_index(name, table_name, columns)


def upgrade() -> None:
    connection_columns = {
        "user_id",
        "state_hash",
        "pkce_verifier_ciphertext",
        "pkce_verifier_nonce",
        "pkce_verifier_key_id",
        "state_expires_at",
        "access_token_ciphertext",
        "access_token_nonce",
        "access_token_key_id",
        "token_expires_at",
        "account_email",
        "connected_at",
        "created_at",
        "updated_at",
    }
    if not _table_exists("google_drive_connections"):
        op.create_table(
            "google_drive_connections",
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("state_hash", sa.String(64)),
            sa.Column("pkce_verifier_ciphertext", sa.LargeBinary()),
            sa.Column("pkce_verifier_nonce", sa.LargeBinary()),
            sa.Column("pkce_verifier_key_id", sa.String(64)),
            sa.Column("state_expires_at", sa.DateTime(timezone=True)),
            sa.Column("access_token_ciphertext", sa.LargeBinary()),
            sa.Column("access_token_nonce", sa.LargeBinary()),
            sa.Column("access_token_key_id", sa.String(64)),
            sa.Column("token_expires_at", sa.DateTime(timezone=True)),
            sa.Column("account_email", sa.String(320)),
            sa.Column("connected_at", sa.DateTime(timezone=True)),
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
            sa.ForeignKeyConstraint(["user_id"], ["admin_users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("user_id"),
            sa.UniqueConstraint("state_hash", name="uq_google_drive_connections_state_hash"),
        )
    else:
        _require_columns("google_drive_connections", connection_columns)
    _ensure_index(
        "idx_google_drive_connections_state_expires",
        "google_drive_connections",
        ["state_expires_at"],
    )
    _ensure_index(
        "idx_google_drive_connections_token_expires",
        "google_drive_connections",
        ["token_expires_at"],
    )
    grant_columns = {
        "id",
        "user_id",
        "folder_id",
        "folder_id_hash",
        "folder_name",
        "can_add_children",
        "created_at",
        "validated_at",
    }
    if not _table_exists("google_drive_folder_grants"):
        op.create_table(
            "google_drive_folder_grants",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("folder_id", sa.String(255), nullable=False),
            sa.Column("folder_id_hash", sa.String(64), nullable=False),
            sa.Column("folder_name", sa.String(255), nullable=False),
            sa.Column("can_add_children", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "validated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "can_add_children IN (0, 1)", name="ck_drive_folder_grants_can_add_children"
            ),
            sa.ForeignKeyConstraint(["user_id"], ["admin_users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "folder_id_hash", name="uq_drive_folder_grant_user_hash"
            ),
        )
    else:
        _require_columns("google_drive_folder_grants", grant_columns)
    _ensure_index(
        "idx_drive_folder_grants_user",
        "google_drive_folder_grants",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_drive_folder_grants_user", table_name="google_drive_folder_grants")
    op.drop_table("google_drive_folder_grants")
    op.drop_index(
        "idx_google_drive_connections_token_expires",
        table_name="google_drive_connections",
    )
    op.drop_index(
        "idx_google_drive_connections_state_expires",
        table_name="google_drive_connections",
    )
    op.drop_table("google_drive_connections")
