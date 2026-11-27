"""Trigger engine + action registry: idempotency, cooldown, audit, all five kinds.

The condition DSL is pinned in test_trigger_conditions.py; this suite pins what
the engine does around it — that a redelivered event fires once, that a cooldown
window suppresses a second firing, that every decision lands in trigger_runs as
an audit row, and that each ``ActionKind`` runs (or fails) the way its handler
promises.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import clock
from app.models.alert_rule import AlertHistory
from app.models.analysis_job import AnalysisJob
from app.models.outbox_message import OutboxMessage
from app.models.report import Report, ReportFormat, ReportType
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
from app.services.triggers.actions import ACTION_REGISTRY
from tests.db_helpers import gecici_oturum

ORG = "org-trigger-test"


@pytest_asyncio.fixture
async def db():
    async with gecici_oturum() as session:
        yield session


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



# The cooldown compares the stamp of the last firing (written by the row's insert) with "now". Both must come
# from the application clock: with a database-stamped created_at the real time stood next to the pinned time, the
# difference was negative, and the cooldown looked active forever (these tests used to pass vacuously).
T0 = clock.TEST_INSTANT


async def _fire(db, ref: str) -> str:
    out = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref=ref, values={"finance.runway_months": 2.0}
    )
    return out[0].status


async def test_the_firing_is_stamped_by_the_application_clock(db):
    await _mk_trigger(db, cooldown_minutes=60)
    clock.pin(T0, tick=False)
    assert await _fire(db, "job-a") == FIRED
    run = (await db.execute(select(TriggerRunRow))).scalars().one()
    assert run.created_at.replace(tzinfo=None) == T0.replace(tzinfo=None)
    alert = (await db.execute(select(AlertHistory))).scalars().one()
    assert alert.created_at.replace(tzinfo=None) == T0.replace(tzinfo=None)


async def test_cooldown_suppresses_inside_the_window(db):
    await _mk_trigger(db, cooldown_minutes=60)
    clock.pin(T0, tick=False)
    assert await _fire(db, "job-a") == FIRED
    clock.pin(T0 + timedelta(minutes=59, seconds=59), tick=False)
    assert await _fire(db, "job-b") == COOLDOWN
    clock.pin(T0 + timedelta(minutes=60) - timedelta(microseconds=1), tick=False)
    assert await _fire(db, "job-c") == COOLDOWN


async def test_cooldown_ends_exactly_at_the_window_edge(db):
    await _mk_trigger(db, cooldown_minutes=60)
    clock.pin(T0, tick=False)
    assert await _fire(db, "job-a") == FIRED
    clock.pin(T0 + timedelta(minutes=60), tick=False)  # elapsed == window: no longer cooling down
    assert await _fire(db, "job-b") == FIRED


async def test_trigger_refires_after_the_window_and_the_new_firing_restarts_it(db):
    await _mk_trigger(db, cooldown_minutes=60)
    clock.pin(T0, tick=False)
    assert await _fire(db, "job-a") == FIRED
    clock.pin(T0 + timedelta(hours=2), tick=False)
    assert await _fire(db, "job-b") == FIRED
    clock.pin(T0 + timedelta(hours=2, minutes=30), tick=False)  # inside the window of the SECOND firing
    assert await _fire(db, "job-c") == COOLDOWN
    assert len((await db.execute(select(AlertHistory))).scalars().all()) == 2


async def test_cooldown_does_not_depend_on_the_real_date(db):
    """The suite runs at fixed instants years from the real date; the cooldown must behave the same."""
    await _mk_trigger(db, cooldown_minutes=60)
    for start in (clock.parse_instant("2024-02-29T23:59:30Z"), clock.parse_instant("2031-01-01T00:00:30Z")):
        await db.execute(TriggerRunRow.__table__.delete())
        await db.commit()
        clock.pin(start, tick=False)
        assert await _fire(db, f"a-{start.year}") == FIRED
        clock.pin(start + timedelta(minutes=30), tick=False)
        assert await _fire(db, f"b-{start.year}") == COOLDOWN
        clock.pin(start + timedelta(minutes=61), tick=False)
        assert await _fire(db, f"c-{start.year}") == FIRED

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


async def test_unregistered_action_kind_reports_error(db, monkeypatch):
    # Every ActionKind now has a handler, so drop one from the registry to keep
    # the engine's "no handler" branch honest (a partial deployment can ship
    # contracts ahead of handlers).
    monkeypatch.delitem(ACTION_REGISTRY, "report.generate")
    await _mk_trigger(db, action_kind="report.generate")
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == ERROR
    assert "no handler" in outcomes[0].detail
    runs = (await db.execute(select(TriggerRunRow))).scalars().all()
    assert runs[0].status == ERROR


# ── P4-2 actions ──────────────────────────────────────────────────────────────


async def test_webhook_call_is_queued_in_the_outbox_not_sent(db):
    await _mk_trigger(
        db, action_kind="webhook.call",
        action_params={"url": "https://dummy-webhook"},
    )
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0}, payload={"message": "hi"},
    )
    assert outcomes[0].status == FIRED
    result = outcomes[0].action_result
    # The run says what it knows: queued. It does not claim a delivery it did not see.
    assert result["queued"] is True and "delivered" not in result
    row = (await db.execute(select(OutboxMessage))).scalar_one()
    assert (row.channel, row.status, row.id) == ("webhook", "pending", result["outbox_id"])


async def test_webhook_call_requires_url(db):
    await _mk_trigger(db, action_kind="webhook.call", action_params={})
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == ERROR
    assert "action_params.url" in outcomes[0].detail


async def test_analysis_start_enqueues_job_id_from_payload(db, monkeypatch):
    calls: list[str | None] = []

    async def _fake_enqueue(job_id: str, budget_input=None):
        calls.append(job_id)
        return "queued"

    monkeypatch.setattr("app.worker.enqueue_analysis", _fake_enqueue)
    await _mk_trigger(db, action_kind="analysis.start", action_params={})

    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-99",
        values={"finance.runway_months": 1.0}, payload={"job_id": "job-99"},
    )
    assert outcomes[0].status == FIRED
    assert calls == ["job-99"]
    assert outcomes[0].action_result["job_id"] == "job-99"
    assert outcomes[0].action_result["dispatch"] == "queued"


async def test_analysis_start_requires_job_id(db):
    await _mk_trigger(db, action_kind="analysis.start", action_params={})
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == ERROR
    assert "job_id" in outcomes[0].detail


async def test_cascade_simulate_runs_and_returns_scenario(db, monkeypatch):
    class _FakeCtx:
        last_cfo_result = {
            "dashboard": {
                "pnl": {"net_profit": -100_000.0, "revenue": 1_200_000.0, "total_opex": 1_300_000.0},
                "cashflow": {"runway_months": 2.0},
                "forecast": {},
            }
        }
        last_chro_result: dict[str, Any] = {}
        last_cto_result: dict[str, Any] = {}
        last_cmo_result: dict[str, Any] = {}
        last_coo_result: dict[str, Any] = {}

    async def _fake_ctx(org_id: str, db=None):
        return _FakeCtx()

    monkeypatch.setattr("app.services.company_context.get_company_context", _fake_ctx)
    await _mk_trigger(
        db, action_kind="cascade.simulate",
        action_params={"trigger": "cash_crisis", "runway_months": 2.0},
    )

    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == FIRED
    result = outcomes[0].action_result
    assert result["trigger"] == "cash_crisis"
    assert isinstance(result["result"], dict) and result["result"]


async def test_cascade_simulate_without_the_inputs_returns_unavailable_not_a_made_up_run(db, monkeypatch):
    class _EmptyCtx:
        last_cfo_result: dict[str, Any] = {}
        last_chro_result = last_cto_result = last_cmo_result = last_coo_result = None

    async def _fake_ctx(org_id: str, db=None):
        return _EmptyCtx()

    monkeypatch.setattr("app.services.company_context.get_company_context", _fake_ctx)
    await _mk_trigger(
        db, action_kind="cascade.simulate",
        action_params={"trigger": "cash_crisis", "runway_months": 2.0},
    )
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    result = outcomes[0].action_result
    assert result["result"] is None and result["unavailable"]


async def test_cascade_simulate_rejects_unknown_trigger(db):
    await _mk_trigger(
        db, action_kind="cascade.simulate", action_params={"trigger": "nope"}
    )
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == ERROR
    assert "unknown cascade trigger" in outcomes[0].detail


async def _seed_job_with_dashboard(
    db: AsyncSession, job_id: str = "job-r1", *, org_id: str = ORG
) -> None:
    db.add(
        AnalysisJob(
            id=job_id,
            filename="upload.pdf",
            file_path="/tmp/upload.pdf",
            file_type="pdf",
            org_id=org_id,
        )
    )
    await db.flush()
    db.add(
        Report(
            job_id=job_id,
            report_type=ReportType.FULL,
            report_format=ReportFormat.JSON,
            data={"cashflow": {"runway_months": 5.0}},
        )
    )
    await db.flush()


async def test_report_generate_writes_pdf_and_report_row(db, tmp_path, monkeypatch):
    await _seed_job_with_dashboard(db)

    def _fake_pdf(dashboard: dict[str, Any], company_name: str, period: str | None):
        assert dashboard["cashflow"]["runway_months"] == 5.0
        assert company_name == "Acme"
        assert period == "2026-09"
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(
        "app.services.executive_report_pdf.generate_executive_report", _fake_pdf
    )
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))
    await _mk_trigger(
        db,
        action_kind="report.generate",
        action_params={
            "job_id": "job-r1",
            "company_name": "Acme",
            "period": "2026-09",
        },
    )

    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-r1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == FIRED
    result = outcomes[0].action_result
    expected = tmp_path / "reports" / "job-r1" / "executive_report.pdf"
    assert result["file_path"] == str(expected)
    assert result["bytes"] == 13
    assert expected.read_bytes() == b"%PDF-1.4 fake"

    pdf_rows = (
        await db.execute(
            select(Report).where(Report.report_format == ReportFormat.PDF)
        )
    ).scalars().all()
    assert len(pdf_rows) == 1
    assert pdf_rows[0].job_id == "job-r1"
    assert pdf_rows[0].file_path == str(expected)


async def test_report_generate_takes_job_id_from_payload(db, tmp_path, monkeypatch):
    await _seed_job_with_dashboard(db, job_id="job-r2")
    monkeypatch.setattr(
        "app.services.executive_report_pdf.generate_executive_report",
        lambda *_args, **_kw: b"%PDF-1.4 fake",
    )
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))
    await _mk_trigger(db, action_kind="report.generate", action_params={})

    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-r2",
        values={"finance.runway_months": 1.0}, payload={"job_id": "job-r2"},
    )
    assert outcomes[0].status == FIRED
    assert outcomes[0].action_result["job_id"] == "job-r2"


async def test_report_generate_requires_job_id(db):
    await _mk_trigger(db, action_kind="report.generate", action_params={})
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-1",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == ERROR
    assert "job_id" in outcomes[0].detail


async def test_report_generate_rejects_foreign_org_job(db):
    await _seed_job_with_dashboard(db, job_id="job-other", org_id="org-someone-else")
    await _mk_trigger(
        db, action_kind="report.generate", action_params={"job_id": "job-other"}
    )
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-other",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == ERROR
    assert "no analysis job" in outcomes[0].detail


async def test_report_generate_requires_dashboard_json(db):
    db.add(
        AnalysisJob(
            id="job-bare",
            filename="upload.pdf",
            file_path="/tmp/upload.pdf",
            file_type="pdf",
            org_id=ORG,
        )
    )
    await db.flush()
    await _mk_trigger(
        db, action_kind="report.generate", action_params={"job_id": "job-bare"}
    )
    outcomes = await handle_event(
        db, org_id=ORG, event_kind="job.completed", event_ref="job-bare",
        values={"finance.runway_months": 1.0},
    )
    assert outcomes[0].status == ERROR
    assert "no dashboard JSON" in outcomes[0].detail


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
