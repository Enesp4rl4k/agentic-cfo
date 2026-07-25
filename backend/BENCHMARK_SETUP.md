"""
Benchmark Integration Setup Guide

This document explains how to set up and use the TCMB + BDDK benchmark
integration for Turkish sector comparison across all C-suite agents.

Author: AI CFO System
Date: 2026-07
"""

# ═══════════════════════════════════════════════════════════════════════════
# 1. ENVIRONMENT SETUP
# ═══════════════════════════════════════════════════════════════════════════

## .env Configuration

Add these variables to your `.env` file:

```bash
# TCMB EVDS API — Optional (benchmarks work without it, using static data)
# Get free API key at: https://evds2.tcmb.gov.tr/index.php?lang=tr
TCMB_API_KEY=your_tcmb_api_key_here

# Redis — For benchmark caching (highly recommended for performance)
REDIS_URL=redis://localhost:6379/0
```

## Dependencies

All required dependencies are in `requirements.txt`:
- `redis==5.0.7` — async Redis client
- `httpx==0.27.0` — HTTP client for TCMB EVDS API
- `pydantic==2.8.2` — data validation

No additional packages needed.

## Redis Setup (Development)

```bash
# Install Redis locally
# macOS
brew install redis

# Ubuntu/Debian
sudo apt-get install redis-server

# Windows (Docker recommended)
docker run -d -p 6379:6379 redis:latest

# Start Redis
redis-server

# Test connection
redis-cli ping  # Should output: PONG
```

## Production Redis

Use a managed Redis service:
- AWS ElastiCache
- Azure Cache for Redis
- Google Cloud Memorystore
- Upstash (serverless)

Update `REDIS_URL` in `.env` with your service connection string.


# ═══════════════════════════════════════════════════════════════════════════
# 2. TCMB API INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

## Getting a TCMB API Key

1. Visit: https://evds2.tcmb.gov.tr/index.php?lang=tr
2. Register for a free account
3. Generate an API key
4. Add to `.env` as `TCMB_API_KEY`

## What Data is Fetched

The system automatically fetches:
- **Quarterly sector data**: Net margin, ROA, ROE by sector
- **Banking sector metrics**: BDDK official statistics
- **Macro indicators**: Inflation, growth, interest rates
- **Exchange rates**: USD/TL, EUR/TL trends

## Fallback Behavior

If TCMB API is unavailable:
- ✅ Benchmark comparisons still work (using static BDDK 2024 data)
- ✅ Redis caching prevents repeated API calls
- ✅ Graceful degradation — no user-facing errors


# ═══════════════════════════════════════════════════════════════════════════
# 3. BENCHMARK DATA STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════

## Supported Sectors

- `retail` — Perakende ticaret
- `manufacturing` — Üretim
- `technology` — Teknoloji/Yazılım
- `construction` — İnşaat
- `services` — Hizmetler
- `food_beverage` — Yiyecek-İçecek
- `logistics` — Lojistik
- `banking` — BDDK: Bankacılık
- `insurance` — BDDK: Sigorta
- `leasing` — BDDK: Finansal Kiralama
- `default` — Genel ortalama

## Supported Metrics

### Financial (CFO)
- `net_margin` — Net kar marjı (%\)
- `gross_margin` — Brüt kar marjı (%)
- `ebitda_margin` — FAVÖK marjı (%)
- `roa` — Return on Assets
- `roe` — Return on Equity
- `debt_to_equity` — Borç/özsermaye oranı
- `current_ratio` — Likidite oranı

### Operational (COO)
- `opex_to_revenue` — Gider/ciro oranı
- `revenue_growth_yoy` — Yıllık büyüme (%)

### Human Capital (CHRO)
- `headcount_growth_yoy` — Personel büyümesi (%)
- `revenue_per_headcount` — Kişi başına gelir (K TL)

### Marketing (CMO)
- `cac_payback_months` — Müşteri edinim geri dönüş (ay)
- `ltv_to_cac_ratio` — Lifetime Value / CAC oranı


# ═══════════════════════════════════════════════════════════════════════════
# 4. API USAGE — BACKEND
# ═══════════════════════════════════════════════════════════════════════════

## Basic Usage

```python
from app.services.benchmark import get_benchmark_engine

# Get benchmark engine (sync version, no caching)
engine = get_benchmark_engine()

# Get sector benchmark
benchmark = engine.get_sector_benchmark(
    metric="net_margin",
    sector="technology"
)

print(f"Net margin p50: {benchmark['p50']}")
print(f"Percentile bands: p25={benchmark['p25']}, p75={benchmark['p75']}")
```

