"""
Forecast Agent — Skill 4 of 5.

Responsibility: Generate 3/6/12-month financial forecasts with three scenarios
(optimistic, base, pessimistic). Detects runway risk and cash-out dates.

Uses historical monthly series from P&L + Cash Flow to extrapolate trends.
GPT-4o adds strategic commentary on each scenario.

Cash runway starts from the balance a bank statement proves (`app.services.runway`):
with no proven balance there is no runway, and an alert, however severe, is shown and
never a reason to hold the run (a hold is for what a person can decide about THIS upload).

done_when: state['forecast'] contains scenarios dict and alerts list.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from app.agents.forecast_montecarlo import _monte_carlo_simulation
from app.agents.narrative_guard import narrative_guard
from app.agents.state import AgentRunConfig, CFOState, SkillResult
from app.config import get_settings
from app.services.runway import (
    NO_BALANCE,
    RUNWAY_MIN_MONTHS,
    can_project,
    compute_runway,
    opening_cash_for,
    runway_alert,
)
from app.services.telemetry import trace_agent

logger = logging.getLogger(__name__)


def _fmt(cents: int) -> str:
    return f"₺{cents / 100:,.0f}"


SEASONALITY_MIN_MONTHS = 24   # every calendar month observed at least twice


def _detect_seasonality(
    monthly_series: list[dict[str, Any]],
) -> dict[int, float]:
    """
    Detect monthly seasonality indices using numpy.

    Returns a dict mapping month number (1-12) to a seasonality multiplier.
    1.0 = average month, 1.3 = 30% above average, 0.7 = 30% below average.

    Index = a calendar month's mean income / the mean of all months (no
    detrending). It needs every calendar month seen at least twice — at least
    24 months. From one year each "index" is that month's own noise, and it was
    applied to the forecast (live audit 2026-10-24: January 0,627 from 2024
    alone; plan v8 §A3). Less history → {} and a flat projection.
    """
    if len(monthly_series) < SEASONALITY_MIN_MONTHS:
        return {}  # Not enough data for seasonality

    try:
        import numpy as np

        # Build arrays indexed by calendar month
        monthly_revenue: dict[int, list[int]] = {}  # month_key → income
        for entry in monthly_series:
            m_num = int(entry["month"][5:7])
            monthly_revenue.setdefault(m_num, []).append(entry["in"])

        if len(monthly_revenue) < 12 or min(len(v) for v in monthly_revenue.values()) < 2:
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
    revenue_rate: float = 1.01,
    cost_rate: float = 1.01,
    seasonality_indices: dict[int, float] | None = None,
    # Deprecated alias kept for backward compatibility — use revenue_rate instead
    growth_rate: float | None = None,
) -> list[dict[str, Any]]:
    """
    Growth-rate extrapolation with independent revenue and cost rates.

    revenue_rate: monthly revenue multiplier, e.g. 1.05 = +5%/month
    cost_rate:    monthly cost multiplier,    e.g. 0.99 = -1%/month
    seasonality_indices: dict[calendar_month → multiplier] from _detect_seasonality().
      If provided, each projected month's revenue is multiplied by its seasonal index.
      Costs get a partial seasonal adjustment (30% of the revenue seasonal effect).

    Note: The old single `growth_rate` parameter incorrectly derived cost_rate as
    (2 - growth_rate), which caused costs to *decrease* in optimistic scenarios.
    This is now fixed by explicitly separating revenue_rate and cost_rate.
    """
    if not monthly_series:
        return []

    # Backward compatibility: the deprecated growth_rate sets the revenue rate
    # (comparing floats to the defaults to guess whether a caller set them
    # could not tell an explicit 1.01 from the default)
    if growth_rate is not None:
        revenue_rate = growth_rate
        cost_rate = 1.0  # neutral cost assumption for legacy callers

    # Use average of last 3 months as baseline
    recent = monthly_series[-3:] if len(monthly_series) >= 3 else monthly_series
    avg_in  = int(statistics.mean(e["in"]  for e in recent))
    avg_out = int(statistics.mean(e["out"] for e in recent))

    projected: list[dict[str, Any]] = []
    cur_in  = avg_in
    cur_out = avg_out

    last_month = monthly_series[-1]["month"]
    year, month = int(last_month[:4]), int(last_month[5:7])

    for _i in range(1, months_ahead + 1):
        month += 1
        if month > 12:
            month = 1
            year += 1

        cur_in  = int(cur_in  * revenue_rate)
        cur_out = int(cur_out * cost_rate)

        # Apply seasonality adjustment to revenue
        seasonal_adj = 1.0
        if seasonality_indices:
            seasonal_adj = seasonality_indices.get(month, 1.0)

        adjusted_in  = int(cur_in  * seasonal_adj)
        # Costs get a partial seasonal effect (30% of revenue swing)
        cost_seasonal = 1.0 + (seasonal_adj - 1.0) * 0.3
        adjusted_out = int(cur_out * cost_seasonal)

        projected.append({
            "month": f"{year:04d}-{month:02d}",
            "in":    adjusted_in,
            "out":   adjusted_out,
            "net":   adjusted_in - adjusted_out,
            "projected": True,
            "seasonal_index": round(seasonal_adj, 3) if seasonality_indices else None,
        })

    return projected


def _compute_scenarios(
    cashflow: dict[str, Any], pnl: dict[str, Any], runway: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Generate optimistic / base / pessimistic projections for 12 months.

    Seasonality detection runs on the historical monthly_series.
    If >= 12 months of data exist, each projected month is adjusted by
    its historical seasonal index (e.g. December typically higher for retail).

    Scenario definitions (revenue_rate, cost_rate):
      optimistic:  revenue +5%/mo, costs -1%/mo (efficiency gains)
      base:        revenue +1%/mo, costs +1%/mo (steady state)
      pessimistic: revenue -3%/mo, costs +1%/mo (contracting market)

    `runway` is the measured runway block (`app.services.runway.compute_runway`): scenario
    runways count down from its proven opening cash, and only when the burn is measured too.
    Without it they are None: unknown, not "stable".
    """
    series = cashflow.get("monthly_series", [])

    # Detect seasonality from historical data (returns {} below 24 months)
    seasonality_indices = _detect_seasonality(series)
    has_seasonality = bool(seasonality_indices)

    opt_desc  = "Gelir ayda %5 büyür, giderler ayda %1 düşer (verimlilik kazanımları)."
    base_desc = "Gelir ayda %1 büyür, giderler ayda %1 artar (sabit seyir)."
    pess_desc = "Gelir ayda %3 düşer, giderler ayda %1 artar (daralan piyasa)."
    if has_seasonality:
        opt_desc  += " Geçmiş mevsimsellik uygulandı."
        base_desc += " Geçmiş mevsimsellik uygulandı."
        pess_desc += " Geçmiş mevsimsellik uygulandı."

    scenarios = {
        "optimistic": {
            "label": "İyimser",
            "description": opt_desc,
            "revenue_rate": 1.05,
            "growth_rate": 1.05,
            "cost_rate":    0.99,
            "months": _extrapolate(series, 12, revenue_rate=1.05, cost_rate=0.99,
                                   seasonality_indices=seasonality_indices or None),
            "seasonality_applied": has_seasonality,
        },
        "base": {
            "label": "Baz",
            "description": base_desc,
            "revenue_rate": 1.01,
            "growth_rate": 1.01,
            "cost_rate":    1.01,
            "months": _extrapolate(series, 12, revenue_rate=1.01, cost_rate=1.01,
                                   seasonality_indices=seasonality_indices or None),
            "seasonality_applied": has_seasonality,
        },
        "pessimistic": {
            "label": "Kötümser",
            "description": pess_desc,
            "revenue_rate": 0.97,
            "growth_rate": 0.97,
            "cost_rate":    1.01,
            "months": _extrapolate(series, 12, revenue_rate=0.97, cost_rate=1.01,
                                   seasonality_indices=seasonality_indices or None),
            "seasonality_applied": has_seasonality,
        },
    }


    # Runway: months until the proven balance plus the cumulative net goes negative within
    # the projection. Only with a measured balance AND burn: else None, with the reason.
    opening = runway["opening_cash_cents"] if runway and can_project(runway) else None
    for _key, scenario in scenarios.items():
        runway_months: int | None = None
        if opening is not None:
            cumulative = opening
            for i, m in enumerate(scenario["months"], start=1):
                cumulative += m["net"]
                if cumulative < 0:
                    runway_months = i
                    break
        scenario["runway_months"] = runway_months
        scenario["runway_basis"] = runway["status"] if runway else NO_BALANCE
        scenario["twelve_month_net"] = sum(m["net"] for m in scenario["months"])

    return scenarios


