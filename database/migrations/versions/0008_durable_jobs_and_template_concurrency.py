"""durable emission jobs and serialized template versions

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-13

This is an expand migration: certificate rows and completed batches remain
compatible while new workers gain leases, encrypted work items and retry state.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _require_columns(table_name: str, required: set[str]) -> None:
    missing = sorted(required - _column_names(table_name))
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"A tabela preexistente {table_name!r} é incompatível; colunas ausentes: {joined}."
        )


def _ensure_index(
    name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
    **dialect_options,
) -> None:
    existing = {index["name"]: index for index in _inspector().get_indexes(table_name)}
    if name in existing:
        found = existing[name]
        if list(found.get("column_names") or []) != columns or bool(found.get("unique")) != unique:
            raise RuntimeError(f"O índice preexistente {name!r} possui definição incompatível.")
        return
    op.create_index(
        name,
        table_name,
        columns,
        unique=unique,
        **dialect_options,
    )


def _check_constraint(table_name: str, name: str) -> dict | None:
    return next(
        (
            constraint
            for constraint in _inspector().get_check_constraints(table_name)
            if constraint.get("name") == name
        ),
        None,
    )


def upgrade() -> None:
    existing_columns = _column_names("emission_batches")
    durable_columns = (
        sa.Column("context_ciphertext", sa.LargeBinary()),
        sa.Column("context_nonce", sa.LargeBinary()),
        sa.Column("payload_key_id", sa.String(64)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("worker_heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
    )
    status_constraint = _check_constraint("emission_batches", "ck_emission_batches_status")
    status_sql = str((status_constraint or {}).get("sqltext") or "").casefold()
    status_is_current = "partial" in status_sql and "cancelled" in status_sql
    attempts_constraint = _check_constraint("emission_batches", "ck_emission_batches_attempts")

    with op.batch_alter_table("emission_batches") as batch:
        for column in durable_columns:
            if column.name not in existing_columns:
                batch.add_column(column)
        if status_constraint and not status_is_current:
            batch.drop_constraint("ck_emission_batches_status", type_="check")
        if not status_is_current:
            batch.create_check_constraint(
                "ck_emission_batches_status",
                "status IN ('queued', 'processing', 'completed', 'partial', 'failed', 'cancelled')",
            )
        if attempts_constraint is None:
            batch.create_check_constraint(
                "ck_emission_batches_attempts",
                "attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts",
            )

    _ensure_index(
        "idx_emission_batches_claim",
        "emission_batches",
        ["status", "next_attempt_at", "lease_expires_at"],
    )

    if not _table_exists("emission_batch_items"):
        op.create_table(
            "emission_batch_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("batch_id", sa.String(36), nullable=False),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("business_key", sa.String(64), nullable=False),
            sa.Column("payload_ciphertext", sa.LargeBinary()),
            sa.Column("payload_nonce", sa.LargeBinary()),
            sa.Column("payload_key_id", sa.String(64)),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("certificate_code", sa.String(64)),
            sa.Column("error_code", sa.String(64)),
            sa.Column("error_message", sa.String(500)),
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
                "status IN ('queued', 'processing', 'generated', 'duplicate', "
                "'failed', 'cancelled')",
                name="ck_emission_batch_items_status",
            ),
            sa.CheckConstraint("attempt_count >= 0", name="ck_emission_batch_items_attempts"),
            sa.ForeignKeyConstraint(["batch_id"], ["emission_batches.id"], ondelete="CASCADE"),
        )
    else:
        _require_columns(
            "emission_batch_items",
            {
                "id",
                "batch_id",
                "row_number",
                "status",
                "business_key",
                "payload_ciphertext",
                "payload_nonce",
                "payload_key_id",
                "attempt_count",
                "certificate_code",
                "error_code",
                "error_message",
                "created_at",
                "started_at",
                "completed_at",
                "updated_at",
            },
        )
    _ensure_index(
        "idx_emission_batch_items_batch_status",
        "emission_batch_items",
        ["batch_id", "status", "id"],
    )
    _ensure_index(
        "uq_emission_batch_items_batch_row",
        "emission_batch_items",
        ["batch_id", "row_number"],
        unique=True,
    )

    if not _table_exists("template_version_sequence"):
        op.create_table(
            "template_version_sequence",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("next_number", sa.Integer(), nullable=False),
            sa.CheckConstraint("id = 1", name="ck_template_version_sequence_singleton"),
            sa.CheckConstraint("next_number >= 1", name="ck_template_version_sequence_positive"),
        )
    else:
        _require_columns("template_version_sequence", {"id", "next_number"})
    op.execute(
        sa.text(
            "INSERT INTO template_version_sequence (id, next_number) "
            "SELECT 1, (SELECT COALESCE(MAX(version_number), 0) + 1 FROM template_versions) "
            "WHERE NOT EXISTS (SELECT 1 FROM template_version_sequence WHERE id = 1)"
        )
    )

    # Repair any legacy drift deterministically before enforcing one active row.
    op.execute(
        sa.text(
            "UPDATE template_versions SET is_active = 0 "
            "WHERE is_active = 1 AND id NOT IN ("
            "SELECT id FROM template_versions WHERE is_active = 1 "
            "ORDER BY version_number DESC LIMIT 1)"
        )
    )
    _ensure_index(
        "uq_template_versions_single_active",
        "template_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = 1"),
        sqlite_where=sa.text("is_active = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_template_versions_single_active", table_name="template_versions")
    op.drop_table("template_version_sequence")

    op.drop_index("uq_emission_batch_items_batch_row", table_name="emission_batch_items")
    op.drop_index("idx_emission_batch_items_batch_status", table_name="emission_batch_items")
    op.drop_table("emission_batch_items")
    op.drop_index("idx_emission_batches_claim", table_name="emission_batches")

    op.execute(
        sa.text(
            "UPDATE emission_batches SET status = 'failed' WHERE status IN ('partial', 'cancelled')"
        )
    )
    with op.batch_alter_table("emission_batches") as batch:
        batch.drop_constraint("ck_emission_batches_attempts", type_="check")
        batch.drop_constraint("ck_emission_batches_status", type_="check")
        batch.create_check_constraint(
            "ck_emission_batches_status",
            "status IN ('queued', 'processing', 'completed', 'failed')",
        )
        batch.drop_column("last_error_code")
        batch.drop_column("cancel_requested_at")
        batch.drop_column("worker_heartbeat_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_owner")
        batch.drop_column("next_attempt_at")
        batch.drop_column("max_attempts")
        batch.drop_column("attempt_count")
        batch.drop_column("payload_key_id")
        batch.drop_column("context_nonce")
        batch.drop_column("context_ciphertext")
