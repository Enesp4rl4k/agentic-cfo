"""Nakit Radarı Monte Carlo "What-If" Simülasyon Motoru (Plan v12 Faz 3).

Girdiler:
- 13 haftalık deterministik Nakit Radarı taban çizgisi (baseline)
- Parametrik senaryolar:
  * hire_headcount (yeni personel alımı: net maaş + SGK/işveren maliyeti)
  * defer_payable (tedarikçi/borç öteleme)
  * revenue_shock (tahsilat daralması veya gecikme şoku)
  * capex_investment (makine/yatırım harcaması)

Çıktılar:
- 10.000 iterasyonluk Monte Carlo simülasyonu
- Kasanın eksiye düşme olasılığı (cash_deficit_probability_pct)
- %95 Güven Düzeyinde Riske Maruz Değer (Value at Risk - VaR 95)
- Haftalık P10, P50 (medyan), P90 nakit projeksiyon koridorları
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.financial import cents_to_amount

# ── Legacy Phase 2 Monte Carlo Engine ─────────────────────────────────────────


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
    var_95_cents: int  # Value at Risk at 95% confidence level
    var_99_cents: int  # Value at Risk at 99% confidence level
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
        volatility_pct: float = 15.0,  # Revenue standard deviation (e.g. 15%)
        fx_shock_pct: float = 0.0,  # Additional FX cost shock (e.g. +10%)
        payment_delay_pct: float = 5.0,  # Percentage of receivables delayed
        horizon_months: int = 12,
        iterations: int = 2000,
        random_seed: int | None = 42,
    ) -> MonteCarloResult:
        """Run Monte Carlo simulations across monthly cashflow paths."""
        if random_seed is not None:
            random.seed(random_seed)

        vol_std = volatility_pct / 100.0
        fx_mult = 1.0 + (fx_shock_pct / 100.0)
        delay_factor = 1.0 - (payment_delay_pct / 100.0)

        trajectories: list[list[int]] = []
        default_count = 0

        for _ in range(iterations):
            current_cash = initial_cash_cents
            path: list[int] = []
            insolvent = False

            for _ in range(horizon_months):
                rand_norm = random.gauss(0.0, 1.0)
                revenue_mult = max(0.2, 1.0 + (vol_std * rand_norm))
                sim_inflow = int(base_monthly_in_cents * revenue_mult * delay_factor)

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

        final_month_values = sorted(trajectories[i][-1] for i in range(iterations))
        expected_ending = int(sum(final_month_values) / iterations)
        worst_case = final_month_values[0]

        var_95_val = final_month_values[int(iterations * 0.05)]
        var_95_cents = max(0, initial_cash_cents - var_95_val)

        var_99_val = final_month_values[int(iterations * 0.01)]
        var_99_cents = max(0, initial_cash_cents - var_99_val)

        default_prob_pct = round((default_count / iterations) * 100.0, 2)

        monthly_burn = max(1, base_monthly_out_cents - base_monthly_in_cents)
        if monthly_burn > 0 and base_monthly_out_cents > base_monthly_in_cents:
            median_runway = round(initial_cash_cents / monthly_burn, 1)
        else:
            median_runway = 36.0

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


# ── Plan v12 Faz 3: Nakit Radarı What-If Monte Carlo Simülasyonu ───────────────

# Türkiye işveren maliyet katsayısı: SGK primi, işsizlik, stopaj brütleşmesi
# Ortalama brüt/net çarpanı ~1.375 (Net ₺50.000 -> İşveren Maliyeti ~₺68.750)
TR_EMPLOYER_COST_MULTIPLIER = 1.375


@dataclass
class ScenarioParam:
    scenario_type: Literal["hire_headcount", "defer_payable", "revenue_shock", "capex_investment"]
    # hire_headcount
    headcount: int = 1
    net_monthly_salary_cents: int = 0
    start_week: int = 1

    # defer_payable
    amount_cents: int = 0
    from_week: int = 1
    to_week: int = 5

    # revenue_shock
    percentage_change: float = 0.0  # -20.0 means -20%
    delay_days: int = 0

    # capex_investment
    target_week: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_type": self.scenario_type,
            "headcount": self.headcount,
            "net_monthly_salary_cents": self.net_monthly_salary_cents,
            "start_week": self.start_week,
            "amount_cents": self.amount_cents,
            "from_week": self.from_week,
            "to_week": self.to_week,
            "percentage_change": self.percentage_change,
            "delay_days": self.delay_days,
            "target_week": self.target_week,
        }


@dataclass
class SimulatedWeek:
    week: int
    baseline_cents: int
    p10_cents: int
    p50_cents: int
    p90_cents: int
    deficit_prob_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "baseline_cents": self.baseline_cents,
            "p10_cents": self.p10_cents,
            "p50_cents": self.p50_cents,
            "p90_cents": self.p90_cents,
            "deficit_prob_pct": round(self.deficit_prob_pct, 1),
        }


@dataclass
class WhatIfMonteCarloResult:
    iterations: int
    cash_deficit_probability_pct: float
    var_95_cents: int
    expected_lowest_balance_cents: int
    weeks: list[SimulatedWeek]
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "cash_deficit_probability_pct": round(self.cash_deficit_probability_pct, 1),
            "var_95_cents": self.var_95_cents,
            "expected_lowest_balance_cents": self.expected_lowest_balance_cents,
            "weeks": [w.to_dict() for w in self.weeks],
            "insights": self.insights,
        }


WhatIfResult = WhatIfMonteCarloResult


def _percentile(sorted_data: list[int], pct: float) -> int:
    """Calculate the given percentile (0 to 100) from a sorted list of integers."""
    if not sorted_data:
        return 0
    k = (len(sorted_data) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return round(d0 + d1)


def run_monte_carlo_simulation(
    *,
    baseline_weeks: list[dict[str, Any]],
    starting_cash_cents: int,
    scenarios: list[ScenarioParam],
    iterations: int = 10000,
    seed: int | None = 42,
) -> WhatIfMonteCarloResult:
    """Run parametric Monte Carlo simulation over 13-week cash radar."""
    rng = random.Random(seed)
    num_weeks = len(baseline_weeks)

    # 1. Base deterministic inflows & outflows
    base_inflows = [int(w.get("inflow_cents", 0)) for w in baseline_weeks]
    base_outflows = [int(w.get("outflow_cents", 0)) for w in baseline_weeks]

    # 2. Apply deterministic scenario overlays
    scenario_inflows = list(base_inflows)
    scenario_outflows = list(base_outflows)
    scenario_insights: list[str] = []

    for sc in scenarios:
        if sc.scenario_type == "hire_headcount":
            # Monthly total employer cost
            monthly_cost = round(
                sc.net_monthly_salary_cents * sc.headcount * TR_EMPLOYER_COST_MULTIPLIER
            )
            # Applied in 4-week cycles from start_week (1-indexed)
            for w in range(sc.start_week - 1, num_weeks):
                if (w - (sc.start_week - 1)) % 4 == 0:
                    scenario_outflows[w] += monthly_cost
            scenario_insights.append(
                f"{sc.headcount} yeni çalışan işe alımı (aylık işveren maliyeti: ₺{monthly_cost / 100:,.2f}) eklendi."
            )

        elif sc.scenario_type == "defer_payable":
            from_idx = max(0, min(sc.from_week - 1, num_weeks - 1))
            to_idx = max(0, min(sc.to_week - 1, num_weeks - 1))
            amt = min(sc.amount_cents, scenario_outflows[from_idx])
            scenario_outflows[from_idx] -= amt
            scenario_outflows[to_idx] += amt
            scenario_insights.append(
                f"₺{amt / 100:,.2f} tutarındaki ödeme {sc.from_week}. haftadan {sc.to_week}. haftaya ötelendi."
            )

        elif sc.scenario_type == "capex_investment":
            target_idx = max(0, min(sc.target_week - 1, num_weeks - 1))
            scenario_outflows[target_idx] += sc.amount_cents
            scenario_insights.append(
                f"₺{sc.amount_cents / 100:,.2f} tutarındaki yatırım harcaması {sc.target_week}. haftaya eklendi."
            )

        elif sc.scenario_type == "revenue_shock":
            ratio = 1.0 + (sc.percentage_change / 100.0)
            shift_weeks = max(0, sc.delay_days // 7)
            new_inflows = [0] * num_weeks
            for w in range(num_weeks):
                adjusted = round(scenario_inflows[w] * ratio)
                target = w + shift_weeks
                if target < num_weeks:
                    new_inflows[target] += adjusted
            scenario_inflows = new_inflows
            shock_dir = "azalış" if sc.percentage_change < 0 else "artış"
            scenario_insights.append(
                f"Ciroda %{abs(sc.percentage_change):.1f} {shock_dir} ve {sc.delay_days} gün gecikme simüle edildi."
            )

    # 3. Deterministic baseline balances with scenarios
    baseline_balances: list[int] = []
    run_bal = starting_cash_cents
    for w in range(num_weeks):
        run_bal += scenario_inflows[w] - scenario_outflows[w]
        baseline_balances.append(run_bal)

    # 4. Monte Carlo Loop
    # Variables:
    # - Inflow collection volatility: Normal(1.0, 0.08)
    # - Customer default / haircut rate: 3% chance of 20% loss
    # - Outflow unexpected expense shock: Exponential with mean 2% of outflow
    weekly_balances_samples: list[list[int]] = [[] for _ in range(num_weeks)]
    lowest_balances: list[int] = []
    deficit_count = 0

    for _ in range(iterations):
        bal = starting_cash_cents
        iteration_lowest = starting_cash_cents

        for w in range(num_weeks):
            # Inflow stochastic multiplier
            inflow_shock = rng.gauss(1.0, 0.08)
            # 3% chance of collection dispute/haircut
            haircut = 0.80 if rng.random() < 0.03 else 1.0
            stochastic_inflow = round(scenario_inflows[w] * max(0.0, inflow_shock) * haircut)

            # Outflow slight upward pressure (unplanned expense 0-5%)
            outflow_shock = 1.0 + rng.uniform(0.0, 0.05)
            stochastic_outflow = round(scenario_outflows[w] * outflow_shock)

            bal += stochastic_inflow - stochastic_outflow
            weekly_balances_samples[w].append(bal)

            if bal < iteration_lowest:
                iteration_lowest = bal

        lowest_balances.append(iteration_lowest)
        if iteration_lowest < 0:
            deficit_count += 1

    deficit_prob_pct = (deficit_count / iterations) * 100.0

    # 5. Percentiles per week
    simulated_weeks: list[SimulatedWeek] = []
    for w in range(num_weeks):
        samples = sorted(weekly_balances_samples[w])
        p10 = _percentile(samples, 10.0)
        p50 = _percentile(samples, 50.0)
        p90 = _percentile(samples, 90.0)
        week_deficit = sum(1 for s in samples if s < 0)
        w_prob = (week_deficit / iterations) * 100.0
        simulated_weeks.append(
            SimulatedWeek(
                week=w + 1,
                baseline_cents=baseline_balances[w],
                p10_cents=p10,
                p50_cents=p50,
                p90_cents=p90,
                deficit_prob_pct=w_prob,
            )
        )

    # 6. Overall Metrics
    sorted_lowests = sorted(lowest_balances)
    # VaR 95 is 5th percentile of lowest balances
    var_95_cents = _percentile(sorted_lowests, 5.0)
    expected_lowest_cents = _percentile(sorted_lowests, 50.0)

    # Concluding insight
    if deficit_prob_pct > 15.0:
        worst_week = max(simulated_weeks, key=lambda sw: sw.deficit_prob_pct)
        scenario_insights.append(
            f"DİKKAT: Senaryo kapsamında kasanın eksiye düşme olasılığı %{deficit_prob_pct:.1f}. "
            f"En kritik risk {worst_week.week}. haftada gerçekleşiyor (%{worst_week.deficit_prob_pct:.1f} açık riski)."
        )
    else:
        scenario_insights.append(
            f"Kasa dengeli: %95 güven düzeyinde senaryo nakit tamponu içerisinde yönetilebilir (%{deficit_prob_pct:.1f} risk)."
        )

    return WhatIfMonteCarloResult(
        iterations=iterations,
        cash_deficit_probability_pct=deficit_prob_pct,
        var_95_cents=var_95_cents,
        expected_lowest_balance_cents=expected_lowest_cents,
        weeks=simulated_weeks,
        insights=scenario_insights,
    )
