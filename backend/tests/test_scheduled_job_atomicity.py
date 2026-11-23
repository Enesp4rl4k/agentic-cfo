"""A scheduled run and its ledger `done` mark stand or fall together; a repeated run repeats no effect.

Each test makes the run fail at the boundary (the `done` mark raises, or an alert's own commit fails) and
then runs the slot again. Nothing leaves the process: delivery is stubbed, effects are counted as rows.

* Monday briefing: one transaction (work + mark); a failure leaves no outbox row and no notification.
* Nightly intelligence: its notification service used to commit the in-app rows BEFORE the mark, so a crash
  between them repeated them on the retry; it now leaves the commit to the ledger run.
* Hourly KRI scan: it commits each alert as it goes (the alert log), so its alert ids derive from the slot:
  the retry of the same slot finds them and writes nothing new. A rolled-back alert fails the slot.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as database
from app import scheduler
from app.agents.orchestration.proactive_alerts import ProactiveAlertOrchestrator
from app.models.analysis_job import AnalysisJob
from app.models.in_app_notification import InAppNotification
from app.models.job_run import DONE, FAILED, ScheduledJobRun
from app.models.outbox_message import OutboxMessage
from app.models.proactive_alert import ProactiveAlert
from app.models.report import Report
from app.services import job_runs, outbox
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import statement, upload

MONDAY_0700 = datetime(2025, 2, 3, 7, 0, 30, tzinfo=UTC)
NIGHT_0200 = datetime(2025, 2, 4, 2, 0, 30, tzinfo=UTC)
KRI_NOW = datetime(2025, 2, 3, 9, 20, tzinfo=UTC)


@pytest.fixture
def real_transactions():
    """Returns `start()`, which gives the test engine production's transaction boundaries from then on.

    SQLite's driver opens a transaction lazily: a SAVEPOINT (the outbox's `begin_nested`) that comes before the
    first write is outside one, and its RELEASE commits. Postgres has no such quirk, so after the test's own
    setup (plain, fast) the scheduled runs get the documented recipe: an explicit BEGIN."""
    active = {"on": False}

    def begin(conn):
        if active["on"]:
            conn.connection.dbapi_connection.isolation_level = None
            conn.exec_driver_sql("BEGIN")

    event.listen(Engine, "begin", begin)
    yield lambda: active.update(on=True)
    event.remove(Engine, "begin", begin)


@pytest_asyncio.fixture
async def client(monkeypatch):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "engine", lambda: None)
        monkeypatch.setattr(database, "get_session_factory", lambda _e: c._maker)

        async def no_delivery(*_a, **_k):
            return {}

        monkeypatch.setattr(outbox, "deliver_pending", no_delivery)  # nothing is sent
        yield c


@pytest.fixture
def crash_at_the_mark(monkeypatch):
    """`mark_done` raises for the first `n` calls: the process dies between the work and the mark."""
    state = {"n": 1}
    real = job_runs.mark_done

    async def mark_done(db, run_id, **kw):
        if state["n"] > 0:
            state["n"] -= 1
            raise RuntimeError("process died between the work and the done mark")
        await real(db, run_id, **kw)

    monkeypatch.setattr(job_runs, "mark_done", mark_done)
    return state


async def count(client, model, *where) -> int:
    async with client._maker() as db:
        return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def ledger(client, job: str) -> list[tuple[str, str]]:
    async with client._maker() as db:
        rows = (await db.execute(select(ScheduledJobRun).where(ScheduledJobRun.job == job))).scalars().all()
    return sorted((r.period, r.status) for r in rows)


async def company(client, email: str) -> tuple[str, str]:
    _, org_id, _ = await kullanici(client, email, role="owner")
    job_id = await upload(
        client, org_id, {"amount_cents": 50_000_00, "transaction_date": "2025-01-31", "type": "income"},
        meta=statement("2025-01-31", 50_000_00),
    )
    return org_id, job_id


async def test_monday_briefing_work_and_mark_are_one_transaction(client, crash_at_the_mark, monkeypatch, real_transactions):
    async def no_redis():
        raise ConnectionError("no redis in the test")

    monkeypatch.setattr("app.worker.get_arq_pool", no_redis)
    org_id, _ = await company(client, "sahip@example.com")
    real_transactions()
    mails = (OutboxMessage.org_id == org_id, OutboxMessage.source == "monday_briefing")
    notes = (InAppNotification.org_id == org_id, InAppNotification.source == "monday_briefing")

    first = await scheduler._dispatch_monday_briefings(MONDAY_0700)
    assert first.failed == 1 and first.done == 0
    assert await count(client, OutboxMessage, *mails) == 0, "the outbox rows rolled back with the work"
    assert await count(client, InAppNotification, *notes) == 0
    assert await ledger(client, "monday_briefing") == [("2025-02-03", FAILED)], "no slot marked done without its work"

    second = await scheduler._dispatch_monday_briefings(MONDAY_0700)
    assert second.done == 1
    assert await count(client, OutboxMessage, *mails) == 1 and await count(client, InAppNotification, *notes) == 1
    assert await ledger(client, "monday_briefing") == [("2025-02-03", DONE)]

    await scheduler._dispatch_monday_briefings(MONDAY_0700)  # a third call (catch-up, second scheduler)
    assert await count(client, OutboxMessage, *mails) == 1 and await count(client, InAppNotification, *notes) == 1


async def test_nightly_alerts_are_not_committed_before_the_done_mark(client, crash_at_the_mark, real_transactions):
    org_id, job_id = await company(client, "gece@example.com")
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        job.completed_at = NIGHT_0200
        db.add(Report(
            job_id=job_id, report_type="full", report_format="json",
            data={"cashflow": {"alerts": [{"level": "critical", "message": "Nakit bu ay tükeniyor"}]}},
        ))
        await db.commit()
    notes = (InAppNotification.org_id == org_id,)
    real_transactions()

    first = await scheduler._nightly_intelligence_run(NIGHT_0200)
    assert first.failed == 1 and await count(client, InAppNotification, *notes) == 0, "rolled back with the run"
    assert await ledger(client, "nightly_intelligence") == [("2025-02-04", FAILED)]

    second = await scheduler._nightly_intelligence_run(NIGHT_0200)
    assert second.done == 1 and await count(client, InAppNotification, *notes) == 1
    assert await ledger(client, "nightly_intelligence") == [("2025-02-04", DONE)]
    await scheduler._nightly_intelligence_run(NIGHT_0200)
    assert await count(client, InAppNotification, *notes) == 1


@pytest.fixture
def one_red_kri(monkeypatch):
    """One organisation with one red KRI; alerts go to the bell and to one e-mail address (the outbox)."""
    async def orgs(self):
        return ["org-kri"]

    async def kris(self, org_id):
        return {"posture": {"red_kris": [{"name": "Nakit Rezervi", "current_value": 1, "unit": "ay"}]}}

    async def channels(self, org_id, severity):
        return ["in_app", "email"]

    async def emails(self, org_id):
        return ["sahip@example.com"]

    for name, fn in (("_get_active_orgs", orgs), ("_compute_current_kris", kris),
                     ("_get_alert_channels", channels), ("_get_alert_emails", emails)):
        monkeypatch.setattr(ProactiveAlertOrchestrator, name, fn)


async def kri_effects(client) -> tuple[int, int, int]:
    return (
        await count(client, ProactiveAlert),
        await count(client, InAppNotification, InAppNotification.source == "proactive_alert"),
        await count(client, OutboxMessage, OutboxMessage.source == "proactive_alert"),
    )


async def test_kri_scan_retry_of_a_slot_whose_alerts_committed_repeats_nothing(client, one_red_kri, crash_at_the_mark):
    first = await scheduler._hourly_proactive_kri_scan(KRI_NOW)
    assert first.failed == 1
    assert await ledger(client, "hourly_kri_scan") == [("2025-02-03T09", FAILED)]
    assert await kri_effects(client) == (1, 1, 1), "the alert log committed as it went"

    second = await scheduler._hourly_proactive_kri_scan(KRI_NOW)
    assert second.done == 1
    assert await kri_effects(client) == (1, 1, 1), "same slot, same alert id: no second bell, no second e-mail"
    assert await ledger(client, "hourly_kri_scan") == [("2025-02-03T09", DONE)]

    await scheduler._hourly_proactive_kri_scan(KRI_NOW.replace(hour=10))  # the next hour is a new slot
    assert (await kri_effects(client))[0] == 2


async def test_kri_scan_with_a_rolled_back_alert_is_not_marked_done(client, one_red_kri, monkeypatch):
    state = {"n": 1}
    real = AsyncSession.commit

    async def commit(self):
        if state["n"] > 0 and any(isinstance(o, ProactiveAlert) for o in self.new):
            state["n"] -= 1
            raise RuntimeError("commit failed")
        await real(self)

    monkeypatch.setattr(AsyncSession, "commit", commit)
    first = await scheduler._hourly_proactive_kri_scan(KRI_NOW)
    assert first.failed == 1 and await kri_effects(client) == (0, 0, 0), "the alert and its effects rolled back"
    assert await ledger(client, "hourly_kri_scan") == [("2025-02-03T09", FAILED)], "not marked done without its work"

    second = await scheduler._hourly_proactive_kri_scan(KRI_NOW)
    assert second.done == 1 and await kri_effects(client) == (1, 1, 1)


def _kri(name: str, **extra) -> dict:
    return {"name": name, "current_value": 1, "unit": "ay", **extra}


@pytest.fixture
def two_orgs_one_raises(monkeypatch):
    """Org A's KRI computation raises (until `state["a_fails"]` is cleared); org B has one red KRI."""
    state = {"a_fails": True}

    async def orgs(self):
        return ["org-a", "org-b"]

    async def kris(self, org_id):
        if org_id == "org-a" and state["a_fails"]:
            raise RuntimeError("KRI computation failed for org-a")
        return {"posture": {"red_kris": [_kri(f"Nakit {org_id}")]}}

    async def channels(self, org_id, severity):
        return ["in_app", "email"]

    async def emails(self, org_id):
        return ["sahip@example.com"]

    for name, fn in (("_get_active_orgs", orgs), ("_compute_current_kris", kris),
                     ("_get_alert_channels", channels), ("_get_alert_emails", emails)):
        monkeypatch.setattr(ProactiveAlertOrchestrator, name, fn)
    return state


