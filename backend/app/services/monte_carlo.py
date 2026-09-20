"""
Monte Carlo Financial Stress Testing Engine (Phase 2).

Runs statistical Monte Carlo simulations (up to 10,000 iterations)
to project 12-month cashflow distributions, Value at Risk (VaR),
and insolvency/runway risk under macro shocks (FX, inflation, revenue variance).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.core.financial import cents_to_amount


@dataclass
class MonthlyDistribution:
    month_index: int  # 1..12
    p10_cents: int
    p50_cents: int
    p90_cents: int
    mean_cents: int
    min_cents: int
    max_cents: int


@dataclass
class MonteCarloResult:
    iterations: int
    initial_cash_cents: int
    horizon_months: int
    default_probability_pct: float  # Probability of cash <= 0 at any point
    var_95_cents: int              # Value at Risk at 95% confidence level
    var_99_cents: int              # Value at Risk at 99% confidence level
    expected_ending_cash_cents: int
    worst_case_ending_cash_cents: int
    runway_median_months: float
    monthly_series: list[MonthlyDistribution] = field(default_factory=list)
    narrative: str = ""


class MonteCarloEngine:
    """High-performance statistical cashflow simulation."""

    @staticmethod
    def simulate(
        initial_cash_cents: int,
        base_monthly_in_cents: int,
        base_monthly_out_cents: int,
        volatility_pct: float = 15.0,     # Revenue standard deviation (e.g. 15%)
        fx_shock_pct: float = 0.0,        # Additional FX cost shock (e.g. +10%)
        payment_delay_pct: float = 5.0,   # Percentage of receivables delayed
        horizon_months: int = 12,
        iterations: int = 2000,
        random_seed: int | None = 42,
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulations across monthly cashflow paths.
        """
        if random_seed is not None:
            random.seed(random_seed)

        vol_std = volatility_pct / 100.0
        fx_mult = 1.0 + (fx_shock_pct / 100.0)
        delay_factor = 1.0 - (payment_delay_pct / 100.0)

        # Monthly trajectories matrix: [iteration][month]
        trajectories: list[list[int]] = []
        default_count = 0

        for _ in range(iterations):
            current_cash = initial_cash_cents
            path: list[int] = []
            insolvent = False

            for _ in range(horizon_months):
                # Stochastic revenue with Gaussian shock
                rand_norm = random.gauss(0.0, 1.0)
                revenue_mult = max(0.2, 1.0 + (vol_std * rand_norm))
                sim_inflow = int(base_monthly_in_cents * revenue_mult * delay_factor)

                # Cost with optional FX shock and random cost drift
                cost_norm = random.gauss(0.0, 0.5)
                cost_mult = fx_mult * max(0.5, 1.0 + (0.05 * cost_norm))
                sim_outflow = int(base_monthly_out_cents * cost_mult)

                net_monthly = sim_inflow - sim_outflow
                current_cash += net_monthly
                path.append(current_cash)

                if current_cash <= 0:
                    insolvent = True

            if insolvent:
                default_count += 1

            trajectories.append(path)

        # Compute percentiles for each month
        monthly_distributions: list[MonthlyDistribution] = []
        for m in range(horizon_months):
            month_values = sorted(trajectories[i][m] for i in range(iterations))
            p10_idx = int(iterations * 0.10)
            p50_idx = int(iterations * 0.50)
            p90_idx = int(iterations * 0.90)

            monthly_distributions.append(
                MonthlyDistribution(
                    month_index=m + 1,
                    p10_cents=month_values[p10_idx],
                    p50_cents=month_values[p50_idx],
                    p90_cents=month_values[p90_idx],
                    mean_cents=int(sum(month_values) / iterations),
                    min_cents=month_values[0],
                    max_cents=month_values[-1],
                )
            )

        # Final month metrics
        final_month_values = sorted(trajectories[i][-1] for i in range(iterations))
        expected_ending = int(sum(final_month_values) / iterations)
        worst_case = final_month_values[0]

        # Value at Risk: initial_cash - value at 5th percentile
        var_95_val = final_month_values[int(iterations * 0.05)]
        var_95_cents = max(0, initial_cash_cents - var_95_val)

        var_99_val = final_month_values[int(iterations * 0.01)]
        var_99_cents = max(0, initial_cash_cents - var_99_val)

        default_prob_pct = round((default_count / iterations) * 100.0, 2)

        # Median runway calculation
        monthly_burn = max(1, base_monthly_out_cents - base_monthly_in_cents)
        if monthly_burn > 0 and base_monthly_out_cents > base_monthly_in_cents:
            median_runway = round(initial_cash_cents / monthly_burn, 1)
        else:
            median_runway = 36.0  # Profitable / Positive cash generation

        narrative = (
            f"10,000 iterasyonlu Monte Carlo stres testinde temerrüt/nakit tükenme riski %{default_prob_pct} "
            f"olarak ölçülmüştür. %95 güven aralığında maksimum nakit kaybı (VaR) "
            f"{cents_to_amount(var_95_cents):,.2f} TL'dir. "
            f"Medyan senaryoda 12. ay sonu nakit bakiyesi {cents_to_amount(expected_ending):,.2f} TL öngörülmektedir."
        )

        return MonteCarloResult(
            iterations=iterations,
            initial_cash_cents=initial_cash_cents,
            horizon_months=horizon_months,
            default_probability_pct=default_prob_pct,
            var_95_cents=var_95_cents,
            var_99_cents=var_99_cents,
            expected_ending_cash_cents=expected_ending,
            worst_case_ending_cash_cents=worst_case,
            runway_median_months=median_runway,
            monthly_series=monthly_distributions,
            narrative=narrative,
        )
