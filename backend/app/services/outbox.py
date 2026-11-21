"""The outbox: write an external effect once, deliver it, keep what happened (plan v11 C9).

`enqueue` writes a row keyed by what the effect is for; the same key twice writes
nothing new. `deliver_pending` sends what is pending and records the outcome on the
row: sent, failed with the reason, or retried until MAX_ATTEMPTS. Nothing is skipped
in silence: a missing SMTP configuration is a failure with a reason the screen shows.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox_message import FAILED, HELD, PENDING, SENT, OutboxMessage
from app.services.alert_dispatcher import AlertDispatcher
from app.services.notification_service import send_plain_email

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BATCH = 100
CHANNELS = ("email", "slack", "webhook")


async def enqueue(
    db: AsyncSession,
    *,
    key: str,
    org_id: str,
    channel: str,
    recipient: str,
    subject: str,
    body: str,
    source: str,
    source_ref: str,
    held_reason: str | None = None,
) -> OutboxMessage:
    """Write the effect once. A row with the same key is returned unchanged."""
    query = select(OutboxMessage).where(OutboxMessage.key == key)
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing is not None:
        return existing
    row = OutboxMessage(
        key=key,
        org_id=org_id,
        channel=channel,
        recipient=recipient,
        subject=subject[:255],
        body=body,
        source=source,
        source_ref=source_ref,
        status=HELD if held_reason else PENDING,
        attempts=0,
        last_error=held_reason,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # Another worker wrote the same effect first; theirs is the one.
        existing = (await db.execute(query)).scalar_one_or_none()
        if existing is None:
            raise
        return existing
    return row


def _host(url: str) -> str:
    """What the screen may show of a destination: Slack and webhook URLs carry a secret."""
    return (urlsplit(url).hostname or "unknown")[:255]


async def enqueue_slack(
    db: AsyncSession,
    *,
    key: str,
    org_id: str,
    webhook_url: str,
    title: str,
    message: str,
    severity: str,
    source: str,
    source_ref: str,
) -> OutboxMessage:
    """A Slack message as an outbox row. The URL lives in the body; the recipient is its host."""
    body = json.dumps({"url": webhook_url, "title": title, "message": message, "severity": severity})
    return await enqueue(
        db, key=key, org_id=org_id, channel="slack", recipient=_host(webhook_url),
        subject=title, body=body, source=source, source_ref=source_ref,
    )


async def enqueue_webhook(
    db: AsyncSession,
    *,
    key: str,
    org_id: str,
    url: str,
    event_type: str,
    data: dict[str, Any],
    source: str,
    source_ref: str,
) -> OutboxMessage:
    """A webhook POST as an outbox row (same storage rule as Slack)."""
    body = json.dumps({"url": url, "event_type": event_type, "data": data}, default=str)
    return await enqueue(
        db, key=key, org_id=org_id, channel="webhook", recipient=_host(url),
        subject=event_type, body=body, source=source, source_ref=source_ref,
    )


async def _send_http(row: OutboxMessage) -> str:
    """Deliver a slack/webhook row; the same outcome words as send_plain_email."""
    try:
        spec = json.loads(row.body)
        url = str(spec["url"])
        if row.channel == "slack":
            sent = await AlertDispatcher.dispatch_slack(
                url, str(spec["title"]), str(spec["message"]), str(spec.get("severity", "warning"))
            )
        else:
            sent = await AlertDispatcher.dispatch_webhook(url, str(spec["event_type"]), spec["data"])
    except (ValueError, KeyError, TypeError) as exc:
        return f"failed:bad_payload: {exc}"
    return "sent" if sent.delivered else f"failed:http_{sent.status_code}"


async def release(db: AsyncSession, *, org_id: str, source: str, source_ref: str) -> int:
    """A person allowed it: held messages for this source become pending."""
    rows = (
        await db.execute(
            select(OutboxMessage).where(
                OutboxMessage.org_id == org_id,
                OutboxMessage.source == source,
                OutboxMessage.source_ref == source_ref,
                OutboxMessage.status == HELD,
            )
        )
    ).scalars().all()
    for row in rows:
        row.status = PENDING
        row.last_error = None
    return len(rows)


async def deliver_pending(db: AsyncSession, *, limit: int = BATCH) -> dict[str, int]:
    """Send pending e-mail, Slack and webhook rows; record sent, failed (with reason) or a retry."""
    rows = (
        await db.execute(
            select(OutboxMessage)
            .where(OutboxMessage.status == PENDING, OutboxMessage.channel.in_(CHANNELS))
            .order_by(OutboxMessage.created_at)
            .limit(limit)
        )
    ).scalars().all()
    counts = {"sent": 0, "failed": 0, "retry": 0}
    for row in rows:
        if row.channel == "email":
            outcome = await send_plain_email(row.recipient, row.subject, row.body)
        else:
            outcome = await _send_http(row)
        row.attempts += 1
        if outcome == "sent":
            row.status = SENT
            row.sent_at = datetime.now(UTC)
            row.last_error = None
            counts["sent"] += 1
        elif outcome == "not_configured":
            # Retrying cannot help until someone configures SMTP; say so and stop.
            row.status = FAILED
            row.last_error = "smtp_not_configured"
            counts["failed"] += 1
        else:
            row.last_error = outcome.removeprefix("failed:")[:500]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = FAILED
                counts["failed"] += 1
            else:
                counts["retry"] += 1
        await db.flush()
    if any(counts.values()):
        logger.info("outbox delivery: %s", counts)
    return counts
