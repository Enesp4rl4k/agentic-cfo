"""The decision record of a change to the company's identity facts (`PATCH /org/me`)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecidedVia, DecisionKind
from app.models.organization import Organization
from app.models.user import User
from app.services.acting_role import acting_role
from app.services.decisions import record_decision
from app.services.regional.packs import normalize_packs


def identity_view(org: Organization) -> dict[str, Any]:
    """The facts a decision about the company's identity shows. The tax number is masked to its last
    three digits (a sole trader's is a person's national number); the full value stays on the organisation."""
    vkn = getattr(org, "vkn", None)
    return {
        "country_code": getattr(org, "country_code", None),
        "regional_packs": normalize_packs(getattr(org, "regional_packs", None)),
        "vkn": f"{'*' * max(len(vkn) - 3, 0)}{vkn[-3:]}" if vkn else None,
        "legal_title": (getattr(org, "legal_title", None) or "")[:80] or None,
    }


async def record_identity_change(db: AsyncSession, org: Organization, user: User, before: dict[str, Any]) -> None:
    """Name, description, logo, locale and focus mode are housekeeping and decide nothing. The tax number,
    country, regional packs and legal title decide how every document is read (one wrong digit turns every
    invoice's direction around): when one of them really changes, the change is a recorded decision, written
    in the caller's transaction."""
    after = identity_view(org)
    changed = sorted(k for k in before if before[k] != after[k])
    if not changed:
        return
    await record_decision(
        db, org_id=str(org.id), kind=DecisionKind.ORG_IDENTITY_CHANGE, target_type="organization",
        target_id=str(org.id), outcome="changed", decided_via=DecidedVia.HUMAN, decided_by=str(user.id),
        before={k: before[k] for k in changed},
        after={**{k: after[k] for k in changed}, "acting_role": await acting_role(db, user)},
    )
