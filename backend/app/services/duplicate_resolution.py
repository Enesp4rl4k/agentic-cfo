"""What a person's answers on a possible duplicate do to the rest of the books (plan v10 G23).

Two decisions, never one:

1. **Resolve the row** (`POST /ledger/rows/{id}/resolve`, any writer): the row's `ledger_status` flips and
   `settle_resolution` applies what follows, in the same transaction (the caller commits):
   - *keep* (separate money): the row's open item is opened, so the radar counts the payable;
   - *exclude* (the same document): no open item remains. Proposals against it are rejected; money
     already confirmed against it refuses the answer (`MatchedMoney`) until the match is undone;
   - one `duplicate_resolution` decision is recorded.
   Excluding never teaches the ledger anything about suppliers. When the two rows carry the same number
   but different counterparties, the response only *proposes* an alias, with both names and the
   consequence in words.
2. **Declare two counterparties one supplier** (`POST /ledger/counterparty-aliases`, an owner, admin or
   the accountant): the explicit confirmation of that proposal. `counterparty_aliases` maps one party
   token to the other and ingest reads it (`ledger.record_ids`) from then on. Its own decision
   (`counterparty_alias`, before/after) is recorded. Revoking is the same authority and the same record;
   it affects future ingests only, and the rows ingested while it was active are listed for review
   (`rows_ingested_under`), never rewritten.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.invoice_identity import key_number, key_party, party_token
from app.models.canonical_transaction import CanonicalTransaction, money_rows
from app.models.counterparty_alias import CounterpartyAlias
from app.models.decision import DecidedVia, Decision, DecisionKind
from app.models.transaction import Transaction
from app.models.user import User
from app.services.decisions import record_decision
from app.services.ledger_documents import (
    drop_open_item,
    load_aliases,
    open_item_for_row,
    source_transaction,
)
from app.services.reconciliation import reconcile_org


class AliasRefused(Exception):
    """Why two counterparties cannot be declared one supplier here."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class AliasProposal:
    alias_token: str
    canonical_token: str
    alias_name: str | None
    canonical_name: str | None

    @property
    def confirmation_text(self) -> str:
        a, c = self.alias_name or "?", self.canonical_name or "?"
        return f"Bundan sonra {a} ve {c} aynı tedarikçi sayılacak."

    def as_dict(self, row_id: str) -> dict[str, Any]:
        return {
            "row_id": row_id, "alias_token": self.alias_token, "canonical_token": self.canonical_token,
            "alias_name": self.alias_name, "canonical_name": self.canonical_name,
            "confirmation_text": self.confirmation_text,
        }


def _pair(
    row: CanonicalTransaction, match: CanonicalTransaction | None, aliases: dict[str, str]
) -> tuple[str, str]:
    """(alias token, canonical token) for two rows that read as one supplier's invoice, or refuse."""
    if match is None:
        raise AliasRefused("no_match", "Bu satırın eşleştiği başka bir kayıt yok.")
    mine, theirs = key_party(row.source_record_id), key_party(match.source_record_id)
    if not (mine and theirs and mine[0] == theirs[0]) or key_number(row.source_record_id) != key_number(
        match.source_record_id
    ):
        raise AliasRefused("not_same_number", "İki kayıt aynı numaralı, aynı yönlü, karşı tarafı adlı faturalar değil.")
    if aliases.get(theirs[1]) == mine[1]:
        raise AliasRefused("cycle", "Bu eşleme bir döngü oluştururdu: ters yönde bir eşleme var, önce onu geri alın.")
    canonical = aliases.get(theirs[1], theirs[1])  # never a chain
    if canonical == mine[1] or aliases.get(mine[1]) == canonical:
        raise AliasRefused("already_same", "Bu iki ad zaten aynı tedarikçi sayılıyor.")
    return mine[1], canonical


async def propose_alias(
    db: AsyncSession, row: CanonicalTransaction, aliases: dict[str, str] | None = None
) -> AliasProposal:
    """The alias an excluded row suggests, with both raw names. Raises `AliasRefused` when none fits."""
    org_id = str(row.org_id)
    aliases = aliases if aliases is not None else await load_aliases(db, org_id)
    match = await db.get(CanonicalTransaction, row.duplicate_of) if row.duplicate_of else None
    if match is not None and str(match.org_id) != org_id:
        match = None
    alias, canonical = _pair(row, match, aliases)
    mine = await source_transaction(db, row, aliases)
    theirs = await source_transaction(db, match, aliases) if match is not None else None
    return AliasProposal(alias, canonical, mine.counterparty if mine else None, theirs.counterparty if theirs else None)


