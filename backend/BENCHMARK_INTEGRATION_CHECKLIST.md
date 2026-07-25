# Benchmark Integration Checklist — Developer Guide

Use this checklist to integrate benchmarks into your agent code and dashboards.

---

## ✅ Pre-Integration Setup

- [ ] Redis running: `redis-cli ping` → PONG
- [ ] `.env` configured with `REDIS_URL` (optional: `TCMB_API_KEY`)
- [ ] Tests passing: `pytest tests/test_agents/test_benchmark_integration.py -v`
- [ ] Read `BENCHMARK_INTEGRATION_README.md` (quick overview)
- [ ] Read `BENCHMARK_SETUP.md` (detailed reference)

---

## ✅ CFO Agent Integration

### In `backend/app/agents/cfo/...` (your file)

```python
# Step 1: Import utilities
from app.services.benchmark_utils import (
    cfo_benchmark_margins,
    cfo_benchmark_returns,
    cfo_benchmark_leverage,
)

# Step 2: In your agent's run_* function
def get_company_financials() -> dict:
    # Get company P&L data (your existing code)
    company_pnl = {
        "gross_margin": 0.40,
        "net_margin": 0.08,
        "ebitda_margin": 0.12,
        "revenue": 1_000_000,
        "total_opex": 250_000,
    }
    
    # Get company balance sheet (your existing code)
    company_bs = {
        "net_income_cents": 800_000_00,
        "total_assets_cents": 10_000_000_00,
        "total_equity_cents": 1_000_000_00,
        "total_debt_cents": 5_000_000_00,
        "current_assets_cents": 4_000_000_00,
        "current_liabilities_cents": 2_000_000_00,
    }
    
    # Step 3: Call benchmark functions
    margin_benchmarks = cfo_benchmark_margins(company_pnl, sector="banking")
    returns_benchmarks = cfo_benchmark_returns(company_bs, sector="banking")
    leverage_benchmarks = cfo_benchmark_leverage(company_bs, sector="banking")
    
    # Step 4: Add to state
    state["benchmarks"] = {
        "margins": margin_benchmarks,
        "returns": returns_benchmarks,
        "leverage": leverage_benchmarks,
    }
    
    return state
```

### Verification
- [ ] Import statements work (no AttributeError)
- [ ] Benchmark functions return dict with keys: `overall_position`, `gap_analysis`
- [ ] State includes `state["benchmarks"]["margins"]` etc.
- [ ] Run CFO tests (if exist)

---

## ✅ CTO Agent Integration

### In `backend/app/agents/cto/...` (your file)

```python
# Step 1: Import
from app.services.benchmark_utils import (
    cto_benchmark_cloud_efficiency,
    cto_benchmark_tech_debt,
)

# Step 2: Gather infrastructure data
company_infra = {
    "infra_cost_cents": 10_000_00,      # 100K/month
    "infra_waste_cents": 1_500_00,      # 15K waste
    "headcount": 50,
    "debt_score": 4.5,                  # 0-10 scale
    "velocity_trend": "stable",         # or "increasing", "decreasing"
    "mttr_hours": 2.5,
}

# Step 3: Call benchmark functions
cloud_efficiency = cto_benchmark_cloud_efficiency(company_infra, sector="technology")
tech_debt = cto_benchmark_tech_debt(company_infra, sector="technology")

# Step 4: Add to state
state["benchmarks"] = {
    "cloud_efficiency": cloud_efficiency,
    "tech_debt": tech_debt,
}
```

### Expected Output
```python
{
    "cloud_efficiency": {
        "waste_percentage": 15.0,
        "efficiency_grade": "B",
        "efficiency_score": 85.0,
        "recommendation": "Cloud tasarrufu %10-15 optimize..."
    },
    "tech_debt": {
        "debt_score": 4.5,
        "debt_health": "good",
        "velocity_trend": "stable",
        "mttr_hours": 2.5,
        "action_items": [...]
    }
}
```

### Verification
- [ ] Cloud efficiency score returned (0-100)
- [ ] Tech debt health label present (optimal/good/concerning/critical)
- [ ] Action items array populated
- [ ] All metrics have corresponding benchmark data

---

## ✅ CHRO Agent Integration

### In `backend/app/agents/chro/...` (your file)

```python
from app.services.benchmark_utils import (
    chro_benchmark_headcount,
    chro_benchmark_compensation,
    chro_benchmark_attrition,
)

# Gather HR data
company_hr = {
    "headcount": 150,
    "headcount_prev_year": 130,
    "revenue_cents": 50_000_000_00,
    "total_compensation_cents": 10_000_000_00,
    "attrition_rate": 0.12,
    "voluntary_attrition": 0.09,
    "involuntary_attrition": 0.03,
}

# Call utilities
headcount = chro_benchmark_headcount(company_hr, sector="technology")
compensation = chro_benchmark_compensation(company_hr, sector="technology")
attrition = chro_benchmark_attrition(company_hr, sector="technology")

# Add to state
state["benchmarks"] = {
    "headcount": headcount,
    "compensation": compensation,
    "attrition": attrition,
}
```

