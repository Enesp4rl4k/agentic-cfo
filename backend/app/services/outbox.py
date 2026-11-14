"""The outbox: write an external effect once, deliver it, keep what happened (plan v11 C9).

`enqueue` writes a row keyed by what the effect is for; the same key twice writes
nothing new. `deliver_pending` sends what is pending and records the outcome on the
row: sent, failed with the reason, or retried until MAX_ATTEMPTS. Nothing is skipped
in silence: a missing SMTP configuration is a failure with a reason the screen shows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox_message import FAILED, HELD, PENDING, SENT, OutboxMessage
from app.services.notification_service import send_plain_email

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BATCH = 100


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
    """Send pending e-mail; record sent, failed (with reason) or a retry on each row."""
    rows = (
        await db.execute(
            select(OutboxMessage)
            .where(OutboxMessage.status == PENDING, OutboxMessage.channel == "email")
            .order_by(OutboxMessage.created_at)
            .limit(limit)
        )
    ).scalars().all()
    counts = {"sent": 0, "failed": 0, "retry": 0}
    for row in rows:
        outcome = await send_plain_email(row.recipient, row.subject, row.body)
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
