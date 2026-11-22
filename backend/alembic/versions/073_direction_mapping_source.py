"""direction_mappings: the source a sign answer was given for, a standing rule, and a chain override flag.

A remembered "minus = out" answer must not leak to another source that merely shares generic header words:
the mapping now records the header signature and the account identity the header stated, an explicit standing
rule for identity-less files, and the time and reason a verifying balance chain overrode it.

Revision ID: 073_direction_mapping_source
Revises: 072_email_verification
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "073_direction_mapping_source"
down_revision = "072_email_verification"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("header_signature", sa.String(32), None),
    ("identity", sa.String(120), None),
    ("standing", sa.Boolean(), "0"),
    ("flagged_at", sa.DateTime(timezone=True), None),
    ("flagged_note", sa.String(300), None),
)


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("direction_mappings")}
    for name, kind, default in _COLUMNS:
        if name not in have:
            op.add_column("direction_mappings", sa.Column(
                name, kind, nullable=name != "standing", server_default=default))


def downgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("direction_mappings")}
    for name, _, _ in reversed(_COLUMNS):
        if name in have:
            op.drop_column("direction_mappings", name)
