"""F8/F12/F16: ISO dates, integrity flag, CHECK constraints + FKs

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-19

- F8: convert issue_date/start_date/end_date from 'por extenso' to ISO
  (YYYY-MM-DD) for correct chronological ordering; index issue_date.
- F12: add ``integrity_blocked`` so tampered/corrupt files can be quarantined.
- F16: CHECK constraints (status / storage_provider / role) and FOREIGN KEYs
  (issued_by, revoked_by, audit_log.actor_id → admin_users) with ON DELETE SET
  NULL so removing a user never destroys certificate/audit history.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

LOGGER = logging.getLogger("alembic.0005")

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "", "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
        ]
    )
    if m
}
_EXTENSO_RE = re.compile(r"(\d{1,2}) de ([a-zà-ÿç]+) de (\d{4})", re.IGNORECASE)


def _ascii_lower(text: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


def _to_iso(value: object) -> str | None:
    if value is None:
        return None
    s = " ".join(str(value).strip().split())
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    m = _EXTENSO_RE.fullmatch(s)
    if m:
        month = _MONTHS.get(_ascii_lower(m.group(2)))
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1))).isoformat()
            except ValueError:
                return None
    return None


def _convert_dates(bind) -> None:
    rows = bind.execute(
        sa.text("SELECT id, issue_date, start_date, end_date FROM certificates")
    ).fetchall()
    unconvertible: list[str] = []
    for row in rows:
        updates = {}
        for col in ("issue_date", "start_date", "end_date"):
            current = getattr(row, col)
            if not current:
                continue
            iso = _to_iso(current)
            if iso is None:
                if col == "issue_date":
                    unconvertible.append(f"id={row.id} ({current!r})")
                continue
            if iso != current:
                updates[col] = iso
        if updates:
            sets = ", ".join(f"{k} = :{k}" for k in updates)
            bind.execute(
                sa.text(f"UPDATE certificates SET {sets} WHERE id = :id"),
                {**updates, "id": row.id},
            )
    if unconvertible:
        LOGGER.warning(
            "0005: %d issue_date não convertíveis para ISO (mantidas como estão): %s",
            len(unconvertible),
            ", ".join(unconvertible[:50]),
        )


def upgrade() -> None:
    bind = op.get_bind()

    # F12: integrity flag.
    op.add_column(
        "certificates",
        sa.Column("integrity_blocked", sa.Integer(), nullable=False, server_default="0"),
    )

    # F8: convert existing dates to ISO + index.
    _convert_dates(bind)
    op.create_index("idx_certificates_issue_date", "certificates", ["issue_date"])

    # F16: CHECK constraints + FKs (batch mode recreates the table on SQLite).
    with op.batch_alter_table("certificates") as batch:
        batch.create_check_constraint(
            "ck_certificates_status",
            "status IN ('pending', 'ativo', 'revogado', 'failed')",
        )
        batch.create_check_constraint(
            "ck_certificates_storage_provider",
            "storage_provider IN ('local', 'google_drive')",
        )
        batch.create_foreign_key(
            "fk_certificates_issued_by", "admin_users", ["issued_by"], ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_certificates_revoked_by", "admin_users", ["revoked_by"], ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("admin_users") as batch:
        batch.create_check_constraint(
            "ck_admin_users_role", "role IN ('admin', 'secretaria', 'auditor')"
        )

    with op.batch_alter_table("audit_log") as batch:
        batch.create_foreign_key(
            "fk_audit_log_actor_id", "admin_users", ["actor_id"], ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_constraint("fk_audit_log_actor_id", type_="foreignkey")
    with op.batch_alter_table("admin_users") as batch:
        batch.drop_constraint("ck_admin_users_role", type_="check")
    with op.batch_alter_table("certificates") as batch:
        batch.drop_constraint("fk_certificates_revoked_by", type_="foreignkey")
        batch.drop_constraint("fk_certificates_issued_by", type_="foreignkey")
        batch.drop_constraint("ck_certificates_storage_provider", type_="check")
        batch.drop_constraint("ck_certificates_status", type_="check")
    op.drop_index("idx_certificates_issue_date", table_name="certificates")
    op.drop_column("certificates", "integrity_blocked")
