"""LLM egress: the organisation's data-mode choice and the payload-free audit columns of a call.

* organizations.llm_data_mode      the owner's own choice (off | masked | raw); null = the platform default
* llm_call_logs.data_mode          the mode a call was made under
* llm_call_logs.bytes_out          bytes that left in the call (all attempts); never the payload
* llm_call_logs.replaced           {"counts": {placeholder type: n}, "flags": [...], "sends": n}

Revision ID: 079_llm_egress_audit
Revises: 078_privacy_records
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "079_llm_egress_audit"
down_revision = "078_privacy_records"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "llm_data_mode" not in _cols("organizations"):
        op.add_column("organizations", sa.Column("llm_data_mode", sa.String(8), nullable=True))
    have = _cols("llm_call_logs")
    if "data_mode" not in have:
        op.add_column("llm_call_logs", sa.Column("data_mode", sa.String(8), nullable=True))
    if "bytes_out" not in have:
        op.add_column("llm_call_logs", sa.Column("bytes_out", sa.Integer(), nullable=False, server_default="0"))
    if "replaced" not in have:
        op.add_column("llm_call_logs", sa.Column("replaced", sa.JSON(), nullable=True))


def downgrade() -> None:
    have = _cols("llm_call_logs")
    for name in ("replaced", "bytes_out", "data_mode"):
        if name in have:
            op.drop_column("llm_call_logs", name)
    if "llm_data_mode" in _cols("organizations"):
        op.drop_column("organizations", "llm_data_mode")