async def settle_resolution(
    db: AsyncSession, *, user: User, row: CanonicalTransaction, action: str
) -> dict[str, Any]:
    """Apply a resolved row's consequences and record the decision. Does not commit.

    Raises `MatchedMoney` (see `drop_open_item`): the caller rolls back and refuses.
    """
    org_id = str(row.org_id)
    match = await db.get(CanonicalTransaction, row.duplicate_of) if row.duplicate_of else None
    if match is not None and str(match.org_id) != org_id:
        match = None
    keep = action == "keep"
    opened, outcome, rejected = False, "unchanged", []
    if keep:
        opened = await open_item_for_row(db, row)
        if opened:
            await reconcile_org(db, org_id)
    else:
        outcome, rejected = await drop_open_item(db, row, str(user.id))
    evidence = [{"type": "ledger_row", "id": str(row.id)}]
    if match is not None:
        evidence.append({"type": "ledger_row", "id": str(match.id)})
    decision = await record_decision(
        db, org_id=org_id, kind=DecisionKind.DUPLICATE_RESOLUTION, target_type="ledger_row",
        target_id=str(row.id), outcome="kept_separate" if keep else "same_document",
        decided_via=DecidedVia.HUMAN, decided_by=str(user.id), evidence_refs=evidence,
        before={"ledger_status": "possible_duplicate", "source_record_id": row.source_record_id},
        after={"ledger_status": "active" if keep else "excluded"},
    )
    proposal = None
    if not keep:
        try:
            proposal = (await propose_alias(db, row)).as_dict(str(row.id))
        except AliasRefused:
            proposal = None
    return {
        "open_item": "opened" if opened else ("removed" if outcome == "removed" else "unchanged"),
        "rejected_proposals": rejected,
        "decision_id": str(decision.id),
        # Excluding is not a statement about suppliers. A person who thinks these two names are one
        # supplier confirms it separately (POST /ledger/counterparty-aliases) after reading this text.
        "proposed_alias": proposal,
    }


async def confirm_alias(db: AsyncSession, *, user: User, row: CanonicalTransaction) -> dict[str, Any]:
    """Declare the proposal for an excluded row a standing alias. Does not commit. Raises `AliasRefused`."""
    org_id = str(row.org_id)
    if row.ledger_status != "excluded":
        raise AliasRefused("not_excluded", "Önce kayıt aynı belge olarak dışlanmalı.")
    aliases = await load_aliases(db, org_id)
    proposal = await propose_alias(db, row, aliases)
    existing = (await db.execute(select(CounterpartyAlias).where(
        CounterpartyAlias.org_id == org_id, CounterpartyAlias.alias_token == proposal.alias_token,
    ))).scalar_one_or_none()
    repointed_rows = (await db.execute(select(CounterpartyAlias.id, CounterpartyAlias.canonical_token).where(
        CounterpartyAlias.org_id == org_id, CounterpartyAlias.canonical_token == proposal.alias_token,
        CounterpartyAlias.revoked_at.is_(None),
    ))).all()
    repointed = [str(i) for i, _ in repointed_rows]
    decision = await record_decision(
        db, org_id=org_id, kind=DecisionKind.COUNTERPARTY_ALIAS, target_type="counterparty_alias",
        target_id=existing.id if existing else f"{proposal.alias_token}>{proposal.canonical_token}",
        outcome="created", decided_via=DecidedVia.HUMAN, decided_by=str(user.id),
        reason=proposal.confirmation_text,
        evidence_refs=[{"type": "ledger_row", "id": str(row.id)}],
        before={"active": bool(existing and existing.revoked_at is None), "canonical_token": existing.canonical_token if existing else None},
        after={"active": True, "alias_token": proposal.alias_token, "canonical_token": proposal.canonical_token,
               "alias_name": proposal.alias_name, "canonical_name": proposal.canonical_name,
               "repointed": len(repointed),
               # What each re-pointed alias read as before, so revoking this alias restores the chain.
               "repointed_from": {str(i): str(was) for i, was in repointed_rows}},
    )
    # Whatever pointed at the alias now points at the canonical token: one hop, always.
    if repointed:
        await db.execute(update(CounterpartyAlias).where(CounterpartyAlias.id.in_(repointed))
                         .values(canonical_token=proposal.canonical_token))
    if existing is None:
        existing = CounterpartyAlias(org_id=org_id, alias_token=proposal.alias_token)
        db.add(existing)
    existing.canonical_token = proposal.canonical_token
    existing.alias_name, existing.canonical_name = proposal.alias_name, proposal.canonical_name
    existing.decision_id, existing.created_by = str(decision.id), str(user.id)
    existing.revoked_at = existing.revoked_by = existing.revoke_decision_id = None
    await db.flush()
    return {"alias": alias_dict(existing), "confirmation_text": proposal.confirmation_text,
            "decision_id": str(decision.id)}


