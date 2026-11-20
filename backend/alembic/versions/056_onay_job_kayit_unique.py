"""One review row per journal entry: unique (job_id, kayit_id).

The entry id is now derived from the transaction behind it, so a re-run of the same
file gives the same ids and a decision the accountant made is kept instead of
orphaned. A second row for the same entry could then only be a duplicate that makes
the accountant decide twice.

Ids were random uuid4, so no (job_id, kayit_id) pair repeats in existing data; the
constraint is added as it stands. Should one exist anyway (a hand-edited database),
the migration keeps the row that carries a decision, else the oldest, and removes
the rest: the alternative is a migration that fails halfway on a live database.

Revision ID: 056_onay_job_kayit_unique
Revises: 055_payment_plan_changes
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "056_onay_job_kayit_unique"
down_revision = "055_payment_plan_changes"
branch_labels = None
depends_on = None

_TABLE = "smmm_onay_kayitlari"
_NAME = "uq_smmm_onay_job_kayit"


def _constraints(bind) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_unique_constraints(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names() or _NAME in _constraints(bind):
        return
    # A pair that repeats, if any: keep the decided row (or the oldest), drop the others.
    dup = bind.execute(sa.text(
        f"SELECT job_id, kayit_id FROM {_TABLE} GROUP BY job_id, kayit_id HAVING COUNT(*) > 1"
    )).fetchall()
    for job_id, kayit_id in dup:
        rows = bind.execute(
            sa.text(
                f"SELECT id, durum FROM {_TABLE} WHERE job_id = :j AND kayit_id = :k "
                "ORDER BY CASE WHEN durum = 'bekliyor' THEN 1 ELSE 0 END, created_at"
            ),
            {"j": job_id, "k": kayit_id},
        ).fetchall()
        for (rid, _durum) in rows[1:]:
            bind.execute(sa.text(f"DELETE FROM {_TABLE} WHERE id = :i"), {"i": rid})
    with op.batch_alter_table(_TABLE) as batch:
        batch.create_unique_constraint(_NAME, ["job_id", "kayit_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names() and _NAME in _constraints(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_constraint(_NAME, type_="unique")
