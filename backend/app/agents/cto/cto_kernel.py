"""
CTO Kernel -- Otomatik CTO Veri Uretimi

CFO verisi, CompanyContext ve sektör benchmark'larindan
CTO pipeline'ina beslenecek otomatik input uretir.

Veri onceligi:
  1. Dogrudan gecilen CTO verisi (cloud_billing_csv, git_log_text, ...)
  2. CFO opex verisi -> tech butce tahmini
  3. Sektör benchmark (SaaS: tech spend %15-25 of revenue)
  4. Headcount'tan muhendis sayisi tahmini

Cikti (CTOState-uyumlu):
  - cloud_billing_csv: sintetik CSV (tahmini cloud maliyetler)
  - git_log_text: bos ama pipeline calisabilir
  - tech_summary: hazir özet (pipeline'i bypass eder)
  - overall_health_score, tech_debt_score, infra_waste_pct, velocity_trend
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


# ── Sektör benchmark sabitleri ────────────────────────────────────────────────

# SaaS şirketleri için tipik oranlar
BENCHMARKS = {
    "tech_spend_pct_revenue":  0.18,   # gelirin %18'i tech harcama
    "cloud_pct_tech_spend":    0.35,   # tech harcamanin %35'i cloud
    "eng_pct_headcount":       0.30,   # toplam personetin %30'u muhendis
    "mttr_hours_p50":          4.0,    # medyan MTTR (saat)
    "sprint_velocity_p50":     35.0,   # medyan sprint velocity (story point)
    "tech_debt_healthy":       3.5,    # saglikli tech debt skoru (10 uzerinden)
    "infra_waste_pct":         0.15,   # tipik altyapi israf orani
    "deploy_freq_weekly":      3.0,    # haftalik deployment sayisi
    "lead_time_days_p50":      5.0,    # medyan lead time (gun)
}


@dataclass
class CTOKernelOutput:
    """CTO Kernel'in urettigi senkronize cikti."""

    # Genel saglik metrikleri
    overall_health_score:  float        # 0-10
    tech_debt_score:       float        # 0-10 (yuksek = kotu)
    infra_waste_pct:       float        # 0-1
    velocity_trend:        str          # improving | stable | deteriorating

    # Altyapi
    monthly_infra_cost_try: float       # TRY
    infra_waste_try:        float       # TRY
    cloud_pct_total:        float       # cloud'un toplam tech harcamadaki orani

    # Gelistirme verimliligi
    estimated_engineers:   int
    sprint_velocity_score: float        # 0-10
    deploy_frequency:      float        # haftalik
    lead_time_days:        float

    # Guvenlik & teknik borc
    security_score:        float        # 0-10
    open_vulnerabilities:  int

    # Maliyet tahminleri
    monthly_tech_budget_try: float
    annual_tech_budget_try:  float

    # Veri kaynagi
    data_source:     str    # "real" | "estimated" | "benchmark"
    confidence:      float  # 0-1

    # Sentetik CSV (pipeline icin)
    cloud_billing_csv: str | None = None
    narrative:         str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}

    def to_cto_state_patch(self) -> dict[str, Any]:
        """CTOState'e dogrudan patch olarak uygulanabilir dict."""
        return {
            "overall_health_score": self.overall_health_score,
            "tech_debt_score":      self.tech_debt_score,
            "infra_waste_pct":      self.infra_waste_pct,
            "velocity_trend":       self.velocity_trend,
            "avg_mttr_hours":       4.0 if self.velocity_trend == "stable" else
                                    6.0 if self.velocity_trend == "deteriorating" else 2.5,
        }