def _build_forecast_alerts(
    scenarios: dict[str, Any], runway: dict[str, Any] | None = None, *, limited_history: bool = False
) -> list[dict[str, str]]:
    """What the forecast says about cash, each alert with its basis.

    Only the measured runway (a proven balance over a burn read from enough months) may be
    critical. A scenario is an assumption, so what it says is at most a warning. Whether an
    alert is shown never depends on it being critical, and none of them holds the run.
    """
    alerts: list[dict[str, str]] = []
    if runway is not None:
        measured = runway_alert(runway)
        if measured:
            alerts.append(measured)

    pessimistic_runway = scenarios["pessimistic"].get("runway_months")
    if pessimistic_runway is not None and pessimistic_runway <= 6:
        alerts.append({
            "level": "warning",
            "basis": "scenario",
            "message": (
                f"Kötümser senaryo (varsayım: gelir ayda %3 düşer, gider %1 artar): kasa "
                f"{pessimistic_runway} ay içinde tükenebilir. Bu bir ölçüm değil, bir senaryo."
            ),
        })

    if not limited_history and scenarios["base"]["twelve_month_net"] < 0:
        alerts.append({
            "level": "warning",
            "basis": "scenario",
            "message": "Baz senaryoda 12 aylık net nakit negatif — karlılık yolu belirsiz, maliyet optimizasyonu şart.",
        })

    return alerts


