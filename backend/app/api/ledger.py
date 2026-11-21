"""The company ledger: what it holds, and the rows waiting for a person."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant, require_writer
from app.api.auth import get_current_user
from app.api.contract import Envelope
from app.api.ledger_schema import LedgerSummaryOut
from app.api.radar_schema import CashRadarOut
from app.core.invoice_identity import key_number
from app.database import get_db
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.models.user import User
from app.services.cash_radar import compute_cash_radar
from app.services.duplicate_resolution import settle_resolution
from app.services.ledger import (
    ACTIVE,
    EXCLUDED,
    POSSIBLE_DUPLICATE,
    Period,
    ledger_summary,
    load_aliases,
    source_transaction,
)
from app.services.ledger_documents import MAX_VARIANTS, MatchedMoney, base_key, variant_rows
from app.services.reconciliation import (
    BY_SUM,
    CONFIRMED,
    PROPOSED,
    REJECTED,
    payment_behaviour,
    settle_from_matches,
)

router = APIRouter()


class ResolveRequest(BaseModel):
    action: Literal["keep", "exclude"]


class SettlementRequest(BaseModel):
    action: Literal["confirm", "reject"]


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Bu işlem için bir organizasyon gerekli.")
    return str(user.org_id)


def _row(r: CanonicalTransaction) -> dict[str, Any]:
    return {
        "id": r.id,
        "transaction_date": r.transaction_date.isoformat()[:10],
        "amount_cents": r.amount_cents,
        "currency": r.currency,
        "direction": r.direction,
        "description": r.description,
        "category": r.category,
        "source_job_id": r.source_job_id,
    }


@router.get(
    "/ledger/summary",
    response_model=Envelope[LedgerSummaryOut],
    responses={400: {"description": "The user has no organisation, or the period is not valid."}},
)
async def get_summary(
    start: str | None = None,
    end: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Figures for one period of whole months (`start`, `end` as YYYY-MM).

    With neither, the last 12 months of data; the period used is in `data.period`.
    """
    try:
        period = Period(start or None, end or None)
    except ValueError:
        raise HTTPException(400, "Geçersiz dönem (YYYY-AA biçiminde, başlangıç bitişten sonra olamaz).") from None
    return {"data": await ledger_summary(db, _org(user), period), "error": None}


