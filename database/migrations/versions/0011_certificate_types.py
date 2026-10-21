"""persist controlled certificate types on batches and certificates

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

VALUES = (
    "listener",
    "speaker",
    "organizing_committee",
    "teams",
    "monitoring",
    "tcc_board_professor",
    "scientific_initiation",
)
CHECK_SQL = "certificate_type IS NULL OR certificate_type IN ({})".format(
    ", ".join(f"'{value}'" for value in VALUES)
)


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _checks(table: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)
        if constraint.get("name")
    }


def _add_check(table: str, name: str) -> None:
    if name in _checks(table):
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(name, CHECK_SQL)
    else:
        op.create_check_constraint(name, table, CHECK_SQL)


def upgrade() -> None:
    if "certificate_type" not in _columns("certificates"):
        op.add_column("certificates", sa.Column("certificate_type", sa.String(32)))
    if "certificate_type" not in _columns("emission_batches"):
        op.add_column("emission_batches", sa.Column("certificate_type", sa.String(32)))

    _add_check("certificates", "ck_certificates_certificate_type")
    _add_check("emission_batches", "ck_emission_batches_certificate_type")

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("certificates")}
    if "idx_certificates_certificate_type" not in indexes:
        op.create_index("idx_certificates_certificate_type", "certificates", ["certificate_type"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("certificates")}
    if "idx_certificates_certificate_type" in indexes:
        op.drop_index("idx_certificates_certificate_type", table_name="certificates")

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("emission_batches") as batch:
            batch.drop_constraint("ck_emission_batches_certificate_type", type_="check")
            batch.drop_column("certificate_type")
        with op.batch_alter_table("certificates") as batch:
            batch.drop_constraint("ck_certificates_certificate_type", type_="check")
            batch.drop_column("certificate_type")
    else:
        op.drop_constraint(
            "ck_emission_batches_certificate_type", "emission_batches", type_="check"
        )
        op.drop_column("emission_batches", "certificate_type")
        op.drop_constraint("ck_certificates_certificate_type", "certificates", type_="check")
        op.drop_column("certificates", "certificate_type")
