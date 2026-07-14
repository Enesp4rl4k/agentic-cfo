"""
Cash Flow Agent — Skill 3 of 10.

Extended analysis:
  - Operating / Investing / Financing classification
  - Monthly cash flow series
  - Working Capital calculation
  - Burn Rate (monthly average cash consumption)
  - Cash Runway (months until depletion at current burn rate)
  - DSO / DIO / DPO working capital days
  - Cash Conversion Cycle (CCC)
  - Liquidity alerts (negative operating CF, consecutive negative months)
  - Multi-language narrative: tr / en / de

done_when: state['cashflow'] contains operating, net_change, working_capital,
           burn_rate, runway_months (all integers in cents where applicable).
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.agents.i18n import get_language_instruction, validate_language
from app.config import get_settings

logger = logging.getLogger(__name__)

OPERATING_CATEGORIES = {
    "revenue", "cogs", "salary", "rent", "utilities",
    "marketing", "technology", "tax", "other_expense", "other_income",
}
INVESTING_CATEGORIES: set[str] = {"equipment", "property", "investment"}
FINANCING_CATEGORIES = {"loan"}


def _fmt(cents: int) -> str:
    return f"₺{cents / 100:,.2f}"


def _classify_cashflow(transactions: list[dict[str, Any]]) -> dict[str, Any]:
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
            month_key = str(raw_date)[:7]
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
        "investing_in": investing_in,
        "investing_out": investing_out,
        "financing": financing,
        "financing_in": financing_in,
        "financing_out": financing_out,
        "net_change": net_change,
        "monthly_series": monthly_series,
    }


def _compute_working_capital(
    transactions: list[dict[str, Any]],
    cashflow: dict[str, Any],
    pnl: dict[str, Any],
) -> dict[str, Any]:
    """
    Working Capital = Current Assets - Current Liabilities
    Approximated from transaction data.
    """
    revenue = pnl.get("revenue", 0)
    cogs = pnl.get("cogs", 0)
    total_expenses = pnl.get("total_expenses", 0)

    # DSO = Accounts Receivable / (Revenue / 365)
    # Proxy AR: revenue × (DSO_assumed / 365) — we compute DSO from payment timing instead
    # Simplified: use 30-day DSO assumption, improve if explicit AR data available
    accounts_receivable_est = int(revenue * 30 / 365)
    inventory_est = int(cogs * 30 / 365)
    cash = max(0, cashflow.get("net_change", 0))
    current_assets_est = cash + accounts_receivable_est + inventory_est

    accounts_payable_est = int(total_expenses * 30 / 365)
    loan_payments = pnl.get("loan_payments", 0)
    current_liabilities_est = accounts_payable_est + loan_payments

    working_capital = current_assets_est - current_liabilities_est

    # DSO, DIO, DPO
    dso = round(accounts_receivable_est * 365 / max(revenue, 1), 1)
    dio = round(inventory_est * 365 / max(cogs, 1), 1)
    dpo = round(accounts_payable_est * 365 / max(total_expenses, 1), 1)
    ccc = round(dso + dio - dpo, 1)

    return {
        "current_assets_est": current_assets_est,
        "current_liabilities_est": current_liabilities_est,
        "working_capital": working_capital,
        "working_capital_ratio": round(current_assets_est / max(current_liabilities_est, 1), 3),
        "dso_days": dso,
        "dio_days": dio,
        "dpo_days": dpo,
        "cash_conversion_cycle": ccc,
        "accounts_receivable_est": accounts_receivable_est,
        "inventory_est": inventory_est,
        "accounts_payable_est": accounts_payable_est,
    }


def _compute_burn_rate(monthly_series: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Burn rate = average monthly net cash outflow.
    Runway = current cash balance / burn rate.
    """
    if not monthly_series:
        return {
            "monthly_burn_rate": 0,
            "avg_monthly_inflow": 0,
            "avg_monthly_outflow": 0,
            "runway_months": None,
            "current_cash_balance": 0,
        }

    inflows = [m["in"] for m in monthly_series]
    outflows = [m["out"] for m in monthly_series]
    nets = [m["net"] for m in monthly_series]

    avg_inflow = int(statistics.mean(inflows)) if inflows else 0
    avg_outflow = int(statistics.mean(outflows)) if outflows else 0
    monthly_burn = avg_outflow - avg_inflow  # positive = burning cash

    # Cumulative cash position
    cumulative = sum(nets)
    current_balance = max(0, cumulative)

    # Runway: how many months at current burn rate
    if monthly_burn > 0 and current_balance > 0:
        runway_months = round(current_balance / monthly_burn, 1)
    elif monthly_burn <= 0:
        runway_months = None  # Not burning — runway is infinite
    else:
        runway_months = 0.0

    return {
        "monthly_burn_rate": max(0, monthly_burn),
        "avg_monthly_inflow": avg_inflow,
        "avg_monthly_outflow": avg_outflow,
        "runway_months": runway_months,
        "current_cash_balance": current_balance,
    }


