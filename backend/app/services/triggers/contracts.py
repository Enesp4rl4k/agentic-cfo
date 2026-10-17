"""Trigger engine contracts (P4-0) — the envelope the P4-1 engine implements.

Storage (trigger_definition / trigger_run tables), the action registry and
the /tetikler router land in P4-1 against these types; this module pins the
shape now so the API, the DB row and the evaluator agree from day one.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.triggers.conditions import Condition

ActionKind = Literal[
    "alert.dispatch",
    "analysis.start",
    "cascade.simulate",
    "report.generate",
    "webhook.call",
]

EventKind = Literal["job.completed", "tx.arrived", "anomaly.detected", "schedule"]


class TriggerDefinition(BaseModel):
    """A stored rule: on `events`, if `condition` holds → run `action_kind`.

    `action_params` is a free-form envelope in P4-0; each action kind
    validates its own payload inside the P4-1 registry (deliberate layering,
    not an oversight). Idempotency and audit live on trigger_run rows, also
    P4-1.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    events: list[EventKind] = Field(min_length=1)
    condition: Condition
    action_kind: ActionKind
    action_params: dict[str, Any] = Field(default_factory=dict)
    cooldown_minutes: int = Field(default=60, ge=0, le=43_200)  # ≤ 30 gün
    enabled: bool = True
