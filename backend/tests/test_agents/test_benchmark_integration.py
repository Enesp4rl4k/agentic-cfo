"""
Integration tests for benchmark system.

Tests cover:
- TCMB API client
- Benchmark engine
- Gap analysis
- Agent-specific utilities
- Caching layer
- Error handling
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.benchmark import (
    BenchmarkEngine,
    TCMBClient,
    get_benchmark_engine,
    get_benchmark_engine_async,
)
from app.services.benchmark_utils import (
    cfo_benchmark_margins,
    cfo_benchmark_returns,
    cfo_benchmark_leverage,
    cto_benchmark_cloud_efficiency,
    cto_benchmark_tech_debt,
    chro_benchmark_headcount,
    chro_benchmark_compensation,
    chro_benchmark_attrition,
    cmo_benchmark_unit_economics,
    coo_benchmark_efficiency,
    risk_benchmark_kri_thresholds,
)


# ═══════════════════════════════════════════════════════════════════════════
# TCMB Client Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tcmb_client_initialization():
    """Test TCMB client initialization."""
    client = TCMBClient(api_key="test-key")
    assert client.api_key == "test-key"
    await client.close()


@pytest.mark.asyncio
async def test_tcmb_client_no_api_key():
    """Test TCMB client graceful handling when no API key."""
    client = TCMBClient(api_key=None)
    series = await client.get_series("TP.DK.USD.A.YTL")
    assert series == []
    await client.close()


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark Engine Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_benchmark_engine_initialization():
    """Test benchmark engine initialization."""
    engine = BenchmarkEngine(tcmb_client=None, redis_client=None)
    assert engine is not None


def test_get_sector_benchmark_valid_metric():
    """Test getting benchmark for valid metric and sector."""
    engine = get_benchmark_engine()
    
    benchmark = engine.get_sector_benchmark("net_margin", "banking")
    
    assert benchmark["metric"] == "net_margin"
    assert benchmark["sector"] == "banking"
    assert "median" in benchmark
    assert "p25" in benchmark
    assert "p50" in benchmark
    assert "p75" in benchmark
    assert benchmark["p25"] <= benchmark["p50"] <= benchmark["p75"]


def test_get_sector_benchmark_default_sector():
    """Test default sector fallback."""
    engine = get_benchmark_engine()
    
    benchmark = engine.get_sector_benchmark("net_margin", "invalid_sector")
    
    assert benchmark["sector"] == "invalid_sector"
    # Should use default values
    assert benchmark["median"] is not None


def test_get_sector_benchmark_invalid_metric():
    """Test invalid metric returns error."""
    engine = get_benchmark_engine()
    
    result = engine.get_sector_benchmark("invalid_metric", "banking")
    
    assert "error" in result


def test_compare_to_benchmark_top_25():
    """Test comparison when company is in top 25."""
    engine = get_benchmark_engine()
    
    # Net margin: p75 for banking is around 0.12, so 0.13 should be top_25
    comparison = engine.compare_to_benchmark("net_margin", 0.13, "banking")
    
    assert comparison["company_value"] == 0.13
    assert comparison["percentile_position"] == "top_25"
    assert comparison["vs_median_pct"] > 0


def test_compare_to_benchmark_bottom_25():
    """Test comparison when company is in bottom 25."""
    engine = get_benchmark_engine()
    
    # Net margin: p25 for banking is around 0.05, so 0.03 should be bottom_25
    comparison = engine.compare_to_benchmark("net_margin", 0.03, "banking")
    
    assert comparison["company_value"] == 0.03
    assert comparison["percentile_position"] == "bottom_25"
    assert comparison["vs_median_pct"] < 0


def test_compare_to_benchmark_p50_p75():
    """Test comparison when company is between p50-p75."""
    engine = get_benchmark_engine()
    
    # Net margin for banking: p50=0.08, p75=0.12
    # So 0.10 should be p50_p75
    comparison = engine.compare_to_benchmark("net_margin", 0.10, "banking")
    
    assert comparison["percentile_position"] == "p50_p75"


def test_build_full_comparison():
    """Test building full comparison report."""
    engine = get_benchmark_engine()
    
    pnl = {
        "revenue": 1_000_000,
        "gross_margin": 0.40,
        "net_margin": 0.08,
        "ebitda_margin": 0.12,
        "total_opex": 250_000,
    }
    
    comparison = engine.build_full_comparison(pnl, sector="banking")
    
    assert comparison["sector"] == "banking"
    assert "metrics" in comparison
    assert "gross_margin" in comparison["metrics"]
    assert "net_margin" in comparison["metrics"]
    assert "ebitda_margin" in comparison["metrics"]
    assert "overall_score" in comparison
    assert "overall_label" in comparison


def test_calculate_gap_analysis():
    """Test gap analysis calculation."""
    engine = get_benchmark_engine()
    
    gap = engine.calculate_gap_analysis(
        company_value=0.08,
        benchmark_median=0.12,
        metric_name="Net Margin",
        sector="banking",
    )
    
    assert gap["company_value"] == 0.08
    assert gap["benchmark_median"] == 0.12
    assert gap["gap_absolute"] == -0.04
    assert gap["gap_percentage"] == -33.3
    assert gap["direction"] == "behind"
    assert gap["severity"] in ("high", "critical")
    assert "gap_interpretation" in gap


def test_calculate_gap_analysis_ahead():
    """Test gap analysis when ahead of benchmark."""
    engine = get_benchmark_engine()
    
    gap = engine.calculate_gap_analysis(
        company_value=0.15,
        benchmark_median=0.12,
        metric_name="Net Margin",
        sector="banking",
    )
    
    assert gap["direction"] == "ahead"
    assert gap["severity"] == "good"


# ═══════════════════════════════════════════════════════════════════════════
# CFO Agent Utilities Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_cfo_benchmark_margins():
    """Test CFO margin benchmarking."""
    pnl = {
        "gross_margin": 0.40,
        "net_margin": 0.08,
        "ebitda_margin": 0.12,
    }
    
    result = cfo_benchmark_margins(pnl, sector="banking")
    
    assert "gross_margin" in result
    assert "net_margin" in result
    assert "ebitda_margin" in result
    assert "overall_position" in result
    assert result["overall_position"] in [
        "sektörün üstünde",
        "sektör ortalamasında",
        "sektörün altında",
    ]


def test_cfo_benchmark_returns():
    """Test CFO returns benchmarking."""
    financials = {
        "net_income_cents": 800_000_00,
        "total_assets_cents": 10_000_000_00,
        "total_equity_cents": 1_000_000_00,
    }
    
    result = cfo_benchmark_returns(financials, sector="banking")
    
    assert "roa" in result
    assert "roe" in result
    assert "gap_analysis" in result
    assert "roa_gap" in result["gap_analysis"]
    assert "roe_gap" in result["gap_analysis"]


def test_cfo_benchmark_leverage():
    """Test CFO leverage benchmarking."""
    bs = {
        "total_debt_cents": 5_000_000_00,
        "total_equity_cents": 3_000_000_00,
        "current_assets_cents": 4_000_000_00,
        "current_liabilities_cents": 2_000_000_00,
    }
    
    result = cfo_benchmark_leverage(bs, sector="banking")
    
    assert "debt_to_equity" in result
    assert "current_ratio" in result
    assert "leverage_health" in result
    assert "liquidity_health" in result
    assert result["leverage_health"] in ["healthy", "moderate", "high", "critical"]


# ═══════════════════════════════════════════════════════════════════════════
# CTO Agent Utilities Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_cto_benchmark_cloud_efficiency():
    """Test CTO cloud efficiency benchmarking."""
    infra = {
        "infra_cost_cents": 10_000_00,
        "infra_waste_cents": 800_00,
        "headcount": 50,
    }
    
    result = cto_benchmark_cloud_efficiency(infra, sector="technology")
    
    assert "waste_ratio" in result
    assert "waste_percentage" in result
    assert "cost_per_engineer_annual" in result
    assert "efficiency_score" in result
    assert "efficiency_grade" in result
    assert result["efficiency_grade"] in ["A", "B", "C", "D", "F"]


def test_cto_benchmark_tech_debt():
    """Test CTO tech debt benchmarking."""
    tech = {
        "debt_score": 4.5,
        "velocity_trend": "stable",
        "mttr_hours": 2.5,
    }
    
    result = cto_benchmark_tech_debt(tech, sector="technology")
    
    assert "debt_score" in result
    assert "debt_health" in result
    assert "velocity_trend" in result
    assert "mttr_hours" in result
    assert "incident_response_benchmark" in result
    assert "action_items" in result


# ═══════════════════════════════════════════════════════════════════════════
# CHRO Agent Utilities Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_chro_benchmark_headcount():
    """Test CHRO headcount benchmarking."""
    hr = {
        "headcount": 150,
        "headcount_prev_year": 130,
        "revenue_cents": 50_000_000_00,
    }
    
    result = chro_benchmark_headcount(hr, sector="technology")
    
    assert "headcount_growth" in result
    assert "revenue_per_headcount" in result
    assert "productivity_efficiency" in result
    assert "headcount_change" in result
    assert result["headcount_change"] == 20


def test_chro_benchmark_compensation():
    """Test CHRO compensation benchmarking."""
    hr = {
        "total_compensation_cents": 10_000_000_00,
        "headcount": 100,
        "revenue_cents": 50_000_000_00,
    }
    
    result = chro_benchmark_compensation(hr, sector="technology")
    
    assert "compensation_per_employee_annual" in result
    assert "compensation_to_revenue_ratio" in result
    assert "benchmark_gap" in result
    assert "competitiveness" in result


def test_chro_benchmark_attrition():
    """Test CHRO attrition benchmarking."""
    hr = {
        "attrition_rate": 0.12,
        "voluntary_attrition": 0.09,
        "involuntary_attrition": 0.03,
    }
    
    result = chro_benchmark_attrition(hr, sector="technology")
    
    assert "annual_attrition_rate" in result
    assert "voluntary_attrition" in result
    assert "involuntary_attrition" in result
    assert "sector_benchmark_attrition" in result
    assert "health_assessment" in result


# ═══════════════════════════════════════════════════════════════════════════
# CMO Agent Utilities Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_cmo_benchmark_unit_economics():
    """Test CMO unit economics benchmarking."""
    marketing = {
        "cac_dollars": 150,
        "ltv_dollars": 600,
        "payback_months": 8,
        "customer_count": 5000,
        "monthly_recurring_revenue_cents": 2_500_00,
    }
    
    result = cmo_benchmark_unit_economics(marketing, sector="technology")
    
    assert "cac_usd" in result
    assert "ltv_usd" in result
    assert "ltv_to_cac_ratio" in result
    assert "payback_period_months" in result
    assert "unit_economics_health" in result
    assert "recommendation" in result


def test_cmo_benchmark_unit_economics_at_risk():
    """Test CMO unit economics when at risk."""
    marketing = {
        "cac_dollars": 500,
        "ltv_dollars": 600,
        "payback_months": 24,
        "customer_count": 5000,
        "monthly_recurring_revenue_cents": 2_500_00,
    }
    
    result = cmo_benchmark_unit_economics(marketing, sector="technology")
    
    assert result["ltv_to_cac_ratio"] < 2.0
    assert result["unit_economics_health"] == "at_risk"


# ═══════════════════════════════════════════════════════════════════════════
# COO Agent Utilities Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_coo_benchmark_efficiency():
    """Test COO operational efficiency benchmarking."""
    ops = {
        "process_cycle_days": 7,
        "sla_compliance_pct": 97,
        "resource_utilization_pct": 82,
    }
    
    result = coo_benchmark_efficiency(ops, sector="manufacturing")
    
    assert "process_cycle_days" in result
    assert "process_efficiency" in result
    assert "sla_compliance_pct" in result
    assert "sla_performance" in result
    assert "resource_utilization_pct" in result
    assert "utilization_efficiency" in result
    assert "overall_operational_health" in result


# ═══════════════════════════════════════════════════════════════════════════
# Risk Agent Utilities Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_risk_benchmark_kri_thresholds():
    """Test risk KRI benchmarking."""
    risk = {
        "kri_scores": {
            "credit_risk": 0.06,
            "liquidity_risk": 0.12,
            "operational_risk": 0.08,
        },
        "risk_profile": "moderate",
    }
    
    result = risk_benchmark_kri_thresholds(risk, sector="banking")
    
    assert "kri_assessments" in result
    assert "credit_risk" in result["kri_assessments"]
    assert "overall_kri_score" in result
    assert "risk_profile" in result


# ═══════════════════════════════════════════════════════════════════════════
# Sector Coverage Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("sector", [
    "retail", "manufacturing", "technology", "construction",
    "services", "food_beverage", "logistics", "banking",
    "insurance", "leasing", "default"
])
def test_all_sectors_supported(sector):
    """Test all sectors are supported."""
    engine = get_benchmark_engine()
    
    benchmark = engine.get_sector_benchmark("net_margin", sector)
    
    assert benchmark["sector"] == sector
    assert "median" in benchmark


@pytest.mark.parametrize("metric", [
    "gross_margin", "net_margin", "ebitda_margin", "opex_to_revenue",
    "revenue_growth_yoy", "roa", "roe", "debt_to_equity", "current_ratio",
    "headcount_growth_yoy", "revenue_per_headcount", "cac_payback_months",
    "ltv_to_cac_ratio"
])
def test_all_metrics_supported(metric):
    """Test all metrics are supported."""
    engine = get_benchmark_engine()
    
    benchmark = engine.get_sector_benchmark(metric, "default")
    
    assert benchmark["metric"] == metric
    assert "median" in benchmark


# ═══════════════════════════════════════════════════════════════════════════
# Edge Cases & Error Handling
# ═══════════════════════════════════════════════════════════════════════════


def test_gap_analysis_zero_median():
    """Test gap analysis with zero median returns error."""
    engine = get_benchmark_engine()
    
    gap = engine.calculate_gap_analysis(0.5, 0.0, "Test", "default")
    
    assert "error" in gap


def test_cfo_zero_revenue_handling():
    """Test CFO utilities handle zero revenue gracefully."""
    financials = {
        "net_income_cents": 0,
        "total_assets_cents": 0,
        "total_equity_cents": 0,
    }
    
    result = cfo_benchmark_returns(financials, sector="banking")
    
    assert result is not None  # Should not crash


def test_chro_zero_headcount_handling():
    """Test CHRO utilities handle zero headcount gracefully."""
    hr = {
        "headcount": 0,
        "headcount_prev_year": 0,
        "revenue_cents": 0,
    }
    
    result = chro_benchmark_headcount(hr, sector="technology")
    
    assert result is not None  # Should not crash


def test_cto_zero_cost_handling():
    """Test CTO utilities handle zero cost gracefully."""
    infra = {
        "infra_cost_cents": 0,
        "infra_waste_cents": 0,
        "headcount": 50,
    }
    
    result = cto_benchmark_cloud_efficiency(infra, sector="technology")
    
    assert result["waste_ratio"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# Caching Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_cache_key_generation():
    """Test cache key generation."""
    engine = get_benchmark_engine()
    
    key = engine._cache_key("net_margin", "banking")
    
    assert key == "benchmark:net_margin:banking"


@pytest.mark.asyncio
async def test_get_redis_client_not_available():
    """Test graceful handling when Redis not available."""
    engine = BenchmarkEngine(tcmb_client=None, redis_client=None)
    
    # Should work without Redis
    result = await engine._get_cached("benchmark:net_margin:banking")
    
    assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# Module Singleton Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_get_benchmark_engine_singleton():
    """Test benchmark engine is singleton."""
    engine1 = get_benchmark_engine()
    engine2 = get_benchmark_engine()
    
    assert engine1 is engine2


@pytest.mark.asyncio
async def test_get_benchmark_engine_async_singleton():
    """Test async benchmark engine is singleton."""
    engine1 = await get_benchmark_engine_async()
    engine2 = await get_benchmark_engine_async()
    
    assert engine1 is engine2
