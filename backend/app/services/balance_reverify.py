"""A statement's balance chain, read again after a person has answered what was held.

A statement held for a person (a direction nobody could place, rows that did not parse, a currency) is
proven or not at ingest, on rows that still had open questions. The person's answer changes the rows, so
what the statement proves must be read again from the rows as they now are: otherwise a statement the
owner has fully resolved never reaches the cash radar's opening balance or the runway.

At ingest a statement with held rows stores its chain (`snapshot_chain`: every row's place in the file,
its date, amount, direction and printed balance, and which rows were held). `reverify` rebuilds the
statement from that and the held rows' current state:

- a row a person released or corrected counts as they left it;
- a row still waiting counts only when it is complete; one that is not (no direction, no amount) leaves
  the statement unverified: "N satır bekliyor";
- a row a person rejected is out of the books and so out of the chain. If it carried a balance the chain
  usually does not close without it: the statement stays unverified, and says so.

It runs inside the decision's own transaction (`held_rows.resolve_uncommitted`), is a function of the
stored chain and the rows alone (running it twice changes nothing and writes nothing the second time),
and writes one decision record (`balance_reverification`) naming the answers that caused it.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob
from app.models.decision import DecidedVia, DecisionKind
from app.models.held_transaction import PENDING, REJECTED, HeldTransaction
from app.services.bank_balance import assess, closing_balance, statement_extent
from app.services.decisions import record_decision


def mark_positions(rows: list[dict[str, Any]]) -> None:
    """Number the rows of a file, in file order, in place (a row keeps its number when it is held)."""
    for i, row in enumerate(rows):
        row.setdefault("file_pos", i)


def snapshot_chain(rows: list[dict[str, Any]], held: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The file's rows as the chain sees them; None when no row carries a balance."""
    if not any(r.get("balance_cents") is not None for r in rows):
        return None
    waiting = {r.get("file_pos") for r in held}
    return {"rows": [
        {
            "pos": r["file_pos"], "date": str(r.get("transaction_date") or "")[:10] or None,
            "amount_cents": r.get("amount_cents"), "type": r.get("type"),
            "balance_cents": r.get("balance_cents"), "currency": r.get("currency"),
            "held": r["file_pos"] in waiting,
        }
        for r in rows
    ]}


def statement_whole(
    rows: list[dict[str, Any]], held: list[dict[str, Any]], counts: dict[str, Any] | None, raw_text: str,
) -> dict[str, Any]:
    """What a statement with held rows proves over ALL its rows as read, as pipeline state.

    The closing balance and extent, the proof (`bank_balance.assess`) and the chain a person's later
    answer is read from (`snapshot_chain`). Only what the rows prove is present.
    """
    from app.services.statement_account import account_identity

    closing = closing_balance(rows)
    out: dict[str, Any] = {"statement_closing_balance": closing} if closing is not None else {}
    if (extent := statement_extent(rows)) is not None:
        out["statement_extent"] = extent
    out["balance_proof"] = assess(rows, counts, identity=account_identity(raw_text) or None)
    if (chain := snapshot_chain(rows, held)) is not None:
        out["statement_chain"] = chain
    return out


def _row(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "transaction_date": source.get("transaction_date") or source.get("date"),
        "amount_cents": source.get("amount_cents"), "type": source.get("type"),
        "balance_cents": source.get("balance_cents"), "currency": source.get("currency"),
    }


def _complete(row: dict[str, Any]) -> bool:
    amount = row["amount_cents"]
    if row["type"] not in ("income", "expense") or not isinstance(amount, int) or isinstance(amount, bool):
        return False
    # A balance is not required: a statement that prints its balance on some rows only has rows between them.
    if not row["transaction_date"]:
        return False
    return not parse_transaction_date(row["transaction_date"])[1]


