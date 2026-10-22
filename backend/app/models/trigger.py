"""The two tables the P4-1 trigger engine persists (P4-0 pinned the shapes).

`trigger_definitions` stores the `TriggerDefinition` envelope from
``triggers/contracts.py`` — the events/condition/action_params columns are JSON
text so the row round-trips through ``parse_condition`` / ``condition_to_dict``
exactly as the DSL authors it.

`trigger_runs` is both the audit trail and the idempotency guard: one row per
(trigger, event) evaluation, with a unique constraint on that pair so a redelivered
event can never fire twice. ``status`` records the decision — ``fired``,
``cooldown``, ``condition_false`` or ``error`` — so "why didn't my rule fire?" is
answerable from the data.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TriggerDefinitionRow(Base):
    """One stored rule: on ``events``, if ``condition`` holds → run ``action_kind``."""

    __tablename__ = "trigger_definitions"
    __table_args__ = (
        Index("ix_trigger_definitions_org_enabled", "org_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # JSON list[EventKind]: ["job.completed", "schedule", …]
    events: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON condition tree (triggers.conditions DSL).
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    action_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # JSON object — the free-form envelope each action kind validates.
    action_params: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    cooldown_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def to_dict(self) -> dict[str, Any]:
        import json

        def _load(raw: str | None, default: Any) -> Any:
            try:
                return json.loads(raw) if raw else default
            except (TypeError, ValueError):
                return default

        return {
            "id": self.id,
            "name": self.name,
            "events": _load(self.events, []),
            "condition": _load(self.condition, {}),
            "action_kind": self.action_kind,
            "action_params": _load(self.action_params, {}),
            "cooldown_minutes": self.cooldown_minutes,
            "enabled": bool(self.enabled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TriggerRunRow(Base):
    """One evaluation of a trigger against one event — audit + idempotency record."""

    __tablename__ = "trigger_runs"
    __table_args__ = (
        # The idempotency guard: a redelivered event (same trigger + event_ref)
        # can only ever be handled once.
        UniqueConstraint(
            "trigger_id", "event_ref", name="uq_trigger_runs_trigger_event"
        ),
        # Cooldown lookup: latest fired run for a trigger.
        Index("ix_trigger_runs_trigger_created", "trigger_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # Deliberately not a hard FK (matches alert_history.rule_id): the definition
    # may be deleted while its audit history stays readable.
    trigger_id: Mapped[str] = mapped_column(String(32), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    event_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    action_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # JSON object — what the action handler returned (or the error).
    action_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        import json

        try:
            result = json.loads(self.action_result) if self.action_result else None
        except (TypeError, ValueError):
            result = None
        return {
            "id": self.id,
            "trigger_id": self.trigger_id,
            "event_kind": self.event_kind,
            "event_ref": self.event_ref,
            "status": self.status,
            "action_kind": self.action_kind,
            "action_result": result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
