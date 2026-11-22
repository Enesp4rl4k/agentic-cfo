"""The company's outside accountant (`smmm`): is there one, and what waits for them across companies.

Many small companies have no finance person; their accountant belongs to several organisations and
does the month close for each. Two questions follow, and both are answered here from MEMBERSHIPS, never
from the organisation the user happens to be acting in:

* `has_active_smmm(org)`: an active user holds an `smmm` membership of that organisation. The screens
  adapt to it (no "send to the accountant" when there is none; a suggestion to invite one).
* `workload(user)`: for every organisation where THIS user is an `smmm`, what awaits them: entries in
  the approval queue, the previous month's close, a briefing held for their release. Every query is
  scoped to the organisation ids of the caller's own smmm memberships, so a company they merely belong
  to in another role, and every company they do not belong to, contribute nothing.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.canonical_transaction import CanonicalTransaction
from app.models.donem_kilidi import DonemKilidi
from app.models.organization import Organization, OrgMembership
from app.models.outbox_message import HELD, OutboxMessage
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.models.user import User, UserRole

SMMM = UserRole.SMMM.value
BRIEFING_SOURCE = "monday_briefing"


async def active_member_ids(
    db: AsyncSession, org_id: str, roles: tuple[str, ...], *, excluding: str | None = None
) -> set[str]:
    """Active users holding one of `roles` in the organisation: by membership row, and (for organisations
    older than memberships, migration 050) by `users.org_id` + `users.role` when they have no membership row
    in it. The role that counts is the one in the organisation, never another organisation's."""
    members = {
        str(u)
        for (u,) in (
            await db.execute(
                select(OrgMembership.user_id)
                .join(User, User.id == OrgMembership.user_id)
                .where(OrgMembership.org_id == org_id, OrgMembership.role.in_(roles), User.is_active.is_(True))
            )
        ).all()
    }
    has_row = select(OrgMembership.id).where(OrgMembership.user_id == User.id, OrgMembership.org_id == org_id)
    legacy = {
        str(u)
        for (u,) in (
            await db.execute(
                select(User.id).where(
                    User.org_id == org_id, User.role.in_(roles), User.is_active.is_(True), ~has_row.exists()
                )
            )
        ).all()
    }
    return (members | legacy) - ({excluding} if excluding else set())


async def has_active_smmm(db: AsyncSession, org_id: str | None) -> bool:
    if not org_id:
        return False
    return bool(await active_member_ids(db, str(org_id), (SMMM,)))


def previous_month(today: datetime | None = None) -> str:
    now = today or datetime.now(UTC)
    year, month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    return f"{year}-{month:02d}"


def _month_bounds(period: str) -> tuple[datetime, datetime]:
    year, month = int(period[:4]), int(period[5:7])
    nxt = (year + 1, 1) if month == 12 else (year, month + 1)
    return datetime(year, month, 1, tzinfo=UTC), datetime(nxt[0], nxt[1], 1, tzinfo=UTC)


async def workload(db: AsyncSession, user_id: str, *, today: datetime | None = None) -> dict[str, Any]:
    """The caller's organisations as an accountant, each with the counts that await them."""
    orgs = (
        await db.execute(
            select(Organization.id, Organization.name)
            .join(OrgMembership, OrgMembership.org_id == Organization.id)
            .where(
                OrgMembership.user_id == user_id, OrgMembership.role == SMMM, Organization.is_active.is_(True),
            )
            .order_by(Organization.name)
        )
    ).all()
    org_ids = [str(o.id) for o in orgs]
    if not org_ids:
        return {"organizations": [], "total_waiting": 0}

    pending = {
        str(o): int(n)
        for o, n in (
            await db.execute(
                select(SMMMOnayKaydi.org_id, func.count())
                .where(SMMMOnayKaydi.org_id.in_(org_ids), SMMMOnayKaydi.durum == OnayDurumu.BEKLIYOR)
                .group_by(SMMMOnayKaydi.org_id)
            )
        ).all()
    }
    held = {
        str(o): int(n)
        for o, n in (
            await db.execute(
                select(OutboxMessage.org_id, func.count(func.distinct(OutboxMessage.source_ref)))
                .where(
                    OutboxMessage.org_id.in_(org_ids), OutboxMessage.source == BRIEFING_SOURCE,
                    OutboxMessage.status == HELD,
                )
                .group_by(OutboxMessage.org_id)
            )
        ).all()
    }
    period = previous_month(today)
    start, end = _month_bounds(period)
    closed = {
        str(o)
        for (o,) in (
            await db.execute(
                select(DonemKilidi.org_id).where(DonemKilidi.org_id.in_(org_ids), DonemKilidi.donem == period)
            )
        ).all()
    }
    with_rows = {
        str(o)
        for (o,) in (
            await db.execute(
                select(CanonicalTransaction.org_id)
                .where(
                    CanonicalTransaction.org_id.in_(org_ids),
                    CanonicalTransaction.transaction_date >= start,
                    CanonicalTransaction.transaction_date < end,
                    CanonicalTransaction.corrects_id.is_(None),
                )
                .group_by(CanonicalTransaction.org_id)
            )
        ).all()
    }
    out = []
    for o in orgs:
        oid = str(o.id)
        to_close = oid in with_rows and oid not in closed
        row = {
            "org_id": oid, "name": o.name,
            "pending_onay": pending.get(oid, 0),
            "month_to_close": period if to_close else None,
            "briefings_held": held.get(oid, 0),
        }
        row["waiting"] = row["pending_onay"] + (1 if to_close else 0) + row["briefings_held"]
        out.append(row)
    return {"organizations": out, "total_waiting": sum(int(r["waiting"]) for r in out)}
