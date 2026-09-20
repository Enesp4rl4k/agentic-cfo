"""canonical_transactions.sync_run_id points at sync_runs; the indexes the models declare.

Migration 021 gave canonical_transactions.sync_run_id a foreign key to
analysis_jobs.id. The column holds sync run ids (scheduled_sync writes
SyncRun ids into it), so on Postgres every canonical row a scheduled sync
wrote violated the constraint. The model always said sync_runs.id; SQLite
does not enforce foreign keys by default, so nothing local could see it.

The models also declare eleven non-unique indexes no migration created —
among them transactions by date, category, type and vendor, which every
report filters on. Created here where missing. (The three unique indexes the
models declare are already enforced by unique constraints of other names.)

Found by the first schema comparison against Postgres in CI.

Revision ID: 038_fk_and_missing_indexes
Revises: 037_missing_tables
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "038_fk_and_missing_indexes"
down_revision = "037_missing_tables"
branch_labels = None
depends_on = None

_FK_NAME = "fk_canonical_transactions_sync_run_id_sync_runs"

_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_alert_history_org_created", "alert_history", ("org_id", "created_at")),
    ("ix_alert_rules_org_enabled", "alert_rules", ("org_id", "enabled")),
    ("ix_analysis_jobs_created_at", "analysis_jobs", ("created_at",)),
    ("ix_analysis_jobs_status", "analysis_jobs", ("status",)),
    ("ix_rag_chunks_source_type", "rag_chunks", ("source_type",)),
    ("ix_smmm_musteri_kayit_muhasebeci_id", "smmm_musteri_kayit", ("muhasebeci_id",)),
    ("ix_transactions_category", "transactions", ("category",)),
    ("ix_transactions_created_at", "transactions", ("created_at",)),
    ("ix_transactions_transaction_date", "transactions", ("transaction_date",)),
    ("ix_transactions_type", "transactions", ("type",)),
    ("ix_transactions_vendor", "transactions", ("vendor",)),
)


def _canonical_fks(inspector: sa.Inspector) -> list[dict]:
    return [fk for fk in inspector.get_foreign_keys("canonical_transactions")
            if fk.get("constrained_columns") == ["sync_run_id"]]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if bind.dialect.name == "postgresql" and {"canonical_transactions", "sync_runs"} <= tables:
        for fk in _canonical_fks(inspector):
            if fk.get("referred_table") != "sync_runs" and fk.get("name"):
                op.drop_constraint(fk["name"], "canonical_transactions", type_="foreignkey")
        if not any(fk.get("referred_table") == "sync_runs" for fk in _canonical_fks(sa.inspect(bind))):
            # Rows written through the wrong key may name no sync run; they
            # cannot satisfy the right one, so they are cleared first.
            op.execute(
                "UPDATE canonical_transactions SET sync_run_id = NULL "
                "WHERE sync_run_id IS NOT NULL AND sync_run_id NOT IN (SELECT id FROM sync_runs)"
            )
            op.create_foreign_key(_FK_NAME, "canonical_transactions", "sync_runs",
                                  ["sync_run_id"], ["id"], ondelete="SET NULL")

    for name, table, columns in _INDEXES:
        if table not in tables:
            continue
        existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}
        if name not in existing:
            op.create_index(name, table, list(columns))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for name, table, _columns in reversed(_INDEXES):
        if table in tables and name in {ix["name"] for ix in inspector.get_indexes(table)}:
            op.drop_index(name, table_name=table)
    # The foreign key to sync_runs is dropped, not pointed back at
    # analysis_jobs: that would restore the fault this revision removes. It
    # has to go, or 022's downgrade cannot drop sync_runs.
    if bind.dialect.name == "postgresql" and "canonical_transactions" in tables:
        if any(fk.get("name") == _FK_NAME for fk in _canonical_fks(inspector)):
            op.drop_constraint(_FK_NAME, "canonical_transactions", type_="foreignkey")