@narrative_guard
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


def _build_scenario_explanation(
    scenarios: dict[str, Any],
    monte_carlo: dict[str, Any] | None,
) -> dict[str, str]:
    """
    S1-3: Human-readable explanation of what each scenario assumes.
    Shows the key growth assumptions behind optimistic/base/pessimistic.
    """
    explanations: dict[str, str] = {}

    for name, sc in scenarios.items():
        growth = (sc.get("revenue_rate", 1.0) - 1.0) * 100
        runway = sc.get("runway_months")
        twelve_net = sc.get("twelve_month_net", 0)

        if name == "optimistic":
            label = "İyimser Senaryo"
            assumption = f"Gelir aylık %{growth:.1f} büyüme varsayıyor"
        elif name == "pessimistic":
            label = "Kötümser Senaryo"
            assumption = f"Gelir aylık %{abs(growth):.1f} daralma varsayıyor"
        else:
            label = "Baz Senaryo"
            assumption = f"Mevcut trend devam ediyor (aylık %{growth:.1f})"

        basis = sc.get("runway_basis")
        runway_text = (
            f"Nakit ömrü: {runway:.0f} ay" if runway
            else "Nakit ömrü: 12 ay içinde tükenmiyor" if basis in ("computed", "not_burning")
            else "Nakit ömrü hesaplanamadı (kasa bakiyesi bilinmiyor ya da yetersiz veri)"
        )

        explanations[name] = (
            f"{label}: {assumption}. "
            f"12 aylık net nakit: {_fmt(twelve_net)}. "
            f"{runway_text}."
        )

    if monte_carlo:
        # What the number is: the share of simulations that go negative — not a
        # forecast's "reliability", which the last sentence used to derive from
        # that same share (a risky outcome is not an unreliable model).
        rp = monte_carlo.get("runway_risk_pct")
        n = monte_carlo.get("n_simulations", 0)
        temel = (
            "aylık büyüme ortalaması ve oynaklığı geçmiş aylarınızdan hesaplandı"
            if monte_carlo.get("growth_basis") == "gecmis_aylar"
            else "geçmiş ay sayısı yetersiz olduğu için varsayılan büyüme ve oynaklık kullanıldı"
        )
        explanations["monte_carlo_summary"] = (
            f"{n} simülasyonun %{rp:.0f}'inde kasa ilk 6 ayda sıfırın altına iniyor ({temel})."
            if rp is not None
            else "Kasa bakiyesi bilinmediği ya da aylık hareket yetersiz olduğu için kasanın "
                 "tükenme payı hesaplanmadı."
        )

    return explanations


