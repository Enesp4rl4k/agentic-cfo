"""
013 — company_context_snapshots: Text → JSONB (PostgreSQL) / Text (SQLite)

Changes:
  1. Converts context_json column from Text to JSONB on PostgreSQL.
     On SQLite (dev), Text is kept as-is — JSONB is a PG-only type.
  2. Adds a GIN index on context_json for fast key-path queries (PG only).
  3. Adds company_context_snapshots table if it doesn't already exist
     (safe to run on fresh installs too).

Why JSONB?
  - Enables indexed key-path queries:
      SELECT * FROM company_context_snapshots
      WHERE context_json->>'org_id' = 'xxx';
  - Allows partial updates without rewriting the full blob.
  - Storage: JSONB is binary-compressed; large contexts (>512 KB) are
    stored more efficiently.

Downgrade: JSONB → Text is lossless (JSONB is a strict superset of text JSON).

Revision ID: 013_company_context_jsonb
Revises:     012_sync_schedules
Create Date: 2026-08-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = "013_company_context_jsonb"
down_revision = "012_sync_schedules"
branch_labels = None
depends_on    = None


def _is_postgresql() -> bool:
    """Return True if the current DB dialect is PostgreSQL."""
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    """
    1. Create company_context_snapshots if it doesn't exist (idempotent).
    2. On PostgreSQL: alter context_json Text → JSONB + add GIN index.
    3. On SQLite: no-op (JSONB not supported; use Text + application-level trim).
    """
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    # ── Step 1: Create table if it was never created via create_all ──────────
    if "company_context_snapshots" not in tables:
        if _is_postgresql():
            op.create_table(
                "company_context_snapshots",
                sa.Column("id",           sa.String(36),  primary_key=True),
                sa.Column("org_id",       sa.String(36),  nullable=False, unique=True, index=True),
                sa.Column("context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
                sa.Column("created_at",   sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
                sa.Column("updated_at",   sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            )
        else:
            # SQLite — plain Text JSON
            op.create_table(
                "company_context_snapshots",
                sa.Column("id",           sa.String(36),  primary_key=True),
                sa.Column("org_id",       sa.String(36),  nullable=False, unique=True, index=True),
                sa.Column("context_json", sa.Text(),      nullable=False, server_default="{}"),
                sa.Column("created_at",   sa.DateTime(timezone=True), nullable=False),
                sa.Column("updated_at",   sa.DateTime(timezone=True), nullable=False),
            )
        return   # Table was just created with correct types — nothing more to do

    # ── Step 2: Alter existing table (PostgreSQL only) ────────────────────────
    if not _is_postgresql():
        # SQLite: JSONB not available; application-level trim handles size issues.
        # No schema change needed — the Text column continues to work correctly.
        return

    # Check if column is already JSONB (re-runnable safety)
    columns     = {c["name"]: c for c in inspector.get_columns("company_context_snapshots")}
    col_type    = columns.get("context_json", {}).get("type", None)
    already_jsonb = isinstance(col_type, postgresql.JSONB)

    if not already_jsonb:
        # Cast Text → JSONB.  The USING clause ensures valid JSON text is
        # converted without data loss.  If any row contains invalid JSON,
        # the migration will fail — run cleanup first:
        #   UPDATE company_context_snapshots
        #   SET context_json = '{}'
        #   WHERE context_json IS NULL OR context_json = '';
        op.execute(
            "ALTER TABLE company_context_snapshots "
            "ALTER COLUMN context_json TYPE JSONB "
            "USING context_json::jsonb"
        )

    # ── Step 3: GIN index for fast key-path queries (idempotent) ─────────────
    indexes = {idx["name"] for idx in inspector.get_indexes("company_context_snapshots")}
    if "ix_company_context_jsonb_gin" not in indexes:
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_company_context_jsonb_gin "
            "ON company_context_snapshots USING GIN (context_json)"
        )


def downgrade() -> None:
    """
    Revert JSONB → Text on PostgreSQL.
    SQLite: no-op (was never changed).
    Drop the GIN index if present.
    """
    if not _is_postgresql():
        return

    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    if "company_context_snapshots" not in tables:
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("company_context_snapshots")}
    if "ix_company_context_jsonb_gin" in indexes:
        op.drop_index("ix_company_context_jsonb_gin", table_name="company_context_snapshots")

    # Revert JSONB → Text (lossless)
    op.execute(
        "ALTER TABLE company_context_snapshots "
        "ALTER COLUMN context_json TYPE TEXT "
        "USING context_json::text"
    )
