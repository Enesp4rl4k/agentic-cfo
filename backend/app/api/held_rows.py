"""Rows the system would not book alone: list them, answer them, confirm the company currency.

GET  /held-rows[?job_id=]            the caller's organisation's rows that wait for a person
POST /held-rows/release              release as is, or corrected (type, currency, date, amount)
POST /held-rows/reject               discard
GET  /org/base-currency              the company currency and whether anyone confirmed it
POST /org/base-currency              owner or admin confirms it; rows held only for it are released

Every answer is a recorded decision (services/decisions.py). Scoped to the caller's
organisation: another organisation's rows are never listed and never resolved.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import require_decider, require_writer
from app.api.auth import get_current_user
from app.database import get_db
from app.models.decision import DecidedVia, DecisionKind
from app.models.organization import Organization
from app.models.user import User
from app.services import held_rows
from app.services.decisions import record_decision

router = APIRouter()


class HeldAction(BaseModel):
    ids: list[str] | None = None
    job_id: str | None = None
    reason: str | None = None          # a reason code, e.g. "currency_unknown"
    document_id: str | None = None
    # row id -> the fields a person fixed: type, currency, transaction_date, amount_cents
    corrections: dict[str, dict[str, Any]] | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=1000)


class CurrencyConfirmation(BaseModel):
    currency: str = Field(min_length=3, max_length=3)


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(status_code=409, detail="Bu işlem bir şirket gerektirir.")
    return str(user.org_id)


@router.get("/held-rows")
async def list_held_rows(
    job_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await held_rows.list_pending(db, _org(user), job_id)
    return {"data": {"count": len(rows), "rows": rows}, "error": None}


async def _answer(body: HeldAction, user: User, db: AsyncSession, *, release: bool) -> dict:
    try:
        out = await held_rows.resolve(
            db, _org(user), user_id=user.id, release=release, ids=body.ids, job_id=body.job_id,
            reason=body.reason, document_id=body.document_id, corrections=body.corrections,
            currency=body.currency, note=body.note,
        )
    except held_rows.CorrectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": out, "error": None}


@router.post("/held-rows/release", dependencies=[Depends(require_writer)])
async def release_held_rows(
    body: HeldAction, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return await _answer(body, user, db, release=True)


@router.post("/held-rows/reject", dependencies=[Depends(require_writer)])
async def reject_held_rows(
    body: HeldAction, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return await _answer(body, user, db, release=False)


@router.get("/org/base-currency")
async def get_base_currency(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    org = await db.get(Organization, _org(user))
    confirmed = org is not None and org.base_currency_confirmed_at is not None
    waiting = len(await held_rows.pending_rows(db, _org(user), reason=held_rows.CURRENCY_REASON))
    return {
        "data": {
            # The stored value is only the column default until someone confirms it.
            "currency": org.base_currency if org is not None and confirmed else None,
            "confirmed": confirmed,
            "waiting_for_currency": waiting,
        },
        "error": None,
    }


@router.post("/org/base-currency", dependencies=[Depends(require_decider)])
async def confirm_base_currency(
    body: CurrencyConfirmation, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    code = body.currency.strip().upper()
    if not code.isalpha():
        raise HTTPException(status_code=422, detail="currency must be an ISO-4217 code")
    org = await db.get(Organization, _org(user))
    if org is None:
        raise HTTPException(status_code=404, detail="Not found.")
    before = {"currency": org.base_currency, "confirmed": org.base_currency_confirmed_at is not None}
    org.base_currency = code
    org.base_currency_confirmed_at = datetime.now(UTC)
    org.base_currency_confirmed_by = user.id
    await record_decision(
        db, org_id=org.id, kind=DecisionKind.BASE_CURRENCY_CONFIRMATION, target_type="organization",
        target_id=org.id, outcome=code, decided_via=DecidedVia.HUMAN, decided_by=user.id,
        before=before, after={"currency": code, "confirmed": True},
    )
    await db.commit()
    released = await held_rows.fill_currency(db, org.id, user.id, code)
    return {"data": {"currency": code, "confirmed": True, "released": released}, "error": None}
