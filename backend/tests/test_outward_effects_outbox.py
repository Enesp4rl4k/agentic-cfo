"""Alerts and trigger webhooks leave only through the outbox (ADR 0003, F3).

Before: KRI alerts called Slack and e-mail helpers that did not exist (the error was
swallowed at debug level), the trigger webhook was POSTed inline, and a failed
acknowledgement was answered with `acknowledged: true`.
"""
from __future__ import annotations

import json
import time
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.agents.orchestration.proactive_alerts import AlertEvent, ProactiveAlertOrchestrator
from app.api.alerts import acknowledge_alert
from app.models.alert_preference import AlertPreference
from app.models.outbox_message import OutboxMessage
from app.services import alert_dispatcher, outbox
from app.services.alert_dispatcher import DispatchedAlert
from tests.db_helpers import gecici_oturum

SLACK = "https://hooks.slack.test/services/T000/B000/secret"


@pytest_asyncio.fixture
async def db():
    import app.models  # noqa: F401

    async with gecici_oturum() as session:
        yield session


async def _prefs(db) -> None:
    db.add(AlertPreference(
        org_id="org-1", slack_webhook_url=SLACK,
        email_recipients=json.dumps(["a@x.com", "b@x.com", "c@x.com", "d@x.com"]),
    ))
    await db.commit()


def _alert(channels: list[str]) -> AlertEvent:
    return AlertEvent(
        alert_id="al-1", org_id="org-1", trigger="kri_breach", severity="critical",
        title="Kasa kırmızı", body="Nakit 3 haftalık", metadata={"kri": {"name": "k"}},
        channels=channels, created_at=time.time(),
    )


async def _rows(db) -> list[OutboxMessage]:
    return list((await db.execute(select(OutboxMessage).order_by(OutboxMessage.key))).scalars())


async def test_kri_alert_slack_and_email_are_outbox_rows_to_the_configured_targets(db, monkeypatch):
    await _prefs(db)

    async def boom(*a: Any, **k: Any):
        raise AssertionError("sent inline")

    monkeypatch.setattr(alert_dispatcher.AlertDispatcher, "dispatch_slack", boom)
    monkeypatch.setattr("app.services.outbox.send_plain_email", boom)
    orch = ProactiveAlertOrchestrator(db=db)
    channels = await orch._get_alert_channels("org-1", "critical")
    assert channels == ["in_app", "slack", "email"]

    alert = _alert(["slack", "email"])
    await orch._dispatch_alert(alert)
    await orch._dispatch_alert(alert)  # a redelivery writes nothing new

    rows = await _rows(db)
    assert [(r.channel, r.recipient) for r in rows] == [
        ("email", "a@x.com"), ("email", "b@x.com"), ("email", "c@x.com"),  # first three, as before
        ("slack", "hooks.slack.test"),  # the secret URL is not the displayed recipient
    ]
    assert all(r.status == "pending" and r.source == "proactive_alert" for r in rows)
    assert alert.dispatched is True and alert.dispatch_errors == []


async def test_a_channel_that_cannot_be_written_is_recorded_not_swallowed(db):
    orch = ProactiveAlertOrchestrator(db=db)  # no preference row: no Slack destination
    alert = _alert(["slack"])
    await orch._dispatch_alert(alert)
    assert alert.dispatched is False
    assert any("webhook" in e for e in alert.dispatch_errors)
    assert await _rows(db) == []


async def test_failed_delivery_shows_as_a_failed_outbox_row(db, monkeypatch):
    await _prefs(db)
    await ProactiveAlertOrchestrator(db=db)._dispatch_alert(_alert(["slack"]))

    async def refused(url, title, message, severity="warning", fields=None):
        return DispatchedAlert("x", "slack", url, severity, title, message, delivered=False, status_code=500)

    monkeypatch.setattr(alert_dispatcher.AlertDispatcher, "dispatch_slack", refused)
    for _ in range(outbox.MAX_ATTEMPTS):
        await outbox.deliver_pending(db)

    (row,) = await _rows(db)
    assert (row.status, row.attempts, row.last_error) == ("failed", outbox.MAX_ATTEMPTS, "http_500")


async def test_delivered_slack_row_is_marked_sent(db):
    await _prefs(db)
    await outbox.enqueue_slack(
        db, key="k", org_id="org-1", webhook_url="https://dummy.slack", title="t",
        message="m", severity="warning", source="proactive_alert", source_ref="r",
    )
    counts = await outbox.deliver_pending(db)
    assert counts["sent"] == 1
    assert (await _rows(db))[0].status == "sent"