@router.get("/ledger/possible-duplicates", responses={400: {"description": "The user has no organisation."}})
async def get_possible_duplicates(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Rows that may repeat money already in the ledger, with what they may repeat."""
    org_id = _org(user)
    rows = (await db.execute(
        select(CanonicalTransaction)
        .where(CanonicalTransaction.org_id == org_id, CanonicalTransaction.ledger_status == POSSIBLE_DUPLICATE)
        .order_by(CanonicalTransaction.transaction_date)
    )).scalars().all()
    aliases = await load_aliases(db, org_id)
    versions = await variant_rows(db, org_id, [base_key(r.source_record_id) for r in rows])
    data = []
    for row in rows:
        match = await db.get(CanonicalTransaction, row.duplicate_of) if row.duplicate_of else None
        match = match if match and match.org_id == org_id else None
        data.append({
            **await _with_counterparty(db, row, aliases),
            "reason": _reason(row, match, len(versions.get(base_key(row.source_record_id), [])) - 1),
            "matches": [await _with_counterparty(db, match, aliases)] if match else [],
        })
    return {"data": data, "error": None}


async def _with_counterparty(db: AsyncSession, row: CanonicalTransaction, aliases: dict[str, str]) -> dict[str, Any]:
    """The row, and the counterparty its upload wrote (the ledger row keeps only the vendor)."""
    tx = await source_transaction(db, row, aliases)
    return {**_row(row), "counterparty": tx.counterparty if tx else None}


def _reason(row: CanonicalTransaction, match: CanonicalTransaction | None, variants: int = 0) -> str:
    """Why the row is held, in words the screen can show."""
    if variants >= MAX_VARIANTS:
        return "many_versions"  # "çok sayıda sürüm": one number keeps meeting documents that are not it
    number = key_number(row.source_record_id)
    if match is not None and number and number == key_number(match.source_record_id):
        return "same_number_may_be_a_different_document"  # "aynı numara, farklı belge olabilir"
    return "same_amount_close_in_time"


@router.get("/ledger/open-items", responses={400: {"description": "The user has no organisation."}})
async def get_open_items(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """What this company is owed and owes, soonest due first; undated last."""
    rows = (await db.execute(
        select(OpenItem)
        .where(OpenItem.org_id == _org(user), OpenItem.status == "open")
        .order_by(OpenItem.due_date.is_(None), OpenItem.due_date, OpenItem.issue_date)
    )).scalars()
    return {
        "data": [
            {
                "id": i.id,
                "direction": i.direction,
                "counterparty": i.counterparty,
                "description": i.description,
                "amount_cents": i.amount_cents,
                "currency": i.currency,
                "issue_date": i.issue_date.isoformat(),
                "due_date": i.due_date.isoformat() if i.due_date else None,
                "payment_note": i.payment_note,
            }
            for i in rows
        ],
        "error": None,
    }


@router.get("/ledger/settlements/proposed", responses={400: {"description": "The user has no organisation."}})
async def get_proposed_settlements(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Bank movements that may pay an invoice, waiting for a person."""
    org_id = _org(user)
    matches = (await db.execute(
        select(OpenItemMatch)
        .where(OpenItemMatch.org_id == org_id, OpenItemMatch.status == PROPOSED)
        .order_by(OpenItemMatch.matched_on)
    )).scalars().all()
    data: list[dict[str, Any]] = []
    lumps: dict[str, dict[str, Any]] = {}
    for m in matches:
        item = await db.get(OpenItem, m.open_item_id)
        row = await db.get(CanonicalTransaction, m.ledger_row_id)
        if item is None or row is None:
            continue
        shown = {
            "counterparty": item.counterparty,
            "description": item.description,
            "amount_cents": item.amount_cents,
            "paid_cents": item.paid_cents,
            "due_date": item.due_date.isoformat() if item.due_date else None,
        }
        if m.method == BY_SUM and m.ledger_row_id in lumps:
            # One transfer paying several invoices is one question, not several.
            lumps[m.ledger_row_id]["items"].append(shown)
            lumps[m.ledger_row_id]["amount_cents"] += m.amount_cents
            continue
        entry = {
            "id": m.id,
            "amount_cents": m.amount_cents,
            "method": m.method,
            "row": _row(row),
            "item": shown,
            "items": [shown],
        }
        if m.method == BY_SUM:
            lumps[m.ledger_row_id] = entry
        data.append(entry)
    return {"data": data, "error": None}


def _refresh_view(org_id: str) -> None:
    """A decision changes what the ledger counts, so the company's view follows."""
    from app.core.background import spawn
    from app.post_completion import refresh_company_view_detached

    spawn(refresh_company_view_detached(org_id), name=f"ledger-view-{org_id[:8]}")


@router.post(
    "/ledger/settlements/{match_id}/resolve",
    dependencies=[Depends(require_writer)],
    responses={
        400: {"description": "The user has no organisation."},
        404: {"description": "No such proposal in this organisation."},
        409: {"description": "Already decided."},
    },
)
async def resolve_settlement(
    match_id: str,
    body: SettlementRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """A person's call. "Reject" is remembered: the line counts as its own money."""
    _org(user)
    match = await db.get(OpenItemMatch, match_id)
    if match is None:
        raise HTTPException(404, "Kayıt bulunamadı.")
    ensure_tenant(user, org_id=match.org_id)
    org_id = str(match.org_id)   # the commit below expires the row
    # A lump (one transfer, several invoices) is answered as a whole.
    group = [match]
    if match.method == BY_SUM:
        group = list((await db.execute(
            select(OpenItemMatch).where(
                OpenItemMatch.ledger_row_id == match.ledger_row_id,
                OpenItemMatch.org_id == match.org_id,
                OpenItemMatch.method == BY_SUM,
                OpenItemMatch.status == PROPOSED,
            )
        )).scalars())
    members = [(m.id, m.open_item_id, m.amount_cents) for m in group]
    won = await db.execute(
        update(OpenItemMatch)
        .where(OpenItemMatch.id.in_([m[0] for m in members]), OpenItemMatch.status == PROPOSED)
        .values(status=CONFIRMED if body.action == "confirm" else REJECTED, decided_by=str(user.id))
        .execution_options(synchronize_session=False)
    )
    if won.rowcount != len(members):
        await db.rollback()
        raise HTTPException(409, "Bu öneri karar beklemiyor.")
    if body.action == "confirm":
        await settle_from_matches(db, [item_id for _, item_id, _ in members])
    await db.commit()
    _refresh_view(org_id)
    return {"data": {"id": match_id, "action": body.action}, "error": None}


@router.get("/ledger/payment-behaviour", responses={400: {"description": "The user has no organisation."}})
async def get_payment_behaviour(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """How late each counterparty really settles, from matched bank movements."""
    return {"data": await payment_behaviour(db, _org(user)), "error": None}


@router.get(
    "/ledger/cash-radar",
    response_model=Envelope[CashRadarOut],
    responses={400: {"description": "The user has no organisation or invalid date."}},
)
async def get_cash_radar(
    anchor_date: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The next 13 weeks of open invoices against the last proven bank balance."""
    parsed_anchor: date | None = None
    if anchor_date:
        try:
            parsed_anchor = date.fromisoformat(anchor_date)
        except ValueError:
            raise HTTPException(400, "Geçersiz tarih biçimi (YYYY-AA-GG bekleniyor).") from None
    org_id = _org(user)
    result = await compute_cash_radar(db, org_id, anchor_date=parsed_anchor)
    # O5: what the owner sees today is kept as today's forecast. A past anchor is
    # hindsight and record_forecast refuses it.
    from app.services.radar_forecast_log import knows_something, record_forecast

    if knows_something(result):
        await record_forecast(db, org_id, result, today=datetime.now(UTC).date())
        await db.commit()
    return {"data": result.to_dict(), "error": None}


@router.post(
    "/ledger/rows/{row_id}/resolve",
    dependencies=[Depends(require_writer)],
    responses={
        400: {"description": "The user has no organisation."},
        404: {"description": "No such row in this organisation."},
        409: {"description": "The row is not waiting for a decision."},
    },
)
async def resolve_possible_duplicate(
    row_id: str,
    body: ResolveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """A person's call: it is separate money (keep), or the same money (exclude).

    An excluded row stays on record; it just is not counted. The call is recorded as a decision,
    opens (keep) or removes (exclude) the row's open item in the same transaction
    (`services/duplicate_resolution.py`). Excluding says nothing about suppliers: when the two rows
    have different counterparties the response carries a `proposed_alias` (both names and what it
    would mean), which a decider or the accountant may confirm separately
    (`POST /ledger/counterparty-aliases`). Money already confirmed against the document refuses the
    answer (409 with the match ids) until `POST /ledger/settlements/{id}/undo`.
    """
    _org(user)
    row = await db.get(CanonicalTransaction, row_id)
    if row is None:
        raise HTTPException(404, "Kayıt bulunamadı.")
    ensure_tenant(user, org_id=row.org_id)
    org_id = str(row.org_id)   # the commit below expires the row
    won = await db.execute(
        update(CanonicalTransaction)
        .where(CanonicalTransaction.id == row_id, CanonicalTransaction.ledger_status == POSSIBLE_DUPLICATE)
        .values(ledger_status=ACTIVE if body.action == "keep" else EXCLUDED)
        .execution_options(synchronize_session=False)
    )
    if won.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Bu kayıt karar beklemiyor.")
    await db.refresh(row)
    try:
        effects = await settle_resolution(db, user=user, row=row, action=body.action)
    except MatchedMoney as exc:
        await db.rollback()
        raise HTTPException(409, {
            "reason": "matched_money",
            "message": "Bu belgeye onaylı bir banka eşleşmesi bağlı; önce eşleşmeyi geri alın.",
            "match_ids": exc.match_ids,
        }) from exc
    await db.commit()
    _refresh_view(org_id)
    return {"data": {"id": row_id, "action": body.action, **effects}, "error": None}
