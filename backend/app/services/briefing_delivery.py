"""The Monday briefing by e-mail, through the outbox (plan v10 S1.3, plan v11 A0.5).

Who receives it: the company's owner, admins and CFO (from memberships, and from
`users.org_id` for organisations older than memberships). One message per recipient
per briefing; the outbox key makes a second dispatch a no-op.

Owner decision K10, recommended default applied: when the company has an accountant
(an `smmm` membership), the message is held until the accountant releases it. The
screen does not wait; only the e-mail does.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.organization import OrgMembership
from app.models.outbox_message import OutboxMessage
from app.models.user import User, UserRole
from app.services import outbox
from app.services.monday_briefing import MondayBriefing

SOURCE = "monday_briefing"
RECIPIENT_ROLES = (UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.CFO.value)
HELD_FOR_ACCOUNTANT = "awaiting_accountant_release"


async def recipients(db: AsyncSession, org_id: str) -> list[str]:
    """E-mail addresses of the people the briefing is for, each once, in a stable order."""
    member_ids = select(OrgMembership.user_id).where(
        OrgMembership.org_id == org_id, OrgMembership.role.in_(RECIPIENT_ROLES)
    )
    users = (
        await db.execute(
            select(User.email).where(
                User.is_active.is_(True),
                or_(
                    User.id.in_(member_ids),
                    (User.org_id == org_id) & User.role.in_(RECIPIENT_ROLES),
                ),
            )
        )
    ).scalars().all()
    return sorted(set(users))


async def has_accountant(db: AsyncSession, org_id: str) -> bool:
    found = await db.execute(
        select(OrgMembership.id)
        .where(OrgMembership.org_id == org_id, OrgMembership.role == UserRole.SMMM.value)
        .limit(1)
    )
    return found.scalar_one_or_none() is not None


def _message(briefing: MondayBriefing) -> tuple[str, str]:
    subject = f"Pazartesi bülteni — {briefing.week_start}"
    link = f"{get_settings().frontend_url.rstrip('/')}/bulten"
    body = "\n\n".join(
        [
            f"Hafta: {briefing.week_start} – {briefing.week_end}",
            briefing.sentence_radar,
            briefing.sentence_obligation,
            briefing.sentence_action,
            f"Ayrıntılar ve yanıt: {link}",
        ]
    )
    return subject, body


async def enqueue_briefing_emails(
    db: AsyncSession, org_id: str, briefing: MondayBriefing
) -> list[OutboxMessage]:
    """Write one outbox row per recipient. A briefing with nothing to say writes none."""
    if not briefing.has_data:
        return []
    subject, body = _message(briefing)
    held = HELD_FOR_ACCOUNTANT if await has_accountant(db, org_id) else None
    rows = []
    for address in await recipients(db, org_id):
        rows.append(
            await outbox.enqueue(
                db,
                key=f"{SOURCE}:{org_id}:{briefing.briefing_id}:{address}",
                org_id=org_id,
                channel="email",
                recipient=address,
                subject=subject,
                body=body,
                source=SOURCE,
                source_ref=briefing.briefing_id,
                held_reason=held,
            )
        )
    return rows


async def deliveries(db: AsyncSession, org_id: str, briefing_id: str) -> list[dict[str, object]]:
    """What happened to this briefing's e-mails, for the screen."""
    rows = (
        await db.execute(
            select(OutboxMessage)
            .where(
                OutboxMessage.org_id == org_id,
                OutboxMessage.source == SOURCE,
                OutboxMessage.source_ref == briefing_id,
            )
            .order_by(OutboxMessage.recipient)
        )
    ).scalars().all()
    return [
        {
            "recipient": r.recipient,
            "status": r.status,
            "reason": r.last_error,
            "attempts": r.attempts,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        }
        for r in rows
    ]