def _participants(
    chain: dict[str, Any], held: dict[Any, HeldTransaction],
) -> tuple[list[dict[str, Any]], int, int, int, list[dict[str, Any]]]:
    """(rows in the chain, rows still waiting that block it, rejected rows, rejected rows with a balance, all rows
    in file order with the waiting ones as they are: the reading of a statement that prints a balance on some rows)."""
    rows: list[dict[str, Any]] = []
    whole: list[dict[str, Any]] = []
    blocking = rejected = with_figures = 0
    for entry in chain.get("rows") or []:
        if not entry.get("held"):
            rows.append(_row(entry))
            whole.append(rows[-1])
            continue
        h = held.get(entry["pos"])
        if h is None:
            blocking += 1
            whole.append(_row(entry))
        elif h.status == REJECTED:
            rejected += 1
            if h.payload.get("balance_cents") is not None:
                with_figures += 1
        else:
            row = _row(h.payload)
            if h.status == PENDING and not _complete(row):
                blocking += 1
                whole.append({**row, "type": None})
            else:
                rows.append(row)
                whole.append(row)
    return rows, blocking, rejected, with_figures, whole


def _digest(proof: dict[str, Any] | None, closing: dict[str, Any] | None) -> dict[str, Any]:
    p = proof or {}
    return {
        "state": p.get("state"), "basis": p.get("basis"), "steps": p.get("steps"), "reason": p.get("reason"),
        "closing_cents": (closing or {}).get("balance_cents"), "closing_date": (closing or {}).get("date"),
    }


async def reverify(db: AsyncSession, org_id: str, causes: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Read again the statements whose held rows were just answered. No commit.

    `causes` maps a job id to the decision ids of the answers on its rows. Returns, per statement whose
    proof changed, {job_id, state, basis, reason, decision_id}.
    """
    out: list[dict[str, Any]] = []
    for job_id in sorted(causes):
        job = await db.get(AnalysisJob, job_id)
        meta = dict(job.result_metadata or {}) if job is not None else {}
        chain = meta.get("statement_chain")
        if job is None or str(job.org_id) != org_id or not chain:
            continue
        held = {
            h.payload.get("file_pos"): h
            for h in (await db.execute(
                # The answers were written with UPDATE statements: read the rows as they are now,
                # not as the session loaded them.
                select(HeldTransaction).where(HeldTransaction.job_id == job_id).order_by(HeldTransaction.created_at)
                .execution_options(populate_existing=True)
            )).scalars()
        }
        rows, blocking, rejected, with_figures, whole = _participants(chain, held)
        old = meta.get("balance_proof")
        identity = (old or {}).get("identity")
        if blocking:
            proof = {**assess([], None, identity=identity), "has_balances": True, "reason": f"{blocking} satır bekliyor"}
            # A statement that prints its balance on some rows only is proven by its segments: a waiting row that
            # lies outside them (before the first / after the last printed balance) does not stop that.
            segmented = assess(whole, meta.get("ingest"), recheck=True, identity=identity)
            if segmented.get("segments") and segmented["basis"]:
                proof, rows = segmented, whole
        else:
            proof = assess(rows, meta.get("ingest"), recheck=True, identity=identity)
            if proof["state"] == "unverified" and with_figures:
                proof["reason"] = (
                    f"{with_figures} satır reddedildi; bakiye zinciri bu satırlar olmadan kapanmıyor"
                )
        closing = closing_balance(rows) if proof["basis"] else None
        if _digest(proof, closing) == _digest(old, meta.get("closing_balance") if (old or {}).get("basis") else None):
            continue
        before = _digest(old, meta.get("closing_balance"))
        if proof["basis"]:
            from app.services.coverage import apply_period

            meta["closing_balance"] = closing
            extent = apply_period(statement_extent(rows), chain.get("period"), job.filename)
            if extent is not None:
                meta["statement_extent"] = extent
        decision = await record_decision(
            db, org_id=org_id, kind=DecisionKind.BALANCE_REVERIFICATION, target_type="analysis_job",
            target_id=job_id, outcome=proof["state"], decided_via=DecidedVia.SYSTEM, reason=proof["reason"],
            evidence_refs=[{"type": "analysis_job", "id": job_id}, *({"type": "decision", "id": d} for d in causes[job_id][:40])],
            before=before, after=_digest(proof, closing),
        )
        meta["balance_proof"] = {
            **proof, "reverified_at": datetime.now(UTC).isoformat(), "waiting": blocking, "rejected": rejected,
            "decision_id": decision.id,
        }
        job.result_metadata = meta
        out.append({
            "job_id": job_id, "state": proof["state"], "basis": proof["basis"], "reason": proof["reason"],
            "decision_id": decision.id,
        })
    return out