def _detect_alerts(cashflow: dict[str, Any], burn: dict[str, Any], wc: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    if cashflow["net_change"] < 0:
        alerts.append({"level": "warning", "message": f"Net cash flow negatif: {_fmt(cashflow['net_change'])}"})

    if cashflow["operating"] < 0:
        alerts.append({
            "level": "critical",
            "message": "Faaliyet nakit akışı negatif — işletme kendi kendini finanse edemiyor.",
        })

    # Consecutive negative months
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
                "message": f"2+ ardışık ay negatif nakit akışı ({entry['month']} dahil).",
            })
            break

    # Burn rate warnings
    runway = burn.get("runway_months")
    if runway is not None and runway <= 3:
        alerts.append({
            "level": "critical",
            "message": f"Kritik: nakit süresi {runway:.1f} ay. Acil önlem gerekli.",
        })
    elif runway is not None and runway <= 6:
        alerts.append({
            "level": "warning",
            "message": f"Nakit süresi {runway:.1f} ay. Gider yapısı gözden geçirilmeli.",
        })

    # Working capital
    if wc["working_capital"] < 0:
        alerts.append({
            "level": "critical",
            "message": f"Negatif işletme sermayesi: {_fmt(wc['working_capital'])}. Kısa vadeli yükümlülükler karşılanamayabilir.",
        })

    # High CCC
    if wc["cash_conversion_cycle"] > 90:
        alerts.append({
            "level": "warning",
            "message": f"Nakit dönüşüm döngüsü yüksek: {wc['cash_conversion_cycle']:.0f} gün.",
        })

    return alerts


async def _generate_cashflow_narrative(
    cashflow: dict[str, Any],
    burn: dict[str, Any],
    wc: dict[str, Any],
    alerts: list[dict],
    lang: str,
    settings,
) -> str:
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.2,
        max_tokens=700,
        api_key=settings.openai_api_key,
    )
    lang_instruction = get_language_instruction(lang)
    alert_text = "\n".join(f"- [{a['level'].upper()}] {a['message']}" for a in alerts) or "No critical alerts."

    runway_str = (
        f"{burn['runway_months']:.1f} months" if burn["runway_months"] is not None else "Stable (not burning)"
    )

    messages = [
        SystemMessage(content=(
            "You are an experienced CFO. Analyze the comprehensive cash flow data below and write "
            "a concise, actionable commentary (4-6 sentences). Cover liquidity, burn rate, "
            "working capital efficiency, and cash conversion cycle. "
            f"Be direct about risks and specific about recommended actions. {lang_instruction}"
        )),
        HumanMessage(content=(
            f"Operating CF: {_fmt(cashflow['operating'])}\n"
            f"Investing CF: {_fmt(cashflow['investing'])}\n"
            f"Financing CF: {_fmt(cashflow['financing'])}\n"
            f"Net Change: {_fmt(cashflow['net_change'])}\n\n"
            f"Monthly Burn Rate: {_fmt(burn['monthly_burn_rate'])}\n"
            f"Cash Runway: {runway_str}\n"
            f"Current Balance (est.): {_fmt(burn['current_cash_balance'])}\n\n"
            f"Working Capital: {_fmt(wc['working_capital'])}\n"
            f"DSO: {wc['dso_days']:.0f} days | DIO: {wc['dio_days']:.0f} days | DPO: {wc['dpo_days']:.0f} days\n"
            f"Cash Conversion Cycle: {wc['cash_conversion_cycle']:.0f} days\n\n"
            f"Alerts:\n{alert_text}"
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_cashflow(state: CFOState, config: AgentRunConfig) -> SkillResult:
    transactions = state.get("transactions", [])
    pnl = state.get("pnl", {})
    if not transactions:
        return SkillResult(ok=False, detail="No transactions for cash flow analysis.", halt=True)

    try:
        settings = get_settings()
        lang = validate_language(config.language)

        cashflow = _classify_cashflow(transactions)
        burn = _compute_burn_rate(cashflow["monthly_series"])
        wc = _compute_working_capital(transactions, cashflow, pnl)
        alerts = _detect_alerts(cashflow, burn, wc)
        narrative = await _generate_cashflow_narrative(cashflow, burn, wc, alerts, lang, settings)

        # Merge extended metrics into cashflow dict
        cashflow["burn_rate"] = burn
        cashflow["working_capital"] = wc
        cashflow["alerts"] = alerts
        cashflow["narrative"] = narrative
        cashflow["narrative_lang"] = lang

        has_critical = any(a["level"] == "critical" for a in alerts)
        confidence = 0.90 if not has_critical else 0.82

        return SkillResult(
            ok=True,
            patch={"cashflow": cashflow},
            confidence=confidence,
            needs_review=has_critical,
            detail=(
                f"Cash flow: operating={_fmt(cashflow['operating'])}, "
                f"net={_fmt(cashflow['net_change'])}, "
                f"burn={_fmt(burn['monthly_burn_rate'])}/mo, "
                f"runway={burn['runway_months'] or 'stable'}mo, "
                f"ccc={wc['cash_conversion_cycle']:.0f}d, "
                f"alerts={len(alerts)} [{lang}]"
            ),
        )
    except Exception as exc:
        logger.exception("Cash flow agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Cash flow error: {exc}", halt=True)
