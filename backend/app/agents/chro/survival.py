"""
CHRO Survival Analysis — Kaplan-Meier Attrition Risk Model

Answers the critical HR question:
"In which department/seniority band are employees most likely to leave, and when?"

Methods:
  1. Kaplan-Meier Survival Estimator
     - Computes S(t) = P(employee stays past time t)
     - Works with right-censored data (current employees haven't left yet)
     - Groups by: department, level, hire_cohort

  2. Attrition Risk Scoring
     - Combines: tenure, seniority, dept attrition history, compensation gap
     - Outputs per-employee risk score (0-10) and risk tier (low/medium/high/critical)

  3. Median Survival Time
     - "50% of engineers leave within X months" — actionable for workforce planning

  4. High-Risk Cohort Detection
     - Identifies cohorts (dept × level × tenure_band) with accelerating attrition

Uses only scipy + numpy — no external ML dependencies beyond what's in requirements.txt.

Usage:
    from app.agents.chro.survival import SurvivalAnalyzer
    analyzer = SurvivalAnalyzer(employees, departures)
    result = analyzer.compute_full_analysis()
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ── Kaplan-Meier Estimator ────────────────────────────────────────────────────

def kaplan_meier(
    durations: list[float],   # Time at risk (months of tenure or observed time)
    events:    list[bool],    # True = left (event), False = still employed (censored)
) -> dict[str, Any]:
    """
    Compute Kaplan-Meier survival function.

    S(t) = P(employee remains employed past time t)
    = ∏_{t_i ≤ t} (1 - d_i / n_i)

    where:
      d_i = number of departures at time t_i
      n_i = number at risk just before t_i

    Args:
        durations: Tenure in months for each employee (current or at departure)
        events:    True if the employee left, False if still employed (censored)

    Returns:
        {
          "times":           [t0, t1, ...],   # Event times
          "survival_probs":  [S(t0), ...],    # S(t) values
          "n_risk":          [...],            # At-risk count at each time
          "n_events":        [...],            # Events at each time
          "median_survival": float | None,     # Months until 50% retention
          "survival_at_12m": float,            # P(still here after 12 months)
          "survival_at_24m": float,
        }
    """
    if not durations or len(durations) < 3:
        return {"error": "Kaplan-Meier için en az 3 gözlem gerekiyor."}

    n = len(durations)
    # Build sorted event table
    event_table: dict[float, dict[str, int]] = defaultdict(lambda: {"events": 0, "censored": 0})
    for t, e in zip(durations, events):
        if e:
            event_table[t]["events"] += 1
        else:
            event_table[t]["censored"] += 1

    sorted_times = sorted(event_table.keys())
    times:         list[float] = []
    survival:      list[float] = []
    n_risk_list:   list[int]   = []
    n_events_list: list[int]   = []

    s = 1.0
    n_at_risk = n

    for t in sorted_times:
        d = event_table[t]["events"]
        c = event_table[t]["censored"]

        if d > 0:
            times.append(t)
            n_risk_list.append(n_at_risk)
            n_events_list.append(d)
            s *= (1 - d / n_at_risk)
            survival.append(round(s, 4))

        n_at_risk -= (d + c)

    # Median survival: first t where S(t) ≤ 0.5
    median_survival: float | None = None
    for t, s_val in zip(times, survival):
        if s_val <= 0.5:
            median_survival = t
            break

    # Survival at specific horizons
    def _survival_at(horizon: float) -> float:
        for t, s_val in zip(reversed(times), reversed(survival)):
            if t <= horizon:
                return s_val
        return 1.0  # No events before horizon

    return {
        "times":            times,
        "survival_probs":   survival,
        "n_risk":           n_risk_list,
        "n_events":         n_events_list,
        "median_survival":  median_survival,
        "survival_at_6m":   round(_survival_at(6), 3),
        "survival_at_12m":  round(_survival_at(12), 3),
        "survival_at_24m":  round(_survival_at(24), 3),
        "n_employees":      n,
        "n_departures":     sum(1 for e in events if e),
    }


# ── Attrition Risk Scoring ────────────────────────────────────────────────────

def compute_attrition_risk_score(
    employee: dict[str, Any],
    dept_attrition_rates: dict[str, float],
    comp_gap_pct: float = 0.0,  # % below market (positive = below market)
) -> dict[str, Any]:
    """
    Score individual employee attrition risk (0-10, higher = higher risk).

    Risk factors:
    - Tenure bucket (early tenure = higher risk, "honeymoon" effect ends)
    - Seniority level (mid-level is highest risk due to market demand)
    - Department attrition history (if dept has high attrition, risk multiplier)
    - Compensation gap (below market → higher flight risk)

    Returns:
        {risk_score, risk_tier, risk_factors}
    """
    score = 0.0
    factors: list[str] = []

    # ── 1. Tenure risk ────────────────────────────────────────────────────────
    tenure_years = float(employee.get("tenure_years", employee.get("seniority_years", 1)))
    if tenure_years < 0.5:
        score += 3.0
        factors.append("İlk 6 ay — en yüksek risk dönemi")
    elif tenure_years < 1.0:
        score += 2.5
        factors.append("İlk yıl içinde")
    elif tenure_years < 2.0:
        score += 1.5
        factors.append("1-2 yıl arası — kritik karar dönemi")
    elif tenure_years > 5:
        score -= 0.5  # Loyalty discount
        factors.append("5+ yıl kıdem (sadakat bonusu)")

    # ── 2. Level/seniority risk ───────────────────────────────────────────────
    level = str(employee.get("level", "mid")).lower()
    level_risk = {
        "l1": 2.0, "l2": 2.5, "l3": 3.0, "l4": 2.0, "l5": 1.5, "l6": 1.0,
        "junior": 2.5, "mid": 3.0, "senior": 2.0, "lead": 1.5, "staff": 1.0,
        "principal": 0.8, "manager": 1.5, "director": 1.0, "vp": 0.8,
    }
    lvl_score = level_risk.get(level, 2.0)
    score += lvl_score
    if lvl_score >= 2.5:
        factors.append(f"Orta kıdem (piyasa talebi yüksek: {level})")

    # ── 3. Department risk ────────────────────────────────────────────────────
    dept = str(employee.get("department", employee.get("dept", ""))).lower()
    dept_rate = dept_attrition_rates.get(dept, 0.15)  # Default 15% annual
    dept_multiplier = 1 + dept_rate
    score *= dept_multiplier
    if dept_rate > 0.20:
        factors.append(f"Yüksek attrition geçmişi olan departman (%{dept_rate*100:.0f})")

    # ── 4. Compensation risk ──────────────────────────────────────────────────
    if comp_gap_pct > 10:
        score += 2.0
        factors.append(f"Piyasanın %{comp_gap_pct:.0f} altında ücret — yüksek uçuş riski")
    elif comp_gap_pct > 5:
        score += 1.0
        factors.append(f"Piyasanın %{comp_gap_pct:.0f} altında ücret")

    # Cap at 10
    score = min(10.0, max(0.0, round(score, 1)))

    # Risk tier
    if score >= 7.5:
        tier = "kritik"
    elif score >= 5.5:
        tier = "yüksek"
    elif score >= 3.5:
        tier = "orta"
    else:
        tier = "düşük"

    return {
        "risk_score": score,
        "risk_tier":  tier,
        "risk_factors": factors,
        "employee_id": employee.get("employee_id") or employee.get("id"),
        "name":        employee.get("name"),
        "department":  dept,
        "level":       level,
        "tenure_years": tenure_years,
    }


# ── Full Analysis ─────────────────────────────────────────────────────────────

class SurvivalAnalyzer:
    """
    Full CHRO survival analysis suite.

    Combines Kaplan-Meier curves, attrition risk scoring,
    and cohort-level analysis.
    """

    def __init__(
        self,
        employees: list[dict[str, Any]],    # Current employees
        departures: list[dict[str, Any]],   # Historical departures
    ) -> None:
        self.employees  = employees
        self.departures = departures

    def compute_full_analysis(self) -> dict[str, Any]:
        """
        Run full survival analysis.

        Returns:
            {
              "overall_km":         KM curve for all employees,
              "by_department":      {dept: KM curve},
              "by_level":           {level: KM curve},
              "risk_scores":        [per-employee risk scores],
              "high_risk_cohorts":  [high-risk dept×level groups],
              "summary":            {key metrics},
              "interpretation":     str (Turkish),
            }
        """
        if not self.employees and not self.departures:
            return {"error": "Çalışan verisi yok."}

        # ── Build combined dataset ─────────────────────────────────────────────
        all_records: list[dict[str, Any]] = []

        # Current employees → censored observations
        for emp in self.employees:
            tenure = self._compute_tenure_months(emp)
            all_records.append({
                **emp,
                "tenure_months": tenure,
                "departed": False,
            })

        # Departed employees → actual events
        for dep in self.departures:
            tenure = self._compute_tenure_months(dep)
            all_records.append({
                **dep,
                "tenure_months": tenure,
                "departed": True,
            })

        # ── Overall KM curve ──────────────────────────────────────────────────
        durations = [r["tenure_months"] for r in all_records]
        events    = [r["departed"] for r in all_records]
        overall_km = kaplan_meier(durations, events)

        # ── By department ──────────────────────────────────────────────────────
        dept_groups: dict[str, list[dict]] = defaultdict(list)
        for r in all_records:
            dept = str(r.get("department") or r.get("dept") or "unknown").lower()
            dept_groups[dept].append(r)

        dept_km: dict[str, Any] = {}
        dept_attrition_rates: dict[str, float] = {}
        for dept, records in dept_groups.items():
            if len(records) < 3:
                continue
            d = [r["tenure_months"] for r in records]
            e = [r["departed"] for r in records]
            km = kaplan_meier(d, e)
            dept_km[dept] = km
            # Annual attrition rate approximation: 1 - S(12)
            dept_attrition_rates[dept] = 1 - km.get("survival_at_12m", 0.85)

        # ── By level ──────────────────────────────────────────────────────────
        level_groups: dict[str, list[dict]] = defaultdict(list)
        for r in all_records:
            level = str(r.get("level") or "mid").lower()
            level_groups[level].append(r)

        level_km: dict[str, Any] = {}
        for level, records in level_groups.items():
            if len(records) < 3:
                continue
            d = [r["tenure_months"] for r in records]
            e = [r["departed"] for r in records]
            level_km[level] = kaplan_meier(d, e)

        # ── Risk scoring ──────────────────────────────────────────────────────
        risk_scores: list[dict[str, Any]] = []
        for emp in self.employees:
            comp_gap = self._compute_comp_gap(emp)
            score = compute_attrition_risk_score(emp, dept_attrition_rates, comp_gap)
            risk_scores.append(score)

        risk_scores.sort(key=lambda x: -x["risk_score"])

        # ── High-risk cohorts ─────────────────────────────────────────────────
        cohort_scores: dict[tuple, list[float]] = defaultdict(list)
        for rs in risk_scores:
            key = (rs["department"], rs["level"])
            cohort_scores[key].append(rs["risk_score"])

        high_risk_cohorts = []
        for (dept, level), scores in cohort_scores.items():
            avg_score = statistics.mean(scores)
            if avg_score >= 5.5:
                high_risk_cohorts.append({
                    "department":    dept,
                    "level":         level,
                    "avg_risk_score": round(avg_score, 1),
                    "headcount":     len(scores),
                    "critical_count": sum(1 for s in scores if s >= 7.5),
                })
        high_risk_cohorts.sort(key=lambda x: -x["avg_risk_score"])

        # ── Summary metrics ───────────────────────────────────────────────────
        overall_survival_12m = overall_km.get("survival_at_12m", 1.0)
        annual_attrition_est = round(1 - overall_survival_12m, 3)
        median_survival      = overall_km.get("median_survival")
        critical_count       = sum(1 for r in risk_scores if r["risk_tier"] == "kritik")
        high_count           = sum(1 for r in risk_scores if r["risk_tier"] == "yüksek")

        summary = {
            "total_analyzed":      len(all_records),
            "current_employees":   len(self.employees),
            "historical_departures": len(self.departures),
            "annual_attrition_pct": round(annual_attrition_est * 100, 1),
            "median_survival_months": median_survival,
            "survival_at_12m_pct":  round(overall_survival_12m * 100, 1),
            "critical_risk_count":  critical_count,
            "high_risk_count":      high_count,
            "highest_risk_dept":    high_risk_cohorts[0]["department"] if high_risk_cohorts else None,
        }

        # Turkish interpretation
        interp = self._build_interpretation(summary, high_risk_cohorts, dept_km)

        return {
            "overall_km":        overall_km,
            "by_department":     dept_km,
            "by_level":          level_km,
            "risk_scores":       risk_scores[:20],   # Top 20 highest risk
            "high_risk_cohorts": high_risk_cohorts[:5],
            "summary":           summary,
            "interpretation":    interp,
        }

    def _compute_tenure_months(self, record: dict[str, Any]) -> float:
        """Compute tenure in months from hire_date and optional departure_date."""
        from datetime import datetime, timezone
        try:
            hire_raw = (
                record.get("start_date") or record.get("hire_date") or
                record.get("joined") or record.get("start")
            )
            if not hire_raw:
                return float(record.get("tenure_years", 1)) * 12

            hire_date = datetime.fromisoformat(str(hire_raw)).replace(tzinfo=timezone.utc)

            depart_raw = record.get("departure_date") or record.get("left_date")
            if depart_raw:
                end_date = datetime.fromisoformat(str(depart_raw)).replace(tzinfo=timezone.utc)
            else:
                end_date = datetime.now(timezone.utc)

            months = (end_date - hire_date).days / 30.44
            return max(0.1, round(months, 1))
        except Exception:
            return float(record.get("tenure_years", 1)) * 12

    def _compute_comp_gap(self, employee: dict[str, Any]) -> float:
        """Estimate compensation gap (% below market). Returns 0 if data not available."""
        try:
            salary = float(employee.get("base_salary") or employee.get("salary") or 0)
            market = float(employee.get("market_rate") or 0)
            if salary > 0 and market > 0:
                gap = (market - salary) / market * 100
                return max(0, round(gap, 1))
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _build_interpretation(
        summary: dict[str, Any],
        high_risk_cohorts: list[dict],
        dept_km: dict[str, Any],
    ) -> str:
        """Build Turkish interpretation of survival analysis results."""
        parts: list[str] = []

        attrition = summary["annual_attrition_pct"]
        median    = summary["median_survival_months"]
        s12m      = summary["survival_at_12m_pct"]
        critical  = summary["critical_risk_count"]

        # Overall attrition assessment
        if attrition > 25:
            parts.append(
                f"Yıllık işten ayrılma oranı %{attrition:.0f} — endüstri normunun üzerinde, acil müdahale gerekiyor."
            )
        elif attrition > 15:
            parts.append(
                f"Yıllık işten ayrılma oranı %{attrition:.0f} — kabul edilebilir sınırda, izlenmeli."
            )
        else:
            parts.append(
                f"Yıllık işten ayrılma oranı %{attrition:.0f} — sağlıklı düzeyde."
            )

        # Median survival
        if median:
            parts.append(
                f"Çalışanların %50'si {median:.0f} ay sonra ayrılıyor "
                f"(%{s12m:.0f}'si ilk yılı geçiyor)."
            )

        # High-risk cohorts
        if high_risk_cohorts:
            top = high_risk_cohorts[0]
            parts.append(
                f"En yüksek risk: '{top['department']}' / '{top['level']}' grubu "
                f"(ortalama risk skoru {top['avg_risk_score']}/10, {top['headcount']} çalışan)."
            )

        if critical > 0:
            parts.append(
                f"Kritik risk kategorisinde {critical} çalışan — ücret veya kariyer görüşmesi planlanmalı."
            )

        return " ".join(parts)