## Comparison with Caching (Recommended)

```python
from app.services.benchmark import get_benchmark_engine_async

async def analyze_performance():
    # Get async engine with Redis caching
    engine = await get_benchmark_engine_async()
    
    # Compare company metric to benchmark (cached)
    comparison = await engine.get_sector_benchmark_cached(
        metric="net_margin",
        sector="banking"
    )
    
    return comparison
```

## Full Comparison Report

```python
pnl_data = {
    "revenue": 1_000_000,
    "gross_margin": 0.40,
    "net_margin": 0.08,
    "ebitda_margin": 0.12,
    "total_opex": 150_000,
}

comparison = engine.build_full_comparison(pnl_data, sector="banking")
print(comparison)
# Output: {
#   "sector": "banking",
#   "metrics": {
#     "gross_margin": {...comparison...},
#     "net_margin": {...comparison...},
#     "ebitda_margin": {...comparison...},
#     "opex_to_revenue": {...comparison...},
#   },
#   "overall_score": 3.2,
#   "overall_label": "Sektör ortalamasında"
# }
```

## Gap Analysis

```python
gap = engine.calculate_gap_analysis(
    company_value=0.08,
    benchmark_median=0.12,
    metric_name="Net Margin",
    sector="banking"
)

print(gap["gap_interpretation"])
# Output: "Bizim 0.08, sektör 0.12 → -33.3% gap"
print(gap["severity"])  # "high"
print(gap["emoji"])     # "🟠"
```


# ═══════════════════════════════════════════════════════════════════════════
# 5. AGENT INTEGRATION EXAMPLES
# ═══════════════════════════════════════════════════════════════════════════

## CFO Agent

```python
from app.services.benchmark_utils import cfo_benchmark_margins, cfo_benchmark_returns

# In your CFO agent
company_pnl = {
    "gross_margin": 0.40,
    "net_margin": 0.08,
    "ebitda_margin": 0.12,
}

# Get margin benchmarks
margin_benchmarks = cfo_benchmark_margins(company_pnl, sector="banking")

# Get returns benchmarks
company_bs = {
    "net_income_cents": 800_000_00,  # 800K in cents
    "total_assets_cents": 10_000_000_00,
    "total_equity_cents": 1_000_000_00,
}
returns = cfo_benchmark_returns(company_bs, sector="banking")

# In your state update:
state["benchmarks"]["margins"] = margin_benchmarks
state["benchmarks"]["returns"] = returns
```

## CTO Agent

```python
from app.services.benchmark_utils import cto_benchmark_cloud_efficiency

company_infra = {
    "infra_cost_cents": 10_000_00,  # 100K/month
    "infra_waste_cents": 1_500_00,  # 15K waste
    "headcount": 50,
}

efficiency = cto_benchmark_cloud_efficiency(company_infra, sector="technology")

# In your state:
state["benchmarks"]["cloud_efficiency"] = efficiency
```

## CHRO Agent

```python
from app.services.benchmark_utils import chro_benchmark_headcount, chro_benchmark_attrition

company_hr = {
    "headcount": 150,
    "headcount_prev_year": 130,
    "revenue_cents": 50_000_000_00,
    "attrition_rate": 0.12,
    "voluntary_attrition": 0.09,
    "involuntary_attrition": 0.03,
}

headcount = chro_benchmark_headcount(company_hr, sector="technology")
attrition = chro_benchmark_attrition(company_hr, sector="technology")

state["benchmarks"]["headcount"] = headcount
state["benchmarks"]["attrition"] = attrition
```

## CMO Agent

```python
from app.services.benchmark_utils import cmo_benchmark_unit_economics

company_marketing = {
    "cac_dollars": 150,
    "ltv_dollars": 600,
    "payback_months": 8,
    "customer_count": 5000,
    "monthly_recurring_revenue_cents": 2_500_00,
}

unit_econ = cmo_benchmark_unit_economics(company_marketing, sector="technology")
state["benchmarks"]["unit_economics"] = unit_econ
```

## COO Agent

```python
from app.services.benchmark_utils import coo_benchmark_efficiency

company_ops = {
    "process_cycle_days": 7,
    "sla_compliance_pct": 97,
    "resource_utilization_pct": 82,
}

efficiency = coo_benchmark_efficiency(company_ops, sector="manufacturing")
state["benchmarks"]["operational_efficiency"] = efficiency
```

## Risk Agent

