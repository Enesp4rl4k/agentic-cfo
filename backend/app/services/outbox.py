"""The outbox: write an external effect once, deliver it, keep what happened (plan v11 C9).

`enqueue` writes a row keyed by what the effect is for; the same key twice writes
nothing new. `deliver_pending` sends what is pending and records the outcome on the
row: sent, failed with the reason, or retried until MAX_ATTEMPTS. Nothing is skipped
in silence: a missing SMTP configuration is a failure with a reason the screen shows.

Nothing else in the application sends mail, WhatsApp, Slack or a webhook (the architecture
test fails on it). Two delivery classes:

- `released` (default): business content. It is written pending under an organisation's
  standing preference, or held until a person releases it. At delivery the recipient must
  still be one the organisation configured: an active member or a listed alert recipient
  (e-mail), the configured number (WhatsApp). Otherwise the row fails with the reason.
- `immediate`: transactional security mail and connection tests that need no release. Only
  `app.services.outbox_immediate` writes them, from an allowlist of template kinds whose text
  is rendered from non-business parameters; delivery refuses a row whose kind is not allowed.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email_address import normalize_email
from app.models.alert_preference import AlertPreference
from app.models.organization import OrgMembership
from app.models.outbox_message import (
    FAILED,
    HELD,
    IMMEDIATE,
    PENDING,
    RELEASED,
    SENT,
    OutboxMessage,
)
from app.models.user import User
from app.services.alert_dispatcher import AlertDispatcher
from app.services.outbox_transport import (
    RECORDED,
    live,
    send_plain_email,
    send_slack_bot,
    send_whatsapp,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BATCH = 100
CHANNELS = ("email", "slack", "webhook", "whatsapp", "slack_bot")
SCRUBBED = "[removed after delivery]"


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
    delivery_class: str = RELEASED,
    kind: str | None = None,
) -> OutboxMessage:
    """Write the effect once. A row with the same key is returned unchanged.

    `delivery_class="immediate"` is for `app.services.outbox_immediate` only (its allowlist
    of template kinds is what makes it safe); the architecture test refuses anyone else."""
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
        delivery_class=delivery_class,
        kind=kind,
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


def destination_host(url: str) -> str:
    """What the screen may show of a destination: Slack and webhook URLs carry a secret."""
    return (urlsplit(url).hostname or "unknown")[:255]


def destination_problem(url: str) -> str | None:
    """Why a Slack or webhook URL may not be posted to, or None.

    https only, and never this machine or a private network (a configured URL is user input;
    posting to an internal address is a request forgery). Judged by the literal host: a name
    that resolves to a private address is not caught here."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return "destination_not_https"
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return "destination_is_internal"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if not address.is_global:
        return "destination_is_internal"
    return None


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
        db, key=key, org_id=org_id, channel="slack", recipient=destination_host(webhook_url),
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
        db, key=key, org_id=org_id, channel="webhook", recipient=destination_host(url),
        subject=event_type, body=body, source=source, source_ref=source_ref,
    )


async def enqueue_whatsapp(
    db: AsyncSession,
    *,
    key: str,
    org_id: str,
    number: str,
    subject: str,
    body: str,
    source: str,
    source_ref: str,
) -> OutboxMessage:
    """A WhatsApp text to the organisation's configured number, as an outbox row."""
    return await enqueue(
        db, key=key, org_id=org_id, channel="whatsapp", recipient=number,
        subject=subject, body=body, source=source, source_ref=source_ref,
    )


async def _send_http(row: OutboxMessage) -> str:
    """Deliver a slack/webhook row; the same outcome words as send_plain_email."""
    try:
        spec = json.loads(row.body)
        url = str(spec["url"])
        problem = destination_problem(url)
        if problem:
            return f"failed:{problem}"
        if not live() and AlertDispatcher.transport is None:
            # Development: recorded, not posted (tests inject a transport and go through it).
            RECORDED.append((row.channel, row.recipient, row.subject))
            return "sent:noop"
        if row.channel == "slack":
            sent = await AlertDispatcher.dispatch_slack(
                url, str(spec["title"]), str(spec["message"]), str(spec.get("severity", "warning"))
            )
        else:
            sent = await AlertDispatcher.dispatch_webhook(url, str(spec["event_type"]), spec["data"])
    except (ValueError, KeyError, TypeError) as exc:
        return f"failed:bad_payload: {exc}"
    return "sent" if sent.delivered else f"failed:http_{sent.status_code}"


async def held_rows(
    db: AsyncSession, *, org_id: str, source: str, source_ref: str
) -> list[OutboxMessage]:
    """The messages of one source still waiting for a person."""
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
    return list(rows)


async def release(
    db: AsyncSession,
    *,
    org_id: str,
    source: str,
    source_ref: str,
    refreshed: tuple[str, str] | None = None,
) -> int:
    """A person allowed it: held messages for this source become pending.

    `refreshed` is a (subject, body) the releaser confirmed in place of the held text.
    Who released, and when, is the caller's decision record, written in the same
    transaction (services/briefing_delivery.release_briefing)."""
    rows = await held_rows(db, org_id=org_id, source=source, source_ref=source_ref)
    for row in rows:
        if refreshed is not None:
            row.subject, row.body = refreshed[0][:255], refreshed[1]
        row.status = PENDING
        row.last_error = None
    return len(rows)