def alias_dict(a: CounterpartyAlias) -> dict[str, Any]:
    return {
        "id": str(a.id), "alias_name": a.alias_name, "canonical_name": a.canonical_name,
        "alias_token": a.alias_token, "canonical_token": a.canonical_token,
        "created_by": a.created_by, "created_at": a.created_at.isoformat() if a.created_at else None,
        "decision_id": a.decision_id, "active": a.revoked_at is None,
        "revoked_at": a.revoked_at.isoformat() if a.revoked_at else None,
    }


async def list_aliases(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(CounterpartyAlias).where(CounterpartyAlias.org_id == org_id).order_by(CounterpartyAlias.created_at)
    )).scalars().all()
    return [alias_dict(a) for a in rows]


async def rows_ingested_under(db: AsyncSession, alias: CounterpartyAlias) -> list[dict[str, Any]]:
    """Ledger rows that carry the canonical token because their own counterparty read as the alias.

    These were keyed through the alias. Revoking does not move them: a person looks at each.
    """
    org_id = str(alias.org_id)
    rows = (await db.execute(
        select(CanonicalTransaction).where(
            CanonicalTransaction.org_id == org_id, money_rows(),
            CanonicalTransaction.source_record_id.like(f"inv:_:{alias.canonical_token}:%"),
        )
    )).scalars().all()
    cache: dict[str, list[Transaction]] = {}
    listed = []
    for row in rows:
        tx = await source_transaction(db, row, {str(alias.alias_token): str(alias.canonical_token)}, cache)
        if tx is not None and party_token(org_id, tx.counterparty) == alias.alias_token:
            listed.append({"id": str(row.id), "source_record_id": row.source_record_id,
                           "counterparty": tx.counterparty, "amount_cents": row.amount_cents,
                           "ledger_status": row.ledger_status})
    return listed


async def _restore_repointed(db: AsyncSession, alias: CounterpartyAlias) -> list[str]:
    """Give back the targets confirming `alias` took from other aliases (A->B was re-pointed to A->C).

    Confirming B->C re-points every alias that read as B to C (one hop, never a chain). Revoking B->C
    must undo exactly that, or A would keep reading as C, a supplier it was never declared to be.
    The previous targets are in the decision that created the alias (`repointed_from`). One that is
    itself an alias by now is read through it, and a restore that would loop is left alone.
    """
    created = await db.get(Decision, alias.decision_id) if alias.decision_id else None
    was: dict[str, str] = ((created.after or {}).get("repointed_from") if created else None) or {}
    if not was:
        return []
    org_id = str(alias.org_id)
    active = {
        str(a): str(c) for a, c in (await db.execute(
            select(CounterpartyAlias.alias_token, CounterpartyAlias.canonical_token).where(
                CounterpartyAlias.org_id == org_id, CounterpartyAlias.revoked_at.is_(None),
                CounterpartyAlias.id != alias.id,
            )
        )).all()
    }
    restored: list[str] = []
    for alias_id, previous in was.items():
        row = await db.get(CounterpartyAlias, alias_id)
        if row is None or str(row.org_id) != org_id or row.revoked_at is not None:
            continue
        target = active.get(previous, previous)
        if target != row.alias_token and row.canonical_token != target:
            row.canonical_token = target
            restored.append(alias_id)
    return restored


async def revoke_alias(db: AsyncSession, *, user: User, alias: CounterpartyAlias) -> dict[str, Any]:
    """Stop applying an alias to future ingests; list what it touched. Does not commit."""
    if alias.revoked_at is not None:
        raise AliasRefused("already_revoked", "Bu eşleme zaten geri alınmış.")
    affected = await rows_ingested_under(db, alias)
    restored = await _restore_repointed(db, alias)
    decision = await record_decision(
        db, org_id=str(alias.org_id), kind=DecisionKind.COUNTERPARTY_ALIAS, target_type="counterparty_alias",
        target_id=str(alias.id), outcome="revoked", decided_via=DecidedVia.HUMAN, decided_by=str(user.id),
        reason=f"Bundan sonra {alias.alias_name or '?'} ve {alias.canonical_name or '?'} ayrı tedarikçi sayılacak.",
        before={"active": True, "alias_token": alias.alias_token, "canonical_token": alias.canonical_token},
        after={"active": False, "rows_to_review": len(affected), "restored": restored},
    )
    alias.revoked_at, alias.revoked_by, alias.revoke_decision_id = datetime.now(UTC), str(user.id), str(decision.id)
    await db.flush()
    return {"alias": alias_dict(alias), "rows_ingested_under": affected, "restored_aliases": restored, "decision_id": str(decision.id),
            "note": "Geçmiş kayıtlar değiştirilmedi; yukarıdaki satırları gözden geçirin. Sonraki yüklemeler ayrı tedarikçi olarak okunur."}
