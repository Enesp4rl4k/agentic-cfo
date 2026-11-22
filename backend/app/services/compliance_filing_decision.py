"""The decision record of an outward compliance filing (breach record, breach notification, SOX 302)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecidedVia, DecisionKind
from app.models.user import User
from app.services.acting_role import acting_role
from app.services.decisions import record_decision


async def record_filing(
    db: AsyncSession, user: User, *, org_id: str, target_type: str, target_id: str, outcome: str,
    before: dict[str, Any] | None, after: dict[str, Any],
) -> None:
    """A decider files or certifies something outward: the record is written beside the filing, in its
    transaction. Nothing free-typed is copied (no description, no certifier name): the filing itself keeps those."""
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.COMPLIANCE_FILING, target_type=target_type, target_id=target_id,
        outcome=outcome, decided_via=DecidedVia.HUMAN, decided_by=str(user.id), before=before,
        after={**after, "acting_role": await acting_role(db, user)},
    )
