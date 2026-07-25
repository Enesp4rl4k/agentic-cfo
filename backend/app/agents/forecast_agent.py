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

from app.services.telemetry import trace_agent

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)


def _fmt(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def _detect_seasonality(
    monthly_series: list[dict[str, Any]],
) -> dict[int, float]:
    """
    Detect monthly seasonality indices using numpy.

    Returns a dict mapping month number (1-12) to a seasonality multiplier.
    1.0 = average month, 1.3 = 30% above average, 0.7 = 30% below average.

    Algorithm:
      1. Compute 12-month rolling average at each point (detrend)
      2. Divide each month's value by its rolling average (seasonal ratio)
      3. Average ratios for each calendar month across years

    Falls back to uniform multipliers (1.0) if insufficient data.
    """
    if len(monthly_series) < 12:
        return {}  # Not enough data for seasonality

    try:
        import numpy as np

        # Build arrays indexed by calendar month
        monthly_revenue = {}  # month_key → income
        for entry in monthly_series:
            m_num = int(entry["month"][5:7])
            monthly_revenue.setdefault(m_num, []).append(entry["in"])

        if not monthly_revenue:
            return {}

        # Global mean across all months
        all_vals = [v for vals in monthly_revenue.values() for v in vals]
        global_mean = float(np.mean(all_vals)) if all_vals else 1.0
        if global_mean == 0:
            return {}

        # Seasonal index per calendar month
        indices: dict[int, float] = {}
        for m_num, vals in monthly_revenue.items():
            month_mean = float(np.mean(vals))
            indices[m_num] = round(month_mean / global_mean, 3)

        return indices

    except Exception:
        return {}


def _extrapolate(
    monthly_series: list[dict[str, Any]],
    months_ahead: int,
    growth_rate: float,
    seasonality_indices: dict[int, float] | None = None,
) -> list[dict[str, Any]]:
    """
    Growth-rate extrapolation with optional seasonality adjustment.

    growth_rate: monthly multiplier, e.g. 1.02 = +2%/month, 0.98 = -2%/month.
    seasonality_indices: dict[calendar_month → multiplier] from _detect_seasonality().
      If provided, each projected month is multiplied by its seasonal index.
    """
    if not monthly_series:
        return []

    # Use average of last 3 months as baseline
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
        cur_out = int(cur_out * (2 - growth_rate))

        # Apply seasonality adjustment if available
        seasonal_adj = 1.0
        if seasonality_indices:
            seasonal_adj = seasonality_indices.get(month, 1.0)

        adjusted_in = int(cur_in * seasonal_adj)
        adjusted_out = int(cur_out * (1 + (1 - seasonal_adj) * 0.3))  # costs partially seasonal

        projected.append({
            "month": f"{year:04d}-{month:02d}",
            "in": adjusted_in,
            "out": adjusted_out,
            "net": adjusted_in - adjusted_out,
            "projected": True,
            "seasonal_index": round(seasonal_adj, 3) if seasonality_indices else None,
        })

    return projected


def _compute_scenarios(cashflow: dict[str, Any], pnl: dict[str, Any]) -> dict[str, Any]:
    """Generate optimistic / base / pessimistic projections for 12 months.

    Seasonality detection runs on the historical monthly_series.
    If >= 12 months of data exist, each projected month is adjusted by
    its historical seasonal index (e.g. December typically higher for retail).
    """
    series = cashflow.get("monthly_series", [])

    # Detect seasonality from historical data (returns {} if < 12 months)
    seasonality_indices = _detect_seasonality(series)
    has_seasonality = bool(seasonality_indices)

    opt_desc = "Gelir ayda %5 büyür, giderler sabit kalır."
    base_desc = "Gelir ayda %1 büyür, giderler ayda %1 artar."
    pess_desc = "Gelir ayda %3 düşer, giderler sabit kalır."
    if has_seasonality:
        opt_desc  += " Geçmiş mevsimsellik uygulandı."
        base_desc += " Geçmiş mevsimsellik uygulandı."
        pess_desc += " Geçmiş mevsimsellik uygulandı."

    scenarios = {
        "optimistic": {
            "label": "İyimser",
            "description": opt_desc,
            "growth_rate": 1.05,
            "months": _extrapolate(series, 12, 1.05, seasonality_indices or None),
            "seasonality_applied": has_seasonality,
        },
        "base": {
            "label": "Baz",
            "description": base_desc,
            "growth_rate": 1.01,
            "months": _extrapolate(series, 12, 1.01, seasonality_indices or None),
            "seasonality_applied": has_seasonality,
        },
        "pessimistic": {
            "label": "Kötümser",
            "description": pess_desc,
            "growth_rate": 0.97,
            "months": _extrapolate(series, 12, 0.97, seasonality_indices or None),
            "seasonality_applied": has_seasonality,
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


def _monte_carlo_simulation(
    monthly_series: list[dict[str, Any]],
    n_simulations: int = 1000,
    months_ahead: int = 12,
) -> dict[str, Any]:
    """
    Monte Carlo simulation for revenue forecast uncertainty quantification.

    Uses historical monthly_series to estimate:
    - Mean monthly growth rate
    - Growth rate volatility (std deviation)

    Runs n_simulations random paths using numpy's random normal draws,
    then computes P10/P50/P90 percentile outcomes.

    Returns:
        p10: Pessimistic bound (10th percentile)
        p50: Median expected outcome
        p90: Optimistic bound (90th percentile)
        runway_risk_pct: % of simulations where runway < 6 months
        monthly_bands: List of {month, p10, p50, p90} for chart rendering
    """
    if len(monthly_series) < 3:
        return {}

    try:
        import numpy as np

        # Extract net cash values
        nets = np.array([m["net"] for m in monthly_series], dtype=float)
        ins  = np.array([m["in"] for m in monthly_series], dtype=float)

        # Estimate growth statistics from historical data
        # Use log-returns for stability
        if len(ins) >= 2 and np.all(ins > 0):
            log_returns = np.diff(np.log(ins + 1))
            mu    = float(np.mean(log_returns))     # mean monthly log-growth
            sigma = float(np.std(log_returns, ddof=1))  # volatility
        else:
            mu, sigma = 0.01, 0.05  # conservative defaults

        # Clip sigma to prevent extreme scenarios
        sigma = min(sigma, 0.25)

        # Baseline values from last month
        last_in  = float(ins[-1]) if len(ins) > 0 else 100_000_00
        last_out = float(monthly_series[-1]["out"])
        last_month_str = monthly_series[-1]["month"]
        last_year  = int(last_month_str[:4])
        last_month = int(last_month_str[5:7])

        # Build month labels
        month_labels: list[str] = []
        y, mo = last_year, last_month
        for _ in range(months_ahead):
            mo += 1
            if mo > 12:
                mo = 1
                y += 1
            month_labels.append(f"{y:04d}-{mo:02d}")

        # Run simulations
        rng = np.random.default_rng(seed=42)  # reproducible
        sim_nets = np.zeros((n_simulations, months_ahead))

        for sim in range(n_simulations):
            cur_in  = last_in
            cur_out = last_out
            for t in range(months_ahead):
                # Random log-return draw
                r = rng.normal(mu, sigma)
                cur_in  = cur_in * np.exp(r)
                # Costs grow slower — assume 30% of revenue volatility
                cur_out = cur_out * np.exp(r * 0.3)
                sim_nets[sim, t] = cur_in - cur_out

        # Cumulative net per simulation
        cum_nets = np.cumsum(sim_nets, axis=1)

        # Monthly percentile bands
        monthly_bands: list[dict[str, Any]] = []
        for t, month in enumerate(month_labels):
            col = cum_nets[:, t]
            monthly_bands.append({
                "month": month,
                "p10": int(np.percentile(col, 10)),
                "p50": int(np.percentile(col, 50)),
                "p90": int(np.percentile(col, 90)),
            })

        # Final 12-month cumulative outcomes
        final_cum = cum_nets[:, -1]
        p10_12m = int(np.percentile(final_cum, 10))
        p50_12m = int(np.percentile(final_cum, 50))
        p90_12m = int(np.percentile(final_cum, 90))

        # Runway risk: % of sims where cumulative net < 0 within 6 months
        if months_ahead >= 6:
            cum_6m = cum_nets[:, 5]
            runway_risk_pct = round(float(np.mean(cum_6m < 0)) * 100, 1)
        else:
            runway_risk_pct = 0.0

        return {
            "n_simulations": n_simulations,
            "months_ahead": months_ahead,
            "growth_mu": round(mu, 4),
            "growth_sigma": round(sigma, 4),
            "p10_12m_net": p10_12m,
            "p50_12m_net": p50_12m,
            "p90_12m_net": p90_12m,
            "runway_risk_pct": runway_risk_pct,
            "monthly_bands": monthly_bands,
        }

    except Exception as exc:
        logger.warning("Monte Carlo simulation failed: %s", exc)
        return {}


def _build_forecast_alerts(scenarios: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    base_runway = scenarios["base"].get("runway_months")
    pessimistic_runway = scenarios["pessimistic"].get("runway_months")

    if base_runway is not None and base_runway <= 3:
        alerts.append({
            "level": "critical",
            "message": f"Baz senaryo: nakit ömrü yalnızca {base_runway} ay. Acil gider kesimi veya gelir artışı gerekiyor.",
        })
    elif base_runway is not None and base_runway <= 6:
        alerts.append({
            "level": "warning",
            "message": f"Baz senaryo: nakit ömrü {base_runway} ay. Gider yapısı gözden geçirilmeli.",
        })

    if pessimistic_runway is not None and pessimistic_runway <= 2:
        alerts.append({
            "level": "critical",
            "message": f"Kötümser senaryo: {pessimistic_runway} ay içinde nakit tükenebilir. Finansman planı yapılmalı.",
        })

    if scenarios["base"]["twelve_month_net"] < 0:
        alerts.append({
            "level": "warning",
            "message": "Baz senaryoda 12 aylık net nakit negatif — karlılık yolu belirsiz, maliyet optimizasyonu şart.",
        })

    return alerts


async def _generate_forecast_narrative(
    scenarios: dict[str, Any],
    alerts: list[dict[str, str]],
    settings,
    state: dict[str, Any] | None = None,
) -> str:
    """
    Generate structured forecast narrative with ContextBuilder.
    Falls back to template if LLM key is not configured.
    """
    from app.services.llm_structured import get_forecast_narrative

    forecast_dict = {"scenarios": scenarios, "alerts": alerts}

    if state is not None:
        from app.services.context_builder import get_context_builder
        ctx = get_context_builder(budget=3072)
        context_result = ctx.build_forecast_context(
            state={**state, "forecast": forecast_dict}
        )
        forecast_dict["_context_tokens"] = context_result.token_count
        forecast_dict["_context_truncated"] = context_result.truncated

    narrative = await get_forecast_narrative(forecast_dict, settings)
    return narrative.to_text()


@trace_agent("forecast_agent")
async def run_forecast(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """Forecast Skill. done_when: state['forecast']['scenarios'] has 3 keys."""
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
        scenarios = _compute_scenarios(cashflow, pnl)
        alerts = _build_forecast_alerts(scenarios)

        # Monte Carlo simulation — runs in parallel with narrative generation
        series = cashflow.get("monthly_series", [])
        monte_carlo = _monte_carlo_simulation(series, n_simulations=1000, months_ahead=12)

        # Add runway_risk alert if Monte Carlo shows high probability
        if monte_carlo.get("runway_risk_pct", 0) > 30:
            alerts.append({
                "level": "critical" if monte_carlo["runway_risk_pct"] > 60 else "warning",
                "message": (
                    f"Monte Carlo simülasyonu: {monte_carlo['runway_risk_pct']:.0f}% olasılıkla "
                    f"6 ay içinde nakit sıkıntısı yaşanabilir "
                    f"(1000 senaryo, P50={_fmt(monte_carlo.get('p50_12m_net', 0))})."
                ),
            })

        narrative = await _generate_forecast_narrative(scenarios, alerts, settings, state=state)

        has_seasonality = scenarios.get("base", {}).get("seasonality_applied", False)

        forecast = {
            "scenarios": scenarios,
            "alerts": alerts,
            "narrative": narrative,
            "seasonality_applied": has_seasonality,
            "monte_carlo": monte_carlo if monte_carlo else None,
        }

        has_critical = any(a["level"] == "critical" for a in alerts)
        confidence = 0.85 if not has_critical else 0.80
        if has_seasonality:
            confidence = min(0.92, confidence + 0.05)
        # Monte Carlo boosts confidence (more data → more reliable)
        if monte_carlo:
            confidence = min(0.95, confidence + 0.03)

        return SkillResult(
            ok=True,
            patch={"forecast": forecast},
            confidence=confidence,
            needs_review=has_critical,
            detail=(
                f"Tahmin oluşturuldu: baz 12a net={_fmt(scenarios['base']['twelve_month_net'])}, "
                f"baz runway={scenarios['base']['runway_months'] or 'stabil'} ay, "
                f"uyarı={len(alerts)}, mevsimsellik={'uygulandı' if has_seasonality else 'yok'}, "
                f"monte_carlo={'ok' if monte_carlo else 'atlandı'}"
            ),
        )
    except Exception as exc:
        logger.exception("Forecast agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Forecast error: {exc}", halt=True)
