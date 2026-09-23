"""Job lease columns + the indexes the reaper and rebuild queries scan on.

The claim/reaper contract needs three nullable columns on analysis_jobs
(`locked_by`, `locked_at`, `lease_expires_at`) plus the composite
(status, lease_expires_at) the reaper's every-few-minutes predicate uses —
without it the scan is a full table pass on a table that only grows.

canonical_transactions gets (org_id, transaction_date): the semantic rebuild
filters exactly by that pair (services/semantic/rebuild.py) and 038 created
only single-column indexes for the table.

Revision ID: 039_job_lease
Revises: 038_fk_and_missing_indexes
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "039_job_lease"
down_revision = "038_fk_and_missing_indexes"
branch_labels = None
depends_on = None

_COLUMNS: tuple[tuple[str, str, sa.types.TypeEngine], ...] = (
    ("locked_by", "analysis_jobs", sa.String(128)),
    ("locked_at", "analysis_jobs", sa.DateTime(timezone=True)),
    ("lease_expires_at", "analysis_jobs", sa.DateTime(timezone=True)),
)

_SINGLE_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_analysis_jobs_lease_expires_at", "analysis_jobs", ("lease_expires_at",)),
    (
        "ix_canonical_transactions_org_date",
        "canonical_transactions",
        ("org_id", "transaction_date"),
    ),
    (
        "ix_analysis_jobs_status_lease",
        "analysis_jobs",
        ("status", "lease_expires_at"),
    ),
)


def _has_column(conn: sa.Connection, table: str, column: str) -> bool:
    return any(
        col["name"] == column
        for col in sa.inspect(conn).get_columns(table)
    )


def _has_index(conn: sa.Connection, table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in sa.inspect(conn).get_indexes(table))


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for name, table, type_ in _COLUMNS:
        if table in inspector.get_table_names() and not _has_column(conn, table, name):
            op.add_column(table, sa.Column(name, type_, nullable=True))

    for name, table, columns in _SINGLE_INDEXES:
        if table not in inspector.get_table_names():
            continue
        if _has_column(conn, table, columns[0]) and not _has_index(conn, table, name):
            if conn.dialect.name == "postgresql":
                # CONCURRENTLY cannot run inside the migration transaction;
                # autocommit block, as 013/018 do.
                with op.get_context().autocommit_block():
                    op.create_index(name, table, columns)
            else:
                op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(_SINGLE_INDEXES):
        op.drop_index(name, table_name=table)
    for name, table, _type in reversed(_COLUMNS):
        op.drop_column(table, name)
