"""Transfers between the company's own bank accounts: proposed by evidence, counted out only when a person confirms.

Both legs of a transfer (money leaving account A, the same money arriving on account B) are real movements on two
statements, but not an outflow and not an inflow of the company. Left in, they inflate the burn, the cash-flow totals
and the materiality basis. A transfer is NEVER taken from the amounts alone (two payments of the same size on two
accounts are common). The matcher PROPOSES a pair only when all of these hold:

- both legs come from statements of two KNOWN, distinct accounts of the company, each with a stated IBAN / account number (`bank_accounts.account_groups`:
  an account nothing separates from another is not a counterpart);
- same currency and exact amount, opposite direction, dates at most `WINDOW_DAYS` apart;
- the pairing is unique: no other candidate on either side for the same money;
- there is evidence beyond the amount: one leg's description names the other account's IBAN / account number
  (`counterpart_account`), or says it is a transfer between own accounts (`transfer_wording`).

A proposal changes nothing. A confirmation is a recorded decision (`own_transfer`, target = the two row ids); from
then on `ledger.company_rows` leaves both legs out of every figure the ledger feeds (the cash flow the runway reads,
the monthly outflow of the materiality threshold, the P&L), because that is the one reading of the ledger. Rejecting
records the answer and the pair is not proposed again; a later answer supersedes an earlier one (nothing deleted).
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.turkish import fold
from app.models.canonical_transaction import CanonicalTransaction, money_rows
from app.models.decision import DecidedVia, DecisionKind
from app.services.decisions import list_decisions, record_decision

WINDOW_DAYS = 3
ANSWERS = ("confirm", "reject")
TARGET_TYPE = "own_transfer_pair"
_WORDING = ("virman", "hesaplar arasi", "hesaplarim arasi", "kendi hesab", "own account", "internal transfer", "ic transfer")
_MIN_ACCOUNT_DIGITS = 6


class AnswerRefused(ValueError):
    """The answer is not usable; nothing was written."""


def pair_id(a: str, b: str) -> str:
    left, right = sorted((a, b))
    return f"{left}|{right}"


def _squash(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _names_account(description: str, identity: str | None) -> bool:
    """The description states the other account's IBAN or account number (not a fragment of it)."""
    label, _, value = str(identity or "").partition(":")
    value = _squash(value)
    if label == "iban" and len(value) >= 15:
        return value in _squash(description)
    if label == "acct" and len(value) >= _MIN_ACCOUNT_DIGITS:
        return re.search(rf"(?<!\d){re.escape(value)}(?!\d)", description) is not None
    return False


