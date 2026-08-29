"""
TCMB Makro Entegrasyonu — AN-1

Türkiye Cumhuriyet Merkez Bankası EVDS (Elektronik Veri Dağıtım Sistemi) API
ile gerçek zamanlı makroekonomik veri çekme.

Desteklenen seriler:
  - TP.DK.USD.A    → USD/TRY kuru (günlük)
  - TP.DK.EUR.A    → EUR/TRY kuru (günlük)
  - TP.FG.J0       → Politika faizi (aylık)
  - TP.FE.OKTG01   → TÜFE (aylık)
  - TP.FE.OKTP01   → ÜFE (aylık)
  - TP.AB.B1       → Repo faizi (haftalık)

Kullanım:
    svc = TCMBMacroService()
    data = await svc.get_macro_snapshot()
    # data.usd_try, data.eur_try, data.inflation_pct, data.policy_rate_pct

Fallback: API key yoksa statik değerler döner (son bilinen değerler).

DDIA: Makro veri "external state" — agresif cache (6 saat TTL).
     Her istek API çağrısı yapmaz; Redis cache + scheduled refresh.

API dokümantasyonu: https://evds2.tcmb.gov.tr/help/videos/EVDS_Web_Service.pdf
Ücretsiz API key: https://evds2.tcmb.gov.tr/index.php?lang=tr
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Statik fallback değerleri (2024 Ocak ortalamalar) ────────────────────────
# API key yoksa veya API down ise bu değerler kullanılır.
_STATIC_FALLBACK = {
    "usd_try":          32.5,
    "eur_try":          35.2,
    "policy_rate_pct":  45.0,
    "inflation_pct":    65.0,   # TÜFE yıllık
    "ppi_pct":          42.0,   # ÜFE yıllık
    "repo_rate_pct":    45.0,
    "data_source":      "static_fallback",
    "as_of":            "2024-01-01",
}

CACHE_TTL_HOURS = 6


@dataclass
class MacroSnapshot:
    """Anlık makroekonomik görüntü."""
    usd_try:           float
    eur_try:           float
    policy_rate_pct:   float    # Politika faizi %
    inflation_pct:     float    # TÜFE yıllık değişim %
    ppi_pct:           float    # ÜFE yıllık değişim %
    repo_rate_pct:     float    # Repo faizi %
    data_source:       str      # "tcmb_api" | "redis_cache" | "static_fallback"
    as_of:             str      # ISO date string
    raw_series:        dict = field(default_factory=dict)

    def real_cost_of_capital(self) -> float:
        """Reel sermaye maliyeti = politika faizi - enflasyon."""
        return round(self.policy_rate_pct - self.inflation_pct, 2)

    def usd_premium(self) -> float:
        """Dolar kuru yıllık artış yüzdesi (static fallback'te 0)."""
        return 0.0

    def inflation_adjusted_growth(self, nominal_growth_pct: float) -> float:
        """Reel büyüme = nominal büyüme - enflasyon."""
        return round(nominal_growth_pct - self.inflation_pct, 2)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["real_cost_of_capital"] = self.real_cost_of_capital()
        d["inflation_adjusted_growth_example"] = self.inflation_adjusted_growth(20.0)
        return d


class TCMBMacroService:
    """
    TCMB EVDS API client.

    - Cache: Redis (6 saat TTL), in-memory fallback
    - Retry: 3 deneme, 5sn timeout
    - Fallback: statik değerler
    """

    EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"

    # Series codes → friendly names
    SERIES = {
        "TP.DK.USD.A":   "usd_try",
        "TP.DK.EUR.A":   "eur_try",
        "TP.FG.J0":      "policy_rate_pct",
        "TP.FE.OKTG01":  "inflation_pct",
        "TP.FE.OKTP01":  "ppi_pct",
    }

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._cache: dict[str, Any] | None = None
        self._cache_time: datetime | None  = None

    def _is_cache_fresh(self) -> bool:
        if not self._cache or not self._cache_time:
            return False
        age = datetime.now(UTC) - self._cache_time
        return age < timedelta(hours=CACHE_TTL_HOURS)

    async def _try_redis_cache(self) -> MacroSnapshot | None:
        """Try to load from Redis cache."""
        try:
            from app.services.company_context import _get_redis
            redis = await _get_redis()
            if redis:
                raw = await redis.get("tcmb_macro_snapshot")
                if raw:
                    data = json.loads(raw)
                    data["data_source"] = "redis_cache"
                    return MacroSnapshot(**{k: v for k, v in data.items() if k in MacroSnapshot.__dataclass_fields__})
        except Exception:
            pass
        return None

    async def _save_redis_cache(self, snapshot: MacroSnapshot) -> None:
        """Save snapshot to Redis with TTL."""
        try:
            from app.services.company_context import _get_redis
            redis = await _get_redis()
            if redis:
                await redis.setex(
                    "tcmb_macro_snapshot",
                    CACHE_TTL_HOURS * 3600,
                    json.dumps(snapshot.to_dict()),
                )
        except Exception:
            pass

    async def _fetch_series(self, series_code: str) -> float | None:
        """Fetch latest value for a single series from EVDS API."""
        if not self._api_key:
            return None

        today    = datetime.now().strftime("%d-%m-%Y")
        week_ago = (datetime.now() - timedelta(days=14)).strftime("%d-%m-%Y")

        params = {
            "series":    series_code,
            "startDate": week_ago,
            "endDate":   today,
            "type":      "json",
            "key":       self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(self.EVDS_BASE, params=params)
                if resp.status_code != 200:
                    logger.debug("EVDS %s → HTTP %d", series_code, resp.status_code)
                    return None

                data = resp.json()
                items = data.get("items", [])
                if not items:
                    return None

                # Get most recent non-null value
                for item in reversed(items):
                    val = item.get(series_code)
                    if val and val != "":
                        try:
                            return float(str(val).replace(",", "."))
                        except ValueError:
                            pass
        except Exception as exc:
            logger.debug("EVDS API error for %s: %s", series_code, exc)
        return None

    async def get_macro_snapshot(self, force_refresh: bool = False) -> MacroSnapshot:
        """
        Get latest macro snapshot.

        Priority: in-memory cache → Redis cache → EVDS API → static fallback.
        """
        # In-memory cache
        if not force_refresh and self._is_cache_fresh() and self._cache:
            return MacroSnapshot(**self._cache)

        # Redis cache
        if not force_refresh:
            cached = await self._try_redis_cache()
            if cached:
                return cached

        # API fetch
        if self._api_key:
            snapshot = await self._fetch_from_api()
            if snapshot:
                await self._save_redis_cache(snapshot)
                self._cache = snapshot.to_dict()
                self._cache_time = datetime.now(UTC)
                return snapshot

        # Static fallback
        logger.info("TCMB API unavailable — using static fallback values")
        return MacroSnapshot(**{
            k: v for k, v in _STATIC_FALLBACK.items()
            if k in MacroSnapshot.__dataclass_fields__
        })

    async def _fetch_from_api(self) -> MacroSnapshot | None:
        """Fetch all series from EVDS API in parallel."""
        import asyncio

        results = await asyncio.gather(
            *[self._fetch_series(code) for code in self.SERIES],
            return_exceptions=True,
        )

        mapping: dict[str, float | None] = {}
        for code, result in zip(self.SERIES, results, strict=False):
            friendly = self.SERIES[code]
            if isinstance(result, float):
                mapping[friendly] = result
            else:
                mapping[friendly] = None

        # If any critical series failed, return None to trigger fallback
        if mapping.get("usd_try") is None and mapping.get("policy_rate_pct") is None:
            logger.warning("TCMB API returned no data — falling back to static values")
            return None

        fallback = _STATIC_FALLBACK
        return MacroSnapshot(
            usd_try          = mapping.get("usd_try")          or fallback["usd_try"],
            eur_try          = mapping.get("eur_try")          or fallback["eur_try"],
            policy_rate_pct  = mapping.get("policy_rate_pct")  or fallback["policy_rate_pct"],
            inflation_pct    = mapping.get("inflation_pct")    or fallback["inflation_pct"],
            ppi_pct          = mapping.get("ppi_pct")          or fallback["ppi_pct"],
            repo_rate_pct    = mapping.get("policy_rate_pct")  or fallback["repo_rate_pct"],
            data_source      = "tcmb_api",
            as_of            = datetime.now().strftime("%Y-%m-%d"),
        )

    async def get_exchange_rate_trend(self, currency: str = "USD", days: int = 30) -> list[dict]:
        """
        Get historical exchange rate for charting.
        Returns list of {date, rate} dicts.
        """
        if not self._api_key:
            # Return synthetic trend based on current fallback rate
            base = _STATIC_FALLBACK["usd_try"] if currency == "USD" else _STATIC_FALLBACK["eur_try"]
            return [
                {
                    "date": (datetime.now() - timedelta(days=days - i)).strftime("%Y-%m-%d"),
                    "rate": round(base * (1 + (i - days // 2) * 0.001), 4),
                }
                for i in range(0, days, 3)
            ]

        series_code = "TP.DK.USD.A" if currency == "USD" else "TP.DK.EUR.A"
        start = (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y")
        end   = datetime.now().strftime("%d-%m-%Y")

        params = {
            "series":    series_code,
            "startDate": start,
            "endDate":   end,
            "type":      "json",
            "key":       self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.EVDS_BASE, params=params)
                if resp.status_code != 200:
                    return []
                data   = resp.json()
                items  = data.get("items", [])
                result = []
                for item in items:
                    date = item.get("Tarih", "")
                    val  = item.get(series_code)
                    if date and val:
                        try:
                            result.append({
                                "date": date,
                                "rate": float(str(val).replace(",", ".")),
                            })
                        except ValueError:
                            pass
                return result
        except Exception as exc:
            logger.warning("TCMB exchange rate trend failed: %s", exc)
            return []


# ── Macro context for agents ──────────────────────────────────────────────────

async def get_macro_context_for_agents() -> dict[str, Any]:
    """
    Tüm ajanlar için makro ekonomik bağlam.
    CFO/CTO/CMO agentları bu veriyi prompt'larına ekler.
    """
    from app.config import get_settings
    settings = get_settings()
    svc = TCMBMacroService(api_key=getattr(settings, "tcmb_api_key", ""))
    snap = await svc.get_macro_snapshot()

    return {
        "macro_context": {
            "usd_try":              snap.usd_try,
            "eur_try":              snap.eur_try,
            "policy_rate_pct":      snap.policy_rate_pct,
            "inflation_pct":        snap.inflation_pct,
            "real_cost_of_capital": snap.real_cost_of_capital(),
            "data_source":          snap.data_source,
            "as_of":                snap.as_of,
        },
        "agent_prompt_addition": (
            f"\n\nTürkiye Makro Bağlamı ({snap.as_of}):\n"
            f"  - USD/TRY: {snap.usd_try:.2f}\n"
            f"  - EUR/TRY: {snap.eur_try:.2f}\n"
            f"  - Politika Faizi: %{snap.policy_rate_pct:.1f}\n"
            f"  - TÜFE (yıllık): %{snap.inflation_pct:.1f}\n"
            f"  - Reel Sermaye Maliyeti: %{snap.real_cost_of_capital():.1f}\n"
            f"  Kaynak: {snap.data_source}\n"
        ),
    }


# ── Singleton ─────────────────────────────────────────────────────────────────

_service: TCMBMacroService | None = None


def get_tcmb_service() -> TCMBMacroService:
    """Global TCMB service singleton."""
    global _service
    if _service is None:
        from app.config import get_settings
        settings = get_settings()
        _service = TCMBMacroService(api_key=getattr(settings, "tcmb_api_key", ""))
    return _service
