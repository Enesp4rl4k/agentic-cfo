"""Tests for the numeric reconciliation node."""
from __future__ import annotations

import pytest

from app.agents.reconciliation_node import node_reconcile, reconcile_cfo_state


def _consistent_pnl() -> dict:
    # revenue 100000, cogs 20000, opex 30000 (10000+20000), tax 5000, loans 0
    return {
        "revenue": 100_000,
        "cogs": 20_000,
        "gross_profit": 80_000,
        "opex": {"salary": 20_000, "rent": 10_000},
        "total_opex": 30_000,
        "ebitda": 50_000,
        "tax": 5_000,
        "loan_payments": 0,
        "net_income": 45_000,
        "total_expenses": 55_000,
        "narrative": "Gelir 100000 TL, net kar 45000 TL olarak gerçekleşti.",
    }


def _txns() -> list[dict]:
    return [
        {"type": "income", "amount_cents": 60_000, "category": "sales"},
        {"type": "income", "amount_cents": 40_000, "category": "services"},
        {"type": "expense", "amount_cents": 20_000, "category": "cogs"},
        {"type": "expense", "amount_cents": 20_000, "category": "salary"},
        {"type": "expense", "amount_cents": 10_000, "category": "rent"},
        {"type": "expense", "amount_cents": 5_000, "category": "tax"},
    ]


def test_consistent_state_proceeds():
    state = {"pnl": _consistent_pnl(), "transactions": _txns()}
    v = reconcile_cfo_state(state)  # type: ignore[arg-type]
    assert v.action == "proceed"
    assert not v.identity_failures


def test_broken_net_income_identity_halts():
    pnl = _consistent_pnl()
    pnl["net_income"] = 999_999  # != ebitda - tax - loans
    state = {"pnl": pnl, "transactions": _txns()}
    v = reconcile_cfo_state(state)  # type: ignore[arg-type]
    assert v.action == "halt"
    assert any("net_income" in f for f in v.identity_failures)


def test_revenue_not_matching_income_transactions_halts():
    pnl = _consistent_pnl()
    state = {"pnl": pnl, "transactions": _txns()[2:]}  # drop the income rows
    v = reconcile_cfo_state(state)  # type: ignore[arg-type]
    assert v.action == "halt"
    assert any("revenue" in f for f in v.identity_failures)


def test_ungrounded_money_figure_in_narrative_holds():
    pnl = _consistent_pnl()
    pnl["narrative"] = "Gelir 100000 TL; ancak beklenmedik 7500000 TL kayıp oluştu."
    state = {"pnl": pnl, "transactions": _txns()}
    v = reconcile_cfo_state(state)  # type: ignore[arg-type]
    assert v.action == "hold_for_review"
    assert v.ungrounded_claims


def test_uncategorized_expense_note_is_advisory_only():
    pnl = _consistent_pnl()
    txns = [*_txns(), {"type": "expense", "amount_cents": 3000, "category": "mystery"}]
    state = {"pnl": pnl, "transactions": txns}
    v = reconcile_cfo_state(state)  # type: ignore[arg-type]
    assert v.action == "proceed"
    assert any("outside all P&L categories" in n for n in v.notes)


def test_halted_state_is_skipped():
    v = reconcile_cfo_state({"halted": True})  # type: ignore[arg-type]
    assert v.action == "proceed"


@pytest.mark.asyncio
async def test_node_patches_halt_and_log():
    pnl = _consistent_pnl()
    pnl["gross_profit"] = 1  # break revenue - cogs identity
    state = {"pnl": pnl, "transactions": _txns(), "logs": []}
    out = await node_reconcile(state, {})  # type: ignore[arg-type]
    assert out["halted"] is True
    assert out["reconciliation"]["action"] == "halt"
    assert out["logs"][-1].step == "reconciliation"
    assert out["logs"][-1].ok is False
