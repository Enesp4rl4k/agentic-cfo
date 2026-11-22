"""The decision record of a bank-match answer: a person's, or a built-in rule's.

A proposed match (a bank line that may pay an invoice) is confirmed or rejected by a person; the
reconciler confirms a match by itself only where "a person would not hesitate" (an invoice number
and the exact amount, or the counterparty's name and the exact amount). Both leave one
`settlement_match` decision per match, written in the caller's transaction (`record_decision`).

The automatic rules are fixed in code (`services/reconciliation.py`), not created or approved per
company, so there is no person to name as their author: the record says so (`reason`) and carries
the rule's id. Taking one back is a human decision that supersedes it (`POST /ledger/settlements/{id}/undo`).
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecidedVia, Decision, DecisionKind
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.services.decisions import record_decision, superseded_ids

# Built-in reconciliation rules: stable ids (the `rule_id` column is 36 characters).
RULE_BY_NUMBER = "reconcile.invoice_number_exact"
RULE_BY_NAME = "reconcile.counterparty_amount_exact"
RULE_REASON = (
    "built-in automatic rule (fixed in code, not created by a person); a person may take it back"
)
_RULE_OF_METHOD = {"invoice_number": RULE_BY_NUMBER, "counterparty_and_amount": RULE_BY_NAME}
_NAME_MAX = 80


async def latest_decision_id(db: AsyncSession, org_id: str, target_type: str, target_id: str) -> str | None:
    """The standing (not yet superseded) decision about one target, if any: what a reversal supersedes."""
    row = (await db.execute(
        select(Decision).where(
            Decision.org_id == org_id, Decision.target_type == target_type, Decision.target_id == target_id
        ).order_by(Decision.decided_at.desc(), Decision.id.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None or await superseded_ids(db, org_id, [row.id]):
        return None
    return str(row.id)


async def _counterparties(db: AsyncSession, org_id: str, item_ids: Sequence[str]) -> dict[str, str | None]:
    rows = (await db.execute(
        select(OpenItem.id, OpenItem.counterparty).where(OpenItem.org_id == org_id, OpenItem.id.in_(list(item_ids)))
    )).all()
    return {str(i): (c[:_NAME_MAX] if c else None) for i, c in rows}


def _basis(m: OpenItemMatch, counterparty: str | None, status: str) -> dict[str, object]:
    return {
        "status": status, "amount_cents": int(m.amount_cents), "method": m.method,
        "counterparty": counterparty, "matched_on": m.matched_on.isoformat(),
    }


async def record_person_answer(
    db: AsyncSession, *, org_id: str, user_id: str, role: str, matches: Sequence[OpenItemMatch], outcome: str,
) -> list[str]:
    """One decision per answered match (a lump answers several at once). `outcome`: confirmed | rejected."""
    names = await _counterparties(db, org_id, [m.open_item_id for m in matches])
    ids: list[str] = []
    for m in matches:
        row = await record_decision(
            db, org_id=org_id, kind=DecisionKind.SETTLEMENT_MATCH, target_type="open_item_match",
            target_id=str(m.id), outcome=outcome, decided_via=DecidedVia.HUMAN, decided_by=user_id,
            evidence_refs=[{"type": "open_item", "id": str(m.open_item_id)},
                           {"type": "ledger_row", "id": str(m.ledger_row_id)}],
            before=_basis(m, names.get(str(m.open_item_id)), "proposed"),
            after={"status": outcome, "acting_role": role, "answered_as_lump": len(matches) > 1},
        )
        ids.append(str(row.id))
    return ids


async def record_rule_settlement(db: AsyncSession, *, org_id: str, match: OpenItemMatch, counterparty: str | None) -> None:
    """The reconciler confirmed `match` by itself: a rule decision, linked to its open item and bank line."""
    await record_decision(
        db, org_id=org_id, kind=DecisionKind.SETTLEMENT_MATCH, target_type="open_item_match",
        target_id=str(match.id), outcome="confirmed", decided_via=DecidedVia.RULE,
        rule_id=_RULE_OF_METHOD[match.method], reason=RULE_REASON,
        evidence_refs=[{"type": "open_item", "id": str(match.open_item_id)},
                       {"type": "ledger_row", "id": str(match.ledger_row_id)}],
        before=_basis(match, counterparty, "none"), after={"status": "confirmed"},
    )
