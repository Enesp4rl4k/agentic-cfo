"""Who an organisation is, legally: its tax number and title.

The VKN used to be one global setting (`GIB_VKN`). With an accountant's clients
as organisations of their own, that number belongs to the organisation: an
invoice's direction (did we sell or buy?) is decided by comparing the parties'
VKN with *ours*, and the e-Defter names its owner by it. With one global value,
every company but one got "direction unknown" — or, worse, a wrong direction
when the global company was a party to someone else's invoice.

An organisation with no VKN of its own falls back to the global setting only
when it is not a client organisation (nobody is its `smmm`). A client with no
VKN yet gets none: its invoices are held for review rather than judged against
the accountant's number.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization, OrgMembership
from app.models.user import UserRole


def normalize(raw: str | None) -> str:
    """Digits only; "" unless it is 10 (VKN) or 11 (TCKN) digits."""
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) in (10, 11) else ""


def vkn_gecerli(raw: str | None) -> bool:
    """Whether `raw` is a well-formed VKN (10 digits) or TCKN (11), by checksum.

    Checked when a person types it in: one mistyped digit would otherwise
    silently turn every invoice's direction around.
    """
    n = normalize(raw)
    if len(n) == 10:
        d = [int(c) for c in n]
        total = 0
        for i in range(9):
            tmp = (d[i] + (9 - i)) % 10
            p = (tmp * (2 ** (9 - i))) % 9
            if tmp != 0 and p == 0:
                p = 9
            total += p
        return (10 - total % 10) % 10 == d[9]
    if len(n) == 11:
        d = [int(c) for c in n]
        if d[0] == 0:
            return False
        if ((sum(d[0:9:2]) * 7) - sum(d[1:8:2])) % 10 != d[9]:
            return False
        return sum(d[:10]) % 10 == d[10]
    return False


async def is_client_org(db: AsyncSession, org_id: str) -> bool:
    row = (
        await db.execute(
            select(OrgMembership.id)
            .where(OrgMembership.org_id == str(org_id), OrgMembership.role == UserRole.SMMM.value)
            .limit(1)
        )
    ).first()
    return row is not None


async def vkn_of(db: AsyncSession, org_id: str | None) -> str:
    """The organisation's own VKN, or "" when it has none that can be trusted."""
    if not org_id:
        return _legacy()
    org = await db.get(Organization, str(org_id))
    own = normalize(getattr(org, "vkn", None)) if org is not None else ""
    if own:
        return own
    if await is_client_org(db, str(org_id)):
        return ""
    return _legacy()


def _legacy() -> str:
    from app.config import get_settings

    return normalize(get_settings().gib_vkn)


async def own_vkn(org_id: str | None) -> str:
    """`vkn_of` on its own short session, for code that has none (the agents)."""
    from app.database import session_factory

    async with session_factory()() as db:
        return await vkn_of(db, org_id)