```python
from app.services.benchmark_utils import risk_benchmark_kri_thresholds

company_risk = {
    "kri_scores": {
        "credit_risk": 0.06,
        "liquidity_risk": 0.12,
        "operational_risk": 0.08,
    },
    "risk_profile": "moderate",
}

kri_benchmarks = risk_benchmark_kri_thresholds(company_risk, sector="banking")
state["benchmarks"]["kri"] = kri_benchmarks
```


# ═══════════════════════════════════════════════════════════════════════════
# 6. CACHING STRATEGY
# ═══════════════════════════════════════════════════════════════════════════

## How Caching Works

- **Cache Key Format**: `benchmark:{metric}:{sector}`
- **TTL**: 24 hours (86400 seconds)
- **Fallback**: If Redis unavailable, returns live data (no error)

## Cache Examples

```
benchmark:net_margin:banking        → cached for 24 hours
benchmark:headcount_growth_yoy:technology → cached for 24 hours
benchmark:roa:default              → cached for 24 hours
```

## Manual Cache Invalidation

```python
from app.services.benchmark import get_redis_client

async def invalidate_benchmark_cache(metric: str, sector: str):
    redis = await get_redis_client()
    cache_key = f"benchmark:{metric}:{sector}"
    await redis.delete(cache_key)
    print(f"Cache invalidated: {cache_key}")
```

## Monitor Cache

```python
async def check_cache_stats():
    redis = await get_redis_client()
    info = await redis.info()
    print(f"Redis Memory: {info['used_memory_human']}")
    print(f"Cache Keys: {await redis.dbsize()}")
```


# ═══════════════════════════════════════════════════════════════════════════
# 7. ERROR HANDLING & GRACEFUL DEGRADATION
# ═══════════════════════════════════════════════════════════════════════════

## Scenario: Redis Unavailable

✅ **System behavior**: 
- Benchmarks still return results using static data
- No errors propagated to user
- Logs warning about Redis unavailability
- Performance slightly slower (no caching)

## Scenario: TCMB API Down

✅ **System behavior**:
- Uses static BDDK 2024 benchmark data
- Quarterly data refresh skipped
- All comparisons still work
- Cache remains valid until TTL expires

## Scenario: Invalid Sector

```python
comparison = engine.compare_to_benchmark("net_margin", 0.08, sector="invalid")
# Returns: Uses "default" sector benchmarks
```

## Scenario: Missing Metric

```python
comparison = engine.compare_to_benchmark("unknown_metric", 0.5, sector="banking")
# Returns: {"error": "Unknown metric: unknown_metric"}
```


# ═══════════════════════════════════════════════════════════════════════════
# 8. REPORTING & VISUALIZATION
# ═══════════════════════════════════════════════════════════════════════════

## CEO Board Deck Integration

Benchmarks are automatically overlaid in board deck:

```
Slide 2: Financial Performance
├── Net Margin: 8% (sektör: 12% → -4% gap) 🔴
├── Gross Margin: 40% (sektör: 42% → -2% gap) 🟡
└── EBITDA Margin: 12% (sektör: 15% → -3% gap) 🟡

Slide 3: Technology Health
├── Cloud Efficiency: 92/100 (sektör avg: 85/100) 🟢
├── Tech Debt: 4.5/10 (sektör: 5.5/10) 🟢
└── MTTR: 2.5 hours (sektör avg: 3.2 hours) 🟢
```

## Dashboard Components

Each agent dashboard includes:
- **Benchmark Card**: Current metric vs sector
- **Gap Analysis**: Absolute and percentage difference
- **Percentile Indicator**: Where you stand in distribution
- **Trend**: Arrow showing direction vs previous period
- **Recommendation**: Actionable next step


# ═══════════════════════════════════════════════════════════════════════════
# 9. PERFORMANCE TUNING
# ═══════════════════════════════════════════════════════════════════════════

## Benchmarking Performance

Typical latencies (with Redis):
- First call (cache miss): 50-150ms
- Subsequent calls (cache hit): 2-5ms
- Gap analysis: 1-3ms

## Optimization Tips

1. **Use async version** for all agent code
2. **Pre-warm cache** on startup:

```python
async def warm_benchmark_cache():
    engine = await get_benchmark_engine_async()
    
    metrics = ["net_margin", "roa", "roe", "headcount_growth_yoy"]
    sectors = ["banking", "technology", "manufacturing", "default"]
    
    for metric in metrics:
        for sector in sectors:
            await engine.get_sector_benchmark_cached(metric, sector)
    
    print("Cache warmed successfully")
```

