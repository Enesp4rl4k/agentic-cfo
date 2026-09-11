"""İşi müşavirin müşterisine bağla: analysis_jobs.smmm_client_id.

The SMMM portal and the compliance chain were two islands. `SMMMMusteriKayit`
held an accountant's client companies and carried `client_org_id`,
`last_job_id`, `health_score` — none of which any code ever wrote, so the
portal's dashboard counted analyses that could not be counted and every number
on it was structurally zero.

An accountant could register forty clients and run the chain for none of them.
This is the missing link: a job may belong to one of those clients.

Nullable on purpose. A company analysing its own books has no accountant's
client record, and that is the ordinary case.

Revision ID: 034_job_smmm_client
Revises: 033_estimated_transaction_date
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "034_job_smmm_client"
down_revision = "033_estimated_transaction_date"
branch_labels = None
depends_on = None

_TABLE = "analysis_jobs"
_COLUMN = "smmm_client_id"
_INDEX = "ix_analysis_jobs_smmm_client_id"


def _columns(inspector: sa.Inspector) -> set[str]:
    if _TABLE not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _COLUMN in _columns(inspector):
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(36), nullable=True))
    op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _COLUMN not in _columns(inspector):
        return
    existing = {i["name"] for i in inspector.get_indexes(_TABLE)}
    if _INDEX in existing:
        op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, _COLUMN)
