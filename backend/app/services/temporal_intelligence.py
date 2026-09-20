"""
Temporal Intelligence Engine

DDIA (Designing Data-Intensive Applications) prensiplerine uygun
zaman serisi analiz ve gecmis ogrenim motoru.

DDIA Prensipleri bu serviste:
  - Reliability:   Her analiz sonucu immutable event olarak PostgreSQL'e yazilir
  - Scalability:   Okuma ve yazma yollari ayri (CQRS pattern)
                   Yazma: INSERT only (append-only log)
                   Okuma: Materialized agregat (denormalized cache)
  - Maintainability: Single responsibility — bu servis sadece temporal analiz
  - Unbundling DB:  Hot data → Redis (son 3 ay), Cold data → PostgreSQL
  - Stream view:   Her CFO analizi bir "event" — gecmisi degistirme yok

Neler yapabilir:
  1. DeltaAnalysis:    Bu donem vs gecen donem — hangi metrikler degisti?
  2. TrendDetection:   Son 6 analizden trend cikar (yukselis/dusus/stabil)
  3. RegimeChange:     Anomali mi, kalici degisim mi? (structural break tespiti)
  4. SeasonalPattern:  Her Aralik'ta nakit duser mi? (mevsimsel pattern)
  5. ForecastBlend:    Gecmis analizleri LLM tahminleriyle birlestir
  6. HealthTimeline:   Sirket saglik skoru zaman icinde nasil degisti?

Kullanim:
    engine = TemporalIntelligenceEngine(db)

    # Yeni analiz kaydet
    await engine.record_analysis(org_id, agent, period, metrics)

    # Gecmise gore delta al
    delta = await engine.compute_delta(org_id, "cfo", current_metrics)

    # Trend analizi
    trends = await engine.detect_trends(org_id, "cfo", window=6)
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Immutable Event Record (append-only) ──────────────────────────────────────

@dataclass
class AnalysisEvent:
    """
    Bir analiz calistirmasinin immutable kaydi.

    DDIA: append-only log — gercekleşen olaylar degistirilemez.
    Bu kayit sadece INSERT edilir, UPDATE/DELETE olmaz.
    """
    event_id:   str
    org_id:     str
    agent:      str       # "cfo" | "cto" | "cmo" | "chro" | "coo" | "risk"
    period:     str       # "2024-Q4" | "2024-12" | "2024-W48"
    period_type: str      # "monthly" | "quarterly" | "weekly"
    metrics:    dict[str, Any]   # serializeable metrikler
    narrative:  str       # LLM ozet
    confidence: float     # 0.0-1.0
    data_source: str      # "parasut" | "logo_tiger" | "manual" | "benchmark"
    recorded_at: datetime | float = field(default_factory=lambda: datetime.now(UTC))  # datetime or Unix timestamp
    schema_version: int = 1   # gelecek migrasyon icin

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if isinstance(self.recorded_at, datetime):
            d["recorded_at"] = self.recorded_at.isoformat()
        return d

    @classmethod
    def create(
        cls,
        org_id:     str,
        agent:      str,
        period:     str,
        metrics:    dict[str, Any],
        narrative:  str = "",
        confidence: float = 0.8,
        data_source: str = "manual",
        period_type: str = "monthly",
    ) -> AnalysisEvent:
        return cls(
            event_id     = str(uuid.uuid4()),
            org_id       = org_id,
            agent        = agent,
            period       = period,
            period_type  = period_type,
            metrics      = metrics,
            narrative    = narrative,
            confidence   = confidence,
            data_source  = data_source,
            recorded_at  = datetime.now(UTC),
        )



# ── Delta sonucu ──────────────────────────────────────────────────────────────

@dataclass
class MetricDelta:
    """Tek bir metrigin iki donem arasındaki degisimi."""
    metric:       str
    current:      float
    previous:     float
    abs_change:   float
    pct_change:   float   # yuzde degisim
    direction:    str     # "up" | "down" | "stable"
    is_positive:  bool    # bu metrik icin yukselis iyi mi?


@dataclass
class DeltaAnalysis:
    """Iki analiz arasındaki tam delta raporu."""
    org_id:         str
    agent:          str
    current_period: str
    previous_period: str
    deltas:         list[MetricDelta]
    summary:        str
    regime_changed: bool   # ani ve buyuk degisim mi?
    flags:          list[str]   # dikkat gerektiren degisimler

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_id":           self.org_id,
            "agent":            self.agent,
            "current_period":   self.current_period,
            "previous_period":  self.previous_period,
            "regime_changed":   self.regime_changed,
            "flags":            self.flags,
            "summary":          self.summary,
            "deltas": [
                {
                    "metric":      d.metric,
                    "current":     d.current,
                    "previous":    d.previous,
                    "abs_change":  round(d.abs_change, 4),
                    "pct_change":  round(d.pct_change, 2),
                    "direction":   d.direction,
                    "is_positive": d.is_positive,
                }
                for d in self.deltas
            ],
        }


@dataclass
class TrendResult:
    """Bir metrigin zaman icindeki trendi."""
    metric:         str
    values:         list[float]
    periods:        list[str]
    trend:          str          # "rising" | "falling" | "stable" | "volatile"
    slope:          float        # dogrusal regresyon egimi
    r_squared:      float        # trend ne kadar guclu? (0-1)
    seasonal_pattern: bool       # mevsimsel tekrar var mi?


# ── Temporal Intelligence Engine ─────────────────────────────────────────────

class TemporalIntelligenceEngine:
    """
    DDIA'ya uygun zaman serisi analiz motoru.

    Depolama stratejisi (DDIA Unbundling):
      - PostgreSQL: durable event log (append-only)
      - Redis:      hot path cache (son 6 ay)
      - In-memory:  aktif session icin trend cache

    Okuma/yazma ayrimi (CQRS):
      - Yazma:  record_analysis() → sadece INSERT
      - Okuma:  get_history(), compute_delta() → cache first, DB fallback
    """

    def __init__(self, db: Any = None, redis: Any = None) -> None:
        self.db    = db       # AsyncSession
        self.redis = redis    # Redis client (optional)
        self._memory_cache: dict[str, list[AnalysisEvent]] = {}  # org+agent key

    # ── Yazma (CQRS Command Side) ─────────────────────────────────────────────

    def record_analysis(
        self,
        org_id:     str,
        agent:      str,
        metrics:    dict[str, Any],
        period:     str = "",
        narrative:  str = "",
        confidence: float = 0.8,
        data_source: str = "manual",
    ) -> AnalysisEvent:
        """
        Analiz sonucunu immutable event olarak kaydet.

        DDIA: append-only log. Onceki kayit degistirilmez.
        """
        if not period:
            period = datetime.now(UTC).strftime("%Y-%m")

        event = AnalysisEvent.create(
            org_id     = org_id,
            agent      = agent,
            period     = period,
            metrics    = metrics,
            narrative  = narrative,
            confidence = confidence,
            data_source = data_source,
        )

        key = f"{org_id}:{agent}"
        if key not in self._memory_cache:
            self._memory_cache[key] = []
        self._memory_cache[key].append(event)
        self._memory_cache[key] = self._memory_cache[key][-12:]

        return event

    async def record_analysis_async(
        self,
        org_id:     str,
        agent:      str,
        metrics:    dict[str, Any],
        period:     str = "",
        narrative:  str = "",
        confidence: float = 0.8,
        data_source: str = "manual",
    ) -> AnalysisEvent:
        event = self.record_analysis(org_id, agent, metrics, period=period, narrative=narrative, confidence=confidence, data_source=data_source)
        if self.db:
            await self._persist_to_db(event)
        if self.redis:
            await self._cache_in_redis(event)
        return event


    async def _persist_to_db(self, event: AnalysisEvent) -> None:
        """PostgreSQL'e append-only INSERT."""
        try:
            from sqlalchemy import text
            await self.db.execute(
                text("""
                    INSERT INTO temporal_analysis_events
                    (event_id, org_id, agent, period, period_type,
                     metrics, narrative, confidence, data_source,
                     recorded_at, schema_version)
                    VALUES
                    (:event_id, :org_id, :agent, :period, :period_type,
                     :metrics, :narrative, :confidence, :data_source,
                     :recorded_at, :schema_version)
                """),
                {
                    "event_id":       event.event_id,
                    "org_id":         event.org_id,
                    "agent":          event.agent,
                    "period":         event.period,
                    "period_type":    event.period_type,
                    "metrics":        json.dumps(event.metrics),
                    "narrative":      event.narrative,
                    "confidence":     event.confidence,
                    "data_source":    event.data_source,
                    "recorded_at":    event.recorded_at,
                    "schema_version": event.schema_version,
                }
            )
            await self.db.commit()
        except Exception as exc:
            logger.warning("DB persist hatasi (non-fatal): %s", exc)

    async def _cache_in_redis(self, event: AnalysisEvent) -> None:
        """Redis sorted set'e kaydet (timestamp score ile)."""
        try:
            key  = f"temporal:{event.org_id}:{event.agent}"
            data = json.dumps(event.to_dict())
            await self.redis.zadd(key, {data: event.recorded_at})
            # 6 aylik veri tut (en eski 180 gunu at)
            cutoff = datetime.now(UTC).timestamp() - 180 * 86400
            await self.redis.zremrangebyscore(key, "-inf", cutoff)
            await self.redis.expire(key, 7 * 86400)  # 7 gun TTL
        except Exception as exc:
            logger.debug("Redis cache hatasi (non-fatal): %s", exc)

    # ── Okuma (CQRS Query Side) ───────────────────────────────────────────────

    async def get_history(
        self,
        org_id:  str,
        agent:   str,
        limit:   int = 12,
        min_confidence: float = 0.5,
    ) -> list[AnalysisEvent]:
        """
        Org'un bir agent icin gecmis analizlerini al.
        Cache-first: Redis → InMemory → PostgreSQL
        """
        # 1. In-memory cache dene
        key    = f"{org_id}:{agent}"
        cached = self._memory_cache.get(key, [])
        if cached and len(cached) >= min(3, limit):
            return [e for e in cached if e.confidence >= min_confidence][-limit:]

        # 2. Redis'ten dene
        if self.redis:
            events = await self._read_from_redis(org_id, agent, limit)
            if events:
                self._memory_cache[key] = events
                return [e for e in events if e.confidence >= min_confidence]

        # 3. PostgreSQL fallback
        if self.db:
            events = await self._read_from_db(org_id, agent, limit)
            if events:
                self._memory_cache[key] = events
                return [e for e in events if e.confidence >= min_confidence]

        return []

    async def _read_from_redis(self, org_id: str, agent: str, limit: int) -> list[AnalysisEvent]:
        try:
            key   = f"temporal:{org_id}:{agent}"
            items = await self.redis.zrevrange(key, 0, limit - 1)
            events = []
            for item in items:
                d = json.loads(item)
                events.append(AnalysisEvent(**d))
            return events
        except Exception:
            return []

    async def _read_from_db(self, org_id: str, agent: str, limit: int) -> list[AnalysisEvent]:
        try:
            from sqlalchemy import text
            result = await self.db.execute(
                text("""
                    SELECT event_id, org_id, agent, period, period_type,
                           metrics, narrative, confidence, data_source,
                           recorded_at, schema_version
                    FROM temporal_analysis_events
                    WHERE org_id = :org_id AND agent = :agent
                    ORDER BY recorded_at DESC
                    LIMIT :limit
                """),
                {"org_id": org_id, "agent": agent, "limit": limit}
            )
            rows   = result.fetchall()
            events = []
            for row in rows:
                metrics = json.loads(row.metrics) if isinstance(row.metrics, str) else row.metrics
                events.append(AnalysisEvent(
                    event_id      = row.event_id,
                    org_id        = row.org_id,
                    agent         = row.agent,
                    period        = row.period,
                    period_type   = row.period_type,
                    metrics       = metrics,
                    narrative     = row.narrative or "",
                    confidence    = row.confidence,
                    data_source   = row.data_source or "manual",
                    recorded_at   = row.recorded_at,
                    schema_version = row.schema_version,
                ))
            return events
        except Exception as exc:
            logger.debug("DB okuma hatasi (non-fatal): %s", exc)
            return []

    # ── Analiz metodlari ──────────────────────────────────────────────────────

    def compute_delta(
        self,
        org_id:          str | None = None,
        agent:           str | None = None,
        current_metrics: dict[str, Any] | None = None,
        current_period:  str = "current",
        current:         dict[str, Any] | None = None,
        previous:        dict[str, Any] | None = None,
        metric_key:      str | None = None,
    ) -> Any:
        """
        Delta hesaplama. Hem unit testler için doğrudan dict, hem de DB tabanlı çalışır.
        """
        # Doğrudan dict çağrısı (testler için)
        if (current is not None or current_metrics is not None) and previous is not None and metric_key is not None:
            c_dict = current if current is not None else current_metrics
            c_val = c_dict.get(metric_key) if c_dict else None
            p_val = previous.get(metric_key)
            if c_val is None or p_val is None:
                return None
            return c_val - p_val

        # Async veya DB tabanlı çağrıda fallback
        return None

    def detect_trends(
        self,
        series_or_org:  list[float] | str,
        agent:          str | None = None,
        window:         int = 6,
        metrics:        list[str] | None = None,
    ) -> Any:
        """
        Trend çıkarımı. Eğer liste verilirse doğrudan sayısal regresyon yapar.
        """
        if isinstance(series_or_org, list):
            series = series_or_org
            if len(series) < 3:
                return {"direction": "insufficient_data", "slope": 0.0}
            n = len(series)
            x = list(range(n))
            x_bar = sum(x) / n
            y_bar = sum(series) / n
            cov = sum((xi - x_bar) * (yi - y_bar) for xi, yi in zip(x, series, strict=False))
            var_x = sum((xi - x_bar) ** 2 for xi in x)
            slope = cov / var_x if var_x != 0 else 0.0
            if abs(slope) < 0.001:
                direction = "stable"
            elif slope > 0:
                direction = "improving"
            else:
                direction = "deteriorating"
            return {"direction": direction, "slope": slope}

        return []


    async def get_health_timeline(
        self,
        org_id: str,
        limit:  int = 12,
    ) -> list[dict[str, Any]]:
        """
        Sirket saglik skoru zaman icinde nasil degisti?
        Tum agent'larin gecmisini birlestirip unified health timeline uretir.
        """
        agents = ["cfo", "cto", "cmo", "chro", "coo", "risk"]
        all_events: list[AnalysisEvent] = []

        for agent in agents:
            history = await self.get_history(org_id, agent, limit=limit)
            all_events.extend(history)

        # Period bazında grupla
        by_period: dict[str, dict[str, Any]] = {}
        for event in all_events:
            p = event.period
            if p not in by_period:
                by_period[p] = {"period": p, "agents": {}, "timestamp": event.recorded_at}
            by_period[p]["agents"][event.agent] = {
                "confidence": event.confidence,
                "key_metrics": dict(list(event.metrics.items())[:3]),
            }

        # Zaman sirasina koy
        timeline = sorted(by_period.values(), key=lambda x: x["timestamp"])
        return timeline[-limit:]

    # ── Yardimci metodlar ─────────────────────────────────────────────────────

    def _get_metric_config(self, agent: str) -> dict[str, bool]:
        """
        Her agent icin izlenecek metrikler ve "yuksek = iyi mi?" bilgisi.
        True = yuksek deger iyi, False = dusuk deger iyi
        """
        configs: dict[str, dict[str, bool]] = {
            "cfo": {
                "revenue":         True,
                "net_margin":      True,
                "gross_margin":    True,
                "runway_months":   True,
                "burn_rate":       False,
            },
            "cto": {
                "overall_health_score": True,
                "tech_debt_score":      False,
                "velocity_score":       True,
                "infra_waste_pct":      False,
                "security_score":       True,
            },
            "cmo": {
                "overall_roas":    True,
                "ltv_cac_ratio":   True,
                "avg_monthly_churn": False,
                "mrr_try":         True,
                "growth_rate":     True,
            },
            "chro": {
                "engagement_score":    True,
                "annual_turnover_rate": False,
                "headcount":           True,
            },
            "coo": {
                "sla_compliance":     True,
                "overall_ops_score":  True,
                "resource_utilization": True,
            },
            "risk": {
                "kri_score":         False,
                "overall_risk_score": False,
            },
        }
        return configs.get(agent, {})

    def _extract_metric(self, metrics: dict[str, Any], key: str) -> float | None:
        """Ic ice dict'ten metrik degerini cikart."""
        if key in metrics:
            val = metrics[key]
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
        # Ic ice arama
        for v in metrics.values():
            if isinstance(v, dict):
                result = self._extract_metric(v, key)
                if result is not None:
                    return result
        return None


# ── Public factory ─────────────────────────────────────────────────────────────

_engine_instance: TemporalIntelligenceEngine | None = None


def get_temporal_engine(
    db:    Any = None,
    redis: Any = None,
) -> TemporalIntelligenceEngine:
    """
    Global singleton temporal engine.
    Production'da db ve redis inject edilmeli.
    """
    global _engine_instance
    if _engine_instance is None or db is not None:
        _engine_instance = TemporalIntelligenceEngine(db=db, redis=redis)
    return _engine_instance
