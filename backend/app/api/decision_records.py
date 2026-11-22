"""The decision record, read-only: who decided what, when, on which evidence.

GET /decision-records   the caller's organisation's decisions, newest first

Filters: `kind`, `target_type`, `target_id`, `decided_by`, `since`, `until` (an aware or UTC datetime; `until` exclusive), `current_only`; paged by `limit`/`offset`.
There is deliberately no write route: decisions are recorded by the endpoints that
make them, inside their own transaction (`app.services.decisions.record_decision`).
Who may read what: the history of ONE object (`target_type` and `target_id` both given) is open to any member
who can see that object, so a viewer can open "Karar geçmişi" on a settlement. The company-wide log (anything
else) is for owner, admin, cfo and smmm (`WRITER_ROLES`): it holds who was invited or removed, the authority
policy and security settings. Another organisation's decisions never appear: the query is scoped to the caller's
organisation, and a caller without one is refused.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import WRITER_ROLES
from app.api.auth import get_current_user
from app.api.contract import Envelope
from app.database import get_db
from app.models.decision import Decision
from app.models.user import User
from app.services import decisions as svc
from app.services.acting_role import acting_role

router = APIRouter()


class EvidenceRef(BaseModel):
    type: str
    id: str


class DecisionView(BaseModel):
    id: str
    kind: str
    target_type: str
    target_id: str
    outcome: str
    decided_by: str | None
    decided_via: str
    rule_id: str | None
    decided_at: datetime
    reason: str | None
    evidence_refs: list[EvidenceRef]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    supersedes_id: str | None
    superseded_by_id: str | None


class DecisionListMeta(BaseModel):
    total: int
    limit: int
    offset: int


class DecisionList(Envelope[list[DecisionView]]):
    meta: DecisionListMeta  # type: ignore[assignment]  # narrows the envelope's free-form meta


def _view(row: Decision, replaced_by: str | None) -> DecisionView:
    return DecisionView(
        id=row.id, kind=row.kind, target_type=row.target_type, target_id=row.target_id,
        outcome=row.outcome, decided_by=row.decided_by, decided_via=row.decided_via,
        rule_id=row.rule_id, decided_at=row.decided_at, reason=row.reason,
        evidence_refs=[EvidenceRef(**r) for r in row.evidence_refs or []],
        before=row.before, after=row.after, supersedes_id=row.supersedes_id,
        superseded_by_id=replaced_by,
    )


@router.get(
    "/decision-records", response_model=DecisionList,
    responses={
        400: {"description": "The user has no organisation."},
        403: {"description": "The company-wide log needs owner, admin, cfo or smmm; one object's history is open to members."},
    },
)
async def list_decision_records(
    kind: str | None = Query(default=None, max_length=40),
    target_type: str | None = Query(default=None, max_length=40),
    target_id: str | None = Query(default=None, max_length=120),
    decided_by: str | None = Query(default=None, max_length=36),
    since: datetime | None = None,
    until: datetime | None = None,
    current_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DecisionList:
    if not user.org_id:
        raise HTTPException(400, "Bu işlem için bir organizasyon gerekli.")
    org_id = str(user.org_id)
    since, until = (d if d is None or d.tzinfo else d.replace(tzinfo=UTC) for d in (since, until))
    one_object = target_type is not None and target_id is not None
    if not one_object and await acting_role(db, user) not in WRITER_ROLES:
        raise HTTPException(403, "Şirket genelindeki karar günlüğü için owner, admin, cfo veya smmm rolü gerekir.")
    rows, total = await svc.list_decisions(
        db, org_id, kind=kind, target_type=target_type, target_id=target_id,
        current_only=current_only, limit=limit, offset=offset, decided_by=decided_by, since=since, until=until,
    )
    replaced = await svc.superseded_ids(db, org_id, [r.id for r in rows])
    return DecisionList(
        data=[_view(r, replaced.get(r.id)) for r in rows],
        meta=DecisionListMeta(total=total, limit=limit, offset=offset),
    )
