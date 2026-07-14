"""
Forecast Agent — Skill 4 of 5.

Responsibility: Generate 3/6/12-month financial forecasts with three scenarios
(optimistic, base, pessimistic). Detects runway risk and cash-out dates.

Uses historical monthly series from P&L + Cash Flow to extrapolate trends.
GPT-4o adds strategic commentary on each scenario.

done_when: state['forecast'] contains scenarios dict and alerts list.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)


def _fmt(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def _extrapolate(
    monthly_series: list[dict[str, Any]],
    months_ahead: int,
    growth_rate: float,
) -> list[dict[str, Any]]:
    """
    Simple linear + growth-rate extrapolation from the last N months of data.
    growth_rate: monthly multiplier, e.g. 1.02 = +2%/month, 0.98 = -2%/month.
    """
    if not monthly_series:
        return []

    last = monthly_series[-1]
    last_in = last["in"]
    last_out = last["out"]

    # Use average of last 3 months as baseline if available
    recent = monthly_series[-3:] if len(monthly_series) >= 3 else monthly_series
    avg_in = int(statistics.mean(e["in"] for e in recent))
    avg_out = int(statistics.mean(e["out"] for e in recent))

    projected: list[dict[str, Any]] = []
    cur_in = avg_in
    cur_out = avg_out

    last_month = monthly_series[-1]["month"]
    year, month = int(last_month[:4]), int(last_month[5:7])

    for i in range(1, months_ahead + 1):
        month += 1
        if month > 12:
            month = 1
            year += 1
        cur_in = int(cur_in * growth_rate)
        cur_out = int(cur_out * (2 - growth_rate))  # expenses move inversely to revenue
        projected.append({
            "month": f"{year:04d}-{month:02d}",
            "in": cur_in,
            "out": cur_out,
            "net": cur_in - cur_out,
            "projected": True,
        })

    return projected


def _compute_scenarios(cashflow: dict[str, Any], pnl: dict[str, Any]) -> dict[str, Any]:
    """Generate optimistic / base / pessimistic projections for 12 months."""
    series = cashflow.get("monthly_series", [])

    scenarios = {
        "optimistic": {
            "label": "Optimistic",
            "description": "Revenue grows 5%/month, costs stay flat.",
            "growth_rate": 1.05,
            "months": _extrapolate(series, 12, 1.05),
        },
        "base": {
            "label": "Base",
            "description": "Revenue grows 1%/month, costs grow 1%/month.",
            "growth_rate": 1.01,
            "months": _extrapolate(series, 12, 1.01),
        },
        "pessimistic": {
            "label": "Pessimistic",
            "description": "Revenue declines 3%/month, costs stay flat.",
            "growth_rate": 0.97,
            "months": _extrapolate(series, 12, 0.97),
        },
    }

    # Runway calculation: how many months until cumulative net goes negative
    for key, scenario in scenarios.items():
        cumulative = 0
        runway_months: int | None = None
        for i, m in enumerate(scenario["months"], start=1):
            cumulative += m["net"]
            if cumulative < 0 and runway_months is None:
                runway_months = i
        scenario["runway_months"] = runway_months
        scenario["twelve_month_net"] = sum(m["net"] for m in scenario["months"])

    return scenarios


def _build_forecast_alerts(scenarios: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    base_runway = scenarios["base"].get("runway_months")
    pessimistic_runway = scenarios["pessimistic"].get("runway_months")

    if base_runway is not None and base_runway <= 3:
        alerts.append({
            "level": "critical",
            "message": f"Base scenario: cash runway is only {base_runway} month(s). Immediate action required.",
        })
    elif base_runway is not None and base_runway <= 6:
        alerts.append({
            "level": "warning",
            "message": f"Base scenario: cash runway is {base_runway} months. Review cost structure.",
        })

    if pessimistic_runway is not None and pessimistic_runway <= 2:
        alerts.append({
            "level": "critical",
            "message": f"Pessimistic scenario: business may run out of cash in {pessimistic_runway} month(s).",
        })

    if scenarios["base"]["twelve_month_net"] < 0:
        alerts.append({
            "level": "warning",
            "message": "Base scenario 12-month net is negative — profitability path unclear.",
        })

    return alerts


async def _generate_forecast_narrative(
    scenarios: dict[str, Any],
    alerts: list[dict[str, str]],
    lang: str,
    settings,
) -> str:
    from app.agents.i18n import get_language_instruction
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.3,
        max_tokens=768,
        api_key=settings.openai_api_key,
    )
    lang_instruction = get_language_instruction(lang)
    scenario_text = "\n".join(
        f"- {s['label']}: 12-month net {_fmt(s['twelve_month_net'])}, "
        f"runway {s['runway_months'] or 'no limit'} months"
        for s in scenarios.values()
    )
    alert_text = "\n".join(f"- [{a['level'].upper()}] {a['message']}" for a in alerts) or "No critical alerts."
    messages = [
        SystemMessage(content=(
            "You are an experienced CFO. Review the financial forecast scenarios and "
            "provide a concise strategic recommendation (4-6 sentences). "
            f"Be specific about what actions management should take now. {lang_instruction}"
        )),
        HumanMessage(content=(
            f"12-Month Forecast Scenarios:\n{scenario_text}\n\n"
            f"Risk Alerts:\n{alert_text}"
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_forecast(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """Forecast Skill. done_when: state['forecast']['scenarios'] has 3 keys."""
    from app.agents.i18n import validate_language
    cashflow = state.get("cashflow", {})
    pnl = state.get("pnl", {})

    if not cashflow or not pnl:
        return SkillResult(
            ok=False,
            detail="Cash flow or P&L data missing — cannot generate forecast.",
            halt=True,
        )

    try:
        settings = get_settings()
        lang = validate_language(config.language)
        scenarios = _compute_scenarios(cashflow, pnl)
        alerts = _build_forecast_alerts(scenarios)
        narrative = await _generate_forecast_narrative(scenarios, alerts, lang, settings)

        forecast = {
            "scenarios": scenarios,
            "alerts": alerts,
            "narrative": narrative,
        }

        has_critical = any(a["level"] == "critical" for a in alerts)
        confidence = 0.85 if not has_critical else 0.80

        return SkillResult(
            ok=True,
            patch={"forecast": forecast},
            confidence=confidence,
            needs_review=has_critical,
            detail=(
                f"Forecast generated: base 12m net={_fmt(scenarios['base']['twelve_month_net'])}, "
                f"base runway={scenarios['base']['runway_months'] or 'stable'} months, "
                f"alerts={len(alerts)}"
            ),
        )
    except Exception as exc:
        logger.exception("Forecast agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Forecast error: {exc}", halt=True)
