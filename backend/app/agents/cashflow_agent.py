"""
Cash Flow Agent — Skill 3 of 5.

Responsibility: Compute the cash flow statement and detect liquidity risks.
Classifies transactions into: Operating / Investing / Financing activities.
Generates rule-based alerts when cash position is critical.

done_when: state['cashflow'] contains operating, investing, financing, net_change (cents integers).
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.state import AgentRunConfig, CFOState, SkillResult
from app.config import get_settings
from app.services.telemetry import trace_agent

logger = logging.getLogger(__name__)

OPERATING_CATEGORIES = {
    "revenue", "cogs", "salary", "rent", "utilities",
    "marketing", "technology", "tax", "other_expense", "other_income",
}
INVESTING_CATEGORIES: set[str] = set()   # extend when asset purchases are added
FINANCING_CATEGORIES = {"loan"}


def _fmt(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _classify_cashflow(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — classifies each transaction and sums by activity."""
    operating_in = operating_out = 0
    investing_in = investing_out = 0
    financing_in = financing_out = 0
    monthly: dict[str, dict[str, int]] = {}

    for tx in transactions:
        amount = tx.get("amount_cents", 0)
        tx_type = tx.get("type", "expense")
        category = tx.get("category", "other_expense")
        raw_date = tx.get("transaction_date")

        if raw_date:
            month_key = str(raw_date)[:7]  # "YYYY-MM"
            bucket = monthly.setdefault(month_key, {"in": 0, "out": 0})
            if tx_type == "income":
                bucket["in"] += amount
            else:
                bucket["out"] += amount

        if category in FINANCING_CATEGORIES:
            if tx_type == "income":
                financing_in += amount
            else:
                financing_out += amount
        elif category in INVESTING_CATEGORIES:
            if tx_type == "income":
                investing_in += amount
            else:
                investing_out += amount
        else:
            if tx_type == "income":
                operating_in += amount
            else:
                operating_out += amount

    operating = operating_in - operating_out
    investing = investing_in - investing_out
    financing = financing_in - financing_out
    net_change = operating + investing + financing

    monthly_series = [
        {"month": k, "in": v["in"], "out": v["out"], "net": v["in"] - v["out"]}
        for k, v in sorted(monthly.items())
    ]

    # S1-2: Cash Conversion Cycle (CCC) — proxy calculation from transaction data
    # CCC = DSO + DIO - DPO
    # DSO (Days Sales Outstanding): how long to collect receivables
    # DIO (Days Inventory Outstanding): how long inventory sits (0 for service cos)
    # DPO (Days Payable Outstanding): how long to pay suppliers
    ccc = _compute_ccc(transactions, operating_in, operating_out)

    return {
        "operating": operating,
        "operating_in": operating_in,
        "operating_out": operating_out,
        "investing": investing,
        "financing": financing,
        "net_change": net_change,
        "monthly_series": monthly_series,
        # CCC metrics
        "dso_days": ccc["dso_days"],
        "dpo_days": ccc["dpo_days"],
        "ccc_days": ccc["ccc_days"],
        "ccc_interpretation": ccc["interpretation"],
    }


def _compute_ccc(
    transactions: list[dict[str, Any]],
    total_revenue_cents: int,
    total_expenses_cents: int,
) -> dict[str, Any]:
    """
    S1-2: Cash Conversion Cycle estimation.

    Uses transaction data to estimate:
      DSO = (Accounts Receivable proxy / Revenue) × 365
      DPO = (Accounts Payable proxy / COGS) × 365
      CCC = DSO - DPO  (no inventory for most service/tech companies)

    For companies without explicit AR/AP tracking, we use
    income timing vs. expense timing as a proxy.
    """

    if not transactions or total_revenue_cents == 0:
        return {"dso_days": None, "dpo_days": None, "ccc_days": None, "interpretation": "Yetersiz veri"}

    # Estimate DSO: average lag between income transactions and month start
    # As a proxy: if revenue arrives in clumps vs. uniformly → high DSO
    income_txs = [t for t in transactions if t.get("type") == "income"]
    expense_txs = [t for t in transactions if t.get("type") == "expense"
                   and t.get("category") in ("cogs", "other_expense")]

    # Simple proxy: annualized revenue / 365 gives daily revenue
    # DSO = avg days until payment collected (use 30 as baseline for invoice businesses)
    # DPO = avg days to pay suppliers

    # Count transactions per month to estimate payment patterns
    months_with_income = set()
    months_with_expense = set()
    for t in income_txs:
        m = str(t.get("transaction_date", ""))[:7]
        if m:
            months_with_income.add(m)
    for t in expense_txs:
        m = str(t.get("transaction_date", ""))[:7]
        if m:
            months_with_expense.add(m)

    n_income_months = max(1, len(months_with_income))
    max(1, len(months_with_expense))

    # Proxy DSO: transactions per month vs revenue size
    avg_monthly_revenue = total_revenue_cents / n_income_months
    avg_monthly_revenue / 30

    # High-value, few transactions → higher DSO (invoice-based)
    # Low-value, many transactions → lower DSO (retail/subscription)
    n_income_txs = max(1, len(income_txs))
    avg_invoice_size = total_revenue_cents / n_income_txs
    # Heuristic: avg invoice > 10K TRY → B2B, longer DSO
    if avg_invoice_size > 10_000_00:  # 10,000 TRY in kuruş
        dso_days = 45  # B2B typical
    elif avg_invoice_size > 1_000_00:  # 1,000 TRY
        dso_days = 20  # mixed
    else:
        dso_days = 7   # retail/subscription

    # DPO proxy: how spread out are expense payments
    n_expense_txs = max(1, len(expense_txs))
    avg_expense_size = total_expenses_cents / n_expense_txs if total_expenses_cents > 0 else 0
    if avg_expense_size > 5_000_00:  # 5,000 TRY — larger supplier invoices
        dpo_days = 30
    else:
        dpo_days = 15

    ccc_days = dso_days - dpo_days  # DIO = 0 for service companies

    interpretation = (
        "Negatif CCC — tahsilat ödemeden önce geliyor (sağlıklı)" if ccc_days < 0 else
        f"CCC {ccc_days} gün — tahsilat gecikiyor, nakit sıkışıklığı riski" if ccc_days > 45 else
        f"CCC {ccc_days} gün — normal aralıkta"
    )

    return {
        "dso_days": dso_days,
        "dpo_days": dpo_days,
        "ccc_days": ccc_days,
        "interpretation": interpretation,
    }


