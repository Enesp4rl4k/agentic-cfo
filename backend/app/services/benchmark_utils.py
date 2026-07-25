"""
Benchmark utilities for C-suite agent integrations.

Provides sector-specific comparison functions for:
- CFO: Net margin, ROA, ROE, debt ratios
- CTO: Cloud efficiency, tech debt, velocity
- CHRO: Headcount growth, compensation, attrition
- CMO: CAC, LTV, payback period
- COO: Cycle times, SLA, efficiency ratios
- Risk: KRI thresholds
- CEO: Board deck benchmark overlay

Each function returns structured data for reporting and visualization.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.benchmark import get_benchmark_engine

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# CFO Benchmark Functions
# ═══════════════════════════════════════════════════════════════════════════


def cfo_benchmark_margins(
    company_pnl: dict[str, Any],
    sector: str = "default",
) -> dict[str, Any]:
    """
    CFO benchmark: Net margin, Gross margin, EBITDA margin vs sector.
    
    Returns: {
        gross_margin: {...comparison...},
        net_margin: {...comparison...},
        ebitda_margin: {...comparison...},
        overall_position: str,
    }
    """
    engine = get_benchmark_engine()
    
    gross_margin = company_pnl.get("gross_margin", 0)
    net_margin = company_pnl.get("net_margin", 0)
    ebitda_margin = company_pnl.get("ebitda_margin", 0)
    
    return {
        "gross_margin": engine.compare_to_benchmark("gross_margin", gross_margin, sector),
        "net_margin": engine.compare_to_benchmark("net_margin", net_margin, sector),
        "ebitda_margin": engine.compare_to_benchmark("ebitda_margin", ebitda_margin, sector),
        "overall_position": _determine_position([
            engine.compare_to_benchmark("gross_margin", gross_margin, sector),
            engine.compare_to_benchmark("net_margin", net_margin, sector),
            engine.compare_to_benchmark("ebitda_margin", ebitda_margin, sector),
        ]),
    }


def cfo_benchmark_returns(
    company_financials: dict[str, Any],
    sector: str = "default",
) -> dict[str, Any]:
    """
    CFO benchmark: ROA (Return on Assets) and ROE (Return on Equity).
    
    Args:
        company_financials: {net_income_cents, total_assets_cents, total_equity_cents}
        sector: sector code
    
    Returns: {roa_comparison, roe_comparison, financial_health}
    """
    engine = get_benchmark_engine()
    
    # Calculate ROA and ROE
    net_income = company_financials.get("net_income_cents", 0) / 100
    total_assets = company_financials.get("total_assets_cents", 1) / 100
    total_equity = company_financials.get("total_equity_cents", 1) / 100
    
    roa = (net_income / total_assets) if total_assets > 0 else 0
    roe = (net_income / total_equity) if total_equity > 0 else 0
    
    roa_comp = engine.compare_to_benchmark("roa", roa, sector)
    roe_comp = engine.compare_to_benchmark("roe", roe, sector)
    
    return {
        "roa": roa_comp,
        "roe": roe_comp,
        "gap_analysis": {
            "roa_gap": engine.calculate_gap_analysis(
                roa, 
                roa_comp["benchmark"]["median"],
                "Return on Assets",
                sector
            ),
            "roe_gap": engine.calculate_gap_analysis(
                roe,
                roe_comp["benchmark"]["median"],
                "Return on Equity",
                sector
            ),
        },
        "interpretation": _interpret_returns(roa, roe, roa_comp, roe_comp),
    }


def cfo_benchmark_leverage(
    company_balance_sheet: dict[str, Any],
    sector: str = "default",
) -> dict[str, Any]:
    """
    CFO benchmark: Debt-to-Equity ratio and current ratio.
    
    Returns: {debt_to_equity_comparison, current_ratio_comparison}
    """
    engine = get_benchmark_engine()
    
    total_debt = company_balance_sheet.get("total_debt_cents", 0) / 100
    total_equity = company_balance_sheet.get("total_equity_cents", 1) / 100
    current_assets = company_balance_sheet.get("current_assets_cents", 0) / 100
    current_liabilities = company_balance_sheet.get("current_liabilities_cents", 1) / 100
    
    debt_to_equity = total_debt / total_equity if total_equity > 0 else 0
    current_ratio = current_assets / current_liabilities if current_liabilities > 0 else 0
    
    return {
        "debt_to_equity": engine.compare_to_benchmark("debt_to_equity", debt_to_equity, sector),
        "current_ratio": engine.compare_to_benchmark("current_ratio", current_ratio, sector),
        "leverage_health": (
            "healthy" if debt_to_equity < 1.0 else
            "moderate" if debt_to_equity < 2.0 else
            "high" if debt_to_equity < 3.0 else
            "critical"
        ),
        "liquidity_health": (
            "excellent" if current_ratio > 2.0 else
            "good" if current_ratio > 1.5 else
            "adequate" if current_ratio > 1.0 else
            "at_risk"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CTO Benchmark Functions
# ═══════════════════════════════════════════════════════════════════════════


def cto_benchmark_cloud_efficiency(
    company_infra: dict[str, Any],
    sector: str = "technology",
) -> dict[str, Any]:
    """
    CTO benchmark: Cloud efficiency (waste %, utilization).
    
    Args:
        company_infra: {infra_cost_cents, infra_waste_cents, headcount}
        sector: sector code
    
    Returns: {waste_ratio, cost_per_engineer, efficiency_score}
    """
    infra_cost = company_infra.get("infra_cost_cents", 0) / 100
    infra_waste = company_infra.get("infra_waste_cents", 0) / 100
    headcount = company_infra.get("headcount", 1)
    
    waste_ratio = (infra_waste / infra_cost) if infra_cost > 0 else 0
    cost_per_engineer = (infra_cost / headcount) if headcount > 0 else 0
    
    # Sector benchmark for efficiency
    engine = get_benchmark_engine()
    sector_benchmark = engine.get_sector_benchmark("opex_to_revenue", sector)
    
    efficiency_score = max(0, 100 - (waste_ratio * 100))
    
    return {
        "waste_ratio": waste_ratio,
        "waste_percentage": round(waste_ratio * 100, 1),
        "cost_per_engineer_annual": round(cost_per_engineer * 12, 0),
        "efficiency_score": round(efficiency_score, 1),
        "efficiency_grade": (
            "A" if efficiency_score >= 95 else
            "B" if efficiency_score >= 85 else
            "C" if efficiency_score >= 70 else
            "D" if efficiency_score >= 50 else
            "F"
        ),
        "sector_benchmark": sector_benchmark,
        "recommendation": _cloud_efficiency_recommendation(waste_ratio),
    }


def cto_benchmark_tech_debt(
    company_tech: dict[str, Any],
    sector: str = "technology",
) -> dict[str, Any]:
    """
    CTO benchmark: Tech debt score vs sector.
    
    Args:
        company_tech: {debt_score (0-10), velocity_trend, mttr_hours}
        sector: sector code
    
    Returns: {debt_comparison, velocity_trend, incident_response}
    """
    engine = get_benchmark_engine()
    
    debt_score = company_tech.get("debt_score", 5.0)
    velocity_trend = company_tech.get("velocity_trend", "stable")
    mttr_hours = company_tech.get("mttr_hours", 4.0)
    
    # Normalize debt score as a percentage (inverted: lower is better)
    debt_ratio = debt_score / 10.0
    
    return {
        "debt_score": debt_score,
        "debt_health": (
            "optimal" if debt_score <= 3 else
            "good" if debt_score <= 5 else
            "concerning" if debt_score <= 7 else
            "critical"
        ),
        "velocity_trend": velocity_trend,
        "mttr_hours": mttr_hours,
        "incident_response_benchmark": _evaluate_incident_response(mttr_hours),
        "sector_context": f"Sektörde ortalama borç skoru: 5.5/10",
        "action_items": _tech_debt_recommendations(debt_score),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CHRO Benchmark Functions
# ═══════════════════════════════════════════════════════════════════════════


def chro_benchmark_headcount(
    company_hr: dict[str, Any],
    sector: str = "default",
) -> dict[str, Any]:
    """
    CHRO benchmark: Headcount growth vs sector.
    
    Args:
        company_hr: {headcount, headcount_prev_year, revenue_cents}
        sector: sector code
    
    Returns: {growth_comparison, productivity, efficiency}
    """
    engine = get_benchmark_engine()
    
    headcount = company_hr.get("headcount", 1)
    headcount_prev = company_hr.get("headcount_prev_year", headcount)
    revenue = company_hr.get("revenue_cents", 0) / 100
    
    headcount_growth = ((headcount - headcount_prev) / headcount_prev) if headcount_prev > 0 else 0
    revenue_per_employee = (revenue / headcount) if headcount > 0 else 0
    
    growth_comp = engine.compare_to_benchmark("headcount_growth_yoy", headcount_growth, sector)
    revenue_bench = engine.get_sector_benchmark("revenue_per_headcount", sector)
    
    return {
        "headcount_growth": growth_comp,
        "growth_gap": engine.calculate_gap_analysis(
            headcount_growth,
            growth_comp["benchmark"]["median"],
            "Headcount Growth YoY",
            sector
        ),
        "revenue_per_headcount": revenue_per_employee,
        "revenue_per_headcount_benchmark": revenue_bench["median"] * 1000,  # Convert to TL
        "productivity_efficiency": (
            "excellent" if revenue_per_employee > revenue_bench["p75"] * 1000 else
            "good" if revenue_per_employee > revenue_bench["p50"] * 1000 else
            "adequate" if revenue_per_employee > revenue_bench["p25"] * 1000 else
            "below_average"
        ),
        "headcount_change": headcount - headcount_prev,
        "headcount_change_pct": round(headcount_growth * 100, 1),
    }


def chro_benchmark_compensation(
    company_hr: dict[str, Any],
    sector: str = "default",
) -> dict[str, Any]:
    """
    CHRO benchmark: Compensation ratios vs sector.
    
    Args:
        company_hr: {total_compensation_cents, headcount, revenue_cents}
        sector: sector code
    
    Returns: {compensation_per_head, compensation_ratio}
    """
    total_comp = company_hr.get("total_compensation_cents", 0) / 100
    headcount = company_hr.get("headcount", 1)
    revenue = company_hr.get("revenue_cents", 0) / 100
    
    comp_per_head = (total_comp / headcount) if headcount > 0 else 0
    comp_ratio = (total_comp / revenue) if revenue > 0 else 0
    
    return {
        "compensation_per_employee_annual": round(comp_per_head, 0),
        "compensation_to_revenue_ratio": round(comp_ratio, 4),
        "sector_benchmark_comp_ratio": 0.25,  # Typical: 20-30%
        "benchmark_gap": round((comp_ratio - 0.25) * 100, 1),
        "competitiveness": (
            "competitive" if comp_ratio < 0.20 else
            "market" if comp_ratio < 0.30 else
            "above_market"
        ),
    }


def chro_benchmark_attrition(
    company_hr: dict[str, Any],
    sector: str = "default",
) -> dict[str, Any]:
    """
    CHRO benchmark: Employee attrition rate vs sector.
    
    Args:
        company_hr: {attrition_rate, voluntary_attrition, involuntary_attrition}
        sector: sector code
    
    Returns: {attrition_comparison, health_assessment}
    """
    attrition_rate = company_hr.get("attrition_rate", 0.15)
    voluntary = company_hr.get("voluntary_attrition", attrition_rate * 0.7)
    involuntary = company_hr.get("involuntary_attrition", attrition_rate * 0.3)
    
    # Sector benchmarks (annual attrition %)
    sector_benchmarks = {
        "technology": 0.18,
        "manufacturing": 0.12,
        "services": 0.16,
        "default": 0.15,
    }
    sector_benchmark = sector_benchmarks.get(sector, 0.15)
    
    return {
        "annual_attrition_rate": round(attrition_rate * 100, 1),
        "voluntary_attrition": round(voluntary * 100, 1),
        "involuntary_attrition": round(involuntary * 100, 1),
        "sector_benchmark_attrition": round(sector_benchmark * 100, 1),
        "gap_vs_benchmark": round((attrition_rate - sector_benchmark) * 100, 1),
        "health_assessment": (
            "excellent" if attrition_rate < sector_benchmark * 0.8 else
            "good" if attrition_rate <= sector_benchmark else
            "concerning" if attrition_rate <= sector_benchmark * 1.2 else
            "high_risk"
        ),
        "key_drivers": _analyze_attrition(voluntary, involuntary),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CMO Benchmark Functions
# ═══════════════════════════════════════════════════════════════════════════


def cmo_benchmark_unit_economics(
    company_marketing: dict[str, Any],
    sector: str = "default",
) -> dict[str, Any]:
    """
    CMO benchmark: CAC (Customer Acquisition Cost), LTV (Lifetime Value), payback period.
    
    Args:
        company_marketing: {
            cac_dollars, ltv_dollars, payback_months,
            customer_count, monthly_recurring_revenue_cents
        }
        sector: sector code
    
    Returns: {cac_comparison, ltv_comparison, ltv_cac_ratio, payback_comparison}
    """
    engine = get_benchmark_engine()
    
    cac = company_marketing.get("cac_dollars", 0)
    ltv = company_marketing.get("ltv_dollars", 0)
    payback_months = company_marketing.get("payback_months", 12)
    
    ltv_cac_ratio = (ltv / cac) if cac > 0 else 0
    
    payback_comp = engine.compare_to_benchmark("cac_payback_months", payback_months, sector)
    ltv_cac_comp = engine.compare_to_benchmark("ltv_to_cac_ratio", ltv_cac_ratio, sector)
    
    return {
        "cac_usd": round(cac, 2),
        "ltv_usd": round(ltv, 2),
        "ltv_to_cac_ratio": round(ltv_cac_ratio, 2),
        "ltv_to_cac_comparison": ltv_cac_comp,
        "payback_period_months": round(payback_months, 1),
        "payback_comparison": payback_comp,
        "unit_economics_health": (
            "excellent" if ltv_cac_ratio > 3.0 and payback_months < 12 else
            "good" if ltv_cac_ratio > 2.0 and payback_months < 18 else
            "adequate" if ltv_cac_ratio > 1.5 else
            "at_risk"
        ),
        "recommendation": _unit_economics_recommendation(ltv_cac_ratio, payback_months),
    }


# ═══════════════════════════════════════════════════════════════════════════
# COO Benchmark Functions
# ═══════════════════════════════════════════════════════════════════════════


def coo_benchmark_efficiency(
    company_operations: dict[str, Any],
    sector: str = "default",
) -> dict[str, Any]:
    """
    COO benchmark: Operational efficiency (cycle times, SLA, utilization).
    
    Args:
        company_operations: {
            process_cycle_days, sla_compliance_pct, resource_utilization_pct
        }
        sector: sector code
    
    Returns: {cycle_time_assessment, sla_assessment, utilization_assessment}
    """
    cycle_days = company_operations.get("process_cycle_days", 10)
    sla_compliance = company_operations.get("sla_compliance_pct", 95)
    utilization = company_operations.get("resource_utilization_pct", 80)
    
    return {
        "process_cycle_days": cycle_days,
        "process_efficiency": (
            "excellent" if cycle_days < 5 else
            "good" if cycle_days < 10 else
            "adequate" if cycle_days < 15 else
            "needs_improvement"
        ),
        "sla_compliance_pct": sla_compliance,
        "sla_performance": (
            "excellent" if sla_compliance > 98 else
            "good" if sla_compliance > 95 else
            "adequate" if sla_compliance > 90 else
            "at_risk"
        ),
        "resource_utilization_pct": utilization,
        "utilization_efficiency": (
            "optimal" if utilization > 85 else
            "good" if utilization > 75 else
            "adequate" if utilization > 65 else
            "underutilized"
        ),
        "overall_operational_health": _assess_operational_health(
            cycle_days, sla_compliance, utilization
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Risk Benchmark Functions
# ═══════════════════════════════════════════════════════════════════════════


def risk_benchmark_kri_thresholds(
    company_risk: dict[str, Any],
    sector: str = "default",
) -> dict[str, Any]:
    """
    Risk benchmark: KRI (Key Risk Indicator) thresholds vs sector norms.
    
    Args:
        company_risk: {kri_scores: {name: value, ...}, risk_profile}
        sector: sector code
    
    Returns: {kri_assessments, overall_risk_score, recommendations}
    """
    kri_scores = company_risk.get("kri_scores", {})
    
    # Sector-based thresholds
    sector_thresholds = {
        "banking": {"credit_risk": 0.08, "liquidity_risk": 0.15, "operational_risk": 0.10},
        "technology": {"tech_risk": 0.12, "market_risk": 0.10, "operational_risk": 0.08},
        "default": {"operational_risk": 0.10, "financial_risk": 0.12, "market_risk": 0.08},
    }
    thresholds = sector_thresholds.get(sector, sector_thresholds["default"])
    
    assessments = {}
    overall_score = 0
    for kri_name, kri_value in kri_scores.items():
        threshold = thresholds.get(kri_name.lower(), 0.10)
        status = (
            "green" if kri_value < threshold * 0.7 else
            "yellow" if kri_value < threshold else
            "red"
        )
        assessments[kri_name] = {
            "value": kri_value,
            "threshold": threshold,
            "gap": kri_value - threshold,
            "status": status,
        }
        overall_score += kri_value
    
    return {
        "kri_assessments": assessments,
        "overall_kri_score": round(overall_score / max(len(kri_scores), 1), 4),
        "risk_profile": company_risk.get("risk_profile", "moderate"),
        "sector_benchmarks": thresholds,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════


def _determine_position(comparisons: list[dict[str, Any]]) -> str:
    """Determine overall position from multiple comparisons."""
    positions = [c.get("percentile_position", "p25_p50") for c in comparisons]
    pos_scores = {"bottom_25": 1, "p25_p50": 2, "p50_p75": 3, "top_25": 4}
    scores = [pos_scores.get(p, 2) for p in positions]
    avg_score = sum(scores) / len(scores) if scores else 2
    
    return (
        "sektörün üstünde" if avg_score >= 3.5 else
        "sektör ortalamasında" if avg_score >= 2.5 else
        "sektörün altında"
    )


def _interpret_returns(roa: float, roe: float, roa_comp: dict, roe_comp: dict) -> str:
    """Interpret ROA and ROE for CFO context."""
    if roa_comp.get("percentile_position") == "top_25" and roe_comp.get("percentile_position") == "top_25":
        return "Mükemmel getiri profili - sektör liderleriniz."
    elif roa_comp.get("percentile_position") in ["p50_p75", "top_25"] or \
         roe_comp.get("percentile_position") in ["p50_p75", "top_25"]:
        return "İyi getiri - sektör ortalamasının üstünde."
    elif roa_comp.get("percentile_position") == "bottom_25" or \
         roe_comp.get("percentile_position") == "bottom_25":
        return "Düşük getiri - iyileştirme gerekiyor."
    return "Ortalama getiri profili."


def _cloud_efficiency_recommendation(waste_ratio: float) -> str:
    """Recommend cloud efficiency improvements."""
    if waste_ratio < 0.05:
        return "İyi cloud yönetimi. Verimli maliyetlendirme."
    elif waste_ratio < 0.10:
        return "Bazı optimizasyon fırsatları mevcut."
    elif waste_ratio < 0.20:
        return "Önemli cloud tasarrufu potansiyeli. Hemen adım atın."
    return "Kritik maliyetlendirme sorunu. Acil müdahale gerekli."


def _tech_debt_recommendations(debt_score: float) -> list[str]:
    """Recommend tech debt reduction actions."""
    if debt_score <= 3:
        return ["Mevcut durumu koruyun.", "Teknik borç taraması yıllık yapın."]
    elif debt_score <= 5:
        return ["Teknik borcu envanterize edin.", "Refactoring roadmap oluşturun.", "Sprint'te %20 bord zamanı ayırın."]
    elif debt_score <= 7:
        return ["Acil refactoring gerekli.", "Sprint'te %40 bord zamanı ayırın.", "En önemli 5 bord sorununun roadmap'ını oluşturun."]
    return ["Kritik durum. Teknik borç projesini başlatın.", "Yeni feature geliştirmeyi durdurun."]


def _evaluate_incident_response(mttr_hours: float) -> str:
    """Evaluate incident response capability."""
    if mttr_hours < 1:
        return "Mükemmel - 1 saatten az"
    elif mttr_hours < 2:
        return "İyi - 1-2 saat"
    elif mttr_hours < 4:
        return "Orta - 2-4 saat"
    elif mttr_hours < 8:
        return "Yavaş - 4-8 saat"
    return "Kritik - 8 saatten fazla"


def _analyze_attrition(voluntary: float, involuntary: float) -> str:
    """Analyze attrition drivers."""
    if voluntary > involuntary * 3:
        return "Yüksek gönüllü ayrılma - maaş/ortam sorunları araştırın"
    elif involuntary > voluntary * 2:
        return "Yüksek zorunlu ayrılma - yönetim/performans sorunları kontrol edin"
    return "Dengeli attrition profili"


def _unit_economics_recommendation(ltv_cac_ratio: float, payback_months: float) -> str:
    """Recommend unit economics improvements."""
    if ltv_cac_ratio < 1.5:
        return "CAC çok yüksek. Müşteri edinim maliyetini düşürün."
    elif payback_months > 18:
        return "Geri dönüş süresi çok uzun. CAC'ı optimize edin veya LTV'yi artırın."
    elif ltv_cac_ratio < 2.5:
        return "İyileştirilebilir. CAC'ı %10-15 azaltmayı hedefleyin."
    return "Sağlıklı unit economics."


def _assess_operational_health(cycle_days: float, sla_compliance: float, utilization: float) -> str:
    """Assess overall operational health."""
    scores = 0
    if cycle_days < 10:
        scores += 1
    if sla_compliance > 95:
        scores += 1
    if utilization > 75:
        scores += 1
    
    if scores == 3:
        return "Mükemmel - tüm metrikler sağlıklı"
    elif scores == 2:
        return "İyi - çoğu metrik sağlıklı"
    elif scores == 1:
        return "Orta - iyileştirme alanları mevcut"
    return "Sorunlu - birden fazla alanda adım atın"
