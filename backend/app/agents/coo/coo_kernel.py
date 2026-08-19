"""
COO Kernel -- Otomatik COO Veri Uretimi

CHRO headcount, CTO uptime/SLA ve CFO gelir verisinden
COO pipeline'ina beslenecek operasyonel metrikler uretir.

Veri onceligi:
  1. Dogrudan gecilen COO verisi
  2. CTO SLA/MTTR verisi
  3. CHRO headcount -> ops kapasite hesabi
  4. CFO gelir/gider -> operasyonel verimlilik
  5. Sektör benchmark

Cikti:
  - sla_compliance, overall_ops_score, resource_utilization
  - process_efficiency, sintetik CSV'ler
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)

# ── Operasyon benchmark sabitleri ─────────────────────────────────────────────

COO_BENCHMARKS = {
    "sla_target":             0.99,    # %99 uptime hedefi
    "healthy_sla_compliance": 0.95,    # saglikli SLA uyumu
    "resource_utilization":   0.75,    # ideal kaynak kullanim orani
    "ops_pct_headcount":      0.20,    # personetin %20'si operasyon
    "process_automation_pct": 0.30,    # islerin %30'u otomatize
    "incident_resolution_h":  4.0,     # ortalama incident cozum (saat)
    "customer_per_ops":       50,      # ops kisi basina musteri sayisi
    "ops_cost_pct_revenue":   0.08,    # gelirin %8'i operasyon maliyeti
}


@dataclass
class COOKernelOutput:
    """COO Kernel ciktisi."""

    # SLA & Kalite
    sla_compliance:         float    # 0-1
    uptime_pct:             float    # 0-1
    avg_incident_resolution_h: float
    monthly_incident_count: int

    # Operasyonel Verimlilik
    overall_ops_score:      float    # 0-10
    process_efficiency_pct: float    # 0-1
    resource_utilization:   float    # 0-1
    automation_pct:         float    # 0-1

    # Kapasite
    ops_headcount:          int
    customer_per_ops:       float
    ops_cost_monthly_try:   float

    # Süreç Kalitesi
    bottleneck_risk:        str      # low | medium | high
    scaling_readiness:      str      # ready | limited | not_ready
    top_bottlenecks:        list[str]

    # Meta
    data_source: str
    confidence:  float

    # Sintetik CSV'ler
    process_csv:  str | None = None
    resource_csv: str | None = None
    sla_csv:      str | None = None
    narrative:    str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}

    def to_coo_state_patch(self) -> dict[str, Any]:
        return {
            "sla_compliance":    self.sla_compliance,
            "overall_ops_score": self.overall_ops_score,
            "resource_utilization": self.resource_utilization,
        }


class COOKernel:
    """COO Kernel -- Otomatik operasyon metrikleri uretir."""

    def __init__(
        self,
        pnl:               dict[str, Any] | None = None,
        cashflow:          dict[str, Any] | None = None,
        chro_data:         dict[str, Any] | None = None,
        cto_data:          dict[str, Any] | None = None,
        cmo_data:          dict[str, Any] | None = None,
        existing_coo_data: dict[str, Any] | None = None,
        company_size:      str = "smb",
    ) -> None:
        self.pnl       = pnl or {}
        self.cashflow  = cashflow or {}
        self.chro_data = chro_data or {}
        self.cto_data  = cto_data or {}
        self.cmo_data  = cmo_data or {}
        self.existing  = existing_coo_data or {}
        self.size      = company_size

        self.monthly_revenue = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.monthly_opex    = (self.pnl.get("total_opex", 0) or 0) / 100 / 12
        self.net_margin      = self.pnl.get("net_margin", 0) or 0
        self.headcount       = self.chro_data.get("total_headcount", 0) or 0

    def _compute_sla_compliance(self) -> float:
        if self.existing.get("sla_compliance"):
            return float(self.existing["sla_compliance"])
        # CTO sagligi SLA'yi etkiler
        tech_health = self.cto_data.get("overall_health_score", 7.0) or 7.0
        base = COO_BENCHMARKS["healthy_sla_compliance"]
        if tech_health < 5:
            base -= 0.08
        elif tech_health < 7:
            base -= 0.03
        # Nakit sikintisi operasyonu etkiler
        base_sc = {}
        if self.pnl:
            # forecast yoksa net_margin'den tahmin et
            if self.net_margin < 0:
                base -= 0.02
        return max(0.70, min(0.999, round(base, 3)))

    def _compute_ops_score(self, sla: float, utilization: float) -> float:
        if self.existing.get("overall_ops_score"):
            return float(self.existing["overall_ops_score"])
        score = 7.0
        # SLA etkisi
        if sla < 0.90:
            score -= 2.0
        elif sla < 0.95:
            score -= 1.0
        # Kaynak kullanimi
        if utilization > 0.90:
            score -= 1.0  # asiri yuklenme
        elif utilization < 0.60:
            score -= 0.5  # dusuk kullanim
        # Net marj etkisi
        if self.net_margin < 0:
            score -= 1.0
        return max(1.0, min(10.0, round(score, 1)))

    def _estimate_ops_headcount(self) -> int:
        if self.headcount > 0:
            return max(1, round(self.headcount * COO_BENCHMARKS["ops_pct_headcount"]))
        if self.monthly_revenue > 0:
            customers = max(10, round(self.monthly_revenue / 5_000))
            return max(1, round(customers / COO_BENCHMARKS["customer_per_ops"]))
        return 4

    def _identify_bottlenecks(self, sla: float, utilization: float, score: float) -> list[str]:
        bottlenecks = []
        if sla < 0.93:
            bottlenecks.append("SLA ihlalleri — altyapi veya surec sorunu")
        if utilization > 0.88:
            bottlenecks.append("Kaynak tukenmesi — kapasite artirimi gerekiyor")
        if self.net_margin < 0.05:
            bottlenecks.append("Operasyonel maliyet baskisi — verimlilik iyilestirmesi gerekli")
        tech_debt = self.cto_data.get("tech_debt_score", 0) or 0
        if tech_debt > 6:
            bottlenecks.append("Yuksek teknik borc operasyonel verimliligi dusuruyor")
        turnover = self.chro_data.get("annual_turnover_rate", 0) or 0
        if turnover > 0.20:
            bottlenecks.append("Yuksek personel devri — surec bilgisi kayboluyor")
        return bottlenecks[:3]

    def _build_sla_csv(self, sla: float, incidents: int) -> str:
        rows = [
            "month,sla_pct,incidents,p1,p2,p3,avg_resolution_h",
        ]
        for m in range(1, 7):
            mo_sla = round(sla * 100 - (m % 2) * 0.1, 2)
            mo_inc = incidents + (m % 3) - 1
            rows.append(f"2024-{m:02d},{mo_sla},{mo_inc},1,{mo_inc//3},{mo_inc-1-mo_inc//3},4.2")
        return "\n".join(rows)

    def _build_process_csv(self, efficiency: float) -> str:
        processes = [
            ("Musteri Onboarding", 0.80, efficiency),
            ("Destek Ticket Yonetimi", 0.90, efficiency * 0.95),
            ("Faturalama & Odeme", 0.95, 0.98),
            ("Urun Teslimat", 0.85, efficiency * 0.90),
            ("Ic Operasyon", 0.75, efficiency * 0.85),
        ]
        rows = ["process,target_efficiency,actual_efficiency,automation_pct"]
        for name, target, actual in processes:
            rows.append(f"{name},{target:.2f},{actual:.2f},{COO_BENCHMARKS['process_automation_pct']:.2f}")
        return "\n".join(rows)

    def _build_resource_csv(self, hc: int, utilization: float) -> str:
        ops_hc = max(1, round(hc * COO_BENCHMARKS["ops_pct_headcount"]))
        rows = [
            "resource_type,capacity,utilized,utilization_pct,cost_try",
        ]
        rows.append(f"Ops Team,{ops_hc},{round(ops_hc*utilization)},{utilization*100:.0f},{round(ops_hc*35000)}")
        rows.append(f"Systems,100,{round(utilization*100)},{utilization*100:.0f},{round(self.monthly_opex*0.05)}")
        rows.append(f"Tools & Software,100,70,70.0,{round(self.monthly_opex*0.03)}")
        return "\n".join(rows)

    def generate(self) -> COOKernelOutput:
        sla         = self._compute_sla_compliance()
        utilization = float(self.existing.get("resource_utilization") or COO_BENCHMARKS["resource_utilization"])
        ops_score   = self._compute_ops_score(sla, utilization)
        ops_hc      = self._estimate_ops_headcount()
        bottlenecks = self._identify_bottlenecks(sla, utilization, ops_score)
        incidents   = max(1, round((1 - sla) * 200))

        # Process efficiency
        efficiency = min(0.98, sla * 0.95 + 0.02)

        # Scaling readiness
        if ops_score >= 7 and sla >= 0.97:
            scaling = "ready"
        elif ops_score >= 5 and sla >= 0.93:
            scaling = "limited"
        else:
            scaling = "not_ready"

        # Bottleneck risk
        if len(bottlenecks) >= 2 or sla < 0.90:
            bottleneck_risk = "high"
        elif len(bottlenecks) == 1 or sla < 0.95:
            bottleneck_risk = "medium"
        else:
            bottleneck_risk = "low"

        # Operasyon maliyeti
        ops_cost = self.monthly_opex * COO_BENCHMARKS["ops_cost_pct_revenue"]

        if self.existing and len(self.existing) > 2:
            data_source, confidence = "real", 0.90
        elif self.monthly_revenue > 0 or self.headcount > 0:
            data_source, confidence = "estimated", 0.68
        else:
            data_source, confidence = "benchmark", 0.50

        customer_per_ops = (
            (self.monthly_revenue / 5_000) / max(1, ops_hc)
            if self.monthly_revenue > 0 else COO_BENCHMARKS["customer_per_ops"]
        )

        narrative = (
            f"Operasyonel saglik skoru: {ops_score}/10. "
            f"SLA uyumu: %{sla*100:.1f}. "
            f"Kaynak kullanimi: %{utilization*100:.0f}. "
            f"Olcekleme hazirlik: {scaling}."
            + (f" Kritik darbogazlar: {', '.join(bottlenecks[:2])}." if bottlenecks else "")
        )

        return COOKernelOutput(
            sla_compliance=sla,
            uptime_pct=sla,
            avg_incident_resolution_h=COO_BENCHMARKS["incident_resolution_h"],
            monthly_incident_count=incidents,
            overall_ops_score=ops_score,
            process_efficiency_pct=round(efficiency, 3),
            resource_utilization=round(utilization, 2),
            automation_pct=COO_BENCHMARKS["process_automation_pct"],
            ops_headcount=ops_hc,
            customer_per_ops=round(customer_per_ops, 1),
            ops_cost_monthly_try=round(ops_cost),
            bottleneck_risk=bottleneck_risk,
            scaling_readiness=scaling,
            top_bottlenecks=bottlenecks,
            data_source=data_source,
            confidence=confidence,
            process_csv=self._build_process_csv(efficiency),
            resource_csv=self._build_resource_csv(self.headcount or 20, utilization),
            sla_csv=self._build_sla_csv(sla, incidents),
            narrative=narrative,
        )


def get_coo_kernel(
    pnl:               dict[str, Any] | None = None,
    cashflow:          dict[str, Any] | None = None,
    chro_data:         dict[str, Any] | None = None,
    cto_data:          dict[str, Any] | None = None,
    cmo_data:          dict[str, Any] | None = None,
    existing_coo_data: dict[str, Any] | None = None,
    company_size:      str = "smb",
) -> COOKernel:
    return COOKernel(pnl=pnl, cashflow=cashflow, chro_data=chro_data, cto_data=cto_data,
                     cmo_data=cmo_data, existing_coo_data=existing_coo_data, company_size=company_size)


async def run_coo_kernel(
    pnl:               dict[str, Any] | None = None,
    cashflow:          dict[str, Any] | None = None,
    chro_data:         dict[str, Any] | None = None,
    cto_data:          dict[str, Any] | None = None,
    cmo_data:          dict[str, Any] | None = None,
    existing_coo_data: dict[str, Any] | None = None,
    company_size:      str = "smb",
) -> dict[str, Any]:
    kernel = get_coo_kernel(pnl=pnl, cashflow=cashflow, chro_data=chro_data, cto_data=cto_data,
                            cmo_data=cmo_data, existing_coo_data=existing_coo_data, company_size=company_size)
    output = kernel.generate()
    return {"ok": True, "output": output.to_dict(), "patch": output.to_coo_state_patch()}
