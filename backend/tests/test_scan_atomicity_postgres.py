"""The hourly KRI scan's slot/retry guarantees on a real Postgres (SAVEPOINT release semantics differ from SQLite).

Runs only where `DATABASE_URL_OVERRIDE` is a Postgres URL over a migrated schema: the "Migrations on Postgres" CI job
(it applies the migrations first). Everywhere else it is skipped; the same behaviour is covered on SQLite in
`test_scheduled_job_atomicity.py`. Nothing leaves the process: delivery is stubbed; org ids are unique per run.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

import app.database as database
from app import scheduler
from app.agents.orchestration.proactive_alerts import ProactiveAlertOrchestrator
from app.models.in_app_notification import InAppNotification
from app.models.job_run import DONE, FAILED, ScheduledJobRun
from app.models.outbox_message import OutboxMessage
from app.models.proactive_alert import ProactiveAlert
from app.services import outbox

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_OVERRIDE", "").startswith("postgresql"),
    reason="needs the Postgres service of the migrations job",
)

NOW = datetime(2025, 2, 3, 9, 20, tzinfo=UTC)


async def test_one_org_failing_fails_the_slot_and_the_retry_completes_it_once(monkeypatch):
    a, b = f"pg-a-{uuid.uuid4().hex[:8]}", f"pg-b-{uuid.uuid4().hex[:8]}"
    state = {"a_fails": True}

    async def orgs(self):
        return [a, b]

    async def kris(self, org_id):
        if org_id == a and state["a_fails"]:
            raise RuntimeError("KRI computation failed")
        return {"posture": {"red_kris": [{"name": "Nakit", "current_value": 1, "unit": "ay"}]}}

    async def channels(self, org_id, severity):
        return ["in_app", "email"]

    async def emails(self, org_id):
        return ["sahip@example.com"]

    async def no_delivery(*_a, **_k):
        return {}

    for name, fn in (("_get_active_orgs", orgs), ("_compute_current_kris", kris),
                     ("_get_alert_channels", channels), ("_get_alert_emails", emails)):
        monkeypatch.setattr(ProactiveAlertOrchestrator, name, fn)
    monkeypatch.setattr(outbox, "deliver_pending", no_delivery)

    async def effects(org: str) -> tuple[int, int, int]:
        async with database.get_session_factory(database.engine())() as db:
            return tuple(  # type: ignore[return-value]
                (await db.execute(select(func.count()).select_from(m).where(m.org_id == org))).scalar_one()
                for m in (ProactiveAlert, InAppNotification, OutboxMessage)
            )

    async def slot_status() -> list[str]:
        async with database.get_session_factory(database.engine())() as db:
            rows = (await db.execute(
                select(ScheduledJobRun.status).where(
                    ScheduledJobRun.job == "hourly_kri_scan", ScheduledJobRun.period == "2025-02-03T09")
            )).scalars().all()
        return list(rows)

    try:
        first = await scheduler._hourly_proactive_kri_scan(NOW)
        assert first.failed == 1 and await slot_status() == [FAILED]
        assert await effects(b) == (1, 1, 1) and await effects(a) == (0, 0, 0)

        state["a_fails"] = False
        second = await scheduler._hourly_proactive_kri_scan(NOW)
        assert second.done == 1 and await slot_status() == [DONE]
        assert await effects(b) == (1, 1, 1), "B was not repeated by the retry"
        assert await effects(a) == (1, 1, 1)
    finally:
        await database.engine().dispose()
        database._engine = None
