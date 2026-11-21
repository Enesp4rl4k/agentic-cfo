"""The chat never hands the model a figure with a symbol the data does not prove.

Five cases, for both the CFO block (stored dashboard) and the CEO block (condensed financial summary):
a TRY-only company, a USD-only company, several currencies with none confirmed, a confirmed base with
another currency left out, and no currency at all. The LLM is mocked; what is asserted is the system
prompt it would have been sent.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents import chat_agent
from app.agents.ceo.synthesis_agent import _condense_financial_summary
from app.agents.chat_agent import _build_executive_context, _build_financial_context, dogrudan_cevap

LIRA = "₺"


def _pnl(**extra: Any) -> dict[str, Any]:
    return {
        "revenue": 500_000, "gross_profit": 400_000, "gross_margin": 0.8, "ebitda": 300_000,
        "ebitda_margin": 0.6, "net_income": 250_000, "net_margin": 0.5, "opex": {"rent": 100_000}, **extra,
    }


def _dash(**pnl_extra: Any) -> dict[str, Any]:
    return {"pnl": _pnl(**pnl_extra), "cashflow": {"operating": 90_000}, "forecast": {}, "anomalies": []}


def _fin(**extra: Any) -> dict[str, Any]:
    return {"revenue_cents": 50_000_000, "net_income_cents": 25_000_000, "net_margin": 0.5, **extra}


USD_OTHER = [{"currency": "USD", "revenue_cents": 0, "expense_cents": 1_240_000}]


# ── CFO block (stored dashboard) ─────────────────────────────────────────────

def test_try_only_is_labelled_lira() -> None:
    ctx = _build_financial_context(_dash(currency="TRY", base_state="single_unconfirmed"), [])
    assert f"Revenue: {LIRA}500,000" in ctx
    assert "Currency: TRY (the only currency in the data; the company has not confirmed it yet)." in ctx
    assert "$" not in ctx


def test_usd_only_is_never_labelled_lira() -> None:
    ctx = _build_financial_context(_dash(currency="USD", base_state="confirmed"), [])
    assert "Revenue: 500,000 USD" in ctx
    assert "Currency: USD." in ctx
    assert LIRA not in ctx


def test_mixed_and_unconfirmed_has_no_single_currency_and_no_symbol() -> None:
    ctx = _build_financial_context(
        _dash(currency="TRY", base_state="ambiguous", other_currencies=USD_OTHER), [])
    assert "Currency: NOT SINGLE" in ctx
    assert "only the rows in TRY" in ctx
    assert "Revenue: 500,000\n" in ctx           # bare: the model is not handed a symbol
    assert LIRA not in ctx and "500,000 TRY" not in ctx


def test_confirmed_base_lists_the_other_currency_as_not_converted() -> None:
    ctx = _build_financial_context(
        _dash(currency="TRY", base_state="confirmed", other_currencies=USD_OTHER), [])
    assert f"Revenue: {LIRA}500,000" in ctx
    assert "NOT converted" in ctx
    assert "USD: 12,400.00 USD expense" in ctx


def test_no_data_writes_bare_numbers_and_says_unknown() -> None:
    ctx = _build_financial_context({"pnl": _pnl(), "cashflow": {}, "forecast": {}}, [])
    assert "Currency: UNKNOWN" in ctx
    assert "Revenue: 500,000\n" in ctx
    assert LIRA not in ctx


def test_each_recent_transaction_is_in_its_own_currency() -> None:
    txs = [
        {"amount_cents": 1_000_00, "currency": "USD", "type": "income", "transaction_date": "2026-01-02"},
        {"amount_cents": 2_000_00, "currency": "TRY", "type": "income", "transaction_date": "2026-01-01"},
        {"amount_cents": 3_000_00, "type": "income", "transaction_date": "2025-12-31"},
    ]
    ctx = _build_financial_context(_dash(currency="TRY"), txs)
    assert "1,000 USD |" in ctx and f"{LIRA}2,000 |" in ctx
    assert "| 3,000 |" in ctx                    # names no currency: written bare


def test_the_no_model_answer_follows_the_same_label() -> None:
    assert f"{LIRA}500.000" in (dogrudan_cevap("Toplam gelirim ne kadar?", _dash(currency="TRY")) or "")
    assert "500.000 USD" in (dogrudan_cevap("Toplam gelirim ne kadar?", _dash(currency="USD")) or "")
    bare = dogrudan_cevap("Toplam gelirim ne kadar?", _dash(currency="TRY", base_state="ambiguous")) or ""
    assert "500.000" in bare and LIRA not in bare and "TRY" not in bare


# ── CEO block (condensed summary) ────────────────────────────────────────────

def test_ceo_try_only() -> None:
    ctx = _build_executive_context(ceo_result={"financial_summary": _fin(currency="TRY", base_state="confirmed")})
    assert f"Revenue: {LIRA}500,000" in ctx and "Currency: TRY." in ctx


def test_ceo_usd_only() -> None:
    ctx = _build_executive_context(ceo_result={"financial_summary": _fin(currency="USD", base_state="confirmed")})
    assert "Revenue: 500,000 USD" in ctx and LIRA not in ctx


def test_ceo_mixed_unconfirmed_says_so_instead_of_picking_one() -> None:
    ctx = _build_executive_context(ceo_result={"financial_summary": _fin(
        currency="TRY", base_state="ambiguous", other_currencies=USD_OTHER)})
    assert "Currency: NOT SINGLE" in ctx
    assert "Revenue: 500,000\n" in ctx and LIRA not in ctx


def test_ceo_confirmed_base_lists_others_separately() -> None:
    ctx = _build_executive_context(ceo_result={"financial_summary": _fin(
        currency="EUR", base_state="confirmed", other_currencies=USD_OTHER)})
    assert "Revenue: 500,000 EUR" in ctx
    assert "NOT converted" in ctx and "USD: 12,400.00 USD expense" in ctx


def test_ceo_no_currency_in_the_summary_is_bare_and_unknown() -> None:
    ctx = _build_executive_context(ceo_result={"financial_summary": _fin()})
    assert "Currency: UNKNOWN" in ctx and "Revenue: 500,000\n" in ctx and LIRA not in ctx


def test_infrastructure_cost_states_no_currency() -> None:
    ctx = _build_executive_context(cto_result={"infra": {"total_cost_cents": 12_000_00, "waste_estimate_cents": 1_000_00}})
    assert "Infrastructure Cost: 12,000/month" in ctx and LIRA not in ctx
    assert "currency not stated" in ctx


def test_the_ceo_condenser_carries_the_pnl_currency_through() -> None:
    cfo = {"pnl": {"revenue": 1, "currency": "USD", "base_state": "confirmed", "other_currencies": USD_OTHER}}
    summary = _condense_financial_summary(cfo)
    assert summary["currency"] == "USD" and summary["base_state"] == "confirmed"
    assert summary["other_currencies"] == USD_OTHER


# ── What the model is actually sent (LLM mocked) ─────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fin", "expect", "forbid"),
    [
        (_fin(currency="TRY", base_state="confirmed"), f"Revenue: {LIRA}500,000", "USD"),
        (_fin(currency="USD", base_state="confirmed"), "Revenue: 500,000 USD", LIRA),
        (_fin(currency="TRY", base_state="ambiguous", other_currencies=USD_OTHER), "Currency: NOT SINGLE", LIRA),
        (_fin(), "Currency: UNKNOWN", LIRA),
    ],
)
async def test_the_prompt_the_model_receives(monkeypatch: pytest.MonkeyPatch, fin: dict[str, Any], expect: str, forbid: str) -> None:
    sent: dict[str, Any] = {}

    async def fake_complete_text(**kwargs: Any) -> str:
        sent.update(kwargs)
        return " ok "

    monkeypatch.setattr("app.platform.model_gateway.complete_text", fake_complete_text)
    answer = await chat_agent.chat_with_ceo("Nasıl gidiyoruz?", ceo_result={"financial_summary": fin})
    assert answer == "ok"
    prompt = sent["system_prompt"]
    assert expect in prompt
    assert forbid not in prompt.split("Company Data:")[1]
    assert "Format currency as" not in prompt          # the prompt no longer tells the model to write ₺
    assert "never add, change or convert a currency" in prompt
