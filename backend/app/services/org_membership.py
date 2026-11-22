"""Who belongs to which organisation, and in what role.

Until now a user had exactly one `org_id`, and every tenancy check in the app
compares it with the object's `org_id` (`app/api/access.py`). That is why an
accountant's clients had no place to live: every client's data ended up in the
accountant's one organisation.

The model here keeps that comparison untouched. A user may *belong* to several
organisations (`OrgMembership`), but is *acting in* exactly one — `users.org_id`
— and switching the acting organisation is the only way to reach another one.
Every existing route keeps checking `user.org_id`, so no route gained a new way
to see somebody else's data. What changed is only who may change `org_id`: a
user can switch to an organisation they have a membership row for, and
memberships are created by exactly three things — creating the organisation,
accepting its invitation, and an accountant adding a client.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization, OrgMembership
from app.models.user import User, UserRole

VALID_ROLES = frozenset(r.value for r in UserRole)


async def ensure_membership(
    db: AsyncSession, *, user_id: str, org_id: str, role: str
) -> OrgMembership:
    """The user's membership of the organisation, created if absent. Idempotent.

    An existing row keeps its role: a later call must not quietly promote
    someone. The caller commits.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"unknown role: {role!r}")
    row = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == str(user_id), OrgMembership.org_id == str(org_id)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = OrgMembership(user_id=str(user_id), org_id=str(org_id), role=role)
        db.add(row)
        await db.flush()
    return row


def _slug(name: str) -> str:
    base = re.sub(r"[\s_-]+", "-", re.sub(r"[^\w\s-]", "", name.lower().strip())).strip("-")
    return f"{base[:60] or 'musteri'}-{uuid.uuid4().hex[:6]}"


async def create_client_org(
    db: AsyncSession, *, name: str, accountant_user_id: str, home_org_id: str | None,
    home_role: str, vkn: str | None = None,
) -> Organization:
    """A client company as its own organisation, with the accountant as its `smmm`.

    Turkish defaults, since the SMMM portal only exists for the Turkey pack. The
    accountant's own organisation is recorded as a membership too, so switching
    to a client can always be undone. The caller commits.
    """
    from app.services.org_identity import normalize, vkn_gecerli

    org = Organization(
        name=name,
        # A VKN typed in with the client is kept only if it is well formed;
        # a malformed one is left unset (and invoices held) rather than guessed.
        vkn=normalize(vkn) if vkn_gecerli(vkn) else None,
        slug=_slug(name),
        country_code="TR",
        base_currency="TRY",
        locale="tr-TR",
        regional_packs=["tr"],
    )
    db.add(org)
    await db.flush()
    await ensure_membership(
        db, user_id=accountant_user_id, org_id=org.id, role=UserRole.SMMM.value
    )
    if home_org_id:
        await ensure_membership(
            db, user_id=accountant_user_id, org_id=home_org_id, role=home_role
        )
    return org


async def drop_membership(db: AsyncSession, *, user_id: str, org_id: str) -> None:
    """End a user's membership of an organisation. The caller commits.

    The row *is* the right to be there: `/org/switch`, `require_smmm`,
    `org_has_smmm` and the member list all read it, so deleting it removes the
    person everywhere at once. If the organisation is the one they are acting in,
    they fall back to another they still belong to (their home, for an
    accountant), else to none.
    """
    row = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == str(user_id), OrgMembership.org_id == str(org_id)
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.flush()
    user = await db.get(User, str(user_id))
    if user is not None and user.org_id and str(user.org_id) == str(org_id):
        other = (
            await db.execute(
                select(OrgMembership)
                .where(OrgMembership.user_id == str(user_id), OrgMembership.org_id != str(org_id))
                .order_by(OrgMembership.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        user.org_id = other.org_id if other is not None else None
        user.role = other.role if other is not None else UserRole.ANALYST.value