### Verification
- [ ] Headcount growth gap calculated
- [ ] Productivity efficiency rating present
- [ ] Compensation competitiveness assessment included
- [ ] Attrition health status returned

---

## ✅ CMO Agent Integration

### In `backend/app/agents/cmo/...` (your file)

```python
from app.services.benchmark_utils import cmo_benchmark_unit_economics

# Gather marketing data
company_marketing = {
    "cac_dollars": 150,                         # Customer Acquisition Cost
    "ltv_dollars": 600,                         # Lifetime Value
    "payback_months": 8,
    "customer_count": 5000,
    "monthly_recurring_revenue_cents": 2_500_00,
}

# Call utility
unit_econ = cmo_benchmark_unit_economics(company_marketing, sector="technology")

# Add to state
state["benchmarks"] = {
    "unit_economics": unit_econ,
}
```

### Expected Metrics
- [ ] LTV/CAC ratio (should be > 2.0 for healthy)
- [ ] Payback period in months
- [ ] Unit economics health: excellent/good/adequate/at_risk
- [ ] Recommendation for improvement

---

## ✅ COO Agent Integration

### In `backend/app/agents/coo/...` (your file)

```python
from app.services.benchmark_utils import coo_benchmark_efficiency

# Gather operational data
company_operations = {
    "process_cycle_days": 7,
    "sla_compliance_pct": 97,
    "resource_utilization_pct": 82,
}

# Call utility
operational_efficiency = coo_benchmark_efficiency(company_operations, sector="manufacturing")

# Add to state
state["benchmarks"] = {
    "operational_efficiency": operational_efficiency,
}
```

### Verification
- [ ] Efficiency grades returned for each metric
- [ ] Overall operational health assessment present
- [ ] All three metrics have comparison data

---

## ✅ Risk Agent Integration

### In `backend/app/agents/risk/...` (your file)

```python
from app.services.benchmark_utils import risk_benchmark_kri_thresholds

# Gather risk data
company_risk = {
    "kri_scores": {
        "credit_risk": 0.06,
        "liquidity_risk": 0.12,
        "operational_risk": 0.08,
    },
    "risk_profile": "moderate",
}

# Call utility
kri_benchmarks = risk_benchmark_kri_thresholds(company_risk, sector="banking")

# Add to state
state["benchmarks"] = {
    "kri": kri_benchmarks,
}
```

### Expected Output
```python
{
    "kri": {
        "kri_assessments": {
            "credit_risk": {
                "value": 0.06,
                "threshold": 0.08,
                "status": "green"  # or "yellow", "red"
            },
            ...
        },
        "overall_kri_score": 0.087,
        "risk_profile": "moderate"
    }
}
```

---

## ✅ CEO Board Deck Integration

### In `backend/app/agents/ceo/board_deck_agent.py` (already enhanced)

The board deck agent already includes benchmark overlays via `_add_benchmark_overlay()`.

#### Your checklist:
- [ ] Benchmark imports at top of file (already done)
- [ ] `_add_benchmark_overlay()` function exists
- [ ] Slide 2 includes margin benchmarks
- [ ] Slide 3 includes cloud efficiency benchmark
- [ ] Each metric card has `emoji` field for visual indicator
- [ ] `interpretation` field includes Turkish context

#### Typical Board Deck Output
```json
{
  "slide_number": 2,
  "title": "Finansal Performans & Marj Trajektörü",
  "key_metrics": [
    {
      "label": "Net Marj",
      "value": "8%",
      "benchmark_comparison": {
        "sector_median": "12%",
        "gap_pct": -33.3,
        "emoji": "🔴",
        "interpretation": "Sektörde %33 geride..."
      }
    },
    ...
  ]
}
```

---

## ✅ Frontend Dashboard Integration

### Component Props for Benchmark Cards

```typescript
// Example React component
interface BenchmarkCardProps {
  metric: string;              // "Net Margin"
  companyValue: number;        // 0.08
  benchmarkMedian: number;     // 0.12
  gapPercentage: number;       // -33.3
  severity: "critical" | "high" | "medium" | "good";
  emoji: string;               // "🔴" | "🟠" | "🟡" | "🟢"
  interpretation: string;      // Turkish explanation
  percentilePosition: "bottom_25" | "p25_p50" | "p50_p75" | "top_25";
}

export function BenchmarkCard(props: BenchmarkCardProps) {
  return (
    <div className={`benchmark-card severity-${props.severity}`}>
      <div className="metric-name">{props.metric}</div>
      <div className="values">
        <span>Bizim: {props.companyValue}</span>
        <span>Sektör: {props.benchmarkMedian}</span>
        <span className="emoji">{props.emoji}</span>
      </div>
      <div className="gap-analysis">
        Gap: {props.gapPercentage:+.1f}%
      </div>
      <div className="interpretation">{props.interpretation}</div>
    </div>
  );
}
```

### Verification
- [ ] All benchmark data passed to components
- [ ] Emoji renders correctly
- [ ] Gap percentage displays with +/- sign
- [ ] Turkish interpretation is readable
- [ ] Color coding matches severity