async def test_acknowledge_reports_failure_when_it_was_not_stored(monkeypatch):
    async def no_redis():
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.worker.get_arq_pool", no_redis)
    with pytest.raises(HTTPException) as err:
        await acknowledge_alert("job-1", "abc123", current_user=None, db=None, job=None)  # type: ignore[arg-type]
    assert err.value.status_code == 503


async def test_acknowledge_succeeds_only_when_stored(monkeypatch):
    stored: dict[str, str] = {}

    class Pool:
        async def set(self, key: str, value: str, ex: int) -> None:
            stored[key] = value

    async def pool():
        return Pool()

    monkeypatch.setattr("app.worker.get_arq_pool", pool)
    out = await acknowledge_alert("job-1", "abc123", current_user=None, db=None, job=None)  # type: ignore[arg-type]
    assert out["data"]["acknowledged"] is True and "ack:job-1:abc123" in stored


# ── PR #104 leftovers: the notification service and the dispatcher ────────────


async def test_notification_slack_is_queued_in_the_outbox_not_posted(db, monkeypatch):
    import httpx

    from app.services.alert_router import AlertAction, AlertDecision, RawAlert
    from app.services.notification_service import NotificationService

    posted: list[str] = []
    monkeypatch.setattr(
        alert_dispatcher.AlertDispatcher, "transport",
        httpx.MockTransport(lambda r: posted.append(str(r.url)) or httpx.Response(200)),
    )
    decision = AlertDecision(
        action=AlertAction.ESCALATE,
        alert=RawAlert(level="critical", message="Nakit açığı", domain="cfo", source="cashflow", job_id="j"),
        priority_score=0.9,
    )
    queued = await NotificationService()._queue_slack([decision], SLACK, "org-1", "Acme", db)
    assert queued == 1 and posted == []
    (row,) = await _rows(db)
    assert (row.channel, row.status, row.source, row.recipient) == (
        "slack", "pending", "notification", "hooks.slack.test",
    )
    assert "Nakit açığı" in json.loads(row.body)["message"]
    await NotificationService()._queue_slack([decision], SLACK, "org-1", "Acme", db)
    assert len(await _rows(db)) == 1  # the same alert the same day is one message


async def test_a_dummy_url_is_not_a_delivery_unless_something_answered(monkeypatch):
    import httpx

    monkeypatch.setattr(
        alert_dispatcher.AlertDispatcher, "transport",
        httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    sent = await alert_dispatcher.AlertDispatcher.dispatch_slack("https://dummy.slack", "t", "m")
    assert sent.delivered is False and sent.status_code == 500
    sent = await alert_dispatcher.AlertDispatcher.dispatch_webhook("https://dummy.hook", "e", {})
    assert sent.delivered is False


async def test_no_url_is_not_a_delivery():
    for sent in (
        await alert_dispatcher.AlertDispatcher.dispatch_slack("", "t", "m"),
        await alert_dispatcher.AlertDispatcher.dispatch_webhook("", "e", {}),
    ):
        assert sent.delivered is False and sent.status_code == 0


async def test_the_test_transport_is_refused_outside_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    with pytest.raises(RuntimeError, match="test seam"):
        alert_dispatcher.AlertDispatcher._client()
    # And a dispatch that hits the refusal reports no delivery rather than a fake one.
    sent = await alert_dispatcher.AlertDispatcher.dispatch_slack("https://x.example/h", "t", "m")
    assert sent.delivered is False


async def test_in_app_alert_writes_one_bell_row_and_a_redelivery_adds_none(db):
    from app.models.in_app_notification import InAppNotification

    orch = ProactiveAlertOrchestrator(db=db)
    alert = _alert(["in_app"])
    await orch._dispatch_alert(alert)
    await orch._dispatch_alert(alert)

    rows = list((await db.execute(select(InAppNotification))).scalars())
    assert [(r.org_id, r.level, r.source, r.is_read) for r in rows] == [("org-1", "critical", "proactive_alert", False)]
    assert "Kasa kırmızı" in rows[0].message
    assert alert.dispatched is True and alert.dispatch_errors == []


async def test_in_app_alert_without_a_database_is_an_error_not_a_silent_skip():
    alert = _alert(["in_app"])
    await ProactiveAlertOrchestrator(db=None)._dispatch_alert(alert)
    assert alert.dispatched is False and any(e.startswith("in_app") for e in alert.dispatch_errors)