3. **Monitor Redis memory**:

```bash
redis-cli info memory
redis-cli dbsize
```


# ═══════════════════════════════════════════════════════════════════════════
# 10. TROUBLESHOOTING
# ═══════════════════════════════════════════════════════════════════════════

## Redis Connection Issues

```
Error: Connection refused on 127.0.0.1:6379
Solution: 
1. Ensure Redis is running: redis-cli ping
2. Check REDIS_URL in .env
3. Verify firewall rules for production
```

## TCMB API Rate Limiting

```
Error: HTTP 429 Too Many Requests
Solution:
1. Requests are cached for 24 hours — should rarely happen
2. Contact TCMB support: https://evds2.tcmb.gov.tr/
3. Fallback to static data works automatically
```

## Sector Not Found

```
Error: Benchmark returns default sector values
Solution:
1. Check supported sector list above
2. Verify sector parameter spelling
3. Use "default" as fallback
```

## Performance Slow

```
Solutions (in order):
1. Check Redis connection and memory usage
2. Verify network latency to Redis
3. Enable Redis persistence for faster startup
4. Consider using read replicas for scale
```


# ═══════════════════════════════════════════════════════════════════════════
# 11. TESTING
# ═══════════════════════════════════════════════════════════════════════════

## Unit Tests

```python
# tests/test_benchmark_integration.py
import pytest
from app.services.benchmark import get_benchmark_engine
from app.services.benchmark_utils import cfo_benchmark_margins

def test_cfo_benchmark_margins():
    pnl = {
        "gross_margin": 0.40,
        "net_margin": 0.08,
        "ebitda_margin": 0.12,
    }
    result = cfo_benchmark_margins(pnl, sector="banking")
    
    assert "gross_margin" in result
    assert result["gross_margin"]["company_value"] == 0.40
    assert result["overall_position"] in [
        "sektörün üstünde",
        "sektör ortalamasında",
        "sektörün altında",
    ]

def test_gap_analysis():
    engine = get_benchmark_engine()
    gap = engine.calculate_gap_analysis(0.08, 0.12, "Net Margin", "banking")
    
    assert gap["gap_percentage"] == -33.3
    assert gap["severity"] in ["critical", "high", "medium", "good"]
```

## Integration Tests

```bash
# Run full test suite
pytest tests/ -v

# Test with Redis
REDIS_URL=redis://localhost:6379/0 pytest tests/

# Test without Redis (fallback)
REDIS_URL= pytest tests/
```


# ═══════════════════════════════════════════════════════════════════════════
# 12. MONITORING & METRICS
# ═══════════════════════════════════════════════════════════════════════════

## Key Metrics to Track

1. **Cache Hit Rate**: % of requests served from cache
2. **API Latency**: Time to fetch TCMB data
3. **Redis Memory**: MB used by benchmark cache
4. **Benchmark Coverage**: % of agents with benchmark data

## Logging

All benchmark operations are logged:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("app.services.benchmark")

# Logs include:
# - Cache hits/misses
# - API calls and responses
# - Comparison calculations
# - Error conditions
```


# ═══════════════════════════════════════════════════════════════════════════
# 13. ROADMAP
# ═══════════════════════════════════════════════════════════════════════════

## Phase 1 (Current) ✅
- Static BDDK 2024 benchmarks
- Redis caching layer
- Agent-specific utilities
- Gap analysis functions

## Phase 2 (Planned)
- Quarterly TCMB data refresh via scheduler
- Custom sector definitions per company
- Peer group comparisons (vs similar companies)
- Benchmark alerts (automated when falling below threshold)

## Phase 3 (Future)
- Machine learning for sector classification
- Predictive benchmarking (forecast where you'll be)
- Competitive intelligence integration
- Board report generation with benchmarks


# ═══════════════════════════════════════════════════════════════════════════
# 14. SUPPORT & RESOURCES
# ═══════════════════════════════════════════════════════════════════════════

## Documentation
- TCMB EVDS API: https://evds2.tcmb.gov.tr/
- BDDK Statistics: https://www.bddk.org.tr/Istatistikler

## Contact
- TCMB Support: https://evds2.tcmb.gov.tr/
- BDDK Contact: https://www.bddk.org.tr/

## Related Code
- `/backend/app/services/benchmark.py` — Core engine
- `/backend/app/services/benchmark_utils.py` — Agent utilities
- `/backend/app/agents/ceo/board_deck_agent.py` — Board deck integration
- `/backend/app/api/benchmark.py` — REST API endpoints
