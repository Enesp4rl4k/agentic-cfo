"""The one place a caller's role in the organisation they are acting in is read.

`users.role` is a single global column; the role that counts is the caller's
*membership* role in `users.org_id` (see `services/org_membership.py`). Every
role check, guard or inline, reads it here. A user with no membership row in
the acting organisation (a demo guest, a row older than migration 050) falls
back to `users.role`, which switching organisation keeps equal to the
membership role; a user with no organisation also gets `users.role`, so a check
that used to read the column decides exactly as before.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import OrgMembership


async def acting_role(db: AsyncSession, user: Any) -> str:
    """Membership role in the acting organisation, else `users.role`."""
    if user.org_id:
        role = (
            await db.execute(
                select(OrgMembership.role).where(
                    OrgMembership.user_id == str(user.id), OrgMembership.org_id == str(user.org_id)
                )
            )
        ).scalar_one_or_none()
        if role is not None:
            return str(role)
    return str(getattr(user.role, "value", user.role))
