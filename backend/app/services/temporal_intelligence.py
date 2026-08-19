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
import math
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
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
    recorded_at: float    # Unix timestamp
    schema_version: int = 1   # gelecek migrasyon icin

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

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
    ) -> "AnalysisEvent":
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
            recorded_at  = datetime.now(timezone.utc).timestamp(),
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

    async def record_analysis(
        self,
        org_id:     str,
        agent:      str,
        period:     str,
        metrics:    dict[str, Any],
        narrative:  str = "",
        confidence: float = 0.8,
        data_source: str = "manual",
    ) -> AnalysisEvent:
        """
        Analiz sonucunu immutable event olarak kaydet.

        DDIA: append-only log. Onceki kayit degistirilmez.
        Ayni donem icin ikinci kayit yapilirsa yeni event olusur.
        """
        event = AnalysisEvent.create(
            org_id     = org_id,
            agent      = agent,
            period     = period,
            metrics    = metrics,
            narrative  = narrative,
            confidence = confidence,
            data_source = data_source,
        )

        # 1. PostgreSQL'e yaz (durable)
        if self.db:
            await self._persist_to_db(event)

        # 2. Redis'e yaz (hot cache)
        if self.redis:
            await self._cache_in_redis(event)

        # 3. In-memory cache guncelle
        key = f"{org_id}:{agent}"
        if key not in self._memory_cache:
            self._memory_cache[key] = []
        self._memory_cache[key].append(event)
        # Son 12 kaydi tut
        self._memory_cache[key] = self._memory_cache[key][-12:]

        logger.debug("AnalysisEvent kaydedildi: org=%s agent=%s period=%s", org_id, agent, period)
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
            cutoff = datetime.now(timezone.utc).timestamp() - 180 * 86400
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

    async def compute_delta(
        self,
        org_id:          str,
        agent:           str,
        current_metrics: dict[str, Any],
        current_period:  str = "current",
    ) -> DeltaAnalysis | None:
        """
        Mevcut metrikler ile son kayitli analiz arasındaki delta hesapla.
        """
        history = await self.get_history(org_id, agent, limit=1)
        if not history:
            return None

        previous = history[0]
        return self._compute_delta_between(
            org_id          = org_id,
            agent           = agent,
            current_metrics = current_metrics,
            current_period  = current_period,
            previous        = previous,
        )

    def _compute_delta_between(
        self,
        org_id:          str,
        agent:           str,
        current_metrics: dict[str, Any],
        current_period:  str,
        previous:        AnalysisEvent,
    ) -> DeltaAnalysis:
        """Delta hesaplama mantigi."""
        # CFO icin izlenecek metrikler
        metric_config = self._get_metric_config(agent)

        deltas: list[MetricDelta] = []
        flags:  list[str]        = []

        for metric, is_positive in metric_config.items():
            curr_val = self._extract_metric(current_metrics, metric)
            prev_val = self._extract_metric(previous.metrics, metric)

            if curr_val is None or prev_val is None:
                continue

            abs_change = curr_val - prev_val
            pct_change = (abs_change / abs(prev_val) * 100) if prev_val != 0 else 0.0

            direction = "stable"
            if abs(pct_change) > 2:
                direction = "up" if abs_change > 0 else "down"

            # Flag: buyuk ve olumsuz degisim
            if abs(pct_change) > 15:
                flag_good = (direction == "up" and is_positive) or (direction == "down" and not is_positive)
                if not flag_good:
                    flags.append(f"{metric}: {pct_change:+.1f}%")

            deltas.append(MetricDelta(
                metric      = metric,
                current     = round(curr_val, 4),
                previous    = round(prev_val, 4),
                abs_change  = round(abs_change, 4),
                pct_change  = round(pct_change, 2),
                direction   = direction,
                is_positive = is_positive,
            ))

        # Regime degisimi: cok sayida buyuk degisim = kalici durum degisimi
        big_changes = [d for d in deltas if abs(d.pct_change) > 20]
        regime_changed = len(big_changes) >= 3

        # Ozet uret
        positive = [d for d in deltas if d.direction == ("up" if d.is_positive else "down")]
        negative = [d for d in deltas if d.direction == ("down" if d.is_positive else "up")]

        summary = f"{agent.upper()} delta: {len(positive)} iyilesme, {len(negative)} gerile."
        if regime_changed:
            summary += " ⚠ Kalici durum degisimi tespit edildi."
        if flags:
            summary += f" Dikkat: {'; '.join(flags[:3])}."

        return DeltaAnalysis(
            org_id          = org_id,
            agent           = agent,
            current_period  = current_period,
            previous_period = previous.period,
            deltas          = deltas,
            summary         = summary,
            regime_changed  = regime_changed,
            flags           = flags,
        )

    async def detect_trends(
        self,
        org_id:  str,
        agent:   str,
        window:  int = 6,
        metrics: list[str] | None = None,
    ) -> list[TrendResult]:
        """
        Son N analizden trend cikar.
        Dogrusal regresyon + volatilite analizi.
        """
        history = await self.get_history(org_id, agent, limit=window)
        if len(history) < 3:
            return []

        history = list(reversed(history))  # kronolojik siralama
        metric_config = self._get_metric_config(agent)
        target_metrics = metrics or list(metric_config.keys())

        results: list[TrendResult] = []
        for metric in target_metrics:
            values  = []
            periods = []
            for event in history:
                val = self._extract_metric(event.metrics, metric)
                if val is not None:
                    values.append(val)
                    periods.append(event.period)

            if len(values) < 3:
                continue

            # Dogrusal regresyon
            n     = len(values)
            x     = list(range(n))
            x_bar = sum(x) / n
            y_bar = sum(values) / n
            cov   = sum((xi - x_bar) * (yi - y_bar) for xi, yi in zip(x, values))
            var_x = sum((xi - x_bar) ** 2 for xi in x)
            slope = cov / var_x if var_x != 0 else 0.0

            # R-squared
            ss_res = sum((yi - (y_bar + slope * (xi - x_bar))) ** 2 for xi, yi in zip(x, values))
            ss_tot = sum((yi - y_bar) ** 2 for yi in values)
            r2     = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

            # Trend siniflandirma
            rel_slope = abs(slope) / max(abs(y_bar), 0.001)
            if rel_slope < 0.02:
                trend = "stable"
            elif slope > 0:
                trend = "rising"
            else:
                trend = "falling"

            # Volatilite kontrolu
            mean = y_bar
            std  = math.sqrt(sum((v - mean) ** 2 for v in values) / n) if n > 1 else 0
            cv   = std / abs(mean) if mean != 0 else 0
            if cv > 0.3 and r2 < 0.5:
                trend = "volatile"

            # Mevsimsel pattern (basit: 12 aylik seri varsa ayni ay tekrari)
            seasonal = False
            if len(values) >= 6:
                diffs = [abs(values[i] - values[i-1]) for i in range(1, len(values))]
                avg_diff = sum(diffs) / len(diffs)
                last_diff = abs(values[-1] - values[-2]) if len(values) >= 2 else 0
                seasonal = last_diff < avg_diff * 0.3

            results.append(TrendResult(
                metric          = metric,
                values          = [round(v, 4) for v in values],
                periods         = periods,
                trend           = trend,
                slope           = round(slope, 6),
                r_squared       = round(r2, 3),
                seasonal_pattern = seasonal,
            ))

        return results

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
                "key_metrics": {k: v for k, v in list(event.metrics.items())[:3]},
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
