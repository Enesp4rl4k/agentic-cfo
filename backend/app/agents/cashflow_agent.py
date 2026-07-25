"""
Cash Flow Agent — Skill 3 of 5.

Responsibility: Compute the cash flow statement and detect liquidity risks.
Classifies transactions into: Operating / Investing / Financing activities.
Generates rule-based alerts when cash position is critical.

done_when: state['cashflow'] contains operating, investing, financing, net_change (cents integers).
"""
from __future__ import annotations

from app.services.telemetry import trace_agent

import logging
from typing import Any

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

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

    return {
        "operating": operating,
        "operating_in": operating_in,
        "operating_out": operating_out,
        "investing": investing,
        "financing": financing,
        "net_change": net_change,
        "monthly_series": monthly_series,
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