class CTOKernel:
    """
    CTO Kernel -- Otomatik CTO metrikleri uretir.

    Kullanim:
        kernel = CTOKernel(
            pnl=cfo_result["pnl"],
            cashflow=cfo_result["cashflow"],
            chro_data=chro_result,      # opsiyonel
            existing_cto_data=cto_data, # opsiyonel -- varsa kullan
        )
        output = kernel.generate()
        cto_state.update(output.to_cto_state_patch())
    """

    def __init__(
        self,
        pnl:              dict[str, Any] | None = None,
        cashflow:         dict[str, Any] | None = None,
        forecast:         dict[str, Any] | None = None,
        chro_data:        dict[str, Any] | None = None,
        existing_cto_data: dict[str, Any] | None = None,
        company_size:     str = "startup",  # startup | smb | enterprise
    ) -> None:
        self.pnl       = pnl or {}
        self.cashflow  = cashflow or {}
        self.forecast  = forecast or {}
        self.chro_data = chro_data or {}
        self.existing  = existing_cto_data or {}
        self.size      = company_size

        # Temel finansal metrikler
        self.monthly_revenue = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.monthly_opex    = (self.pnl.get("total_opex", 0) or 0) / 100 / 12
        self.headcount       = self.chro_data.get("total_headcount", 0) or 0

        # Size multiplier (tech spend orani)
        self.tech_spend_pct = {
            "startup":    0.22,
            "smb":        0.18,
            "enterprise": 0.12,
        }.get(self.size, 0.18)

    def _estimate_engineers(self) -> int:
        """Headcount'tan muhendis sayisi tahmini."""
        if self.headcount:
            return max(1, round(self.headcount * BENCHMARKS["eng_pct_headcount"]))
        if self.monthly_revenue > 0:
            # Gelire gore kaba tahmin: her 500K TRY gelir icin 1 muhendis
            return max(1, round(self.monthly_revenue / 500_000))
        return 5  # minimum fallback

    def _estimate_tech_budget(self) -> float:
        """Aylik tech butcesi tahmini (TRY)."""
        if self.monthly_opex > 0:
            return self.monthly_opex * self.tech_spend_pct
        if self.monthly_revenue > 0:
            return self.monthly_revenue * BENCHMARKS["tech_spend_pct_revenue"]
        return 50_000  # minimum fallback

    def _compute_health_score(self) -> float:
        """
        Genel teknoloji saglik skoru (0-10, yuksek = iyi).
        Mevcut CTO verisi varsa onu kullan, yoksa CFO'dan tahmin et.
        """
        # Mevcut veri varsa kullan
        if self.existing.get("overall_health_score"):
            return float(self.existing["overall_health_score"])

        score = 7.0  # baslangic

        # Nakit durumu tech sagligini etkiler
        base_sc = (self.forecast.get("scenarios") or {}).get("base") or {}
        runway = base_sc.get("runway_months") or 12
        if runway < 3:
            score -= 2.0
        elif runway < 6:
            score -= 1.0

        # Net marj dusukse tech yatirimi azalir
        net_margin = self.pnl.get("net_margin", 0) or 0
        if net_margin < 0:
            score -= 1.5
        elif net_margin < 0.05:
            score -= 0.5

        # Muhendis basina gelir dusukse kapasite sorunu
        engineers = self._estimate_engineers()
        if engineers > 0 and self.monthly_revenue > 0:
            rev_per_eng = self.monthly_revenue / engineers
            if rev_per_eng < 100_000:
                score -= 0.5  # dusuk verimlilik

        return max(1.0, min(10.0, round(score, 1)))

    def _compute_tech_debt_score(self) -> float:
        """Tech debt skoru (0-10, yuksek = kotu)."""
        if self.existing.get("tech_debt_score"):
            return float(self.existing["tech_debt_score"])

        debt = BENCHMARKS["tech_debt_healthy"]

        # Uzun suredir buyuyen ve hizli giden sirketlerde tech debt yukselir
        revenue_growth = (self.pnl.get("revenue_growth_pct", 0) or 0)
        if revenue_growth > 0.3:
            debt += 1.0  # hizli buyume -> tech borc birikir

        net_margin = self.pnl.get("net_margin", 0) or 0
        if net_margin < 0.05:
            debt += 0.5  # butce kisintisi -> teknik borc ertelenir

        return min(9.0, round(debt, 1))

    def _compute_velocity_trend(self) -> str:
        """Velocity trendi tahmini."""
        if self.existing.get("velocity_trend"):
            return str(self.existing["velocity_trend"])

        base_sc = (self.forecast.get("scenarios") or {}).get("base") or {}
        runway = base_sc.get("runway_months") or 12
        revenue_growth = (self.pnl.get("revenue_growth_pct", 0) or 0)

        if runway < 4 or (self.pnl.get("net_margin", 0) or 0) < -0.1:
            return "deteriorating"
        if revenue_growth > 0.15:
            return "improving"
        return "stable"

    def _build_cloud_billing_csv(
        self, monthly_cloud_cost_try: float
    ) -> str:
        """Tahmini cloud maliyet verisini CSV formatinda uret."""
        # Tipik SaaS cloud maliyet dagilimi
        distribution = {
            "Compute (EC2/GCE)":   0.45,
            "Database (RDS/Cloud SQL)": 0.20,
            "Storage (S3/GCS)":    0.12,
            "Network & CDN":       0.08,
            "Monitoring & Logs":   0.07,
            "Other Services":      0.08,
        }
        lines = ["service,monthly_cost_try,environment,usage_pct"]
        for service, pct in distribution.items():
            cost = round(monthly_cloud_cost_try * pct)
            lines.append(f"{service},{cost},production,{pct*100:.0f}")
        return "\n".join(lines)

    def generate(self) -> CTOKernelOutput:
        """Tum CTO metriklerini hesapla ve CTOKernelOutput dondur."""

        # Temel hesaplamalar
        engineers       = self._estimate_engineers()
        tech_budget_m   = self._estimate_tech_budget()
        cloud_cost_m    = tech_budget_m * BENCHMARKS["cloud_pct_tech_spend"]
        infra_waste     = self.existing.get("infra_waste_pct") or BENCHMARKS["infra_waste_pct"]
        infra_waste_try = cloud_cost_m * infra_waste
        health_score    = self._compute_health_score()
        debt_score      = self._compute_tech_debt_score()
        vel_trend       = self._compute_velocity_trend()

        # Velocity skoru (trend'den)
        vel_score_map = {"improving": 7.5, "stable": 6.0, "deteriorating": 4.0}
        vel_score = vel_score_map[vel_trend]

        # Guvenlik skoru (health score ile korelasyon)
        security_score = max(3.0, min(9.0, health_score * 0.9 + 0.5))
        open_vulns     = max(0, round((10 - security_score) * 3))

        # Lead time (velocity trendi ile korelasyon)
        lead_time = {
            "improving":   3.0,
            "stable":      5.0,
            "deteriorating": 8.0,
        }[vel_trend]

        # Veri kaynagi
        if self.existing and len(self.existing) > 3:
            data_source = "real"
            confidence  = 0.90
        elif self.monthly_revenue > 0 or self.monthly_opex > 0:
            data_source = "estimated"
            confidence  = 0.70
        else:
            data_source = "benchmark"
            confidence  = 0.50

        # Narrative
        narrative = (
            f"Teknoloji saglik skoru: {health_score}/10. "
            f"Tahmini {engineers} muhendis, aylik tech butcesi ₺{tech_budget_m:,.0f}. "
            f"Altyapi maliyeti ₺{cloud_cost_m:,.0f}/ay, "
            f"tahmini israf ₺{infra_waste_try:,.0f} (%{infra_waste*100:.0f}). "
            f"Velocity trendi: {vel_trend}. "
            f"Tech debt skoru: {debt_score}/10."
        )

        return CTOKernelOutput(
            overall_health_score=health_score,
            tech_debt_score=debt_score,
            infra_waste_pct=infra_waste,
            velocity_trend=vel_trend,
            monthly_infra_cost_try=round(cloud_cost_m),
            infra_waste_try=round(infra_waste_try),
            cloud_pct_total=BENCHMARKS["cloud_pct_tech_spend"],
            estimated_engineers=engineers,
            sprint_velocity_score=vel_score,
            deploy_frequency=BENCHMARKS["deploy_freq_weekly"],
            lead_time_days=lead_time,
            security_score=round(security_score, 1),
            open_vulnerabilities=open_vulns,
            monthly_tech_budget_try=round(tech_budget_m),
            annual_tech_budget_try=round(tech_budget_m * 12),
            data_source=data_source,
            confidence=confidence,
            cloud_billing_csv=self._build_cloud_billing_csv(cloud_cost_m),
            narrative=narrative,
        )


