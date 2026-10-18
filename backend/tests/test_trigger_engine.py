"""P4-1 trigger engine: idempotency, cooldown, audit and alert.dispatch.

The condition DSL is pinned in test_trigger_conditions.py; this suite pins what
the engine does around it — that a redelivered event fires once, that a cooldown
window suppresses a second firing, that every decision lands in trigger_runs as
an audit row, and that ``alert.dispatch`` writes a durable alert.
"""
from __future__ import annotations

import json
from typing import Any

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert_rule import AlertHistory
from app.models.trigger import TriggerDefinitionRow, TriggerRunRow
from app.services.triggers import (
    CONDITION_FALSE,
    COOLDOWN,
    DUPLICATE,
    ERROR,
    FIRED,
    handle_event,
    row_to_definition,
)

ORG = "org-trigger-test"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _mk_trigger(
    db: AsyncSession,
    *,
    name: str = "Runway alarm",
    events: list[str] | None = None,
    condition: dict[str, Any] | None = None,
    action_kind: str = "alert.dispatch",
    action_params: dict[str, Any] | None = None,
    cooldown_minutes: int = 60,
    enabled: bool = True,
    org_id: str = ORG,
) -> TriggerDefinitionRow:
    row = TriggerDefinitionRow(
        org_id=org_id,
        name=name,
        events=json.dumps(events or ["job.completed"]),
        condition=json.dumps(
            condition
            or {"metric": "finance.runway_months", "op": "lt", "value": 3}
        ),
        action_kind=action_kind,
        action_params=json.dumps(action_params or {"severity": "critical"}),
        cooldown_minutes=cooldown_minutes,
        enabled=enabled,
    )
    db.add(row)
    await db.commit()
    return row


# ── fire ──────────────────────────────────────────────────────────────────────


async def test_fires_and_writes_alert_and_audit_run(db):
    await _mk_trigger(db)
    low_runway = {"finance.runway_months": 2.5}

    outcomes = await handle_event(
        db,
        org_id=ORG,
        event_kind="job.completed",
        event_ref="job-1",
        values=low_runway,
    )

    assert len(outcomes) == 1
    assert outcomes[0].status == FIRED
    assert outcomes[0].action_result["severity"] == "critical"

    # Durable alert written by alert.dispatch.
    alert = (await db.execute(select(AlertHistory))).scalar_one()
    assert alert.org_id == ORG
    assert alert.severity == "critical"
    assert alert.source.startswith("trigger:")

    # Audit row: fired, with the action result folded in.
    run = (await db.execute(select(TriggerRunRow))).scalar_one()
    assert run.status == FIRED
    assert run.event_kind == "job.completed"
    assert run.event_ref == "job-1"
    assert json.loads(run.action_result)["alert_id"] == alert.id


async def test_alert_dispatch_respects_message_and_severity(db):
    await _mk_trigger(
        db,
        action_params={"message": "Nakit 3 aydan az", "severity": "warning"},
    )
    await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    alert = (await db.execute(select(AlertHistory))).scalar_one()
    assert alert.message == "Nakit 3 aydan az"
    assert alert.severity == "warning"


# ── idempotency ───────────────────────────────────────────────────────────────


async def test_same_event_ref_fires_once(db):
    await _mk_trigger(db)
    values = {"finance.runway_months": 2.0}

    first = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-42",
        values=values,
    )
    second = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-42",
        values=values,
    )

    assert first[0].status == FIRED
    assert second[0].status == DUPLICATE

    runs = (await db.execute(select(TriggerRunRow))).scalars().all()
    assert len(runs) == 1
    alerts = (await db.execute(select(AlertHistory))).scalars().all()
    assert len(alerts) == 1


# ── cooldown ──────────────────────────────────────────────────────────────────


async def test_cooldown_suppresses_second_distinct_event(db):
    await _mk_trigger(db, cooldown_minutes=60)
    values = {"finance.runway_months": 2.0}

    first = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-a", values=values
    )
    second = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-b", values=values
    )

    assert first[0].status == FIRED
    assert second[0].status == COOLDOWN

    runs = (await db.execute(select(TriggerRunRow))).scalars().all()
    assert [r.status for r in sorted(runs, key=lambda r: r.created_at)] == [
        FIRED,
        COOLDOWN,
    ]
    # Only the firing produced an alert.
    assert len((await db.execute(select(AlertHistory))).scalars().all()) == 1


async def test_zero_cooldown_allows_immediate_refire(db):
    await _mk_trigger(db, cooldown_minutes=0)
    values = {"finance.runway_months": 2.0}

    first = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-a", values=values
    )
    second = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-b", values=values
    )

    assert first[0].status == FIRED
    assert second[0].status == FIRED
    assert len((await db.execute(select(AlertHistory))).scalars().all()) == 2


# ── condition misses ──────────────────────────────────────────────────────────


async def test_condition_false_records_audit_without_alert(db):
    await _mk_trigger(db)
    healthy = {"finance.runway_months": 18.0}

    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1", values=healthy
    )

    assert outcomes[0].status == CONDITION_FALSE
    assert (await db.execute(select(AlertHistory))).scalars().all() == []
    runs = (await db.execute(select(TriggerRunRow))).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == CONDITION_FALSE


async def test_missing_snapshot_never_fires(db):
    """No semantic snapshot → empty values → the comparison cannot hold."""
    await _mk_trigger(db)

    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1", values=None
    )

    assert outcomes[0].status == CONDITION_FALSE


# ── filtering ─────────────────────────────────────────────────────────────────


async def test_disabled_trigger_is_skipped(db):
    await _mk_trigger(db, enabled=False)
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes == []
    assert (await db.execute(select(TriggerRunRow))).scalars().all() == []


async def test_event_kind_mismatch_is_skipped(db):
    await _mk_trigger(db, events=["schedule"])
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes == []


async def test_only_matching_triggers_are_considered(db):
    await _mk_trigger(db, name="on schedule", events=["schedule"])
    await _mk_trigger(db, name="on job", events=["job.completed", "schedule"])

    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert [o.name for o in outcomes] == ["on job"]
    assert outcomes[0].status == FIRED


# ── action registry ───────────────────────────────────────────────────────────


async def test_unregistered_action_kind_reports_error(db):
    await _mk_trigger(db, action_kind="webhook.call")
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == ERROR
    assert "no handler" in outcomes[0].detail
    runs = (await db.execute(select(TriggerRunRow))).scalars().all()
    assert runs[0].status == ERROR


# ── row round-trip ────────────────────────────────────────────────────────────


async def test_row_to_definition_roundtrips_condition(db):
    condition = {
        "any": [
            {"metric": "finance.runway_months", "op": "lt", "value": 3},
            {"metric": "finance.critical_anomalies", "op": "gt", "value": 0},
        ]
    }
    row = await _mk_trigger(db, condition=condition, events=["schedule", "job.completed"])

    definition = row_to_definition(row)
    assert definition.name == "Runway alarm"
    assert set(definition.events) == {"schedule", "job.completed"}
    assert definition.action_kind == "alert.dispatch"
    assert definition.cooldown_minutes == 60
    # The parsed condition still evaluates the way the DSL promises.
    from app.services.triggers import evaluate

    assert evaluate(definition.condition, {"finance.runway_months": 2.0}) is True
    assert evaluate(definition.condition, {"finance.runway_months": 20.0}) is False
