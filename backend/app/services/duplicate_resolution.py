"""What a person's answer on a possible duplicate does to the rest of the books (plan v10 G23).

`POST /ledger/rows/{id}/resolve` flips the row's `ledger_status`. Everything that follows from that
answer happens here, in the same database transaction (the caller commits):

- **keep** (it is separate money): the row's open item is opened, so the radar counts the payable.
  A row held as a possible duplicate has none; the radar reads items, not ledger statuses.
- **exclude** (it is the same document): no open item remains for the row, and when both rows are
  invoices with the same free-form number from counterparties that differ only in how they were
  written, the two are linked: `counterparty_aliases` maps the held row's party token to the kept
  row's, and `ingest` reads it from then on (`ledger.record_ids`), so next month's upload of either
  spelling is one supplier.
- either way, one human decision is recorded (`services/decisions.py`, kind `duplicate_resolution`),
  and the alias, if any, points at it.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.invoice_identity import key_number, key_party
from app.models.canonical_transaction import CanonicalTransaction
from app.models.counterparty_alias import CounterpartyAlias
from app.models.decision import DecidedVia, DecisionKind
from app.models.user import User
from app.services.decisions import record_decision
from app.services.ledger import drop_open_item, load_aliases, open_item_for_row
from app.services.reconciliation import reconcile_org


def alias_pair(
    row: CanonicalTransaction, match: CanonicalTransaction | None, aliases: dict[str, str]
) -> tuple[str, str] | None:
    """(alias token, canonical token) if the two rows read as one supplier's invoice under two names."""
    if match is None:
        return None
    mine, theirs = key_party(row.source_record_id), key_party(match.source_record_id)
    if not (mine and theirs and mine[0] == theirs[0] and mine[1] != theirs[1]):
        return None
    if key_number(row.source_record_id) != key_number(match.source_record_id):
        return None
    canonical = aliases.get(theirs[1], theirs[1])  # never a chain
    return (mine[1], canonical) if canonical != mine[1] else None


async def _save_alias(
    db: AsyncSession, org_id: str, pair: tuple[str, str], user: User, decision_id: str
) -> None:
    alias, canonical = pair
    # Whatever pointed at the alias now points at the canonical token: one hop, always.
    await db.execute(
        update(CounterpartyAlias)
        .where(CounterpartyAlias.org_id == org_id, CounterpartyAlias.canonical_token == alias)
        .values(canonical_token=canonical)
    )
    kept = (await db.execute(
        select(CounterpartyAlias.id).where(
            CounterpartyAlias.org_id == org_id, CounterpartyAlias.alias_token == alias,
        )
    )).first()
    if kept is None:
        db.add(CounterpartyAlias(
            org_id=org_id, alias_token=alias, canonical_token=canonical, decision_id=decision_id,
            created_by=str(user.id),
        ))
    else:
        await db.execute(
            update(CounterpartyAlias)
            .where(CounterpartyAlias.org_id == org_id, CounterpartyAlias.alias_token == alias)
            .values(canonical_token=canonical, decision_id=decision_id, created_by=str(user.id))
        )


async def settle_resolution(
    db: AsyncSession, *, user: User, row: CanonicalTransaction, action: str
) -> dict[str, Any]:
    """Apply a resolved row's consequences and record the decision. Does not commit."""
    org_id = str(row.org_id)
    match = await db.get(CanonicalTransaction, row.duplicate_of) if row.duplicate_of else None
    if match is not None and str(match.org_id) != org_id:
        match = None
    keep = action == "keep"
    pair = None if keep else alias_pair(row, match, await load_aliases(db, org_id))
    opened = removed = False
    if keep:
        opened = await open_item_for_row(db, row)
        if opened:
            await reconcile_org(db, org_id)
    else:
        removed = await drop_open_item(db, row)
    evidence = [{"type": "ledger_row", "id": str(row.id)}]
    if match is not None:
        evidence.append({"type": "ledger_row", "id": str(match.id)})
    after: dict[str, Any] = {"ledger_status": "active" if keep else "excluded"}
    if pair:
        after["alias_from"], after["alias_to"] = pair
    decision = await record_decision(
        db, org_id=org_id, kind=DecisionKind.DUPLICATE_RESOLUTION, target_type="ledger_row",
        target_id=str(row.id), outcome="kept_separate" if keep else "same_document",
        decided_via=DecidedVia.HUMAN, decided_by=str(user.id), evidence_refs=evidence,
        before={"ledger_status": "possible_duplicate", "source_record_id": row.source_record_id},
        after=after,
    )
    if pair:
        await _save_alias(db, org_id, pair, user, str(decision.id))
    return {
        "open_item": "opened" if opened else ("removed" if removed else "unchanged"),
        "alias": {"from": pair[0], "to": pair[1]} if pair else None,
        "decision_id": str(decision.id),
    }