# ── Public factory ─────────────────────────────────────────────────────────────

def get_cto_kernel(
    pnl:              dict[str, Any] | None = None,
    cashflow:         dict[str, Any] | None = None,
    forecast:         dict[str, Any] | None = None,
    chro_data:        dict[str, Any] | None = None,
    existing_cto_data: dict[str, Any] | None = None,
    company_size:     str = "smb",
) -> CTOKernel:
    return CTOKernel(
        pnl=pnl, cashflow=cashflow, forecast=forecast,
        chro_data=chro_data, existing_cto_data=existing_cto_data,
        company_size=company_size,
    )


async def run_cto_kernel(
    pnl:              dict[str, Any] | None = None,
    cashflow:         dict[str, Any] | None = None,
    forecast:         dict[str, Any] | None = None,
    chro_data:        dict[str, Any] | None = None,
    existing_cto_data: dict[str, Any] | None = None,
    company_size:     str = "smb",
) -> dict[str, Any]:
    """API endpoint icin ana giris noktasi."""
    kernel = get_cto_kernel(
        pnl=pnl, cashflow=cashflow, forecast=forecast,
        chro_data=chro_data, existing_cto_data=existing_cto_data,
        company_size=company_size,
    )
    output = kernel.generate()
    return {
        "ok":     True,
        "output": output.to_dict(),
        "patch":  output.to_cto_state_patch(),
    }
