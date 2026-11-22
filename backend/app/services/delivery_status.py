"""What an owner or admin may see about outbound destinations (Slack, webhooks).

Read-only, derived from the outbox rows of the organisation: for each destination host, when a
message last went out, when one last failed and why, in words (tr/en). No URL (a Slack or webhook
URL carries a secret), no response body, no payload.

`notify_if_newly_failing` writes ONE in-app notification when a destination starts failing: it is
idempotent (a second failure of the same destination, with no success in between, adds nothing).
The precise reason is shown here and kept in the audit log; the synchronous connection-test
answer is a single sentence (`outbox_immediate.PUBLIC_REFUSAL`).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.in_app_notification import InAppNotification
from app.models.outbox_message import FAILED, SENT, OutboxMessage

DESTINATION_CHANNELS = ("slack", "webhook")

# reason code -> (tr, en)
_REASONS: dict[str, tuple[str, str]] = {
    "destination_is_internal": ("hedef adres iç ağa işaret ediyor", "the address points to an internal network"),
    "destination_not_https": ("hedef adres https değil", "the address is not https"),
    "destination_invalid": ("hedef adres geçersiz", "the address is not valid"),
    "destination_port_not_allowed": ("hedef adresin portuna izin verilmiyor", "the address port is not allowed"),
    "destination_unresolvable": ("hedef adres çözümlenemedi", "the address name could not be resolved"),
    "response_too_large": ("hedefin yanıtı çok büyük", "the destination's answer is too large"),
    "timeout": ("zaman aşımı", "timed out"),
    "connection_failed": ("hedefe bağlanılamadı", "could not connect to the destination"),
    "slack_not_configured": ("Slack yapılandırılmamış", "Slack is not configured"),
    "webhook_not_configured": ("webhook yapılandırılmamış", "the webhook is not configured"),
    "bad_payload": ("mesaj biçimi hatalı", "the message was malformed"),
}
_UNKNOWN = ("gönderim başarısız", "delivery failed")


def describe(reason: str | None) -> dict[str, str]:
    """{code, tr, en} for a failure reason; an HTTP status is named, anything else is generic."""
    code = (reason or "").split(":", 1)[0].strip()
    if code in _REASONS:
        tr, en = _REASONS[code]
    elif code.startswith("http_") and code[5:].isdigit():
        status = code[5:]
        tr, en = f"hedef {status} yanıtı verdi", f"the destination answered {status}"
    else:
        tr, en = _UNKNOWN
        code = "failed"
    return {"code": code, "tr": tr, "en": en}


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


async def destination_status(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    """One entry per destination host (and channel) the organisation has sent to, newest first."""
    rows = (
        await db.execute(
            select(OutboxMessage)
            .where(OutboxMessage.org_id == org_id, OutboxMessage.channel.in_(DESTINATION_CHANNELS))
            .order_by(desc(OutboxMessage.created_at))
            .limit(500)
        )
    ).scalars().all()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:  # newest first: the first success / failure seen is the last one
        entry = out.setdefault(
            (row.channel, row.recipient),
            {"channel": row.channel, "destination": row.recipient, "last_success_at": None,
             "last_failure_at": None, "last_failure": None, "_latest": row.status},
        )
        if row.status == SENT and entry["last_success_at"] is None:
            entry["last_success_at"] = _iso(row.sent_at or row.created_at)
        if row.status == FAILED and entry["last_failure_at"] is None:
            entry["last_failure_at"] = _iso(row.created_at)
            entry["last_failure"] = describe(row.last_error)
    result = []
    for entry in out.values():
        entry["failing"] = entry.pop("_latest") == FAILED
        result.append(entry)
    return result


def _source(channel: str, host: str) -> str:
    """The idempotency key of a destination's outage. Hashed: `source` is returned to every member."""
    digest = hashlib.sha256(host.encode("utf-8")).hexdigest()[:16]
    return f"delivery_failing:{channel}:{digest}"


async def notify_if_newly_failing(db: AsyncSession, row: OutboxMessage) -> bool:
    """One in-app notification when a destination starts failing; nothing for the 2nd, 3rd failure.

    "Starts failing": no notification for this destination exists since its last success. The text
    is one generic sentence (no host, no reason, no URL): every member can read it."""
    if row.channel not in DESTINATION_CHANNELS or row.status != FAILED:
        return False
    last_ok = (
        await db.execute(
            select(OutboxMessage.sent_at)
            .where(
                OutboxMessage.org_id == row.org_id, OutboxMessage.channel == row.channel,
                OutboxMessage.recipient == row.recipient, OutboxMessage.status == SENT,
            )
            .order_by(desc(OutboxMessage.sent_at)).limit(1)
        )
    ).scalar_one_or_none()
    source = _source(row.channel, row.recipient)
    seen = select(InAppNotification.id).where(
        InAppNotification.org_id == row.org_id, InAppNotification.source == source
    )
    if last_ok is not None:
        seen = seen.where(InAppNotification.created_at > last_ok)
    if (await db.execute(seen.limit(1))).first() is not None:
        return False
    # Every member reads this: one generic sentence. Host and reason are in the owner/admin status route.
    db.add(InAppNotification(
        org_id=row.org_id, level="warning", domain="system", source=source, action="route",
        message=(
            "Bir bildirim hedefine ulaşılamıyor; ayrıntılar için yöneticinize danışın. "
            "/ A notification destination cannot be reached; ask your administrator for details."
        ),
    ))
    await db.flush()
    return True
