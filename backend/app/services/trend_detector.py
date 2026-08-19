"""
Trend Detector — S5-1 + S5-2

Geçmiş analizlere bakarak trend ve sezonsal pattern tespiti yapar.
AgentMemoryStore'dan geçmiş episode'ları çekerek:

1. Trend tespiti (S5-1):
   - Gelir büyümesi yavaşlıyor mu?
   - Anomali sıklığı artıyor mu?
   - Aynı anomali geçmişte de var mıydı?

2. Sezonsal pattern detection (S5-2):
   - Aralık ayında gelir her zaman yüksek mi?
   - Belirli aylarda gider artışı var mı?
   - Sezonsal düzeltme tavsiyesi üret

Usage:
    detector = TrendDetector(memory_store)
    result = await detector.analyze(
        org_id="org-123",
        current_pnl=pnl,
        current_anomalies=anomalies,
    )
    # result.trend_alerts, result.seasonal_context, result.recurring_anomalies
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Sonuç yapısı ──────────────────────────────────────────────────────────────

@dataclass
class TrendAnalysisResult:
    org_id: str
    trend_alerts: list[dict[str, str]] = field(default_factory=list)
    seasonal_context: dict[str, Any]   = field(default_factory=dict)
    recurring_anomalies: list[dict]    = field(default_factory=list)
    growth_trajectory: str             = "insufficient_data"  # "accelerating"|"stable"|"decelerating"|"declining"
    revenue_trend_summary: str         = ""
    episodes_analyzed: int             = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trend_alerts":        self.trend_alerts,
            "seasonal_context":    self.seasonal_context,
            "recurring_anomalies": self.recurring_anomalies,
            "growth_trajectory":   self.growth_trajectory,
            "revenue_trend_summary": self.revenue_trend_summary,
            "episodes_analyzed":   self.episodes_analyzed,
        }


# ── TrendDetector ─────────────────────────────────────────────────────────────

class TrendDetector:
    """
    Geçmiş analizleri kullanarak trend ve sezonsal pattern tespit eder.

    Memory store'dan son N episode'u çeker, şimdiki dönemle karşılaştırır.
    Sonuçlar CFO agent narrative'ine inject edilir.
    """

    def __init__(self, memory_store: Any = None) -> None:
        self.memory_store = memory_store

    async def analyze(
        self,
        org_id: str,
        current_pnl: dict[str, Any] | None = None,
        current_anomalies: list[dict] | None = None,
        current_period: str = "",
        top_k: int = 6,
    ) -> TrendAnalysisResult:
        """
        Trend analizi yap.

        Parameters
        ----------
        org_id : str
        current_pnl : dict
            Şimdiki dönem P&L sonucu.
        current_anomalies : list
            Şimdiki dönem tespit edilen anomaliler.
        current_period : str
            Şimdiki dönem (ör. "2024-12").
        top_k : int
            Kaç geçmiş episode'u analiz edeceğiz.
        """
        result = TrendAnalysisResult(org_id=org_id)

        if not self.memory_store:
            result.revenue_trend_summary = "Hafıza modülü bağlı değil — trend analizi mevcut değil"
            return result

        try:
            past_episodes = await self.memory_store.retrieve(
                org_id=org_id,
                agent="pnl_agent",
                top_k=top_k,
            )
        except Exception as exc:
            logger.debug("Memory retrieve failed: %s", exc)
            return result

        if not past_episodes:
            result.revenue_trend_summary = "Önceki analiz bulunamadı — karşılaştırma için yeterli veri yok"
            return result

        result.episodes_analyzed = len(past_episodes)

        # ── S5-1: Revenue trend analizi ────────────────────────────────────────
        revenues = []
        margins  = []
        for ep in past_episodes:
            s = ep.summary or {}
            if s.get("revenue") is not None:
                revenues.append(int(s["revenue"]))
            if s.get("net_margin") is not None:
                margins.append(float(s["net_margin"]))

        if current_pnl and current_pnl.get("revenue"):
            revenues.append(int(current_pnl["revenue"]))
        if current_pnl and current_pnl.get("net_margin") is not None:
            margins.append(float(current_pnl["net_margin"]))

        if len(revenues) >= 3:
            result.growth_trajectory = _classify_trajectory(revenues)
            last = revenues[-1]
            prev = revenues[-2]
            change_pct = (last - prev) / abs(prev) * 100 if prev else 0

            result.revenue_trend_summary = (
                f"Son {len(revenues)} dönem incelendi. "
                f"Gelir trendi: {result.growth_trajectory}. "
                f"Son dönem değişimi: {change_pct:+.1f}%."
            )

            # Trend uyarıları
            if result.growth_trajectory == "declining" and change_pct < -10:
                result.trend_alerts.append({
                    "level":   "critical",
                    "message": f"Gelir {len(revenues)} dönemdir düşüş trendinde. "
                               f"Son dönem: {change_pct:+.1f}%.",
                })
            elif result.growth_trajectory == "decelerating":
                result.trend_alerts.append({
                    "level":   "warning",
                    "message": f"Gelir büyümesi yavaşlıyor ({len(revenues)} dönem analizi).",
                })

        # Margin trend
        if len(margins) >= 3:
            margin_trend = _classify_trajectory(margins)
            if margin_trend == "declining" and margins[-1] < 0.10:
                result.trend_alerts.append({
                    "level":   "warning",
                    "message": f"Net kâr marjı son dönemde %{margins[-1]*100:.1f} — azalış trendinde.",
                })

        # ── S5-2: Sezonsal pattern detection ──────────────────────────────────
        monthly_by_month: dict[int, list[float]] = {}
        for ep in past_episodes:
            period_str = ep.period or ""
            rev = (ep.summary or {}).get("revenue")
            if rev is not None and len(period_str) >= 7:
                try:
                    month_num = int(period_str[5:7])
                    monthly_by_month.setdefault(month_num, []).append(float(rev))
                except (ValueError, IndexError):
                    pass

        if len(monthly_by_month) >= 3:
            # Ortalama her ay için
            month_avgs = {m: statistics.mean(vals) for m, vals in monthly_by_month.items()}
            overall_avg = statistics.mean(month_avgs.values())

            seasonal_indices = {
                m: round(avg / overall_avg, 2) if overall_avg > 0 else 1.0
                for m, avg in month_avgs.items()
            }

            peak_month = max(month_avgs, key=lambda m: month_avgs[m])
            trough_month = min(month_avgs, key=lambda m: month_avgs[m])

            result.seasonal_context = {
                "seasonal_indices": seasonal_indices,
                "peak_month":       peak_month,
                "trough_month":     trough_month,
                "peak_multiplier":  seasonal_indices.get(peak_month, 1.0),
                "trough_multiplier": seasonal_indices.get(trough_month, 1.0),
                "note": (
                    f"Ay {peak_month} en yüksek ({seasonal_indices.get(peak_month, 1):.1f}x ortalama), "
                    f"Ay {trough_month} en düşük ({seasonal_indices.get(trough_month, 1):.1f}x ortalama)."
                ),
            }

        # ── S5-2: Tekrarlayan anomali tespiti ─────────────────────────────────
        if current_anomalies:
            past_anomaly_types: dict[str, int] = {}
            for ep in past_episodes:
                for a in (ep.summary or {}).get("anomalies", []):
                    atype = a.get("anomaly_type", "unknown")
                    past_anomaly_types[atype] = past_anomaly_types.get(atype, 0) + 1

            for anomaly in current_anomalies:
                atype = anomaly.get("anomaly_type", "")
                if past_anomaly_types.get(atype, 0) >= 2:
                    result.recurring_anomalies.append({
                        "anomaly_type":   atype,
                        "current":        anomaly,
                        "past_count":     past_anomaly_types[atype],
                        "warning":        f"Bu anomali türü geçmişte {past_anomaly_types[atype]} kez de görüldü — trend olabilir.",
                    })

        return result


def _classify_trajectory(values: list[float]) -> str:
    """
    Bir değer serisinin büyüme yörüngesini sınıflandır.
    En az 3 değer gerekir.
    """
    if len(values) < 3:
        return "insufficient_data"

    # Son 3 değer arasındaki MoM büyüme oranları
    growths = [
        (values[i] - values[i - 1]) / abs(values[i - 1])
        for i in range(1, len(values))
        if values[i - 1] != 0
    ]
    if not growths:
        return "stable"

    avg_growth = statistics.mean(growths)
    recent_growth = statistics.mean(growths[-2:]) if len(growths) >= 2 else growths[-1]

    if avg_growth < -0.05:
        return "declining"
    if recent_growth < avg_growth - 0.03:
        return "decelerating"
    if avg_growth > 0.05 and recent_growth >= avg_growth:
        return "accelerating"
    return "stable"


# ── Convenience function ──────────────────────────────────────────────────────

async def run_trend_analysis(
    org_id: str,
    current_pnl: dict[str, Any] | None = None,
    current_anomalies: list[dict] | None = None,
    current_period: str = "",
    db: Any = None,
) -> dict[str, Any]:
    """
    Convenience wrapper — worker ve pipeline entegrasyonu için.

    Memory store'u otomatik oluşturur, trend analizi çalıştırır.
    """
    try:
        from app.services.agent_memory import AgentMemoryStore
        store = AgentMemoryStore(backend="sqlite")
    except Exception as exc:
        logger.debug("AgentMemoryStore init failed: %s", exc)
        return {}

    detector = TrendDetector(memory_store=store)
    result = await detector.analyze(
        org_id=org_id,
        current_pnl=current_pnl,
        current_anomalies=current_anomalies,
        current_period=current_period,
    )
    return result.to_dict()
