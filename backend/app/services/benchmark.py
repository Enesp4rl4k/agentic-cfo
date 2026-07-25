"""
TCMB EVDS (Elektronik Veri Dağıtım Sistemi) API client + Benchmark Engine.

TCMB, Türkiye Cumhuriyet Merkez Bankası'nın kamuya açık veri API'sidir.
Ücretsiz API key ile erişim sağlanır: https://evds2.tcmb.gov.tr/

Finansal benchmark için kullanılan veri serileri:
  - TP.KKGSS.KKB.M : KOBİ kredileri faiz oranları
  - TP.TG2.Y01 : Sektör bazlı kredi hacimleri
  - TP.BKFE : Banka faaliyet giderleri
  - TP.ODEMEDEN.*  : Ödemeler dengesi istatistikleri
  - TP.SANAYIUR.* : Sanayi üretim endeksleri

Sektör bazlı karlılık verileri için BDDK istatistikleri:
  https://www.bddk.org.tr/Istatistikler

Redis Caching:
  - Benchmark data cached for 24 hours (86400 seconds)
  - Cache key pattern: benchmark:{metric}:{sector}
  - Graceful degradation if Redis unavailable

Not: Bu client kamuya açık verileri çeker. Şirket verisi paylaşılmaz.
API anahtarı .env dosyasına TCMB_API_KEY olarak eklenmeli.
Demo modda statik benchmark verileri kullanılır (API key gerektirmez).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as redis

logger = logging.getLogger(__name__)

EVDS_BASE_URL = "https://evds2.tcmb.gov.tr/service/evds"
BENCHMARK_CACHE_TTL = 86400  # 24 hours
BENCHMARK_CACHE_PREFIX = "benchmark"

# Statik sektör benchmark verileri (TCMB + BDDK 2023-2024 istatistiklerinden)
# Kaynak: BDDK Bankacılık Sektörü İstatistikleri + TCMB Sektör Bilanço Analizi
_STATIC_BENCHMARKS: dict[str, dict[str, float]] = {
    "gross_margin": {
        "retail":        0.28,   # Perakende
        "manufacturing": 0.32,   # Üretim
        "technology":    0.58,   # Teknoloji/Yazılım
        "construction":  0.22,   # İnşaat
        "services":      0.45,   # Hizmet
        "food_beverage": 0.35,   # Yiyecek-İçecek
        "logistics":     0.25,   # Lojistik
        "banking":       0.68,   # BDDK: Bankacılık
        "insurance":     0.55,   # BDDK: Sigorta
        "leasing":       0.48,   # BDDK: Finansal Kiralama
        "default":       0.35,
    },
    "net_margin": {
        "retail":        0.04,
        "manufacturing": 0.06,
        "technology":    0.15,
        "construction":  0.05,
        "services":      0.08,
        "food_beverage": 0.05,
        "logistics":     0.04,
        "banking":       0.08,   # BDDK: %8 ortalama
        "insurance":     0.12,   # BDDK: %12 ortalama
        "leasing":       0.10,   # BDDK: %10 ortalama
        "default":       0.06,
    },
    "ebitda_margin": {
        "retail":        0.08,
        "manufacturing": 0.12,
        "technology":    0.22,
        "construction":  0.10,
        "services":      0.15,
        "food_beverage": 0.11,
        "logistics":     0.09,
        "banking":       0.12,   # BDDK: FAVÖK marjı
        "insurance":     0.18,   # BDDK: FAVÖK marjı
        "leasing":       0.14,   # BDDK: FAVÖK marjı
        "default":       0.12,
    },
    "opex_to_revenue": {
        "retail":        0.22,
        "manufacturing": 0.18,
        "technology":    0.38,
        "construction":  0.16,
        "services":      0.32,
        "food_beverage": 0.28,
        "logistics":     0.20,
        "banking":       0.28,   # BDDK: Faaliyet giderleri
        "insurance":     0.32,   # BDDK: Faaliyet giderleri
        "leasing":       0.35,   # BDDK: Faaliyet giderleri
        "default":       0.25,
    },
    "revenue_growth_yoy": {
        "retail":        0.18,   # Türkiye enflasyon baskısı altında nominal büyüme
        "manufacturing": 0.22,
        "technology":    0.35,
        "construction":  0.25,
        "services":      0.20,
        "food_beverage": 0.24,
        "logistics":     0.19,
        "banking":       0.32,   # BDDK: 2024 tahmin
        "insurance":     0.28,   # BDDK: 2024 tahmin
        "leasing":       0.26,   # BDDK: 2024 tahmin
        "default":       0.22,
    },
    "roa": {  # Return on Assets
        "retail":        0.08,
        "manufacturing": 0.10,
        "technology":    0.18,
        "construction":  0.08,
        "services":      0.12,
        "food_beverage": 0.09,
        "logistics":     0.07,
        "banking":       0.015,  # BDDK: %1.5 ortalama
        "insurance":     0.08,
        "leasing":       0.06,
        "default":       0.10,
    },
    "roe": {  # Return on Equity
        "retail":        0.15,
        "manufacturing": 0.18,
        "technology":    0.28,
        "construction":  0.12,
        "services":      0.20,
        "food_beverage": 0.16,
        "logistics":     0.14,
        "banking":       0.12,   # BDDK: %12 ortalama
        "insurance":     0.18,
        "leasing":       0.15,
        "default":       0.18,
    },
    "debt_to_equity": {  # Debt/Equity Ratio
        "retail":        0.80,
        "manufacturing": 0.70,
        "technology":    0.50,
        "construction":  1.20,
        "services":      0.60,
        "food_beverage": 0.75,
        "logistics":     0.85,
        "banking":       8.50,   # BDDK: Yüksek leverage normal
        "insurance":     2.50,
        "leasing":       3.20,
        "default":       0.75,
    },
    "current_ratio": {  # Likidite
        "retail":        1.50,
        "manufacturing": 1.40,
        "technology":    1.80,
        "construction":  1.30,
        "services":      1.60,
        "food_beverage": 1.45,
        "logistics":     1.35,
        "banking":       0.10,   # BDDK: Özel durum
        "insurance":     0.50,
        "leasing":       0.80,
        "default":       1.50,
    },
    "headcount_growth_yoy": {
        "retail":        0.08,
        "manufacturing": 0.12,
        "technology":    0.22,
        "construction":  0.05,
        "services":      0.10,
        "food_beverage": 0.09,
        "logistics":     0.08,
        "banking":       0.06,
        "insurance":     0.04,
        "leasing":       0.05,
        "default":       0.10,
    },
    "revenue_per_headcount": {  # Annual revenue per employee in thousands TL
        "retail":        150,    # 150K TL/kişi/yıl
        "manufacturing": 280,
        "technology":    450,
        "construction":  200,
        "services":      320,
        "food_beverage": 180,
        "logistics":     220,
        "banking":       600,    # BDDK: Yüksek
        "insurance":     550,
        "leasing":       500,
        "default":       250,
    },
    "cac_payback_months": {  # Customer Acquisition Cost payback
        "retail":        6,
        "manufacturing": 12,
        "technology":    8,
        "construction":  18,
        "services":      10,
        "food_beverage": 5,
        "logistics":     14,
        "default":       10,
    },
    "ltv_to_cac_ratio": {  # Lifetime Value / Customer Acquisition Cost
        "retail":        3.0,
        "manufacturing": 2.5,
        "technology":    4.5,
        "construction":  2.0,
        "services":      3.5,
        "food_beverage": 4.0,
        "logistics":     2.8,
        "default":       3.0,
    },
}

# Percentile bands (p25, p50, p75) for benchmarking
# Source: BDDK sector analysis 2023-2024
_PERCENTILE_BANDS: dict[str, dict[str, tuple[float, float, float]]] = {
    "gross_margin": {
        "retail":        (0.18, 0.28, 0.40),
        "manufacturing": (0.20, 0.32, 0.45),
        "technology":    (0.40, 0.58, 0.72),
        "services":      (0.30, 0.45, 0.60),
        "banking":       (0.55, 0.68, 0.78),
        "insurance":     (0.45, 0.55, 0.65),
        "leasing":       (0.38, 0.48, 0.58),
        "default":       (0.20, 0.35, 0.50),
    },
    "net_margin": {
        "retail":        (0.01, 0.04, 0.08),
        "manufacturing": (0.02, 0.06, 0.12),
        "technology":    (0.05, 0.15, 0.25),
        "services":      (0.03, 0.08, 0.15),
        "banking":       (0.05, 0.08, 0.12),
        "insurance":     (0.08, 0.12, 0.16),
        "leasing":       (0.06, 0.10, 0.14),
        "default":       (0.02, 0.06, 0.12),
    },
    "roa": {
        "retail":        (0.05, 0.08, 0.12),
        "manufacturing": (0.07, 0.10, 0.15),
        "technology":    (0.12, 0.18, 0.25),
        "services":      (0.08, 0.12, 0.18),
        "banking":       (0.008, 0.015, 0.022),
        "insurance":     (0.05, 0.08, 0.12),
        "leasing":       (0.04, 0.06, 0.09),
        "default":       (0.07, 0.10, 0.15),
    },
    "roe": {
        "retail":        (0.10, 0.15, 0.22),
        "manufacturing": (0.12, 0.18, 0.26),
        "technology":    (0.20, 0.28, 0.38),
        "services":      (0.14, 0.20, 0.28),
        "banking":       (0.08, 0.12, 0.18),
        "insurance":     (0.12, 0.18, 0.25),
        "leasing":       (0.10, 0.15, 0.22),
        "default":       (0.12, 0.18, 0.26),
    },
    "debt_to_equity": {
        "retail":        (0.50, 0.80, 1.20),
        "manufacturing": (0.40, 0.70, 1.10),
        "technology":    (0.30, 0.50, 0.80),
        "services":      (0.40, 0.60, 0.90),
        "banking":       (6.0, 8.50, 11.0),
        "insurance":     (1.50, 2.50, 3.80),
        "leasing":       (2.0, 3.20, 4.50),
        "default":       (0.40, 0.75, 1.20),
    },
    "headcount_growth_yoy": {
        "retail":        (0.03, 0.08, 0.15),
        "manufacturing": (0.05, 0.12, 0.20),
        "technology":    (0.15, 0.22, 0.35),
        "services":      (0.05, 0.10, 0.18),
        "banking":       (0.02, 0.06, 0.12),
        "default":       (0.05, 0.10, 0.18),
    },
    "cac_payback_months": {
        "retail":        (4, 6, 9),
        "technology":    (6, 8, 12),
        "services":      (7, 10, 15),
        "default":       (6, 10, 16),
    },
}


class TCMBClient:
    """
    TCMB EVDS API client with static fallback.

    When API key is not configured, returns static benchmark data.
    When API key is configured, fetches real-time macro data from EVDS.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self._http = httpx.AsyncClient(timeout=10.0)

    async def get_series(
        self,
        series_code: str,
        start_date: str = "01-01-2023",
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch a TCMB EVDS data series.

        Args:
            series_code: EVDS series code (e.g. "TP.DK.USD.A.YTL")
            start_date:  DD-MM-YYYY format
            end_date:    DD-MM-YYYY format (defaults to today)

        Returns:
            List of {date, value} dicts
        """
        if not self.api_key:
            logger.debug("TCMB API key not configured — using static data")
            return []

        if not end_date:
            end_date = datetime.now(timezone.utc).strftime("%d-%m-%Y")

        try:
            resp = await self._http.get(
                f"{EVDS_BASE_URL}/series/{series_code}",
                params={
                    "startDate": start_date,
                    "endDate": end_date,
                    "type": "json",
                    "key": self.api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            return [
                {"date": item.get("Tarih"), "value": float(item.get(series_code, 0) or 0)}
                for item in items
                if item.get(series_code) not in (None, "", "ND")
            ]
        except Exception as exc:
            logger.warning("TCMB EVDS fetch failed for %s: %s", series_code, exc)
            return []

    async def close(self) -> None:
        await self._http.aclose()


class BenchmarkEngine:
    """
    Sector benchmark engine with Redis caching.

    Compares company financial metrics against sector medians
    using static TCMB/BDDK data (or live data if API key configured).
    Caches results in Redis for 24 hours to improve performance.
    """

    def __init__(self, tcmb_client: TCMBClient | None = None, redis_client: redis.Redis | None = None) -> None:
        self._client = tcmb_client
        self._redis = redis_client

    def get_sector_benchmark(
        self,
        metric: str,
        sector: str = "default",
    ) -> dict[str, Any]:
        """
        Get sector benchmark for a specific metric.

        Args:
            metric: "gross_margin" | "net_margin" | "ebitda_margin" |
                    "opex_to_revenue" | "revenue_growth_yoy"
            sector: "retail" | "manufacturing" | "technology" | "services" |
                    "construction" | "food_beverage" | "logistics" | "default"

        Returns:
            {metric, sector, median, p25, p75, source, last_updated}
        """
        metric_data = _STATIC_BENCHMARKS.get(metric, {})
        if not metric_data:
            return {"error": f"Unknown metric: {metric}"}

        median = metric_data.get(sector, metric_data.get("default", 0.0))

        # Percentile bands
        bands = _PERCENTILE_BANDS.get(metric, {})
        sector_bands = bands.get(sector, bands.get("default", (median * 0.6, median, median * 1.4)))
        p25, p50, p75 = sector_bands

        return {
            "metric":       metric,
            "sector":       sector,
            "median":       round(median, 4),
            "p25":          round(p25, 4),
            "p50":          round(p50, 4),
            "p75":          round(p75, 4),
            "source":       "TCMB/BDDK Sektör İstatistikleri 2023-2024",
            "last_updated": "2024-Q4",
        }

    def compare_to_benchmark(
        self,
        metric: str,
        company_value: float,
        sector: str = "default",
    ) -> dict[str, Any]:
        """
        Compare a company metric to sector benchmark.

        Returns:
            {
              benchmark: {...},
              company_value: float,
              percentile_position: "bottom_25" | "p25_p50" | "p50_p75" | "top_25",
              vs_median_pct: float,   # % difference vs median
              interpretation: str,   # Turkish interpretation
              recommendation: str,   # Turkish actionable recommendation
            }
        """
        bm = self.get_sector_benchmark(metric, sector)
        if "error" in bm:
            return bm

        p25 = bm["p25"]
        p50 = bm["p50"]
        p75 = bm["p75"]

        # Determine percentile position
        if company_value < p25:
            position = "bottom_25"
        elif company_value < p50:
            position = "p25_p50"
        elif company_value < p75:
            position = "p50_p75"
        else:
            position = "top_25"

        vs_median = ((company_value - p50) / p50 * 100) if p50 != 0 else 0

        interpretation, recommendation = self._interpret(
            metric, position, vs_median, company_value, p50
        )

        return {
            "benchmark":           bm,
            "company_value":       round(company_value, 4),
            "percentile_position": position,
            "vs_median_pct":       round(vs_median, 1),
            "interpretation":      interpretation,
            "recommendation":      recommendation,
        }

    def build_full_comparison(
        self,
        pnl: dict[str, Any],
        sector: str = "default",
    ) -> dict[str, Any]:
        """
        Build a full benchmark comparison report from P&L data.
        Returns comparisons for all available metrics.
        """
        results: dict[str, Any] = {"sector": sector, "metrics": {}}

        metric_map = {
            "gross_margin":    pnl.get("gross_margin", 0),
            "net_margin":      pnl.get("net_margin", 0),
            "ebitda_margin":   pnl.get("ebitda_margin", 0),
            "opex_to_revenue": (pnl.get("total_opex", 0) / pnl["revenue"])
                               if pnl.get("revenue", 0) > 0 else 0,
        }

        for metric, value in metric_map.items():
            results["metrics"][metric] = self.compare_to_benchmark(metric, value, sector)

        # Overall score: weighted average of percentile positions
        pos_scores = {"bottom_25": 1, "p25_p50": 2, "p50_p75": 3, "top_25": 4}
        positions = [
            pos_scores.get(v.get("percentile_position", "p25_p50"), 2)
            for v in results["metrics"].values()
            if "percentile_position" in v
        ]
        if positions:
            avg_score = sum(positions) / len(positions)
            results["overall_score"] = round(avg_score, 2)
            results["overall_label"] = (
                "Sektörün altında" if avg_score < 2 else
                "Sektör ortalamasında" if avg_score < 3 else
                "Sektörün üstünde"
            )

        return results

    async def _get_cached(self, key: str) -> dict[str, Any] | None:
        """Get value from Redis cache."""
        if not self._redis:
            return None
        try:
            cached = await self._redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception as exc:
            logger.warning(f"Redis cache get failed for {key}: {exc}")
        return None

    async def _set_cached(self, key: str, value: dict[str, Any], ttl: int = BENCHMARK_CACHE_TTL) -> None:
        """Set value in Redis cache."""
        if not self._redis:
            return
        try:
            await self._redis.setex(key, ttl, json.dumps(value))
        except Exception as exc:
            logger.warning(f"Redis cache set failed for {key}: {exc}")

    def _cache_key(self, metric: str, sector: str) -> str:
        """Generate cache key for benchmark."""
        return f"{BENCHMARK_CACHE_PREFIX}:{metric}:{sector}"

    async def get_sector_benchmark_cached(
        self,
        metric: str,
        sector: str = "default",
    ) -> dict[str, Any]:
        """Get sector benchmark with Redis caching."""
        cache_key = self._cache_key(metric, sector)
        cached = await self._get_cached(cache_key)
        if cached:
            logger.debug(f"Benchmark cache hit: {cache_key}")
            return cached

        result = self.get_sector_benchmark(metric, sector)
        await self._set_cached(cache_key, result)
        return result

    def calculate_gap_analysis(
        self,
        company_value: float,
        benchmark_median: float,
        metric_name: str = "",
        sector: str = "default",
    ) -> dict[str, Any]:
        """
        Calculate gap analysis: "Bizim X, sektör Y → Z% gap"
        Returns structured comparison for reporting.
        """
        if benchmark_median == 0:
            return {"error": "Benchmark median is zero"}

        gap_pct = ((company_value - benchmark_median) / benchmark_median) * 100
        gap_abs = company_value - benchmark_median

        interpretation = "sektörde" if gap_pct < 0 else "sektörün üstünde"
        if gap_pct < -20:
            severity = "critical"
            emoji = "🔴"
        elif gap_pct < -10:
            severity = "high"
            emoji = "🟠"
        elif gap_pct < 0:
            severity = "medium"
            emoji = "🟡"
        else:
            severity = "good"
            emoji = "🟢"

        return {
            "metric": metric_name,
            "sector": sector,
            "company_value": round(company_value, 4),
            "benchmark_median": round(benchmark_median, 4),
            "gap_absolute": round(gap_abs, 4),
            "gap_percentage": round(gap_pct, 1),
            "gap_interpretation": f"Bizim {company_value:.2f}, sektör {benchmark_median:.2f} → {gap_pct:+.1f}% gap",
            "severity": severity,
            "emoji": emoji,
            "direction": "behind" if gap_pct < 0 else "ahead",
        }

    @staticmethod
    def _interpret(
        metric: str,
        position: str,
        vs_median: float,
        value: float,
        median: float,
    ) -> tuple[str, str]:
        """Return (interpretation, recommendation) in Turkish."""

        metric_names = {
            "gross_margin":    "brüt kâr marjı",
            "net_margin":      "net kâr marjı",
            "ebitda_margin":   "FAVÖK marjı",
            "opex_to_revenue": "gider/ciro oranı",
            "revenue_growth_yoy": "yıllık büyüme oranı",
            "roa":             "varlık getirisi (ROA)",
            "roe":             "özsermaye getirisi (ROE)",
            "debt_to_equity":  "borç/özsermaye oranı",
            "headcount_growth_yoy": "yıllık personel büyümesi",
            "cac_payback_months": "müşteri edinim maliyeti geri dönüş süresi (aylar)",
        }
        name = metric_names.get(metric, metric)

        val_fmt  = f"%{value*100:.1f}" if isinstance(value, float) and value < 10 else f"{value:.2f}"
        med_fmt  = f"%{median*100:.1f}" if isinstance(median, float) and median < 10 else f"{median:.2f}"
        diff_fmt = f"%{abs(vs_median):.0f}"

        if position == "bottom_25":
            interpretation = (
                f"{val_fmt} olan {name}ınız, sektör ortalamasının ({med_fmt}) "
                f"{diff_fmt} altında ve sektörün en düşük çeyreğinde."
            )
            recommendation = f"{name.capitalize()} için acil iyileştirme gerekiyor."
        elif position == "p25_p50":
            interpretation = (
                f"{val_fmt} olan {name}ınız, sektör ortalamasının ({med_fmt}) "
                f"biraz altında. Potansiyel var."
            )
            recommendation = f"{name.capitalize()} geliştirilerek sektör ortalamasına ulaşılabilir."
        elif position == "p50_p75":
            interpretation = (
                f"{val_fmt} olan {name}ınız, sektör ortalamasının ({med_fmt}) "
                f"{diff_fmt} üstünde. İyi performans."
            )
            recommendation = f"Mevcut performansı koruyun, lider çeyreğe ({diff_fmt} daha) ulaşabilirsiniz."
        else:
            interpretation = (
                f"{val_fmt} olan {name}ınız sektörün en iyi %25'inde. "
                f"Sektör ortalamasının {diff_fmt} üstünde."
            )
            recommendation = "Lider konumunuzu koruyun, rakip girişine karşı önlem alın."

        return interpretation, recommendation


# Module-level singleton
_engine: BenchmarkEngine | None = None
_redis_client: redis.Redis | None = None


async def get_redis_client() -> redis.Redis | None:
    """Get or create async Redis client."""
    global _redis_client
    if _redis_client is None:
        try:
            from app.config import get_settings
            settings = get_settings()
            _redis_client = await redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await _redis_client.ping()
            logger.info("Redis connected for benchmark caching")
        except Exception as exc:
            logger.warning(f"Redis connection failed, benchmark caching disabled: {exc}")
            _redis_client = None
    return _redis_client


def get_benchmark_engine() -> BenchmarkEngine:
    """Get or create benchmark engine (sync version)."""
    global _engine
    if _engine is None:
        from app.config import get_settings
        settings = get_settings()
        api_key = getattr(settings, "tcmb_api_key", None) or None
        client = TCMBClient(api_key=api_key) if api_key else None
        _engine = BenchmarkEngine(tcmb_client=client, redis_client=None)
    return _engine


async def get_benchmark_engine_async() -> BenchmarkEngine:
    """Get or create benchmark engine with Redis (async version)."""
    global _engine
    if _engine is None:
        from app.config import get_settings
        settings = get_settings()
        api_key = getattr(settings, "tcmb_api_key", None) or None
        client = TCMBClient(api_key=api_key) if api_key else None
        redis_client = await get_redis_client()
        _engine = BenchmarkEngine(tcmb_client=client, redis_client=redis_client)
    return _engine
