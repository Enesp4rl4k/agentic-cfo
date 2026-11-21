"""The decision record: who decided what, when, on which evidence. Append-only.

Plan v11 C4 / A1.6. The product principle is "the system proposes, humans decide",
and every decision, including one made by an earned rule or by the system, leaves
one row here. The row REFERENCES the record the decision acted on (`target_*`) and
the evidence it rested on (`evidence_refs`); it does not replace the ledger,
`smmm_onay_kayitlari`, `payment_plan_changes` or `open_item_matches`.

Append-only means: a row is never updated or deleted by application code. A later
decision that replaces an earlier one is a NEW row whose `supersedes_id` points at
the old one. The ORM refuses updates and deletes below (see the listeners); the
only code allowed to touch existing rows is organisation erasure, which uses Core
statements (`app.services.org_erasure`) and is an explicit legal exception.

No foreign key to `users`: erasing a person must not be blocked by, or cascade
into, the record of what they decided. Money inside `before` / `after` is integer
kurus under keys ending `_cents` or `_kurus` (CLAUDE.md), validated by the service.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Text, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base


class DecisionKind(StrEnum):
    """What was decided. Extensible: add a member, no migration (the column is text)."""

    CATEGORY_CORRECTION = "category_correction"
    DUPLICATE_RESOLUTION = "duplicate_resolution"
    SETTLEMENT_MATCH = "settlement_match"
    HELD_RUN_RELEASE = "held_run_release"
    # A person's answer to one extracted row the system would not book alone.
    HELD_ROW_RESOLUTION = "held_row_resolution"
    # An owner/admin confirms the company's currency: the one fact that lets a
    # currency-less document be read in it.
    BASE_CURRENCY_CONFIRMATION = "base_currency_confirmation"
    PLAN_CHANGE = "plan_change"
    BRIEFING_RELEASE = "briefing_release"
    MONTH_CLOSE = "month_close"
    SMMM_ONAY = "smmm_onay"
    ERASURE = "erasure"
    AUTOMATION_RULE_CHANGE = "automation_rule_change"
    # Two counterparty spellings declared one supplier (or the declaration revoked): a standing rule at ingest.
    COUNTERPARTY_ALIAS = "counterparty_alias"
    # What the owner says they did. A statement, not a proof: see `outcome`.
    OWNER_STATEMENT = "owner_statement"
    # A person's company-size answers and the size profile they confirmed.
    SIZE_PROFILE = "size_profile"


class DecidedVia(StrEnum):
    HUMAN = "human"
    RULE = "rule"
    SYSTEM = "system"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        Index("ix_decisions_org_decided_at", "org_id", "decided_at"),
        Index("ix_decisions_org_target", "org_id", "target_type", "target_id"),
        # One successor per decision keeps a supersede chain a line, not a tree.
        Index("uq_decisions_supersedes_id", "supersedes_id", unique=True),
        CheckConstraint("decided_via IN ('human', 'rule', 'system')", name="ck_decisions_decided_via"),
        CheckConstraint("(decided_via = 'rule') = (rule_id IS NOT NULL)", name="ck_decisions_rule_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(120), nullable=False)
    outcome: Mapped[str] = mapped_column(String(60), nullable=False)
    # Nullable only when the decision was not human; see `decided_via`.
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_via: Mapped[str] = mapped_column(String(10), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{"type": "document" | "ledger_row" | "open_item" | ..., "id": "..."}]
    evidence_refs: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=True)


class AppendOnlyError(RuntimeError):
    """Raised on any attempt to update or delete a decision."""


@event.listens_for(Decision, "before_update")
def _refuse_update(*_args: Any) -> None:
    raise AppendOnlyError("decisions are append-only: record a new decision that supersedes it")


@event.listens_for(Decision, "before_delete")
def _refuse_delete(*_args: Any) -> None:
    raise AppendOnlyError("decisions are append-only and are never deleted")


@event.listens_for(Session, "do_orm_execute")
def _refuse_bulk(state: Any) -> None:
    """`update(Decision)` / `delete(Decision)` skip the mapper events; stop them here."""
    if (state.is_update or state.is_delete) and any(m.class_ is Decision for m in state.all_mappers):
        raise AppendOnlyError("decisions are append-only: no bulk update or delete")