async def test_kri_scan_one_org_failing_fails_the_slot_and_the_retry_completes_it(client, two_orgs_one_raises):
    b = (ProactiveAlert.org_id == "org-b",)
    a = (ProactiveAlert.org_id == "org-a",)

    first = await scheduler._hourly_proactive_kri_scan(KRI_NOW)
    assert first.failed == 1 and first.done == 0
    assert await ledger(client, "hourly_kri_scan") == [("2025-02-03T09", FAILED)], "not reported as cleanly done"
    assert await count(client, ProactiveAlert, *b) == 1, "org B's alert committed despite A's failure"
    assert await count(client, ProactiveAlert, *a) == 0

    two_orgs_one_raises["a_fails"] = False
    second = await scheduler._hourly_proactive_kri_scan(KRI_NOW)
    assert second.done == 1
    assert await count(client, ProactiveAlert, *b) == 1, "the retry did not duplicate B"
    assert await count(client, ProactiveAlert, *a) == 1, "the retry completed A"
    assert await count(client, InAppNotification, InAppNotification.source == "proactive_alert") == 2
    assert await count(client, OutboxMessage, OutboxMessage.source == "proactive_alert") == 2
    assert await ledger(client, "hourly_kri_scan") == [("2025-02-03T09", DONE)]


async def test_a_failing_kri_computation_is_an_org_failure_not_no_data(monkeypatch):
    from app.services import company_context

    async def broken(*_a, **_k):
        raise RuntimeError("context unreadable")

    monkeypatch.setattr(company_context, "get_company_context", broken)
    orchestrator = ProactiveAlertOrchestrator(db=None, slot="2025-02-03T09")
    assert await orchestrator._compute_current_kris("org-x") is None
    assert orchestrator.failed_orgs == ["org-x"]


async def test_same_named_kris_in_one_slot_each_get_their_own_alert(client, monkeypatch):
    async def orgs(self):
        return ["org-kri"]

    async def kris(self, org_id):
        return {"posture": {"red_kris": [_kri("Nakit Rezervi"), _kri("Nakit Rezervi"), _kri("Nakit Rezervi", id="k-7")]}}

    for name, fn in (("_get_active_orgs", orgs), ("_compute_current_kris", kris)):
        monkeypatch.setattr(ProactiveAlertOrchestrator, name, fn)

    first = await scheduler._hourly_proactive_kri_scan(KRI_NOW)
    assert first.done == 1 and await count(client, ProactiveAlert) == 3, "no alert dropped by a name collision"
    await scheduler._hourly_proactive_kri_scan(KRI_NOW)  # the same slot again: nothing new, keys are stable
    assert await count(client, ProactiveAlert) == 3
    await scheduler._hourly_proactive_kri_scan(KRI_NOW.replace(hour=10))
    assert await count(client, ProactiveAlert) == 6