async def allowed_email_recipients(db: AsyncSession, org_id: str) -> set[str]:
    """Who may be mailed on behalf of an organisation: its active members and its alert recipients."""
    member_ids = select(OrgMembership.user_id).where(OrgMembership.org_id == org_id)
    members = (
        await db.execute(
            select(User.email).where(
                User.is_active.is_(True), or_(User.id.in_(member_ids), User.org_id == org_id)
            )
        )
    ).scalars().all()
    allowed = {normalize_email(e) for e in members}
    pref = (
        await db.execute(select(AlertPreference).where(AlertPreference.org_id == org_id))
    ).scalar_one_or_none()
    if pref is not None and pref.email_recipients:
        try:
            listed = json.loads(pref.email_recipients)
        except ValueError:
            listed = str(pref.email_recipients).split(",")
        if isinstance(listed, list):
            allowed |= {normalize_email(str(a)) for a in listed if str(a).strip()}
    return allowed


async def _recipient_problem(db: AsyncSession, row: OutboxMessage) -> str | None:
    """A released message goes only to a recipient the organisation configured."""
    if row.channel == "email":
        if normalize_email(row.recipient) not in await allowed_email_recipients(db, row.org_id):
            return "recipient_not_allowed"
    elif row.channel == "whatsapp":
        pref = (
            await db.execute(select(AlertPreference).where(AlertPreference.org_id == row.org_id))
        ).scalar_one_or_none()
        configured = (pref.whatsapp_number or "").strip() if pref is not None else ""
        if not configured or configured.replace(" ", "") != row.recipient.replace(" ", ""):
            return "recipient_not_allowed"
    return None


async def _refusal(db: AsyncSession, row: OutboxMessage) -> str | None:
    """Why this row may not be sent at all (a failure with a reason, never a silent skip)."""
    if row.delivery_class == IMMEDIATE:
        from app.services.outbox_immediate import kind_allows

        return None if kind_allows(row.kind, row.channel) else "immediate_kind_not_allowed"
    if row.delivery_class != RELEASED:
        return "unknown_delivery_class"
    return await _recipient_problem(db, row)


def _scrub(row: OutboxMessage) -> None:
    """A delivered security message no longer needs its one-time link at rest."""
    from app.services.outbox_immediate import kind_scrubs

    if row.delivery_class == IMMEDIATE and kind_scrubs(row.kind):
        row.body = SCRUBBED


async def _send(row: OutboxMessage) -> str:
    if row.channel == "email":
        return await send_plain_email(row.recipient, row.subject, row.body)
    if row.channel == "whatsapp":
        return await send_whatsapp(row.recipient, row.body)
    if row.channel == "slack_bot":
        return await send_slack_bot(row.body)
    return await _send_http(row)


async def deliver_pending(db: AsyncSession, *, limit: int = BATCH) -> dict[str, int]:
    """Send pending rows and record sent, failed (with reason) or a retry.

    Rows are locked while they are sent (skip locked on Postgres), so a delivery kicked by a
    request and the scheduler's pass never send the same row twice."""
    rows = (
        await db.execute(
            select(OutboxMessage)
            .where(OutboxMessage.status == PENDING, OutboxMessage.channel.in_(CHANNELS))
            .order_by(OutboxMessage.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    counts = {"sent": 0, "failed": 0, "retry": 0}
    for row in rows:
        refusal = await _refusal(db, row)
        outcome = f"refused:{refusal}" if refusal else await _send(row)
        row.attempts += 1
        if outcome in ("sent", "sent:noop"):
            row.status = SENT
            row.sent_at = datetime.now(UTC)
            row.last_error = None
            row.transport = "noop" if outcome == "sent:noop" else ("smtp" if row.channel == "email" else "http")
            if outcome == "sent":
                # Only a message that really left: a recorded no-op (development) keeps its text, so a
                # developer can open the invitation or reset link the mail would have carried.
                _scrub(row)
            counts["sent"] += 1
        elif outcome == "not_configured":
            # Retrying cannot help until someone configures the channel; say so and stop.
            row.status = FAILED
            row.last_error = f"{'smtp' if row.channel == 'email' else row.channel}_not_configured"
            _scrub(row)
            counts["failed"] += 1
        elif outcome.startswith("refused:"):
            row.status = FAILED
            row.last_error = outcome.removeprefix("refused:")
            _scrub(row)
            counts["failed"] += 1
        else:
            row.last_error = outcome.removeprefix("failed:")[:500]
            if row.attempts >= MAX_ATTEMPTS or row.last_error.startswith("destination_"):
                row.status = FAILED
                _scrub(row)
                counts["failed"] += 1
            else:
                counts["retry"] += 1
        await db.flush()
    if any(counts.values()):
        logger.info("outbox delivery: %s", counts)
    return counts


async def _deliver_with_own_session() -> None:
    from app.core.background import with_session

    async def work(db: AsyncSession) -> None:
        await deliver_pending(db)
        await db.commit()

    await with_session(work)


def kick() -> None:
    """Deliver now, in the background, what a request just wrote (after its commit).

    The scheduler's five-minute pass remains the retry path; this only removes the wait for a
    link the person is looking for. Never raises, never blocks the request."""
    from app.config import get_settings
    from app.core.background import spawn

    if not get_settings().outbox_kick_on_enqueue:
        return
    try:
        spawn(_deliver_with_own_session(), name="outbox-kick")
    except RuntimeError:  # no running loop (a script): the scheduler will deliver
        logger.debug("outbox kick skipped: no event loop")
