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

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

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
            "message": f"Net cash flow is negative: {_fmt(cashflow['net_change'])}",
        })

    if cashflow["operating"] < 0:
        alerts.append({
            "level": "critical",
            "message": "Operating cash flow is negative — the business cannot fund itself from operations.",
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
                "message": f"2+ consecutive months of negative cash flow detected (including {entry['month']}).",
            })
            break

    return alerts


async def _generate_cashflow_narrative(
    cashflow: dict[str, Any], alerts: list[dict], settings
) -> str:
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.2,
        max_tokens=512,
        api_key=settings.openai_api_key,
    )
    alert_text = "\n".join(f"- [{a['level'].upper()}] {a['message']}" for a in alerts) or "No critical alerts."
    messages = [
        SystemMessage(content=(
            "You are an experienced CFO. Analyze the cash flow statement and write "
            "a concise, actionable commentary (2-4 sentences). Highlight liquidity risks clearly."
        )),
        HumanMessage(content=(
            f"Operating: {_fmt(cashflow['operating'])}\n"
            f"Investing: {_fmt(cashflow['investing'])}\n"
            f"Financing: {_fmt(cashflow['financing'])}\n"
            f"Net Change: {_fmt(cashflow['net_change'])}\n\n"
            f"Alerts:\n{alert_text}"
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_cashflow(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """Cash Flow Skill. done_when: state['cashflow']['net_change'] is an integer."""
    transactions = state.get("transactions", [])
    if not transactions:
        return SkillResult(ok=False, detail="No transactions for cash flow analysis.", halt=True)

    try:
        settings = get_settings()
        cashflow = _classify_cashflow(transactions)
        alerts = _detect_alerts(cashflow)
        narrative = await _generate_cashflow_narrative(cashflow, alerts, settings)

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
