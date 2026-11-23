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
    # The system re-read a statement's balance chain after a person answered its held rows: what it
    # now proves (or why not), linking the answers that caused it.
    BALANCE_REVERIFICATION = "balance_reverification"
    # A person says whether two bank statements nothing links belong to one account (or not): what the
    # opening cash adds up and what the runway counts from.
    ACCOUNT_IDENTITY = "account_identity"
    # An owner/admin confirms the company's currency: the one fact that lets a
    # currency-less document be read in it.
    BASE_CURRENCY_CONFIRMATION = "base_currency_confirmation"
    # One answer for a whole statement file whose amounts' direction could not be placed, and the
    # standing mapping it may leave (or its revocation).
    FILE_DIRECTION_ANSWER = "file_direction_answer"
    DIRECTION_MAPPING = "direction_mapping"
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
    # Who may approve what: the company's authority policy (owner/admin edit it).
    AUTHORITY_POLICY_CHANGE = "authority_policy_change"
    # Someone joined, was invited, or was removed: who may act in the company at all.
    MEMBER_CHANGE = "member_change"
    # A person's yes or no to a proposed action or queued agent job (what the system wants to do).
    ACTION_DECISION = "action_decision"
    # The accountant seals a defensibility packet.
    PACKET_FINALIZATION = "packet_finalization"
    # A person's pick between two agents' conflicting views (accept one, or their own resolution).
    AGENT_CONFLICT_RESOLUTION = "agent_conflict_resolution"
    # A person makes a finished analysis the company's picture (the system did not apply it alone).
    COMPANY_VIEW_ADOPTION = "company_view_adoption"
    # An owner/admin changes a security setting (the IP allow-list: who can reach the company at all).
    SECURITY_SETTING_CHANGE = "security_setting_change"
    # A decider wipes the company's derived agent context (every agent result, the working picture).
    CONTEXT_RESET = "context_reset"
    # A decider files or certifies something outward: a breach record or its notification to the authority,
    # a SOX 302 certification.
    COMPLIANCE_FILING = "compliance_filing"
    # A person confirms how the columns of an uploaded file are read (which one is the amount, the date).
    COLUMN_MAPPING_ACCEPTANCE = "column_mapping_acceptance"
    # A person says whether two movements on two of the company's own accounts are one transfer between them
    # (confirmed: neither counts as outflow or inflow) or not (rejected: both stay as they are).
    OWN_TRANSFER = "own_transfer"
    # An owner/admin changes a fact about the company that decides how its documents are read:
    # tax number, country, regional packs, legal title.
    ORG_IDENTITY_CHANGE = "org_identity_change"

    # The amount above which a decision needs a senior person: acknowledged as proposed, or set by the owner.
    MATERIALITY = "materiality"
    # Who else receives the Monday briefing (the owner's standing choice about the accountant).
    BRIEFING_RECIPIENTS = "briefing_recipients"


class ReadClass(StrEnum):
    """The least role that may READ a decision of a kind: it follows who may see the thing it is about.

    The guards live in `app.api.access` (`READ_ROLES`); this table only names the class, next to the kinds.
    """

    MEMBER = "member"            # any member of the organisation (the object itself is open to them)
    CONTRIBUTOR = "contributor"  # owner, admin, cfo, smmm, analyst
    WRITER = "writer"            # owner, admin, cfo, smmm
    DECIDER = "decider"          # owner, admin


_K = DecisionKind
_R = ReadClass
# EVERY kind has an entry (tests/test_decision_read_scope.py fails when one is missing). A kind that is not
# here, or a stored kind this code no longer knows, is read as DECIDER: fail closed.
DECISION_READ: dict[DecisionKind, ReadClass] = {
    # money objects every member can already open
    _K.CATEGORY_CORRECTION: _R.MEMBER,
    _K.DUPLICATE_RESOLUTION: _R.MEMBER,
    _K.SETTLEMENT_MATCH: _R.MEMBER,
    _K.HELD_RUN_RELEASE: _R.MEMBER,
    _K.HELD_ROW_RESOLUTION: _R.MEMBER,
    _K.BALANCE_REVERIFICATION: _R.MEMBER,
    _K.ACCOUNT_IDENTITY: _R.MEMBER,
    _K.OWN_TRANSFER: _R.MEMBER,
    _K.BASE_CURRENCY_CONFIRMATION: _R.MEMBER,
    _K.FILE_DIRECTION_ANSWER: _R.MEMBER,
    _K.DIRECTION_MAPPING: _R.MEMBER,
    _K.PLAN_CHANGE: _R.MEMBER,
    _K.COUNTERPARTY_ALIAS: _R.MEMBER,
    _K.COMPANY_VIEW_ADOPTION: _R.MEMBER,
    _K.COLUMN_MAPPING_ACCEPTANCE: _R.CONTRIBUTOR,
    # the books' own people
    _K.SMMM_ONAY: _R.WRITER,
    _K.MONTH_CLOSE: _R.WRITER,
    _K.PACKET_FINALIZATION: _R.WRITER,
    _K.ACTION_DECISION: _R.WRITER,
    _K.AGENT_CONFLICT_RESOLUTION: _R.WRITER,
    _K.AUTOMATION_RULE_CHANGE: _R.WRITER,
    _K.BRIEFING_RELEASE: _R.WRITER,
    _K.OWNER_STATEMENT: _R.WRITER,
    _K.SIZE_PROFILE: _R.WRITER,
    _K.AUTHORITY_POLICY_CHANGE: _R.WRITER,
    _K.MEMBER_CHANGE: _R.WRITER,
    _K.ORG_IDENTITY_CHANGE: _R.WRITER,
    # owner-decided settings whose current value every member can read (GET /org/me/materiality and
    # /org/me/briefing-recipients are `require_member`): their decisions follow the same visibility
    _K.MATERIALITY: _R.MEMBER,
    _K.BRIEFING_RECIPIENTS: _R.MEMBER,
    # access, security and outward filings: the deciders only
    _K.SECURITY_SETTING_CHANGE: _R.DECIDER,
    _K.CONTEXT_RESET: _R.DECIDER,
    _K.COMPLIANCE_FILING: _R.DECIDER,
    _K.ERASURE: _R.DECIDER,
}


def read_class(kind: str) -> ReadClass:
    """The read class of a stored kind; anything unknown is DECIDER (fail closed)."""
    try:
        return DECISION_READ[DecisionKind(kind)]
    except (ValueError, KeyError):
        return ReadClass.DECIDER


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
