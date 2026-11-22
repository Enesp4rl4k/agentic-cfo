"""Counterparty aliases and the undo of a confirmed settlement (plan v10 G23).

Declaring two counterparties one supplier is its own decision, apart from "this duplicate is the same
document" (`/ledger/rows/{id}/resolve`, any writer). Here it needs an owner or admin (a decider) or the
accountant (`smmm`): it changes how every later upload of either spelling is read. See
`services/duplicate_resolution.py`.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant, require_writer
from app.api.auth import get_current_user, require_role
from app.database import get_db
from app.models.canonical_transaction import CanonicalTransaction
from app.models.counterparty_alias import CounterpartyAlias
from app.models.decision import DecidedVia, DecisionKind
from app.models.open_item_match import OpenItemMatch
from app.models.user import User
from app.services.acting_role import acting_role
from app.services.decisions import record_decision
from app.services.duplicate_resolution import (
    AliasRefused,
    confirm_alias,
    list_aliases,
    propose_alias,
    revoke_alias,
    rows_ingested_under,
)
from app.services.reconciliation import CONFIRMED, REJECTED, settle_from_matches
from app.services.settlement_decisions import latest_decision_id

router = APIRouter()

# An owner or admin (the deciders, `access.DECIDER_ROLES`) or the accountant: it changes how every later
# upload of either spelling is read. A plain writer (cfo) can answer a duplicate, not make this rule.
require_alias_authority = require_role("owner", "admin", "smmm")


class AliasRequest(BaseModel):
    row_id: str
    # The caller states it has shown the person the consequence text it was given.
    confirm: Literal[True]


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Bu işlem için bir organizasyon gerekli.")
    return str(user.org_id)


async def _load_owned(db: AsyncSession, user: User, alias_id: str) -> CounterpartyAlias:
    alias = await db.get(CounterpartyAlias, alias_id)
    if alias is None:
        raise HTTPException(404, "Eşleme bulunamadı.")
    ensure_tenant(user, org_id=alias.org_id)
    return alias


def _refusal(exc: AliasRefused) -> HTTPException:
    return HTTPException(409, {"reason": exc.reason, "message": exc.detail})


@router.get("/ledger/rows/{row_id}/alias-proposal", responses={404: {"description": "No such row."}})
async def get_alias_proposal(
    row_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """What excluding this row suggests (both names, the consequence in words), or why nothing."""
    _org(user)
    row = await db.get(CanonicalTransaction, row_id)
    if row is None:
        raise HTTPException(404, "Kayıt bulunamadı.")
    ensure_tenant(user, org_id=row.org_id)
    try:
        proposal = await propose_alias(db, row)
    except AliasRefused as exc:
        raise _refusal(exc) from exc
    return {"data": proposal.as_dict(str(row.id)), "error": None}


@router.post(
    "/ledger/counterparty-aliases",
    dependencies=[Depends(require_alias_authority)],
    responses={403: {"description": "Not an owner, admin or accountant."}, 404: {"description": "No such row."},
               409: {"description": "These two cannot be declared one supplier."}},
)
async def create_alias(
    body: AliasRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Declare the two counterparties of an excluded duplicate one supplier (a decision of its own)."""
    _org(user)
    row = await db.get(CanonicalTransaction, body.row_id)
    if row is None:
        raise HTTPException(404, "Kayıt bulunamadı.")
    ensure_tenant(user, org_id=row.org_id)
    try:
        done = await confirm_alias(db, user=user, row=row)
    except AliasRefused as exc:
        await db.rollback()
        raise _refusal(exc) from exc
    await db.commit()
    return {"data": done, "error": None}


@router.get("/ledger/counterparty-aliases")
async def get_aliases(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """This organisation's aliases, active and revoked."""
    return {"data": await list_aliases(db, _org(user)), "error": None}


@router.get("/ledger/counterparty-aliases/{alias_id}/rows")
async def get_alias_rows(
    alias_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Rows ingested while the alias was applied: the ones to review if it is revoked."""
    _org(user)
    alias = await _load_owned(db, user, alias_id)
    return {"data": await rows_ingested_under(db, alias), "error": None}


@router.delete(
    "/ledger/counterparty-aliases/{alias_id}",
    dependencies=[Depends(require_alias_authority)],
    responses={403: {"description": "Not an owner, admin or accountant."}, 404: {"description": "No such alias."},
               409: {"description": "Already revoked."}},
)
async def delete_alias(
    alias_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Revoke an alias: later uploads read the two names as two suppliers; past rows are listed, not rewritten."""
    _org(user)
    alias = await _load_owned(db, user, alias_id)
    try:
        done = await revoke_alias(db, user=user, alias=alias)
    except AliasRefused as exc:
        await db.rollback()
        raise _refusal(exc) from exc
    await db.commit()
    return {"data": done, "error": None}


@router.post(
    "/ledger/settlements/{match_id}/undo",
    dependencies=[Depends(require_writer)],
    responses={404: {"description": "No such match."}, 409: {"description": "Not a confirmed match."}},
)
async def undo_settlement(
    match_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Take back a confirmed match: the invoice is open again, the bank line is its own money again.

    The way out for money matched to a document that turns out to be a duplicate: the duplicate
    cannot be excluded while a confirmed match stands.
    """
    _org(user)
    match = await db.get(OpenItemMatch, match_id)
    if match is None:
        raise HTTPException(404, "Kayıt bulunamadı.")
    ensure_tenant(user, org_id=match.org_id)
    org_id, item_id = str(match.org_id), str(match.open_item_id)
    role = await acting_role(db, user)
    won = await db.execute(
        update(OpenItemMatch)
        .where(OpenItemMatch.id == match_id, OpenItemMatch.status == CONFIRMED)
        .values(status=REJECTED, decided_by=str(user.id))
        .execution_options(synchronize_session=False)
    )
    if won.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Bu eşleşme onaylı değil.")
    await settle_from_matches(db, [item_id])
    # The reversal is its own decision, linked to the confirmation it takes back (a person's or a rule's).
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.SETTLEMENT_MATCH, target_type="open_item_match", target_id=match_id,
        outcome="undone", decided_via=DecidedVia.HUMAN, decided_by=str(user.id),
        evidence_refs=[{"type": "open_item", "id": item_id}],
        before={"status": "confirmed"}, after={"status": "rejected", "acting_role": role},
        supersedes_id=await latest_decision_id(db, org_id, "open_item_match", match_id),
    )
    await db.commit()
    return {"data": {"id": match_id, "status": "rejected", "open_item_id": item_id}, "error": None}