def _evidence(out: dict[str, Any], inc: dict[str, Any], accounts: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    if (_names_account(str(out["description"]), accounts[inc["account"]]["identity"])
            or _names_account(str(inc["description"]), accounts[out["account"]]["identity"])):
        found.append("counterpart_account")
    folded = f"{fold(str(out['description']))} {fold(str(inc['description']))}"
    if any(w in folded for w in _WORDING):
        found.append("transfer_wording")
    return found


def propose(rows: list[dict[str, Any]], accounts: list[dict[str, Any]], window_days: int = WINDOW_DAYS) -> list[dict[str, Any]]:
    """The pairs of cash rows that are evidently one transfer between two known own accounts. Pure.

    `rows`: {id, date (a date), amount_cents, currency, direction, description, job_id}. `accounts`: as
    `bank_accounts.account_groups` returns them. Each row is in at most one proposal.
    """
    # Both sides need a stated account identifier (IBAN / account number): two accounts with no identifier cannot be
    # told apart from one account by a description, so wording alone never pairs them.
    index = {
        job: i for i, a in enumerate(accounts)
        if a["known"] and str(a.get("identity") or "").startswith(("iban:", "acct:")) for job in a["job_ids"]
    }
    legs = [{**r, "account": index[r["job_id"]]} for r in rows if r.get("job_id") in index and r["amount_cents"] > 0]
    outs = [r for r in legs if r["direction"] == "expense"]
    ins = [r for r in legs if r["direction"] == "income"]

    def counterparts(row: dict[str, Any], others: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            o for o in others
            if o["account"] != row["account"] and o["amount_cents"] == row["amount_cents"]
            and str(o["currency"]).upper() == str(row["currency"]).upper()
            and abs((o["date"] - row["date"]).days) <= window_days
        ]

    out: list[dict[str, Any]] = []
    for o in outs:
        found = counterparts(o, ins)
        if len(found) != 1 or len(counterparts(found[0], outs)) != 1:
            continue
        i = found[0]
        why = _evidence(o, i, accounts)
        if not why:
            continue
        out.append({
            "id": pair_id(o["id"], i["id"]), "out_id": o["id"], "in_id": i["id"],
            "amount_cents": o["amount_cents"], "currency": o["currency"], "days_apart": abs((o["date"] - i["date"]).days),
            "out": _side(o, accounts), "in": _side(i, accounts), "evidence": why,
        })
    return sorted(out, key=lambda p: (p["out"]["date"], p["id"]))


def _side(row: dict[str, Any], accounts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"row_id": row["id"], "date": row["date"].isoformat(), "description": row["description"],
            "account": accounts[row["account"]]["name"]}


async def _cash_rows(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    found = (await db.execute(
        select(
            CanonicalTransaction.id, CanonicalTransaction.transaction_date, CanonicalTransaction.amount_cents,
            CanonicalTransaction.currency, CanonicalTransaction.direction, CanonicalTransaction.description,
            CanonicalTransaction.source_job_id,
        ).where(
            CanonicalTransaction.org_id == org_id, CanonicalTransaction.ledger_status == "active",
            CanonicalTransaction.basis == "cash", money_rows(), CanonicalTransaction.source_job_id.is_not(None),
        ).order_by(CanonicalTransaction.transaction_date, CanonicalTransaction.id)
    )).all()
    return [
        {"id": r[0], "date": r[1].date() if hasattr(r[1], "date") else r[1], "amount_cents": int(r[2]), "currency": r[3],
         "direction": r[4], "description": r[5] or "", "job_id": r[6]}
        for r in found
    ]


async def _answers(db: AsyncSession, org_id: str) -> dict[str, Any]:
    rows, _ = await list_decisions(db, org_id, kind=DecisionKind.OWN_TRANSFER.value, current_only=True, limit=5000)
    return {d.target_id: d for d in rows}


async def proposals(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    """The transfers waiting for a person's answer: evident, and not answered yet."""
    from app.services.bank_accounts import account_groups

    accounts = await account_groups(db, org_id)
    if sum(1 for a in accounts if a["known"]) < 2:
        return []
    answered = await _answers(db, org_id)
    return [p for p in propose(await _cash_rows(db, org_id), accounts) if p["id"] not in answered]


async def confirmed_leg_ids(db: AsyncSession, org_id: str) -> set[str]:
    """The ids of the rows that are legs of a CONFIRMED transfer (the current answer of each pair)."""
    legs: set[str] = set()
    for d in (await _answers(db, org_id)).values():
        if d.outcome == "confirm":
            legs.update(str(x) for x in ((d.after or {}).get("out_id"), (d.after or {}).get("in_id")) if x)
    return legs


async def answer(db: AsyncSession, org_id: str, user_id: str, *, out_id: str, in_id: str, answer: str, note: str | None = None) -> dict[str, Any]:
    """Record a person's answer for a proposed pair. No commit. Raises `AnswerRefused`.

    Only a pair that is proposed right now (or already answered, to change the answer) can be answered: the
    caller cannot exclude two arbitrary rows by naming them."""
    if answer not in ANSWERS:
        raise AnswerRefused("yanıt 'confirm' ya da 'reject' olmalı")
    target = pair_id(out_id, in_id)
    standing = (await _answers(db, org_id)).get(target)
    if standing is None and target not in {p["id"] for p in await proposals(db, org_id)}:
        raise AnswerRefused("bu çift önerilen bir hesaplar arası aktarım değil")
    outcome = "confirmed" if answer == "confirm" else "rejected"
    if standing is not None and standing.outcome == ("confirm" if answer == "confirm" else "reject"):
        return {"changed": False, "decision_id": standing.id}
    decision = await record_decision(
        db, org_id=org_id, kind=DecisionKind.OWN_TRANSFER, target_type=TARGET_TYPE, target_id=target,
        outcome=("confirm" if answer == "confirm" else "reject"), decided_via=DecidedVia.HUMAN, decided_by=user_id,
        reason=note, evidence_refs=[{"type": "canonical_transaction", "id": out_id}, {"type": "canonical_transaction", "id": in_id}],
        before={"answer": standing.outcome} if standing is not None else None,
        after={"out_id": out_id, "in_id": in_id, "answer": outcome},
        supersedes_id=standing.id if standing is not None else None,
    )
    return {"changed": True, "decision_id": decision.id, "answer": outcome}


__all__ = ["ANSWERS", "WINDOW_DAYS", "AnswerRefused", "answer", "confirmed_leg_ids", "pair_id", "proposals", "propose"]
