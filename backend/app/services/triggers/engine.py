"""The P4-1 trigger engine — turn an event into (possibly) an action.

``handle_event`` is the single entry point an event source calls when something
happened (a job completed, a transaction arrived, a schedule tick):

1. Load the org's enabled ``trigger_definitions`` matching the event.
2. Evaluate each condition against a metric snapshot (``CompanySemanticSnapshot.values``).
3. **Idempotency** — skip any (trigger, event_ref) already handled (backed by a
   DB unique constraint, so a redelivered event can never fire twice).
4. **Cooldown** — skip if the trigger fired within ``cooldown_minutes``.
5. Dispatch the action through the registry and record a ``trigger_runs`` row
   (the audit trail: ``fired`` / ``cooldown`` / ``condition_false`` / ``error``).

The engine owns its transaction: it flushes its writes and commits at the end so
the audit/idempotency rows are durable for the next delivery of the same event.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trigger import TriggerDefinitionRow, TriggerRunRow
from app.services.triggers.actions import ACTION_REGISTRY
from app.services.triggers.conditions import evaluate, parse_condition
from app.services.triggers.contracts import ActionKind, EventKind, TriggerDefinition

logger = logging.getLogger(__name__)

# Statuses a trigger_runs row (and an outcome) can carry.
FIRED = "fired"
COOLDOWN = "cooldown"
CONDITION_FALSE = "condition_false"
ERROR = "error"
# Returned (not persisted) when the same event_ref was already handled.
DUPLICATE = "duplicate"


@dataclass(slots=True)
class TriggerRunOutcome:
    """What the engine decided for one trigger."""

    trigger_id: str
    name: str
    status: str
    run_id: str | None = None
    action_result: dict[str, Any] | None = None
    detail: str | None = None


def row_to_definition(row: TriggerDefinitionRow) -> TriggerDefinition:
    """Rehydrate the P4-0 envelope from its stored JSON columns."""
    return TriggerDefinition(
        name=row.name,
        events=json.loads(row.events),
        condition=parse_condition(json.loads(row.condition)),
        action_kind=cast(ActionKind, row.action_kind),
        action_params=json.loads(row.action_params) if row.action_params else {},
        cooldown_minutes=row.cooldown_minutes,
        enabled=row.enabled,
    )


async def handle_event(
    db: AsyncSession,
    *,
    org_id: str,
    event_kind: EventKind,
    event_ref: str,
    values: Mapping[str, float] | None = None,
    payload: dict[str, Any] | None = None,
) -> list[TriggerRunOutcome]:
    """Evaluate every enabled trigger for ``event_kind`` and act on the matches.

    ``values`` is the ``{metric_id: value}`` snapshot the conditions read; when
    omitted the latest semantic snapshot for the org is loaded. ``event_ref`` is
    an opaque caller-supplied idempotency key (e.g. the job id for
    ``job.completed``) — the same ref is processed at most once per trigger.
    """
    payload = payload or {}

    rows = (
        await db.execute(
            select(TriggerDefinitionRow).where(
                TriggerDefinitionRow.org_id == org_id,
                TriggerDefinitionRow.enabled.is_(True),
            )
        )
    ).scalars().all()
    matching = [r for r in rows if event_kind in json.loads(r.events)]
    if not matching:
        return []

    if values is None:
        values = await _load_values(db, org_id)

    outcomes = [
        await _handle_one(db, org_id, row, event_kind, event_ref, values, payload)
        for row in matching
    ]
    await db.commit()
    return outcomes


async def _handle_one(
    db: AsyncSession,
    org_id: str,
    row: TriggerDefinitionRow,
    event_kind: EventKind,
    event_ref: str,
    values: Mapping[str, float],
    payload: dict[str, Any],
) -> TriggerRunOutcome:
    trigger_id = row.id

    # 1. Idempotency: has this (trigger, event) already been decided?
    existing = (
        await db.execute(
            select(TriggerRunRow).where(
                TriggerRunRow.trigger_id == trigger_id,
                TriggerRunRow.event_ref == event_ref,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return TriggerRunOutcome(
            trigger_id,
            row.name,
            DUPLICATE,
            run_id=existing.id,
            detail=f"already handled by run {existing.id}",
        )

    definition = row_to_definition(row)

    # 2. Condition.
    if not evaluate(definition.condition, values):
        run = await _record(
            db, org_id, trigger_id, event_kind, event_ref, CONDITION_FALSE, definition
        )
        return TriggerRunOutcome(
            trigger_id,
            row.name,
            CONDITION_FALSE,
            run_id=run.id,
            detail="condition did not hold",
        )

    # 3. Cooldown.
    cooldown_info = await _in_cooldown(db, trigger_id, definition.cooldown_minutes)
    if cooldown_info is not None:
        run = await _record(
            db,
            org_id,
            trigger_id,
            event_kind,
            event_ref,
            COOLDOWN,
            definition,
            detail=cooldown_info,
        )
        return TriggerRunOutcome(
            trigger_id, row.name, COOLDOWN, run_id=run.id, detail=cooldown_info
        )

    # 4. Dispatch.
    handler = ACTION_REGISTRY.get(definition.action_kind)
    if handler is None:
        detail = f"no handler registered for action_kind={definition.action_kind!r}"
        run = await _record(
            db,
            org_id,
            trigger_id,
            event_kind,
            event_ref,
            ERROR,
            definition,
            action_result={"error": detail},
            detail=detail,
        )
        return TriggerRunOutcome(
            trigger_id, row.name, ERROR, run_id=run.id, detail=detail
        )

    try:
        result = await handler(db, org_id, definition, payload)
    except Exception as exc:
        logger.exception(
            "trigger %s action %s failed", trigger_id, definition.action_kind
        )
        detail = f"{type(exc).__name__}: {exc}"
        run = await _record(
            db,
            org_id,
            trigger_id,
            event_kind,
            event_ref,
            ERROR,
            definition,
            action_result={"error": detail},
            detail=detail,
        )
        return TriggerRunOutcome(
            trigger_id, row.name, ERROR, run_id=run.id, detail=detail
        )

    run = await _record(
        db,
        org_id,
        trigger_id,
        event_kind,
        event_ref,
        FIRED,
        definition,
        action_result=result,
    )
    return TriggerRunOutcome(
        trigger_id, row.name, FIRED, run_id=run.id, action_result=result
    )


async def _load_values(db: AsyncSession, org_id: str) -> dict[str, Any]:
    """Latest semantic snapshot's ``{metric_id: value}`` (empty if none yet)."""
    from app.services.semantic.store import get_latest_semantic_snapshot

    snapshot = await get_latest_semantic_snapshot(org_id, db)
    return snapshot.values() if snapshot is not None else {}


