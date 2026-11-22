"""Monte Carlo simulation behind the forecast's uncertainty band (split out of forecast_agent)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MC_MIN_MONTHS = 6   # 5 log-returns: fewer is not an estimate of growth or volatility


def _monte_carlo_simulation(
    monthly_series: list[dict[str, Any]],
    n_simulations: int = 1000,
    months_ahead: int = 12,
    opening_cash_cents: int | None = None,
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
        runway_risk_pct: % of simulations where the proven balance plus the cumulative
            net goes below zero within 6 months; None without a proven balance
        monthly_bands: List of {month, p10, p50, p90} for chart rendering

    Growth and volatility are estimated from the company's months only with at least
    `MC_MIN_MONTHS` of them; otherwise the labelled defaults (mu 0.01, sigma 0.05) stand in
    (`growth_basis` = "varsayilan") and the result is never a basis for an alert.
    """
    if len(monthly_series) < 3:
        return {}

    try:
        import numpy as np

        # Extract net cash values
        np.array([m["net"] for m in monthly_series], dtype=float)
        ins  = np.array([m["in"] for m in monthly_series], dtype=float)

        # Estimate growth statistics from historical data
        # Use log-returns for stability
        if len(ins) >= MC_MIN_MONTHS and np.all(ins > 0):
            log_returns = np.diff(np.log(ins + 1))
            mu    = float(np.mean(log_returns))     # mean monthly log-growth
            sigma = float(np.std(log_returns, ddof=1))  # volatility
            growth_basis = "gecmis_aylar"
        else:
            # Not this company's numbers: a stand-in when there is too little
            # history. Reported, so nothing presents the result as measured.
            mu, sigma = 0.01, 0.05
            growth_basis = "varsayilan"

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

        # Runway risk: % of sims where the balance (proven opening cash + cumulative net)
        # is below zero within 6 months. Counting from zero, as this once did, called every
        # company with a negative month "at risk" whatever it held in the bank.
        runway_risk_pct: float | None = None
        if opening_cash_cents is not None and months_ahead >= 6:
            cum_6m = cum_nets[:, 5] + opening_cash_cents
            runway_risk_pct = round(float(np.mean(cum_6m < 0)) * 100, 1)

        return {
            "n_simulations": n_simulations,
            "months_ahead": months_ahead,
            "growth_mu": round(mu, 4),
            "growth_sigma": round(sigma, 4),
            "growth_basis": growth_basis,
            "p10_12m_net": p10_12m,
            "p50_12m_net": p50_12m,
            "p90_12m_net": p90_12m,
            "runway_risk_pct": runway_risk_pct,
            "runway_risk_basis": "opening_cash" if runway_risk_pct is not None else None,
            "monthly_bands": monthly_bands,
        }

    except Exception as exc:
        logger.warning("Monte Carlo simulation failed: %s", exc)
        return {}