def _detect_alerts(cashflow: dict[str, Any]) -> list[dict[str, str]]:
    """Rule-based alerts — no LLM required."""
    alerts: list[dict[str, str]] = []

    if cashflow["net_change"] < 0:
        alerts.append({
            "level": "warning",
            "message": f"Net nakit akışı negatif: {_fmt(cashflow['net_change'])}. Nakit dengesini izleyin.",
        })

    if cashflow["operating"] < 0:
        alerts.append({
            "level": "critical",
            "message": "Faaliyet nakit akışı negatif — işletme, faaliyetlerini kendi nakit akışıyla finanse edemiyor. Acil önlem gerekiyor.",
        })

    series = cashflow.get("monthly_series", [])
    neg_streak = 0
    for entry in series:
        if entry["net"] < 0:
            neg_streak += 1
        else:
            neg_streak = 0
        if neg_streak >= 2:
            alerts.append({
                "level": "critical",
                "message": f"Art arda 2+ ay negatif nakit akışı tespit edildi ({entry['month']} dahil). Gider kontrolü yapılmalı.",
            })
            break

    return alerts


async def _generate_cashflow_narrative(
    cashflow: dict[str, Any],
    alerts: list[dict],
    settings,
    state: dict[str, Any] | None = None,
) -> str:
    """
    Generate structured CashFlow narrative with ContextBuilder.
    Falls back to template if LLM key is not configured.
    """
    from app.services.llm_structured import get_cashflow_narrative

    cashflow_with_alerts = dict(cashflow)
    cashflow_with_alerts["alerts"] = alerts

    # Attach context metadata via ContextBuilder
    if state is not None:
        from app.services.context_builder import get_context_builder
        ctx = get_context_builder(budget=3072)
        context_result = ctx.build_cashflow_context(
            state={**state, "cashflow": cashflow_with_alerts}
        )
        cashflow_with_alerts["_context_tokens"] = context_result.token_count
        cashflow_with_alerts["_context_truncated"] = context_result.truncated

    narrative = await get_cashflow_narrative(cashflow_with_alerts, settings)
    return narrative.to_text()


@trace_agent("cashflow_agent")
async def run_cashflow(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """Cash Flow Skill. done_when: state['cashflow']['net_change'] is an integer."""
    transactions = state.get("transactions", [])
    if not transactions:
        return SkillResult(ok=False, detail="No transactions for cash flow analysis.", halt=True)

    try:
        settings = get_settings()
        cashflow = _classify_cashflow(transactions)
        alerts = _detect_alerts(cashflow)
        narrative = await _generate_cashflow_narrative(cashflow, alerts, settings, state=state)

        cashflow["alerts"] = alerts
        cashflow["narrative"] = narrative

        has_critical = any(a["level"] == "critical" for a in alerts)
        confidence = 0.90 if not has_critical else 0.85

        # S3-3: Attach cashflow evidence
        try:
            from app.services.evidence_builder import get_evidence_builder
            cashflow = get_evidence_builder().attach_cashflow_evidence(cashflow, transactions)
        except Exception as ev_exc:
            logger.debug("Evidence builder (non-fatal): %s", ev_exc)

        return SkillResult(
            ok=True,
            patch={"cashflow": cashflow},
            confidence=confidence,
            needs_review=has_critical,
            detail=(
                f"Cash flow: operating={_fmt(cashflow['operating'])}, "
                f"net={_fmt(cashflow['net_change'])}, "
                f"alerts={len(alerts)}"
            ),
        )
    except Exception as exc:
        logger.exception("Cash flow agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Cash flow error: {exc}", halt=True)
