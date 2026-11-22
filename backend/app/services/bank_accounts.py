"""The cash a company's bank statements prove: per account, per currency, never summed across currencies.

Each completed statement whose running balances check out (`app.services.bank_balance`) proves the
balance of ONE account on its last day. Which statements are one account:

- consecutive statements: the later one opens on the balance the earlier one closed on (the rule
  coverage uses to join them, `app.services.coverage`);
- the same account number or IBAN, when the file's header states it;
- statements that carry neither (older uploads) are one lineage: the latest of them stands, as it
  always did.

The company's opening cash, in its effective base currency, is the sum of the LATEST proven balance of
each account in that currency. Other currencies are listed with their own totals, never converted. An
account whose latest statement is not proven is left out and named with the reason; an account whose
latest balance is older than the others' says its date. The runway reads exactly this account set
(`app.services.company_runway`): one balance, one burn, one currency.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.currency_totals import DEFAULT_BASE, normalise
from app.models.analysis_job import AnalysisJob, JobStatus
from app.services.bank_balance import basis_of, proof_reason

_LEGACY = "legacy"


def _records(jobs: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(proven statements, statements with balances that are not proven) of the completed jobs."""
    proven: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for job_id, filename, meta in jobs:
        m = meta or {}
        closing = m.get("closing_balance")
        basis = basis_of(m)
        proof = m.get("balance_proof") or {}
        if closing and basis:
            proven.append({
                "job_id": job_id, "filename": filename, "basis": basis,
                "date": str(closing["date"])[:10], "balance_cents": int(closing["balance_cents"]),
                "extent": m.get("statement_extent"), "currency": proof.get("currency"),
                "identity": proof.get("identity"), "reason": proof.get("reason") if basis == "assumed" else None,
            })
        elif proof.get("has_balances") or (closing and not basis):
            excluded.append({"job_id": job_id, "filename": filename, "reason": proof_reason(m)})
    return proven, excluded


def _account_key(rec: dict[str, Any]) -> str | None:
    ident = str(rec.get("identity") or "")
    return ident if ident.startswith(("iban:", "acct:")) else None


def _group(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Statements of one account together (see the module docstring)."""
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    for i, a in enumerate(records):
        for j in range(i + 1, len(records)):
            b = records[j]
            ka, kb = _account_key(a), _account_key(b)
            if ka and ka == kb:
                join(i, j)
                continue
            ea, eb = a.get("extent"), b.get("extent")
            if ea is None and eb is None and not (ka or kb):
                join(i, j)  # both older uploads with no extent: one lineage
            elif ea and eb and _meets(ea, eb):
                join(i, j)
    groups: dict[int, list[dict[str, Any]]] = {}
    for i, rec in enumerate(records):
        groups.setdefault(find(i), []).append(rec)
    return list(groups.values())


def _meets(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """One statement opens on the balance the other closed on, and starts where it ended."""
    for first, second in ((a, b), (b, a)):
        if (
            first.get("closing_cents") is not None
            and second.get("opening_cents") == first["closing_cents"]
            and str(second["start"])[:10] >= str(first["end"])[:10]
        ):
            return True
    return False


def _account(group: list[dict[str, Any]], newest: str, limit: int) -> dict[str, Any]:
    last = max(group, key=lambda r: r["date"])
    ident = next((r["identity"] for r in group if _account_key(r)), None)
    behind = (date.fromisoformat(newest) - date.fromisoformat(last["date"])).days
    return {
        "name": last["filename"], "job_id": last["job_id"], "as_of": last["date"],
        "balance_cents": last["balance_cents"], "currency": last["currency"], "basis": last["basis"],
        "basis_note": last["reason"], "identity": ident, "statements": len(group),
        "behind_days": behind, "lagging": behind > limit,
        "extents": [r["extent"] for r in group if r.get("extent")],
    }


async def proven_balances(db: AsyncSession, org_id: str, currency: str | None = None) -> dict[str, Any]:
    """The company's proven cash: {"opening", "accounts", "excluded", "other_currencies", "currency"}.

    `currency` is the one the figures are in (default: the organisation's effective base,
    `core/currency_totals.effective_base`). `opening` is None when no account in it is proven; else
    {date (newest balance date), balance_cents (sum of the accounts' latest), job_id, filename (the
    newest account's), basis ("known" | "assumed"), accounts, extents}. A statement that does not
    name its currency is counted in `currency`, and `currency_assumed` says so on its account.
    """
    if currency is None:
        from app.services.ledger_base import effective_base_of

        currency = (await effective_base_of(db, org_id)).run_currency
    base = normalise(currency) or DEFAULT_BASE
    jobs = (await db.execute(
        select(AnalysisJob.id, AnalysisJob.filename, AnalysisJob.result_metadata).where(
            AnalysisJob.org_id == org_id, AnalysisJob.status == JobStatus.COMPLETED,
        )
    )).all()
    proven, excluded = _records([tuple(j) for j in jobs])
    limit = get_settings().radar_balance_stale_after_days
    newest = max((r["date"] for r in proven), default=None)
    accounts = [_account(g, newest, limit) for g in _group(proven)] if newest else []
    for a in accounts:
        a["currency_assumed"] = not a["currency"]
        a["currency"] = normalise(a["currency"]) or base
    mine = [a for a in accounts if a["currency"] == base]
    others: dict[str, dict[str, Any]] = {}
    for a in accounts:
        if a["currency"] != base:
            o = others.setdefault(a["currency"], {"currency": a["currency"], "balance_cents": 0, "as_of": a["as_of"], "accounts": 0})
            o["balance_cents"] += a["balance_cents"]
            o["as_of"] = max(o["as_of"], a["as_of"])
            o["accounts"] += 1
    opening = None
    if mine:
        top = max(mine, key=lambda a: a["as_of"])
        weak = any(a["basis"] == "assumed" for a in mine)
        opening = {
            "date": top["as_of"], "balance_cents": sum(a["balance_cents"] for a in mine),
            "job_id": top["job_id"], "filename": top["name"], "basis": "assumed" if weak else "known",
            "accounts": [{k: v for k, v in a.items() if k != "extents"} for a in mine],
            "extents": [e for a in mine for e in a["extents"]],
        }
    return {
        "currency": base, "opening": opening,
        "accounts": [{k: v for k, v in a.items() if k != "extents"} for a in accounts],
        "excluded": excluded, "other_currencies": sorted(others.values(), key=lambda o: o["currency"]),
    }


async def proven_balance(db: AsyncSession, org_id: str, currency: str | None = None) -> dict[str, Any] | None:
    """The company's opening cash in its base currency (see `proven_balances`), or None."""
    opening: dict[str, Any] | None = (await proven_balances(db, org_id, currency))["opening"]
    return opening


async def proven_statements(db: AsyncSession, org_id: str, currency: str | None = None) -> list[dict[str, Any]]:
    """The extents of the statements behind that balance: the accounts in the base currency only.

    Joined statements' extents come in as stored (`app.services.coverage` joins them again); an
    unproven statement, or one in another currency, covers no month of this company's cash.
    """
    opening = await proven_balance(db, org_id, currency)
    return list(opening["extents"]) if opening else []
