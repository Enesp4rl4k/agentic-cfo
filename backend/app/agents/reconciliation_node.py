"""
Numeric reconciliation — an independent check that the numbers the pipeline
*reports* match the numbers it *computed*.

"Nothing grades its own homework": this node does not call the P&L skill. It
re-checks the arithmetic identities that must hold inside ``state['pnl']`` and
verifies that every currency figure quoted in the agent narratives is supported
by a computed value.

Verdicts:
  * ``halt``            — a computed identity is violated (revenue != Σ income,
                          net_income != ebitda - tax - loans, …). The pipeline
                          produced inconsistent numbers; a human must not sign
                          off on them.
  * ``hold_for_review`` — a narrative quotes a money figure that matches no
                          computed value (possible LLM hallucination).
  * ``proceed``         — numbers are internally consistent and grounded.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from app.agents.state import CFOState, StepLog
from app.services.rag.grounding_validator import (
    _claim_supported,
    extract_numeric_claims,
)

logger = logging.getLogger(__name__)

ReconAction = Literal["proceed", "hold_for_review", "halt"]

# Identities are integer-cent arithmetic — allow a tiny slack for rounding only.
_IDENTITY_TOL_CENTS = 2


@dataclass
class ReconVerdict:
    action: ReconAction = "proceed"
    identity_failures: list[str] = field(default_factory=list)
    ungrounded_claims: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def should_halt(self) -> bool:
        return self.action == "halt"

    @property
    def should_hold(self) -> bool:
        return self.action == "hold_for_review"


def _close(a: float, b: float, tol: float = _IDENTITY_TOL_CENTS) -> bool:
    return abs(float(a) - float(b)) <= tol


def _check_pnl_identities(pnl: dict[str, Any], transactions: list[dict]) -> list[str]:
    fails: list[str] = []
    if not pnl:
        return fails

    revenue = pnl.get("revenue", 0) or 0
    cogs = pnl.get("cogs", 0) or 0
    gross_profit = pnl.get("gross_profit", 0) or 0
    total_opex = pnl.get("total_opex", 0) or 0
    ebitda = pnl.get("ebitda", 0) or 0
    tax = pnl.get("tax", 0) or 0
    loans = pnl.get("loan_payments", 0) or 0
    net_income = pnl.get("net_income", 0) or 0
    opex = pnl.get("opex", {}) or {}
    total_expenses = pnl.get("total_expenses")

    # Independent recomputation of the one lossless figure: revenue = Σ income.
    income_sum = sum(
        t.get("amount_cents", 0) for t in transactions if t.get("type") == "income"
    )
    if transactions and not _close(revenue, income_sum):
        fails.append(f"revenue {revenue} != Σ income transactions {income_sum}")

    if not _close(gross_profit, revenue - cogs):
        fails.append(f"gross_profit {gross_profit} != revenue - cogs ({revenue - cogs})")

    if not _close(ebitda, gross_profit - total_opex):
        fails.append(
            f"ebitda {ebitda} != gross_profit - total_opex ({gross_profit - total_opex})"
        )

    if not _close(net_income, ebitda - tax - loans):
        fails.append(
            f"net_income {net_income} != ebitda - tax - loans ({ebitda - tax - loans})"
        )

    if opex and not _close(sum(opex.values()), total_opex):
        fails.append(
            f"Σ opex categories {sum(opex.values())} != total_opex {total_opex}"
        )

    if total_expenses is not None and not _close(
        total_expenses, cogs + total_opex + tax + loans
    ):
        fails.append(
            f"total_expenses {total_expenses} != cogs+opex+tax+loans "
            f"({cogs + total_opex + tax + loans})"
        )
    return fails


def _supported_values(pnl: dict, cashflow: dict, forecast: dict) -> list[float]:
    """Every computed money figure, in both cents and major units."""
    vals: list[float] = []

    def add(x: Any) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            vals.append(float(x))
            vals.append(float(x) / 100.0)  # cents → major unit

    for d in (pnl or {}, cashflow or {}):
        for v in d.values():
            if isinstance(v, dict):
                for vv in v.values():
                    add(vv)
            elif isinstance(v, list):
                continue
            else:
                add(v)

    for scen in (forecast or {}).get("scenarios", {}).values():
        if isinstance(scen, dict):
            for vv in scen.values():
                add(vv)
    return vals


def _uncategorized_expense_note(pnl: dict, transactions: list[dict]) -> str | None:
    """Expenses that fall outside every P&L bucket silently vanish from net_income."""
    if not pnl or not transactions:
        return None
    known = {"cogs", "tax", "loan", "salary", "rent", "utilities",
             "marketing", "technology", "other_expense"}
    orphan = [
        t for t in transactions
        if t.get("type") == "expense" and str(t.get("category", "")) not in known
    ]
    if not orphan:
        return None
    total = sum(t.get("amount_cents", 0) for t in orphan)
    return (
        f"{len(orphan)} expense transaction(s) totalling {total} cents are outside "
        f"all P&L categories and are excluded from net_income"
    )


def reconcile_cfo_state(state: CFOState) -> ReconVerdict:
    if state.get("halted"):
        return ReconVerdict(action="proceed")  # nothing to reconcile

    pnl = state.get("pnl") or {}
    cashflow = state.get("cashflow") or {}
    forecast = state.get("forecast") or {}
    transactions = state.get("transactions") or []

    identity_failures = _check_pnl_identities(pnl, transactions)

    supported = _supported_values(pnl, cashflow, forecast)
    ungrounded: list[str] = []
    for key, blob in (("pnl", pnl), ("cashflow", cashflow), ("forecast", forecast)):
        narrative = blob.get("narrative") if isinstance(blob, dict) else None
        if not narrative:
            continue
        for claim in extract_numeric_claims(str(narrative)):
            # percentages and small counts are not money — skip sub-1000 claims
            if abs(claim) < 1000:
                continue
            if not _claim_supported(claim, supported):
                ungrounded.append(f"{key}: {claim:,.0f}")

    notes: list[str] = []
    note = _uncategorized_expense_note(pnl, transactions)
    if note:
        notes.append(note)

    if identity_failures:
        return ReconVerdict(
            action="halt",
            identity_failures=identity_failures,
            ungrounded_claims=ungrounded,
            notes=notes,
        )
    if ungrounded:
        return ReconVerdict(
            action="hold_for_review", ungrounded_claims=ungrounded, notes=notes
        )
    return ReconVerdict(action="proceed", notes=notes)


async def node_reconcile(state: CFOState, config: dict) -> CFOState:
    """LangGraph node — runs the reconciliation check and patches state."""
    verdict = reconcile_cfo_state(state)

    detail_bits: list[str] = []
    if verdict.identity_failures:
        detail_bits.append("identity: " + "; ".join(verdict.identity_failures))
    if verdict.ungrounded_claims:
        detail_bits.append("ungrounded: " + ", ".join(verdict.ungrounded_claims))
    if verdict.notes:
        detail_bits.append("notes: " + "; ".join(verdict.notes))

    logs = list(state.get("logs") or [])
    logs.append(
        StepLog(
            step="reconciliation",
            ok=verdict.action == "proceed",
            detail="; ".join(detail_bits) or "numbers reconciled",
        )
    )

    patch: dict[str, Any] = {
        "logs": logs,
        "reconciliation": {
            "action": verdict.action,
            "identity_failures": verdict.identity_failures,
            "ungrounded_claims": verdict.ungrounded_claims,
            "notes": verdict.notes,
        },
    }
    if verdict.should_halt:
        patch["halted"] = True
        patch["error"] = "reconciliation failed: " + "; ".join(verdict.identity_failures)
    elif verdict.should_hold:
        patch["awaiting_review"] = True

    if verdict.notes:
        logger.info("Reconciliation notes for job=%s: %s", state.get("job_id"), verdict.notes)

    return {**state, **patch}  # type: ignore[return-value,typeddict-item]
