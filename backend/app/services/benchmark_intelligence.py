"""
Benchmark Intelligence Service

Sirketin metriklerini sektör ortalamalarıyla karşılaştırır.
"Sizin ROAS 2.1x, SaaS sektör ortalaması 2.8x — %25 geride" gibi
benchmark commentary üretir.

Sektör verileri:
  - Türkiye SaaS (2024 benchmark datası)
  - Türkiye KOBİ (50-500 çalışan)
  - E-ticaret Türkiye
  - Genel hizmet sektörü

DDIA: benchmark verileri "reference data" — nadiren değişir,
static dict'te tutmak uygundur. Dış API bağımlılığı yok.

Kullanım:
    svc = BenchmarkIntelligenceService()
    result = svc.compare_cfo(pnl_data, sector="saas")
    # result.items[0].metric = "Net Kâr Marjı"
    # result.items[0].company_value = 0.12
    # result.items[0].benchmark_p50 = 0.15
    # result.items[0].percentile = 40
    # result.items[0].verdict = "Sektörün biraz gerisinde"
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Sektör benchmark veritabanı ───────────────────────────────────────────────
# Kaynak: Türkiye SaaS raporu 2024, KOSGEB KOBİ benchmarks, sektör anketleri
# P25/P50/P75 = yüzdelik dilimler

BENCHMARKS: dict[str, dict[str, dict[str, float]]] = {

    # ── CFO / Finansal ─────────────────────────────────────────────────────────
    "saas_net_margin": {
        "p25": -0.05, "p50": 0.08, "p75": 0.22,
        "label": "Net Kâr Marjı", "unit": "%", "higher_is_better": True,
        "context": "Türkiye SaaS şirketleri 2024",
    },
    "saas_gross_margin": {
        "p25": 0.55, "p50": 0.68, "p75": 0.80,
        "label": "Brüt Kâr Marjı", "unit": "%", "higher_is_better": True,
        "context": "Türkiye SaaS şirketleri 2024",
    },
    "saas_revenue_growth": {
        "p25": 0.10, "p50": 0.25, "p75": 0.55,
        "label": "Yıllık Gelir Büyümesi", "unit": "%", "higher_is_better": True,
        "context": "Türkiye SaaS şirketleri 2024",
    },
    "saas_runway_months": {
        "p25": 6.0, "p50": 12.0, "p75": 24.0,
        "label": "Nakit Ömrü", "unit": "ay", "higher_is_better": True,
        "context": "Türkiye startup/SaaS 2024",
    },

    # ── CMO / Pazarlama ────────────────────────────────────────────────────────
    "saas_roas": {
        "p25": 1.5, "p50": 2.5, "p75": 4.0,
        "label": "Pazarlama ROAS", "unit": "x", "higher_is_better": True,
        "context": "Türkiye dijital pazarlama 2024",
    },
    "saas_cac_months": {
        "p25": 8, "p50": 12, "p75": 20,
        "label": "CAC Geri Dönüş Süresi", "unit": "ay", "higher_is_better": False,
        "context": "Türkiye SaaS ortalama CAC payback",
    },
    "saas_monthly_churn": {
        "p25": 0.01, "p50": 0.025, "p75": 0.05,
        "label": "Aylık Churn Oranı", "unit": "%", "higher_is_better": False,
        "context": "Türkiye B2B SaaS 2024",
    },
    "saas_ltv_cac": {
        "p25": 2.0, "p50": 3.5, "p75": 6.0,
        "label": "LTV/CAC Oranı", "unit": "x", "higher_is_better": True,
        "context": "Türkiye SaaS 2024",
    },

    # ── CTO / Teknoloji ────────────────────────────────────────────────────────
    "saas_tech_spend_pct": {
        "p25": 0.10, "p50": 0.18, "p75": 0.28,
        "label": "Teknoloji Harcaması (Gelirin %)", "unit": "%", "higher_is_better": None,
        "context": "SaaS şirketleri teknoloji bütçesi",
    },
    "saas_infra_waste_pct": {
        "p25": 0.10, "p50": 0.18, "p75": 0.30,
        "label": "Altyapı İsraf Oranı", "unit": "%", "higher_is_better": False,
        "context": "Cloud maliyet optimizasyonu benchmark",
    },
    "saas_deploy_freq_weekly": {
        "p25": 1, "p50": 3, "p75": 10,
        "label": "Haftalık Deployment Sıklığı", "unit": "kez", "higher_is_better": True,
        "context": "SaaS mühendislik olgunluğu",
    },

    # ── CHRO / İnsan Kaynakları ────────────────────────────────────────────────
    "turkey_turnover_rate": {
        "p25": 0.12, "p50": 0.18, "p75": 0.28,
        "label": "Yıllık Personel Devir Hızı", "unit": "%", "higher_is_better": False,
        "context": "Türkiye teknoloji sektörü 2024",
    },
    "turkey_engagement_score": {
        "p25": 55, "p50": 65, "p75": 78,
        "label": "Çalışan Bağlılık Skoru", "unit": "puan", "higher_is_better": True,
        "context": "Türkiye kurumsal çalışan anketi 2024",
    },
    "turkey_revenue_per_employee": {
        "p25": 400_000, "p50": 750_000, "p75": 1_500_000,
        "label": "Çalışan Başına Yıllık Gelir", "unit": "TRY", "higher_is_better": True,
        "context": "Türkiye teknoloji şirketleri 2024",
    },

    # ── COO / Operasyon ────────────────────────────────────────────────────────
    "saas_sla_compliance": {
        "p25": 0.92, "p50": 0.97, "p75": 0.995,
        "label": "SLA Uyum Oranı", "unit": "%", "higher_is_better": True,
        "context": "B2B SaaS müşteri hizmetleri",
    },
    "saas_p1_resolution_h": {
        "p25": 2, "p50": 4, "p75": 8,
        "label": "P1 Incident Çözüm Süresi", "unit": "saat", "higher_is_better": False,
        "context": "SaaS operasyonel olgunluk",
    },

    # ── Risk ───────────────────────────────────────────────────────────────────
    "kri_score_healthy": {
        "p25": 1.0, "p50": 2.5, "p75": 4.5,
        "label": "KRI Risk Skoru", "unit": "/10", "higher_is_better": False,
        "context": "Kurumsal risk yönetimi benchmark",
    },
}


# ── Veri modelleri ────────────────────────────────────────────────────────────

@dataclass
class BenchmarkItem:
    """Tek bir metriğin benchmark karşılaştırması."""
    metric:          str
    label:           str
    company_value:   float
    benchmark_p25:   float
    benchmark_p50:   float
    benchmark_p75:   float
    percentile:      int          # şirketin tahmini yüzdelik dilimi (0-100)
    verdict:         str          # "Sektör lideri" | "Ortalamanın üstünde" | ...
    gap_to_median:   float        # medyandan fark (oransal)
    unit:            str
    higher_is_better: bool | None
    context:         str


@dataclass
class BenchmarkReport:
    """Tam benchmark raporu."""
    sector:       str
    company_name: str
    items:        list[BenchmarkItem]
    overall_score: float        # 0-100 (kaç metrikttte sektör ortalamasının üstünde)
    strengths:    list[str]     # iyi olan metrikler
    gaps:         list[str]     # geride kalınan metrikler
    summary:      str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sector":        self.sector,
            "company_name":  self.company_name,
            "overall_score": self.overall_score,
            "strengths":     self.strengths,
            "gaps":          self.gaps,
            "summary":       self.summary,
            "items": [
                {
                    "metric":           i.metric,
                    "label":            i.label,
                    "company_value":    i.company_value,
                    "benchmark_p50":    i.benchmark_p50,
                    "benchmark_p25":    i.benchmark_p25,
                    "benchmark_p75":    i.benchmark_p75,
                    "percentile":       i.percentile,
                    "verdict":          i.verdict,
                    "gap_to_median":    round(i.gap_to_median, 3),
                    "unit":             i.unit,
                    "higher_is_better": i.higher_is_better,
                    "context":          i.context,
                }
                for i in self.items
            ],
        }


# ── Benchmark Intelligence Service ───────────────────────────────────────────

class BenchmarkIntelligenceService:
    """
    Şirket metriklerini sektör benchmark'larıyla karşılaştırır.

    Desteklenen karşılaştırmalar:
      compare_cfo()   — Finansal metrikler
      compare_cmo()   — Pazarlama metrikleri
      compare_cto()   — Teknoloji metrikleri
      compare_chro()  — İK metrikleri
      compare_coo()   — Operasyon metrikleri
      compare_all()   — Tüm metrikler (cross-domain)
    """

    def _compute_percentile(
        self,
        value: float,
        p25: float,
        p50: float,
        p75: float,
        higher_is_better: bool | None,
    ) -> int:
        """Şirket değerinin tahmini yüzdelik dilimini hesapla."""
        if higher_is_better is None:
            return 50  # Nötr metrik

        # Doğrusal interpolasyon
        if higher_is_better:
            if value >= p75:
                return min(95, 75 + int((value - p75) / max(p75 - p50, 0.001) * 20))
            elif value >= p50:
                return 50 + int((value - p50) / max(p75 - p50, 0.001) * 25)
            elif value >= p25:
                return 25 + int((value - p25) / max(p50 - p25, 0.001) * 25)
            else:
                return max(5, 25 - int((p25 - value) / max(p25, 0.001) * 20))
        else:
            # Düşük değer iyi — ters mantık
            if value <= p25:
                return min(95, 75 + int((p25 - value) / max(p25, 0.001) * 20))
            elif value <= p50:
                return 50 + int((p50 - value) / max(p50 - p25, 0.001) * 25)
            elif value <= p75:
                return 25 + int((p75 - value) / max(p75 - p50, 0.001) * 25)
            else:
                return max(5, 25 - int((value - p75) / max(p75, 0.001) * 20))

    def _compute_verdict(self, percentile: int) -> str:
        if percentile >= 80:  return "Sektör lideri"
        if percentile >= 60:  return "Ortalamanın üstünde"
        if percentile >= 40:  return "Sektör ortalamasında"
        if percentile >= 20:  return "Ortalamanın altında"
        return "Geliştirilmesi gerekiyor"

    def _compare_metric(
        self,
        metric_key:    str,
        company_value: float,
    ) -> BenchmarkItem | None:
        bm = BENCHMARKS.get(metric_key)
        if bm is None:
            return None

        higher = bm.get("higher_is_better")
        p50    = bm["p50"]
        gap    = (company_value - p50) / max(abs(p50), 0.001)

        percentile = self._compute_percentile(
            company_value, bm["p25"], p50, bm["p75"], higher
        )
        verdict = self._compute_verdict(percentile)

        return BenchmarkItem(
            metric          = metric_key,
            label           = bm["label"],
            company_value   = company_value,
            benchmark_p25   = bm["p25"],
            benchmark_p50   = p50,
            benchmark_p75   = bm["p75"],
            percentile      = percentile,
            verdict         = verdict,
            gap_to_median   = round(gap, 3),
            unit            = bm.get("unit", ""),
            higher_is_better = higher,
            context         = bm.get("context", ""),
        )

    def compare_cfo(
        self,
        pnl:      dict[str, Any],
        cashflow: dict[str, Any] | None = None,
        forecast: dict[str, Any] | None = None,
        sector:   str = "saas",
        company_name: str = "Şirket",
    ) -> BenchmarkReport:
        items = []
        monthly_rev = (pnl.get("revenue", 0) or 0) / 100 / 12

        # Net marj
        if (nm := pnl.get("net_margin")) is not None:
            item = self._compare_metric("saas_net_margin", nm)
            if item: items.append(item)

        # Brüt marj
        if (gm := pnl.get("gross_margin")) is not None:
            item = self._compare_metric("saas_gross_margin", gm)
            if item: items.append(item)

        # Gelir büyümesi
        if (rg := pnl.get("revenue_growth_pct")) is not None:
            item = self._compare_metric("saas_revenue_growth", rg)
            if item: items.append(item)

        # Nakit ömrü
        base_sc = ((forecast or {}).get("scenarios") or {}).get("base") or {}
        if (rwm := base_sc.get("runway_months")) is not None:
            item = self._compare_metric("saas_runway_months", rwm)
            if item: items.append(item)

        return self._build_report(items, sector, company_name)

    def compare_cmo(
        self,
        cmo_data:    dict[str, Any],
        sector:      str = "saas",
        company_name: str = "Şirket",
    ) -> BenchmarkReport:
        items = []

        if (roas := cmo_data.get("overall_roas")) is not None:
            item = self._compare_metric("saas_roas", roas)
            if item: items.append(item)

        if (churn := cmo_data.get("avg_monthly_churn")) is not None:
            item = self._compare_metric("saas_monthly_churn", churn)
            if item: items.append(item)

        if (ltv_cac := cmo_data.get("ltv_cac_ratio")) is not None:
            item = self._compare_metric("saas_ltv_cac", ltv_cac)
            if item: items.append(item)

        return self._build_report(items, sector, company_name)

    def compare_chro(
        self,
        chro_data:   dict[str, Any],
        monthly_rev: float = 0,
        sector:      str = "saas",
        company_name: str = "Şirket",
    ) -> BenchmarkReport:
        items = []

        if (tr := chro_data.get("annual_turnover_rate")) is not None:
            item = self._compare_metric("turkey_turnover_rate", tr)
            if item: items.append(item)

        if (eng := chro_data.get("engagement_score")) is not None:
            item = self._compare_metric("turkey_engagement_score", eng)
            if item: items.append(item)

        hc = chro_data.get("total_headcount", 0) or 1
        if monthly_rev > 0 and hc > 0:
            rpe = monthly_rev * 12 / hc
            item = self._compare_metric("turkey_revenue_per_employee", rpe)
            if item: items.append(item)

        return self._build_report(items, sector, company_name)

    def compare_coo(
        self,
        coo_data:    dict[str, Any],
        sector:      str = "saas",
        company_name: str = "Şirket",
    ) -> BenchmarkReport:
        items = []

        if (sla := coo_data.get("sla_compliance")) is not None:
            item = self._compare_metric("saas_sla_compliance", sla)
            if item: items.append(item)

        return self._build_report(items, sector, company_name)

    def compare_all(
        self,
        pnl:         dict[str, Any] | None = None,
        cashflow:    dict[str, Any] | None = None,
        forecast:    dict[str, Any] | None = None,
        cmo_data:    dict[str, Any] | None = None,
        chro_data:   dict[str, Any] | None = None,
        coo_data:    dict[str, Any] | None = None,
        cto_data:    dict[str, Any] | None = None,
        sector:      str = "saas",
        company_name: str = "Şirket",
    ) -> BenchmarkReport:
        """Tüm domain'leri karşılaştır."""
        all_items: list[BenchmarkItem] = []
        monthly_rev = ((pnl or {}).get("revenue", 0) or 0) / 100 / 12

        if pnl:
            r = self.compare_cfo(pnl, cashflow, forecast, sector, company_name)
            all_items.extend(r.items)
        if cmo_data:
            r = self.compare_cmo(cmo_data, sector, company_name)
            all_items.extend(r.items)
        if chro_data:
            r = self.compare_chro(chro_data, monthly_rev, sector, company_name)
            all_items.extend(r.items)
        if coo_data:
            r = self.compare_coo(coo_data, sector, company_name)
            all_items.extend(r.items)

        return self._build_report(all_items, sector, company_name)

    def _build_report(
        self,
        items:        list[BenchmarkItem],
        sector:       str,
        company_name: str,
    ) -> BenchmarkReport:
        if not items:
            return BenchmarkReport(
                sector=sector, company_name=company_name, items=[],
                overall_score=50.0, strengths=[], gaps=[],
                summary="Karşılaştırma için yeterli veri yok.",
            )

        avg_pct    = sum(i.percentile for i in items) / len(items)
        strengths  = [i.label for i in items if i.percentile >= 65]
        gaps       = [i.label for i in items if i.percentile <= 35]

        if avg_pct >= 70:
            summary = f"{company_name} {sector.upper()} sektöründe üst çeyrekte yer alıyor."
        elif avg_pct >= 50:
            summary = f"{company_name} sektör ortalamasının üstünde, gelişim alanları mevcut."
        elif avg_pct >= 30:
            summary = f"{company_name} sektör ortalamasının altında, kritik alanlarda iyileştirme gerekiyor."
        else:
            summary = f"{company_name} sektörün gerisinde, acil aksiyon planı hazırlanmalı."

        if gaps:
            summary += f" Öncelikli gelişim alanları: {', '.join(gaps[:3])}."

        return BenchmarkReport(
            sector=sector, company_name=company_name, items=items,
            overall_score=round(avg_pct, 1),
            strengths=strengths, gaps=gaps, summary=summary,
        )


# ── Public factory ─────────────────────────────────────────────────────────────

def get_benchmark_service() -> BenchmarkIntelligenceService:
    return BenchmarkIntelligenceService()
