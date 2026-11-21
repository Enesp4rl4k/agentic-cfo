"""Rows the system would not book alone: list them, answer them, confirm the company currency.

GET    /held-rows[?job_id=]                 the caller's organisation's rows that wait for a person (any member)
GET    /held-rows/file-questions            files whose direction nobody could place: one question each (any member)
POST   /held-rows/release                   release as is, or corrected (type, currency, date, amount)
POST   /held-rows/reject                    discard
POST   /held-rows/file-direction            answer a file's question once; applied to every row of the file
GET    /held-rows/direction-mappings        the answers remembered for this organisation's statement formats
DELETE /held-rows/direction-mappings/{id}   forget one: that format is asked again
GET    /org/base-currency                   the company currency and whether anyone confirmed it
POST   /org/base-currency                   owner or admin confirms it; rows held only for it are released

Every answer is a recorded decision (services/decisions.py). Scoped to the caller's
organisation: another organisation's rows are never listed, and ids that are not the
caller's organisation's answer 404.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import (
    may_set_standing_rules,
    require_decider,
    require_decider_or_smmm,
    require_member,
    require_writer,
)
from app.api.auth import get_current_user
from app.database import get_db
from app.models.decision import DecidedVia, DecisionKind
from app.models.organization import Organization
from app.models.user import User
from app.services import held_direction, held_rows
from app.services.acting_role import acting_role
from app.services.decisions import record_decision
from app.services.ingest.currencies import is_currency_code

router = APIRouter()


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found.")


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


class FileDirectionAnswer(BaseModel):
    job_id: str
    file_key: str = Field(max_length=32)
    answer: str = Field(max_length=16)
    remember: bool = True
    note: str | None = Field(default=None, max_length=1000)


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(status_code=400, detail="Bu işlem için bir organizasyon gerekli.")
    return str(user.org_id)


@router.get("/held-rows", dependencies=[Depends(require_member)])
async def list_held_rows(
    job_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await held_rows.list_pending(db, _org(user), job_id)
    return {"data": {"count": len(rows), "rows": rows}, "error": None}


@router.get("/held-rows/file-questions", dependencies=[Depends(require_member)])
async def list_file_questions(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    role = await acting_role(db, user)
    return {"data": {
        "files": await held_direction.list_questions(db, _org(user)),
        # Remembering an answer is a standing rule for that statement format: not every writer may.
        "can_remember": may_set_standing_rules(role),
    }, "error": None}


async def _answer(body: HeldAction, user: User, db: AsyncSession, *, release: bool) -> dict:
    try:
        out = await held_rows.resolve(
            db, _org(user), user_id=user.id, release=release, ids=body.ids, job_id=body.job_id,
            reason=body.reason, document_id=body.document_id, corrections=body.corrections,
            currency=body.currency, note=body.note,
        )
    except held_rows.CorrectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except held_rows.UnknownRows as exc:
        raise _not_found() from exc
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


@router.post("/held-rows/file-direction", dependencies=[Depends(require_writer)])
async def answer_file_direction(
    body: FileDirectionAnswer, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    remember = body.remember and may_set_standing_rules(await acting_role(db, user))
    try:
        out = await held_direction.answer_file(
            db, _org(user), user.id, body.job_id, body.file_key, body.answer,
            remember=remember, note=body.note,
        )
    except held_rows.UnknownRows as exc:
        raise _not_found() from exc
    except (held_direction.AnswerError, held_rows.CorrectionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out["remember_refused"] = bool(body.remember and not remember)
    return {"data": out, "error": None}


@router.get("/held-rows/direction-mappings", dependencies=[Depends(require_member)])
async def list_direction_mappings(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    found = await held_direction.active_mappings(db, _org(user))
    return {"data": {"mappings": [held_direction.describe_mapping(m) for m in found]}, "error": None}


@router.delete("/held-rows/direction-mappings/{mapping_id}", dependencies=[Depends(require_decider_or_smmm)])
async def revoke_direction_mapping(
    mapping_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        await held_direction.revoke_mapping(db, _org(user), user.id, mapping_id)
    except held_rows.UnknownRows as exc:
        raise _not_found() from exc
    return {"data": {"revoked": mapping_id}, "error": None}


@router.get("/org/base-currency", dependencies=[Depends(require_member)])
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
    """The one way to set the company currency: owner or admin, a recorded decision with before and after.

    One transaction: the confirmation, the currency filled on the rows that waited for it, the rows
    released by it and the decisions for each. Rows previously admitted as `currency_assumed` keep
    the currency they were stored with; they are returned in `assumed_for_review`, never rewritten.
    """
    code = body.currency.strip().upper()
    if not is_currency_code(code):
        raise HTTPException(status_code=422, detail="currency must be a known ISO-4217 code")
    org = await db.get(Organization, _org(user))
    if org is None:
        raise _not_found()
    before = {"currency": org.base_currency, "confirmed": org.base_currency_confirmed_at is not None}
    org.base_currency = code
    org.base_currency_confirmed_at = datetime.now(UTC)
    org.base_currency_confirmed_by = user.id
    await record_decision(
        db, org_id=org.id, kind=DecisionKind.BASE_CURRENCY_CONFIRMATION, target_type="organization",
        target_id=org.id, outcome=code, decided_via=DecidedVia.HUMAN, decided_by=user.id,
        before=before, after={"currency": code, "confirmed": True},
    )
    released, jobs = await held_rows.fill_currency(db, org.id, user.id, code)
    review = await held_rows.assumed_under_other_currency(db, org.id, code)
    await db.commit()
    released["ledger"] = await held_rows.append_released(db, jobs)
    return {"data": {
        "currency": code, "confirmed": True, "released": released, "assumed_for_review": review,
    }, "error": None}