---

## ✅ Data Validation Checklist

Before calling benchmark functions, verify:

- [ ] `gross_margin` is between 0 and 1 (not percentage)
- [ ] `net_margin` is between 0 and 1
- [ ] `revenue_cents` includes cents (multiply by 100)
- [ ] `attrition_rate` is between 0 and 1 (not percentage)
- [ ] `headcount` is integer > 0
- [ ] `sector` is one of: retail, manufacturing, technology, construction, services, food_beverage, logistics, banking, insurance, leasing, default
- [ ] All currency values are in cents (divide by 100 for display)

---

## ✅ Testing Your Integration

### Unit Test Template

```python
def test_cfo_integration():
    """Test CFO agent integration with benchmarks."""
    from app.services.benchmark_utils import cfo_benchmark_margins
    
    # Sample data
    pnl = {
        "gross_margin": 0.40,
        "net_margin": 0.08,
        "ebitda_margin": 0.12,
    }
    
    # Call
    result = cfo_benchmark_margins(pnl, sector="banking")
    
    # Assert
    assert "gross_margin" in result
    assert "net_margin" in result
    assert "overall_position" in result
    assert result["overall_position"] in [
        "sektörün üstünde",
        "sektör ortalamasında",
        "sektörün altında",
    ]
```

### Manual Testing

```bash
# Test from command line
python -c "
from app.services.benchmark_utils import cfo_benchmark_margins
result = cfo_benchmark_margins({
    'gross_margin': 0.40,
    'net_margin': 0.08,
    'ebitda_margin': 0.12,
}, sector='banking')
print(result)
"
```

---

## ✅ Error Handling

### What to Do If...

#### "ModuleNotFoundError: No module named 'app.services.benchmark_utils'"
- [ ] Ensure file exists: `backend/app/services/benchmark_utils.py`
- [ ] Run from correct directory: `backend/`
- [ ] Restart IDE/Python process

#### "Redis connection refused"
- [ ] Start Redis: `redis-server`
- [ ] Check `REDIS_URL` in `.env`
- [ ] System works without Redis (no error, just slower)

#### "Benchmark returns None or empty dict"
- [ ] Check sector name spelling
- [ ] Verify metric exists for that sector
- [ ] Check data types (margins 0-1, not percentages)

#### "Very slow benchmark calls"
- [ ] Check Redis is running: `redis-cli ping`
- [ ] Check network latency to Redis
- [ ] Check if cache is warming up (first call slower)

---

## ✅ Performance Optimization

- [ ] Use `await get_benchmark_engine_async()` in async contexts
- [ ] Cache results if calling same benchmark multiple times
- [ ] Pre-warm cache on startup: see `BENCHMARK_SETUP.md`
- [ ] Monitor Redis memory: `redis-cli info memory`
- [ ] Clear old cache if memory grows: `redis-cli FLUSHDB`

---

## ✅ Documentation & Support

- [ ] Linked to `BENCHMARK_INTEGRATION_README.md` from your code
- [ ] Linked to `BENCHMARK_SETUP.md` from your docs
- [ ] Added benchmark metrics to agent docstring
- [ ] Included sample output in your agent's notes
- [ ] Updated dashboard documentation with benchmark cards

---

## ✅ Final Verification

Run this complete test:

```python
# test_my_benchmarks.py
from app.services.benchmark_utils import (
    cfo_benchmark_margins,
    cto_benchmark_cloud_efficiency,
    chro_benchmark_headcount,
    cmo_benchmark_unit_economics,
    coo_benchmark_efficiency,
    risk_benchmark_kri_thresholds,
)

# Test each agent
print("CFO...", cfo_benchmark_margins({
    "gross_margin": 0.40, "net_margin": 0.08, "ebitda_margin": 0.12
}, "banking"))

print("CTO...", cto_benchmark_cloud_efficiency({
    "infra_cost_cents": 10_000_00, "infra_waste_cents": 1_500_00, "headcount": 50
}, "technology"))

print("CHRO...", chro_benchmark_headcount({
    "headcount": 150, "headcount_prev_year": 130, "revenue_cents": 50_000_000_00
}, "technology"))

print("CMO...", cmo_benchmark_unit_economics({
    "cac_dollars": 150, "ltv_dollars": 600, "payback_months": 8
}, "technology"))

print("COO...", coo_benchmark_efficiency({
    "process_cycle_days": 7, "sla_compliance_pct": 97, "resource_utilization_pct": 82
}, "manufacturing"))

print("Risk...", risk_benchmark_kri_thresholds({
    "kri_scores": {"credit_risk": 0.06, "operational_risk": 0.08}
}, "banking"))

print("✅ All benchmarks working!")
```

---

## ✅ Sign-Off

Once all items are checked:

- [ ] All agent integrations complete
- [ ] All tests passing
- [ ] Benchmarks rendering in UI
- [ ] Documentation links in place
- [ ] Performance acceptable
- [ ] Error handling verified
- [ ] Ready for code review

---

**Questions?** See `BENCHMARK_INTEGRATION_README.md` or `BENCHMARK_SETUP.md`
