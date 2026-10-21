"""user management, institutional settings and resumable emission batches

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-13

The migration is additive. Existing users keep their credentials and receive
their login as display name; existing certificates remain valid and all new
workflow links/snapshots are nullable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    # Inspectors cache metadata, so create a fresh one after every DDL change.
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _column_names(table_name):
        op.add_column(table_name, column)


def _require_columns(table_name: str, required: set[str]) -> None:
    missing = sorted(required - _column_names(table_name))
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"A tabela preexistente {table_name!r} é incompatível; colunas ausentes: {joined}."
        )


def _ensure_index(name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    existing = {index["name"]: index for index in _inspector().get_indexes(table_name)}
    if name in existing:
        found = existing[name]
        if list(found.get("column_names") or []) != columns or bool(found.get("unique")) != unique:
            raise RuntimeError(f"O índice preexistente {name!r} possui definição incompatível.")
        return
    op.create_index(name, table_name, columns, unique=unique)


def _ensure_foreign_key(
    table_name: str,
    name: str,
    local_columns: list[str],
    remote_table: str,
    remote_columns: list[str],
) -> None:
    for foreign_key in _inspector().get_foreign_keys(table_name):
        if (
            list(foreign_key.get("constrained_columns") or []) == local_columns
            and foreign_key.get("referred_table") == remote_table
            and list(foreign_key.get("referred_columns") or []) == remote_columns
        ):
            return
    with op.batch_alter_table(table_name) as batch:
        batch.create_foreign_key(
            name,
            remote_table,
            local_columns,
            remote_columns,
            ondelete="SET NULL",
        )


def upgrade() -> None:
    _add_column_if_missing("admin_users", sa.Column("name", sa.String(255), nullable=True))
    _add_column_if_missing(
        "admin_users",
        sa.Column("must_change_password", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "admin_users", sa.Column("password_changed_at", sa.DateTime(timezone=True))
    )
    _add_column_if_missing("admin_users", sa.Column("updated_at", sa.DateTime(timezone=True)))
    _add_column_if_missing("admin_users", sa.Column("created_by", sa.Integer()))
    op.execute(sa.text("UPDATE admin_users SET name = username WHERE name IS NULL"))
    name_column = next(
        column for column in _inspector().get_columns("admin_users") if column["name"] == "name"
    )
    if name_column.get("nullable"):
        with op.batch_alter_table("admin_users") as batch:
            batch.alter_column("name", existing_type=sa.String(255), nullable=False)
    _ensure_foreign_key(
        "admin_users",
        "fk_admin_users_created_by",
        ["created_by"],
        "admin_users",
        ["id"],
    )

    if not _table_exists("institutional_settings"):
        op.create_table(
            "institutional_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("institution_name", sa.String(255), nullable=False),
            sa.Column("issue_location", sa.String(255), nullable=False, server_default=""),
            sa.Column("signatory_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("signatory_title", sa.String(255), nullable=False, server_default=""),
            sa.Column("public_url", sa.String(2048), nullable=False, server_default=""),
            sa.Column("retention_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_batch_rows", sa.Integer(), nullable=False, server_default="2000"),
            sa.Column("max_upload_mb", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("secretaria_can_revoke", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("secretaria_can_reissue", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("updated_by", sa.Integer()),
            sa.CheckConstraint("id = 1", name="ck_institutional_settings_singleton"),
            sa.CheckConstraint("retention_days >= 0", name="ck_settings_retention_days"),
            sa.CheckConstraint(
                "max_batch_rows >= 1 AND max_batch_rows <= 10000",
                name="ck_settings_max_batch_rows",
            ),
            sa.CheckConstraint(
                "max_upload_mb >= 1 AND max_upload_mb <= 100",
                name="ck_settings_max_upload_mb",
            ),
            sa.ForeignKeyConstraint(["updated_by"], ["admin_users.id"], ondelete="SET NULL"),
        )
    else:
        _require_columns(
            "institutional_settings",
            {
                "id",
                "institution_name",
                "issue_location",
                "signatory_name",
                "signatory_title",
                "public_url",
                "retention_days",
                "max_batch_rows",
                "max_upload_mb",
                "secretaria_can_revoke",
                "secretaria_can_reissue",
                "updated_at",
                "updated_by",
            },
        )

    if not _table_exists("emission_batches"):
        op.create_table(
            "emission_batches",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
            sa.Column("request_sha256", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("generated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("result_json", sa.Text()),
            sa.Column("invalid_report_json", sa.Text()),
            sa.Column("error_message", sa.String(500)),
            sa.Column("created_by", sa.Integer()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "status IN ('queued', 'processing', 'completed', 'failed')",
                name="ck_emission_batches_status",
            ),
            sa.ForeignKeyConstraint(["created_by"], ["admin_users.id"], ondelete="SET NULL"),
        )
    else:
        _require_columns(
            "emission_batches",
            {
                "id",
                "idempotency_key",
                "request_sha256",
                "status",
                "total_rows",
                "valid_count",
                "invalid_count",
                "processed_count",
                "generated_count",
                "duplicate_count",
                "failed_count",
                "created_by",
                "created_at",
                "updated_at",
            },
        )
    _ensure_index(
        "idx_emission_batches_created_by_created_at",
        "emission_batches",
        ["created_by", "created_at"],
    )
    _ensure_index(
        "idx_emission_batches_status_updated_at",
        "emission_batches",
        ["status", "updated_at"],
    )

    _add_column_if_missing("certificates", sa.Column("institutional_snapshot", sa.Text()))
    _add_column_if_missing("certificates", sa.Column("batch_id", sa.String(36)))
    _add_column_if_missing(
        "certificates",
        sa.Column("reissue_count", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing("certificates", sa.Column("reissued_at", sa.DateTime(timezone=True)))
    _add_column_if_missing("certificates", sa.Column("reissued_by", sa.Integer()))
    _ensure_index("idx_certificates_batch_id", "certificates", ["batch_id"])
    _ensure_foreign_key(
        "certificates",
        "fk_certificates_batch_id",
        ["batch_id"],
        "emission_batches",
        ["id"],
    )
    _ensure_foreign_key(
        "certificates",
        "fk_certificates_reissued_by",
        ["reissued_by"],
        "admin_users",
        ["id"],
    )

    _ensure_index("idx_audit_log_action_created_at", "audit_log", ["action", "created_at"])
    _ensure_index("idx_audit_log_actor_created_at", "audit_log", ["actor_id", "created_at"])
    _ensure_index("idx_audit_log_target", "audit_log", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("idx_audit_log_target", table_name="audit_log")
    op.drop_index("idx_audit_log_actor_created_at", table_name="audit_log")
    op.drop_index("idx_audit_log_action_created_at", table_name="audit_log")

    with op.batch_alter_table("certificates") as batch:
        batch.drop_constraint("fk_certificates_reissued_by", type_="foreignkey")
        batch.drop_constraint("fk_certificates_batch_id", type_="foreignkey")
    op.drop_index("idx_certificates_batch_id", table_name="certificates")
    op.drop_column("certificates", "reissued_by")
    op.drop_column("certificates", "reissued_at")
    op.drop_column("certificates", "reissue_count")
    op.drop_column("certificates", "batch_id")
    op.drop_column("certificates", "institutional_snapshot")

    op.drop_index("idx_emission_batches_status_updated_at", table_name="emission_batches")
    op.drop_index("idx_emission_batches_created_by_created_at", table_name="emission_batches")
    op.drop_table("emission_batches")
    op.drop_table("institutional_settings")

    with op.batch_alter_table("admin_users") as batch:
        batch.drop_constraint("fk_admin_users_created_by", type_="foreignkey")
    op.drop_column("admin_users", "created_by")
    op.drop_column("admin_users", "updated_at")
    op.drop_column("admin_users", "password_changed_at")
    op.drop_column("admin_users", "must_change_password")
    op.drop_column("admin_users", "name")
