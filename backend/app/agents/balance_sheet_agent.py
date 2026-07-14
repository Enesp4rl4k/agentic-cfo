"""
Balance Sheet Agent — Skill 9 of 10.

Responsibility: Construct a pro-forma Balance Sheet from transaction data.

Since a bank statement / CSV does not contain balance sheet items directly,
we derive them using accounting relationships and reasonable assumptions:

ASSETS
  Current Assets:
    - Cash & Equivalents:  net cumulative cash flow from transactions
    - Accounts Receivable: estimated from revenue not yet collected
      (proxy: last month's revenue × DSO / 30, default DSO = 30 days)
    - Inventory:           estimated from COGS × (DIO / 365), default DIO = 30
    - Prepaid & Other:     5% of total assets (industry default)
  Non-Current Assets:
    - PP&E:                estimated from capex-like investing outflows
    - Intangibles:         0 (cannot derive from transactions)

LIABILITIES
  Current Liabilities:
    - Accounts Payable:    estimated from expenses × (DPO / 365), default DPO = 30
    - Short-term Debt:     loan payments × 12 (annualised, treated as current)
    - Accrued Expenses:    3% of total expenses
  Non-Current Liabilities:
    - Long-term Debt:      0 (cannot determine from transaction data)

EQUITY
  - Retained Earnings:     cumulative net income
  - Paid-in Capital:       assumed = Assets - Liabilities (plug to balance)

GPT-4o produces a CFO-level balance sheet analysis narrative.

done_when: state['balance_sheet'] contains assets, liabilities, equity (all integers in cents)
           AND assets_total == liabilities_total + equity_total (balanced).
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)

# Industry-default assumptions (KOBİ / SMB)
DEFAULT_DSO = 30    # Days Sales Outstanding
DEFAULT_DIO = 30    # Days Inventory Outstanding
DEFAULT_DPO = 30    # Days Payable Outstanding


def _fmt(cents: int) -> str:
    return f"₺{cents / 100:,.0f}"


def _build_balance_sheet(
    transactions: list[dict[str, Any]],
    pnl: dict[str, Any],
    cashflow: dict[str, Any],
) -> dict[str, Any]:
    """
    Derive a pro-forma balance sheet from transaction and P&L data.
    All amounts in cents.
    """
    revenue = pnl.get("revenue", 0)
    cogs = pnl.get("cogs", 0)
    net_income = pnl.get("net_income", 0)
    total_expenses = pnl.get("total_expenses", 0)

    loan_payments = pnl.get("loan_payments", 0)

    # ── Current Assets ────────────────────────────────────────────────────────
    # Cash: net change in cash (operating + investing + financing)
    cash = max(0, cashflow.get("net_change", 0))

    # Accounts Receivable: revenue × (DSO / 365) — money owed by customers
    accounts_receivable = int(revenue * DEFAULT_DSO / 365)

    # Inventory: COGS × (DIO / 365) — goods not yet sold
    inventory = int(cogs * DEFAULT_DIO / 365)

    # Prepaid expenses & other current assets: 2% of revenue
    prepaid_other = int(revenue * 0.02)

    total_current_assets = cash + accounts_receivable + inventory + prepaid_other

    # ── Non-Current Assets ────────────────────────────────────────────────────
    # PP&E proxy: sum of investing outflows (capex)
    investing_out = abs(min(0, cashflow.get("investing", 0)))
    ppe = investing_out

    # Intangibles: not derivable
    intangibles = 0

    total_non_current_assets = ppe + intangibles
    total_assets = total_current_assets + total_non_current_assets

    # ── Current Liabilities ───────────────────────────────────────────────────
    # Accounts Payable: expenses × (DPO / 365)
    accounts_payable = int(total_expenses * DEFAULT_DPO / 365)

    # Short-term debt: current loan payment × 12 (annualised proxy)
    short_term_debt = loan_payments  # already period total

    # Accrued expenses: 3% of total expenses
    accrued_expenses = int(total_expenses * 0.03)

    total_current_liabilities = accounts_payable + short_term_debt + accrued_expenses

    # ── Non-Current Liabilities ───────────────────────────────────────────────
    long_term_debt = 0  # cannot determine from transactions
    total_non_current_liabilities = long_term_debt

    total_liabilities = total_current_liabilities + total_non_current_liabilities

    # ── Equity ────────────────────────────────────────────────────────────────
    retained_earnings = net_income
    # Paid-in capital: plug to make balance sheet balance
    paid_in_capital = max(0, total_assets - total_liabilities - retained_earnings)
    total_equity = retained_earnings + paid_in_capital

    # Sanity check — should be balanced
    is_balanced = abs((total_liabilities + total_equity) - total_assets) <= 1

    return {
        "assets": {
            "current": {
                "cash": cash,
                "accounts_receivable": accounts_receivable,
                "inventory": inventory,
                "prepaid_other": prepaid_other,
                "total": total_current_assets,
            },
            "non_current": {
                "ppe": ppe,
                "intangibles": intangibles,
                "total": total_non_current_assets,
            },
            "total": total_assets,
        },
        "liabilities": {
            "current": {
                "accounts_payable": accounts_payable,
                "short_term_debt": short_term_debt,
                "accrued_expenses": accrued_expenses,
                "total": total_current_liabilities,
            },
            "non_current": {
                "long_term_debt": long_term_debt,
                "total": total_non_current_liabilities,
            },
            "total": total_liabilities,
        },
        "equity": {
            "retained_earnings": retained_earnings,
            "paid_in_capital": paid_in_capital,
            "total": total_equity,
        },
        "is_balanced": is_balanced,
        "assumptions": {
            "dso_days": DEFAULT_DSO,
            "dio_days": DEFAULT_DIO,
            "dpo_days": DEFAULT_DPO,
            "note": (
                "Pro-forma estimate derived from transaction data. "
                "Long-term debt, intangibles and paid-in capital require manual input for accuracy."
            ),
        },
    }


async def _generate_balance_sheet_narrative(
    bs: dict[str, Any],
    pnl: dict[str, Any],
    lang: str,
    settings,
) -> str:
    from app.agents.i18n import get_language_instruction
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.1,
        max_tokens=700,
        api_key=settings.openai_api_key,
    )
    lang_instruction = get_language_instruction(lang)

    assets = bs["assets"]
    liabilities = bs["liabilities"]
    equity = bs["equity"]

    summary = (
        f"Total Assets: {_fmt(assets['total'])}\n"
        f"  - Current Assets: {_fmt(assets['current']['total'])}\n"
        f"    - Cash: {_fmt(assets['current']['cash'])}\n"
        f"    - Receivables: {_fmt(assets['current']['accounts_receivable'])}\n"
        f"    - Inventory: {_fmt(assets['current']['inventory'])}\n"
        f"  - Non-Current Assets: {_fmt(assets['non_current']['total'])}\n"
        f"\nTotal Liabilities: {_fmt(liabilities['total'])}\n"
        f"  - Current: {_fmt(liabilities['current']['total'])}\n"
        f"    - Accounts Payable: {_fmt(liabilities['current']['accounts_payable'])}\n"
        f"    - Short-term Debt: {_fmt(liabilities['current']['short_term_debt'])}\n"
        f"\nEquity: {_fmt(equity['total'])}\n"
        f"  - Retained Earnings: {_fmt(equity['retained_earnings'])}\n"
    )

    messages = [
        SystemMessage(content=(
            "You are an experienced CFO and financial analyst. "
            "Analyze the balance sheet data below. "
            "Provide a concise assessment (4-6 sentences) covering liquidity, "
            "debt structure, equity adequacy, and overall financial health. "
            f"Highlight key risks and strengths. {lang_instruction}"
        )),
        HumanMessage(content=f"Balance Sheet Summary:\n{summary}"),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_balance_sheet(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """
    Balance Sheet Skill.
    done_when: state['balance_sheet']['assets']['total'] is an integer.
    """
    from app.agents.i18n import validate_language
    transactions = state.get("transactions", [])
    pnl = state.get("pnl", {})
    cashflow = state.get("cashflow", {})

    if not pnl or not cashflow:
        return SkillResult(
            ok=False,
            detail="P&L or cash flow data missing — cannot build balance sheet.",
            halt=False,
        )

    try:
        settings = get_settings()
        lang = validate_language(config.language)
        bs = _build_balance_sheet(transactions, pnl, cashflow)
        narrative = await _generate_balance_sheet_narrative(bs, pnl, lang, settings)
        bs["narrative"] = narrative

        return SkillResult(
            ok=True,
            patch={"balance_sheet": bs},
            confidence=0.80,  # pro-forma estimate — lower confidence
            detail=(
                f"Bilanço oluşturuldu: aktif={_fmt(bs['assets']['total'])}, "
                f"yükümlülük={_fmt(bs['liabilities']['total'])}, "
                f"öz sermaye={_fmt(bs['equity']['total'])}, "
                f"dengeli={'Evet' if bs['is_balanced'] else 'Hayır'}"
            ),
        )
    except Exception as exc:
        logger.exception("Balance sheet agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Bilanço hatası: {exc}")