async def _in_cooldown(
    db: AsyncSession, trigger_id: str, cooldown_minutes: int
) -> str | None:
    """Return a cooldown reason if the trigger fired within the window, else None."""
    if cooldown_minutes <= 0:
        return None
    last_fired = (
        await db.execute(
            select(TriggerRunRow)
            .where(
                TriggerRunRow.trigger_id == trigger_id,
                TriggerRunRow.status == FIRED,
            )
            .order_by(TriggerRunRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_fired is None or last_fired.created_at is None:
        return None
    fired_at = last_fired.created_at
    if fired_at.tzinfo is None:  # SQLite CURRENT_TIMESTAMP is naive UTC
        fired_at = fired_at.replace(tzinfo=UTC)
    elapsed = datetime.now(UTC) - fired_at
    window = timedelta(minutes=cooldown_minutes)
    if elapsed < window:
        remaining = int((window - elapsed).total_seconds())
        return f"fired {int(elapsed.total_seconds())}s ago; cooldown {cooldown_minutes}m ({remaining}s left)"
    return None


async def _record(
    db: AsyncSession,
    org_id: str,
    trigger_id: str,
    event_kind: str,
    event_ref: str,
    status: str,
    definition: TriggerDefinition,
    *,
    action_result: dict[str, Any] | None = None,
    detail: str | None = None,
) -> TriggerRunRow:
    """Persist one audit row (and fold ``detail`` into the result JSON)."""
    if detail is not None:
        action_result = {**(action_result or {}), "detail": detail}
    run = TriggerRunRow(
        org_id=org_id,
        trigger_id=trigger_id,
        event_kind=event_kind,
        event_ref=event_ref,
        status=status,
        action_kind=definition.action_kind,
        action_result=json.dumps(action_result) if action_result else None,
    )
    db.add(run)
    await db.flush()
    return run
