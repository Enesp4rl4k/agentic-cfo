"""E-mail addresses are stored normalised, and one account per mailbox is enforced.

`app/core/email_address.normalize_email` (NFKC, strip, lower-case) is now applied at
every write and every lookup. This migration brings existing rows to that form and
puts a unique index on `lower(email)` under it.

If two accounts already differ only by spelling, NOTHING is changed: the migration
stops and names the colliding user ids (ids only, no addresses) so a person can decide
which account is the real one. It never merges or deletes accounts.

Invitation tables are normalised too (no uniqueness needed there).

Revision ID: 069_normalised_emails
Revises: 068_held_transactions
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict

import sqlalchemy as sa

from alembic import op

revision = "069_normalised_emails"
down_revision = "068_held_transactions"
branch_labels = None
depends_on = None

INDEX = "uq_users_email_lower"


def _normalize(email: str) -> str:
    # Same as app.core.email_address.normalize_email (a test keeps them equal);
    # copied so a migration never changes meaning when app code does.
    return unicodedata.normalize("NFKC", email).strip().lower()


def _normalise_column(table: str, id_col: str, col: str, *, nullable: bool = False) -> None:
    bind = op.get_bind()
    if table not in sa.inspect(bind).get_table_names():
        return
    t = sa.table(table, sa.column(id_col), sa.column(col))
    for row_id, value in bind.execute(sa.select(t.c[id_col], t.c[col])).all():
        if value is None:
            continue
        fixed = _normalize(value)
        if fixed != value:
            bind.execute(sa.update(t).where(t.c[id_col] == row_id).values({col: fixed}))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return

    users = sa.table("users", sa.column("id"), sa.column("email"))
    groups: dict[str, list[str]] = defaultdict(list)
    for user_id, email in bind.execute(sa.select(users.c.id, users.c.email)).all():
        groups[_normalize(email)].append(str(user_id))
    collisions = sorted(ids for ids in groups.values() if len(ids) > 1)
    if collisions:
        listing = "; ".join(", ".join(sorted(ids)) for ids in collisions)
        raise RuntimeError(
            "Migration 069 stopped, nothing was changed: these user ids have e-mail addresses that "
            f"differ only by case, spacing or Unicode form: {listing}. Resolve each group by hand "
            "(deactivate or re-address the account that is not the real one), then run the migration again."
        )

    _normalise_column("users", "id", "email")
    _normalise_column("org_invites", "id", "email")
    _normalise_column("pilot_invites", "id", "email", nullable=True)

    # Expression indexes are not always reflected, so ask the database to skip it if it is there.
    op.execute(sa.text(f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON users (lower(email))"))


def downgrade() -> None:
    # The addresses stay normalised (the original spellings are not kept); only the index goes.
    op.execute(sa.text(f"DROP INDEX IF EXISTS {INDEX}"))