def _runway_detail(runway: dict[str, Any]) -> str:
    if runway["runway_months"] is not None:
        return f"{runway['runway_months']} ay"
    return {
        "computed": "36 aydan uzun",
        "not_burning": "nakit azalmıyor",
        "no_balance": "hesaplanamadı (kasa bakiyesi bilinmiyor)",
        "insufficient_history": "hesaplanamadı (yetersiz ay)",
    }.get(runway["status"], "hesaplanamadı")


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
        # One balance, as the cash radar reads it: the proven closing balance of a statement.
        # None when no statement proves one: then there is no runway to claim.
        opening = opening_cash_for(state)  # type: ignore[arg-type]
        runway = compute_runway(opening, cashflow)
        series = cashflow.get("monthly_series", [])
        limited_history = len(series) < RUNWAY_MIN_MONTHS
        scenarios = _compute_scenarios(cashflow, pnl, runway)
        alerts = _build_forecast_alerts(scenarios, runway, limited_history=limited_history)

        # Monte Carlo simulation — runs in parallel with narrative generation
        monte_carlo = _monte_carlo_simulation(
            series, n_simulations=1000, months_ahead=12,
            opening_cash_cents=runway["opening_cash_cents"] if can_project(runway) else None,
        )

        # A share of simulations is a statement about a model: shown as a warning at most,
        # and only when growth and volatility were estimated from this company's months.
        risk_pct = monte_carlo.get("runway_risk_pct")
        if risk_pct is not None and risk_pct > 30 and monte_carlo.get("growth_basis") == "gecmis_aylar":
            alerts.append({
                "level": "warning",
                "basis": "monte_carlo",
                "message": (
                    f"Monte Carlo simülasyonunun %{risk_pct:.0f}'inde kasa 6 ay içinde sıfırın "
                    f"altına iniyor (başlangıç: {_fmt(runway['opening_cash_cents'])}; büyüme ve "
                    f"oynaklık geçmiş aylardan tahmin edildi, 1000 senaryo)."
                ),
            })

        narrative = await _generate_forecast_narrative(scenarios, alerts, settings, state=state)

        has_seasonality = scenarios.get("base", {}).get("seasonality_applied", False)

        # S1-3: scenario explanation + confidence interval
        scenario_explanation = _build_scenario_explanation(scenarios, monte_carlo)

        forecast = {
            "scenarios": scenarios,
            "alerts": alerts,
            "runway": runway,
            "history_months": len(series),
            "limited_history": limited_history,
            "narrative": narrative,
            "seasonality_applied": has_seasonality,
            # Why there is no seasonal shape, in the reader's words: a flat
            # projection from less than two years is not "no seasonality".
            "seasonality_note": (
                None if has_seasonality else
                f"Mevsimsellik için yetersiz veri: {len(cashflow.get('monthly_series') or [])} ay "
                f"(en az {SEASONALITY_MIN_MONTHS} ay gerekir); düz projeksiyon."
            ),
            "monte_carlo": monte_carlo if monte_carlo else None,
            "scenario_explanation": scenario_explanation,
            "confidence_interval": {
                "p10": monte_carlo.get("p10_12m_net") if monte_carlo else None,
                "p50": monte_carlo.get("p50_12m_net") if monte_carlo else None,
                "p90": monte_carlo.get("p90_12m_net") if monte_carlo else None,
                "interpretation": (
                    f"1000 Monte Carlo simülasyonunda: "
                    f"%10 olasılıkla {_fmt(monte_carlo['p10_12m_net'])}'ın altında, "
                    f"%50 olasılıkla {_fmt(monte_carlo['p50_12m_net'])}, "
                    f"%90 olasılıkla {_fmt(monte_carlo['p90_12m_net'])}'ın altında"
                    if monte_carlo and monte_carlo.get("p50_12m_net") is not None
                    else "Monte Carlo simülasyonu çalıştırılamadı"
                ),
            },
        }

        # How sure the forecast is of its own arithmetic. Bad news is not doubt: a critical
        # alert does not lower it, and no alert holds the run (it is shown, with its basis).
        confidence = 0.85
        if has_seasonality:
            confidence = min(0.92, confidence + 0.05)
        # Monte Carlo boosts confidence (more data → more reliable)
        if monte_carlo:
            confidence = min(0.95, confidence + 0.03)

        return SkillResult(
            ok=True,
            patch={"forecast": forecast},
            confidence=confidence,
            needs_review=False,
            detail=(
                f"Tahmin oluşturuldu: baz 12a net={_fmt(scenarios['base']['twelve_month_net'])}, "
                f"nakit pisti={_runway_detail(runway)}, "
                f"uyarı={len(alerts)}, mevsimsellik={'uygulandı' if has_seasonality else 'yok'}, "
                f"monte_carlo={'ok' if monte_carlo else 'atlandı'}"
            ),
        )
    except Exception as exc:
        logger.exception("Forecast agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Forecast error: {exc}", halt=True)
