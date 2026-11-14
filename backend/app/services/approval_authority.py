"""Who may decide a held journal entry.

The authority matrix (`app/platform/authority_matrix.py`) says what an entry
needs: "an owner" for a related-party or high-value one, "an smmm" for a
low-confidence, unclassified or fixed-asset one. It was written on the entry and
then never read: the approval routes asked only that the caller belonged to the
organisation, so a `viewer` could approve an entry the policy reserved for the
owner. This is the reading.

Rules (decided by the owner, 2026-11-13):

* `viewer` and `analyst` never decide.
* "owner required": only an owner. Not the accountant, not an admin.
* "smmm required": an `smmm`. When the organisation has no accountant at all (a
  company that keeps its own books, no `smmm` member), an owner, admin or cfo
  may, so such a company is not locked out of its own queue.
* An entry with no recorded requirement is treated as "smmm required".
* A requirement the single approver column cannot hold — several roles, or a
  count above one — is refused, saying why, rather than quietly relaxed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import OrgMembership
from app.models.user import UserRole

_NEVER = frozenset({UserRole.VIEWER.value, UserRole.ANALYST.value})
_OWN_BOOKS = frozenset({UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.CFO.value})
_DEFAULT_REQUIREMENT = [{"role": UserRole.SMMM.value, "count": 1}]


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""


def verdict(user_role: str, authority: dict[str, Any] | None, org_has_smmm: bool) -> Verdict:
    """Pure: may a user with `user_role` decide an entry with this `authority`?"""
    role = str(user_role)
    if role in _NEVER:
        return Verdict(False, "Bu rol kayıt onaylayamaz.")

    reqs = list((authority or {}).get("required_approvals") or []) or _DEFAULT_REQUIREMENT
    if len(reqs) != 1 or int(reqs[0].get("count", 1) or 1) != 1:
        return Verdict(
            False,
            "Bu kayıt birden fazla onay gerektiriyor; çoklu onay henüz desteklenmiyor.",
        )
    needed = str(reqs[0].get("role"))

    if needed == UserRole.OWNER.value:
        ok = role == UserRole.OWNER.value
        return Verdict(ok, "" if ok else "Bu kayıt için şirket sahibinin (owner) onayı gerekiyor.")
    if needed == UserRole.SMMM.value:
        ok = role == UserRole.SMMM.value or (not org_has_smmm and role in _OWN_BOOKS)
        if ok:
            return Verdict(True)
        return Verdict(
            False,
            "Bu kayıt için mali müşavirin (smmm) onayı gerekiyor."
            if org_has_smmm
            else "Bu kaydı owner, admin veya cfo onaylayabilir.",
        )
    ok = role == needed
    return Verdict(ok, "" if ok else f"Bu kayıt için '{needed}' rolünün onayı gerekiyor.")


async def org_has_smmm(db: AsyncSession, org_id: str | None) -> bool:
    if not org_id:
        return False
    row = (
        await db.execute(
            select(OrgMembership.id)
            .where(OrgMembership.org_id == str(org_id), OrgMembership.role == UserRole.SMMM.value)
            .limit(1)
        )
    ).first()
    return row is not None


async def check(db: AsyncSession, user: Any, kayit: Any) -> Verdict:
    """`verdict` for a review row (`SMMMOnayKaydi`) and the acting user."""
    authority = (kayit.orijinal_kayit or {}).get("authority")
    return verdict(str(user.role), authority, await org_has_smmm(db, kayit.org_id))
