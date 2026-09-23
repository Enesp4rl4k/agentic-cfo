"""Karar Defteri API — record, list, measure. (P2)

Tenant rules run through `app.api.access` — `load_owned_job` for the job
in the POST body, `ensure_tenant` visibly inside each `{decision_id}`
handler (the structural route test reads the handler source).

Contract edges:
  - mid-run job → 409; no report → 422; unknown option → 422;
  - a second measurement → 409 (the first reading stands — the outcome
    is not re-rewritable, or "what did we expect" loses its meaning);
  - another organisation's decision does not exist (404).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant, load_owned_job
from app.api.auth import get_current_user
from app.database import get_db
from app.models.decision_log import DecisionLog
from app.models.user import User
from app.services.decision_log import DecisionError, measure_outcome, record_decision

router = APIRouter()

_ERROR_STATUS = {
    "running": 409,
    "no_options": 422,
    "unknown_option": 422,
    "already_closed": 409,
    "no_data": 409,
}


class DecisionCreate(BaseModel):
    job_id: str
    option_id: str
    topic: str | None = None
    rationale: str | None = None


class DecisionOutcome(BaseModel):
    note: str | None = None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _serialize(d: DecisionLog) -> dict[str, Any]:
    return {
        "id": d.id,
        "job_id": d.job_id,
        "org_id": d.org_id,
        "topic": d.topic,
        "chosen_option_id": d.chosen_option_id,
        "chosen_option_label": d.chosen_option_label,
        "rationale": d.rationale,
        "expected": d.expected,
        "status": d.status,
        "actual": d.actual,
        "variance": d.variance,
        "outcome_note": d.outcome_note,
        "measured_at": _iso(d.measured_at),
        "created_by": d.created_by,
        "created_at": _iso(d.created_at),
        "updated_at": _iso(d.updated_at),
    }


def _http_error(exc: DecisionError) -> HTTPException:
    return HTTPException(
        status_code=_ERROR_STATUS.get(exc.code, 422), detail=exc.detail
    )


@router.post("/decisions")
async def create_decision(
    body: DecisionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record a decision — `expected` is the packet's, not the caller's."""
    job = await load_owned_job(db, body.job_id, current_user)
    try:
        decision = await record_decision(
            db,
            job=job,
            user_id=current_user.id,
            option_id=body.option_id,
            topic=body.topic,
            rationale=body.rationale,
        )
        await db.commit()
    except DecisionError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return {"data": _serialize(decision), "error": None}


@router.get("/decisions")
async def list_decisions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    job_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """This org's ledger, newest first (its own decisions when org-less)."""
    q = select(DecisionLog).order_by(desc(DecisionLog.created_at)).limit(
        max(1, min(limit, 200))
    )
    if current_user.org_id:
        q = q.where(DecisionLog.org_id == current_user.org_id)
    else:
        q = q.where(DecisionLog.created_by == current_user.id)
    if status in ("open", "closed"):
        q = q.where(DecisionLog.status == status)
    if job_id:
        q = q.where(DecisionLog.job_id == job_id)
    rows = (await db.execute(q)).scalars().all()
    return {"data": [_serialize(r) for r in rows], "error": None}


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    decision = await db.get(DecisionLog, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
    ensure_tenant(current_user, org_id=decision.org_id, user_id=decision.created_by)
    return {"data": _serialize(decision), "error": None}


@router.post("/decisions/{decision_id}/outcome")
async def post_outcome(
    decision_id: str,
    body: DecisionOutcome | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Measure what happened since the decision and close the row (once)."""
    decision = await db.get(DecisionLog, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
    ensure_tenant(current_user, org_id=decision.org_id, user_id=decision.created_by)
    try:
        await measure_outcome(
            db, decision=decision, note=body.note if body else None
        )
        await db.commit()
    except DecisionError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return {"data": _serialize(decision), "error": None}
