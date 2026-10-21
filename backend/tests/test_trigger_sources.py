"""P4-3 event sources: real events reach the trigger engine, once, safely.

The engine suite pins what ``handle_event`` does with an event; this suite pins
that the two seams which *emit* events deliver them the way the engine promises:

- ``job.completed`` projects metrics from the very dashboard the analysis
  persisted (same projector the semantic snapshot uses, so units agree),
- ``tx.arrived`` evaluates against the org's latest semantic snapshot and stays
  silent when nothing arrived,
- event_ref is the job id, so the engine's ``(trigger, event_ref)`` uniqueness
  turns a worker-then-approval continuation (or an ARQ retry) into one firing,
  not two,
- ``anomaly.detected`` fires per distinct set of findings (a rescan that finds
  the same anomalies is a duplicate) and ``schedule`` fires once per UTC day,
- every ``EventKind`` in the contract has an emitter, so no rule can be built
  on an event nothing ever sends.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert_rule import AlertHistory
from app.models.trigger import TriggerDefinitionRow, TriggerRunRow
from app.services.semantic.store import save_semantic_snapshot
from app.services.semantic.types import CompanySemanticSnapshot, MetricPoint, Period
from app.services.triggers import COOLDOWN, DUPLICATE, FIRED
from app.services.triggers.contracts import EventKind
from app.services.triggers.sources import (
    emit_anomaly_detected,
    emit_job_completed,
    emit_job_events,
    emit_schedule_tick,
    emit_tx_arrived,
)

ORG = "org-trigger-src"

# A dashboard whose base-scenario runway is 2.5 months — the value a
# `finance.runway_months lt 3` condition is built to catch.
DASH_LOW_RUNWAY = {"forecast": {"scenarios": {"base": {"runway_months": 2.5}}}}
DASH_SAFE_RUNWAY = {"forecast": {"scenarios": {"base": {"runway_months": 12.0}}}}


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
    events: list[str] | None = None,
    condition: dict[str, Any] | None = None,
    action_kind: str = "alert.dispatch",
    action_params: dict[str, Any] | None = None,
    cooldown_minutes: int = 0,
    org_id: str = ORG,
) -> TriggerDefinitionRow:
    row = TriggerDefinitionRow(
        org_id=org_id,
        name="Runway alarm",
        events=json.dumps(events or ["job.completed"]),
        condition=json.dumps(
            condition or {"metric": "finance.runway_months", "op": "lt", "value": 3}
        ),
        action_kind=action_kind,
        action_params=json.dumps(action_params or {"severity": "critical"}),
        cooldown_minutes=cooldown_minutes,
        enabled=True,
    )
    db.add(row)
    await db.commit()
    return row


async def _runs(db: AsyncSession) -> list[TriggerRunRow]:
    return list(
        (
            await db.execute(
                select(TriggerRunRow).order_by(TriggerRunRow.created_at)
            )
        ).scalars()
    )


# ── job.completed ─────────────────────────────────────────────────────────────


async def test_job_completed_projects_metrics_and_fires(db):
    await _mk_trigger(db)

    await emit_job_completed(
        db, job_id="job-1", org_id=ORG, dashboard=DASH_LOW_RUNWAY
    )

    alert = (await db.execute(select(AlertHistory))).scalar_one()
    assert alert.org_id == ORG
    assert alert.severity == "critical"
    assert alert.source.startswith("trigger:")

    (run,) = await _runs(db)
    assert run.status == FIRED
    assert run.event_kind == "job.completed"
    assert run.event_ref == "job-1"


async def test_job_completed_condition_false_on_safe_runway(db):
    await _mk_trigger(db)

    await emit_job_completed(
        db, job_id="job-2", org_id=ORG, dashboard=DASH_SAFE_RUNWAY
    )

    assert (await db.execute(select(AlertHistory))).scalar_one_or_none() is None
    (run,) = await _runs(db)
    assert run.status == "condition_false"


async def test_job_completed_sees_lira_to_cents_projection(db):
    """Revenue is lira on the wire and cents in the catalog — the projector's
    boundary, so a trigger on `finance.revenue` compares catalog units."""
    await _mk_trigger(
        db,
        condition={"metric": "finance.revenue", "op": "lt", "value": 100},
    )

    await emit_job_completed(
        db,
        job_id="job-3",
        org_id=ORG,
        dashboard={"pnl": {"revenue": 50.0}},  # 50 lira → 5000 cents
    )

    (run,) = await _runs(db)
    assert run.status == "condition_false"  # 5000 cents is not < 100


async def test_job_completed_fires_once_per_job_across_redelivery(db):
    """Worker then review-approval both emit; the job id keys uniqueness."""
    await _mk_trigger(db)

    first = await emit_job_completed(
        db, job_id="job-4", org_id=ORG, dashboard=DASH_LOW_RUNWAY
    )
    second = await emit_job_completed(
        db, job_id="job-4", org_id=ORG, dashboard=DASH_LOW_RUNWAY
    )

    assert first[0].status == FIRED
    assert second[0].status == DUPLICATE
    # One firing means one durable alert and one audit row, not two.
    assert len((await db.execute(select(AlertHistory))).scalars().all()) == 1
    assert len(await _runs(db)) == 1


async def test_job_completed_respects_cooldown_window(db):
    await _mk_trigger(db, cooldown_minutes=60)

    await emit_job_completed(
        db, job_id="job-5", org_id=ORG, dashboard=DASH_LOW_RUNWAY
    )
    await emit_job_completed(
        db, job_id="job-6", org_id=ORG, dashboard=DASH_LOW_RUNWAY
    )

    runs = await _runs(db)
    assert [r.status for r in runs] == [FIRED, COOLDOWN]


async def test_job_completed_empty_dashboard_evaluates_not_crashes(db):
    await _mk_trigger(db)

    await emit_job_completed(db, job_id="job-7", org_id=ORG, dashboard=None)

    (run,) = await _runs(db)
    assert run.status == "condition_false"  # no runway value → condition can't hold


async def test_job_completed_ignores_other_orgs_rules(db):
    await _mk_trigger(db, org_id="org-someone-else")

    await emit_job_completed(
        db, job_id="job-8", org_id=ORG, dashboard=DASH_LOW_RUNWAY
    )

    assert await _runs(db) == []


# ── tx.arrived ────────────────────────────────────────────────────────────────


async def _seed_snapshot(db: AsyncSession, *, runway: float) -> None:
    await save_semantic_snapshot(
        CompanySemanticSnapshot(
            org_id=ORG,
            period=Period(key="2026-09"),
            currency="USD",
            locale="tr-TR",
            metrics=[
                MetricPoint(
                    metric_id="finance.runway_months", value=runway, unit="months"
                )
            ],
            source_job_ids=["seed"],
        ),
        db,
    )
    await db.commit()


async def _seed_transactions(db: AsyncSession, job_id: str, n: int) -> None:
    from app.models.transaction import Transaction, TransactionType

    for i in range(n):
        db.add(
            Transaction(
                job_id=job_id,
                amount_kurus=100,
                currency="USD",
                type=TransactionType.EXPENSE,
                category="other_expense",
                description=f"tx {i}",
                transaction_date=datetime(2026, 9, 15, tzinfo=UTC),
            )
        )
    await db.commit()


async def test_tx_arrived_fires_against_latest_snapshot(db):
    from app.models.transaction import Transaction, TransactionType

    await _mk_trigger(db, events=["tx.arrived"])
    await _seed_snapshot(db, runway=2.0)
    db.add(
        Transaction(
            job_id="job-t1", amount_kurus=100, currency="USD",
            type=TransactionType.EXPENSE, category="other_expense",
            description="kira", transaction_date=datetime(2026, 9, 15, tzinfo=UTC),
        )
    )
    await db.commit()

    await emit_tx_arrived(db, job_id="job-t1", org_id=ORG)

    (run,) = await _runs(db)
    assert run.status == FIRED
    assert run.event_kind == "tx.arrived"
    assert json.loads(run.action_result or "{}")["severity"] == "critical"


async def test_tx_arrived_condition_false_when_snapshot_is_healthy(db):
    await _mk_trigger(db, events=["tx.arrived"])
    await _seed_snapshot(db, runway=24.0)
    await _seed_transactions(db, "job-t2", 2)

    await emit_tx_arrived(db, job_id="job-t2", org_id=ORG)

    (run,) = await _runs(db)
    assert run.status == "condition_false"


async def test_tx_arrived_skips_when_no_transactions(db):
    await _mk_trigger(db, events=["tx.arrived"])
    await _seed_snapshot(db, runway=2.0)

    await emit_tx_arrived(db, job_id="job-t3", org_id=ORG)

    # "Nothing arrived" is not an event: no evaluation, no audit row.
    assert await _runs(db) == []


async def test_tx_arrived_is_idempotent_per_job(db):
    await _mk_trigger(db, events=["tx.arrived"])
    await _seed_snapshot(db, runway=2.0)
    await _seed_transactions(db, "job-t4", 1)

    first = await emit_tx_arrived(db, job_id="job-t4", org_id=ORG)
    second = await emit_tx_arrived(db, job_id="job-t4", org_id=ORG)

    assert first[0].status == FIRED
    assert second[0].status == DUPLICATE
    assert len(await _runs(db)) == 1


# ── anomaly.detected ──────────────────────────────────────────────────────────


async def _seed_anomalies(
    db: AsyncSession, job_id: str, findings: list[tuple[str, str, str]]
) -> None:
    from app.models.anomaly import Anomaly

    for anomaly_type, severity, title in findings:
        db.add(
            Anomaly(
                job_id=job_id,
                anomaly_type=anomaly_type,
                severity=severity,
                title=title,
                description=title,
            )
        )
    await db.commit()


async def _clear_anomalies(db: AsyncSession, job_id: str) -> None:
    from app.models.anomaly import Anomaly

    for row in (
        await db.execute(select(Anomaly).where(Anomaly.job_id == job_id))
    ).scalars():
        await db.delete(row)
    await db.commit()


async def test_anomaly_detected_payload_reaches_the_action(db, monkeypatch):
    seen: dict[str, Any] = {}

    async def _capture(_db, _org, _definition, payload):
        seen.update(payload)
        return {"ok": True}

    from app.services.triggers import actions

    monkeypatch.setitem(actions.ACTION_REGISTRY, "alert.dispatch", _capture)
    await _mk_trigger(db, events=["anomaly.detected"])
    await _seed_snapshot(db, runway=2.0)
    await _seed_anomalies(db, "job-a2", [
        ("duplicate", "high", "A"),
        ("unusual_amount", "critical", "B"),
        ("round_number", "high", "C"),
    ])

    (outcome,) = await emit_anomaly_detected(db, job_id="job-a2", org_id=ORG)

    assert outcome.status == FIRED
    assert seen == {
        "job_id": "job-a2",
        "anomaly_count": 3,
        "by_severity": {"critical": 1, "high": 2},
    }


async def test_anomaly_detected_skips_when_no_anomalies(db):
    await _mk_trigger(db, events=["anomaly.detected"])
    await _seed_snapshot(db, runway=2.0)

    assert await emit_anomaly_detected(db, job_id="job-a3", org_id=ORG) == []
    assert await _runs(db) == []


async def test_anomaly_rescan_with_same_findings_is_duplicate(db):
    """A rescan deletes and re-inserts rows (new ids) — same findings, one event."""
    await _mk_trigger(db, events=["anomaly.detected"])
    await _seed_snapshot(db, runway=2.0)
    findings = [("duplicate", "high", "Mükerrer ödeme")]
    await _seed_anomalies(db, "job-a4", findings)
    first = await emit_anomaly_detected(db, job_id="job-a4", org_id=ORG)

    await _clear_anomalies(db, "job-a4")
    await _seed_anomalies(db, "job-a4", findings)
    second = await emit_anomaly_detected(db, job_id="job-a4", org_id=ORG)

    assert first[0].status == FIRED
    assert second[0].status == DUPLICATE
    assert len(await _runs(db)) == 1


async def test_anomaly_rescan_with_new_findings_is_a_new_event(db):
    await _mk_trigger(db, events=["anomaly.detected"])
    await _seed_snapshot(db, runway=2.0)
    await _seed_anomalies(db, "job-a5", [("duplicate", "high", "A")])
    await emit_anomaly_detected(db, job_id="job-a5", org_id=ORG)

    await _seed_anomalies(db, "job-a5", [("expense_spike", "critical", "B")])
    await emit_anomaly_detected(db, job_id="job-a5", org_id=ORG)

    runs = await _runs(db)
    assert [r.status for r in runs] == [FIRED, FIRED]
    assert runs[0].event_ref != runs[1].event_ref


async def test_job_events_seam_includes_anomaly_detected(db):
    """The worker/approval seam emits anomaly.detected alongside the others."""
    await _mk_trigger(db, events=["anomaly.detected"])
    await _seed_snapshot(db, runway=2.0)
    await _seed_anomalies(db, "job-a6", [("duplicate", "high", "A")])

    outcomes = await emit_job_events(
        db, job_id="job-a6", org_id=ORG, dashboard=None
    )

    assert [o.status for o in outcomes] == [FIRED]
    (run,) = await _runs(db)
    assert run.event_kind == "anomaly.detected"


# ── schedule ──────────────────────────────────────────────────────────────────


DAY1 = datetime(2026, 10, 21, 0, 10, tzinfo=UTC)
DAY1_LATER = datetime(2026, 10, 21, 13, 10, tzinfo=UTC)
DAY2 = datetime(2026, 10, 22, 0, 10, tzinfo=UTC)


async def test_schedule_fires_once_per_utc_day(db):
    await _mk_trigger(db, events=["schedule"])
    await _seed_snapshot(db, runway=2.0)

    first = await emit_schedule_tick(db, now=DAY1)
    later_same_day = await emit_schedule_tick(db, now=DAY1_LATER)
    next_day = await emit_schedule_tick(db, now=DAY2)

    assert [o.status for o in first] == [FIRED]
    assert [o.status for o in later_same_day] == [DUPLICATE]
    assert [o.status for o in next_day] == [FIRED]
    assert [r.event_ref for r in await _runs(db)] == [
        "schedule:2026-10-21",
        "schedule:2026-10-22",
    ]


async def test_schedule_evaluates_condition_against_latest_snapshot(db):
    await _mk_trigger(db, events=["schedule"])
    await _seed_snapshot(db, runway=24.0)

    (outcome,) = await emit_schedule_tick(db, now=DAY1)

    assert outcome.status == "condition_false"


async def test_schedule_only_touches_orgs_with_schedule_rules(db):
    await _mk_trigger(db, events=["job.completed"])  # ORG: not a schedule rule
    await _mk_trigger(db, events=["schedule"], org_id="org-scheduled")

    outcomes = await emit_schedule_tick(db, now=DAY1)

    (run,) = await _runs(db)
    assert run.org_id == "org-scheduled"
    assert len(outcomes) == 1


async def test_schedule_skips_disabled_rules(db):
    row = await _mk_trigger(db, events=["schedule"])
    row.enabled = False
    await db.commit()

    assert await emit_schedule_tick(db, now=DAY1) == []


def test_scheduler_registers_the_schedule_tick():
    """The emitter has a door: the app's scheduler calls it hourly."""
    from app import scheduler as sched

    sched._scheduler = None
    try:
        job = sched.get_scheduler().get_job("trigger_schedule_tick")
        assert job is not None
    finally:
        sched._scheduler = None


# ── contract ↔ source parity ──────────────────────────────────────────────────


def test_every_event_kind_has_an_emitter():
    """A kind in ``EventKind`` with no ``event_kind="…"`` emitter in sources.py
    would let users build rules that can never fire — fail instead."""
    import app.services.triggers.sources as sources

    text = Path(sources.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r'event_kind="([^"]+)"', text))
    assert emitted == set(get_args(EventKind))
