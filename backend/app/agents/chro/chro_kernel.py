"""
CHRO Kernel -- Otomatik CHRO Veri Uretimi

CFO opex verisi, headcount tahmini ve Turkiye is gucü
benchmark'larindan CHRO pipeline'ina besleme yapar.

Veri onceligi:
  1. Dogrudan gecilen CHRO verisi
  2. CFO opex'inden personel gider orani
  3. Sektör benchmark (Turkiye SaaS/KOBİ)
  4. Headcount tahmini (gelir / kisi basina gelir)

Cikti:
  - annual_turnover_rate, engagement_score, total_headcount
  - avg_monthly_salary_try, compensation CSV, attrition CSV
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)

# ── Türkiye iş gücü benchmark sabitleri ──────────────────────────────────────

CHRO_BENCHMARKS = {
    "turkey_saas_turnover":    0.18,   # yillik %18 turnover
    "turkey_smb_turnover":     0.22,   # KOBİ'lerde daha yüksek
    "engagement_healthy":      68.0,   # saglikli engagement skoru
    "personnel_pct_opex":      0.45,   # opex'in %45'i personel
    "revenue_per_employee":    800_000, # TRY/yil kisi basina gelir
    "sgk_employer_rate":       0.225,  # isveren SGK payi
    "benefits_pct_salary":     0.15,   # yan haklar (maasın %15'i)
    "training_pct_salary":     0.02,   # egitim butcesi
    "replacement_cost_months": 3,      # issiz kalan pozisyon maliyeti (ay maas)
    "time_to_hire_days":       45,     # ortalama ise alim suresi
}


@dataclass
class CHROKernelOutput:
    """CHRO Kernel ciktisi."""

    # Headcount
    total_headcount:       int
    estimated_engineers:   int
    estimated_sales:       int
    estimated_ops:         int

    # Turnover & Attrition
    annual_turnover_rate:  float    # 0-1
    monthly_attrition:     float    # 0-1
    at_risk_employees:     int      # attrition riski tasiyan kisi sayisi
    turnover_cost_annual_try: float # yillik turnover maliyeti

    # Compensation
    avg_monthly_salary_try:   float
    total_monthly_payroll_try: float
    total_monthly_personnel_cost_try: float  # SGK dahil
    compensation_benchmark_pct: float  # sektör ortalamasina gore (1.0 = ortalama)

    # Engagement & Culture
    engagement_score:         float   # 0-100
    open_critical_roles:      int
    time_to_hire_days:        float

    # Training & Development
    monthly_training_budget_try: float
    skills_gap_risk:          str    # low | medium | high

    # Meta
    data_source: str
    confidence:  float

    # Sintetik CSV'ler
    headcount_csv:    str | None = None
    attrition_csv:    str | None = None
    compensation_csv: str | None = None
    narrative:        str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}

    def to_chro_state_patch(self) -> dict[str, Any]:
        return {
            "total_headcount":       self.total_headcount,
            "annual_turnover_rate":  self.annual_turnover_rate,
            "engagement_score":      self.engagement_score,
            "avg_monthly_salary_try": self.avg_monthly_salary_try,
            "open_critical_roles":   self.open_critical_roles,
        }


class CHROKernel:
    """CHRO Kernel -- Otomatik insan kaynakları metrikleri üretir."""

    def __init__(
        self,
        pnl:               dict[str, Any] | None = None,
        cashflow:          dict[str, Any] | None = None,
        forecast:          dict[str, Any] | None = None,
        existing_chro_data: dict[str, Any] | None = None,
        company_size:      str = "smb",
        sector:            str = "saas",
    ) -> None:
        self.pnl      = pnl or {}
        self.cashflow = cashflow or {}
        self.forecast = forecast or {}
        self.existing = existing_chro_data or {}
        self.size     = company_size
        self.sector   = sector

        self.monthly_revenue = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.monthly_opex    = (self.pnl.get("total_opex", 0) or 0) / 100 / 12
        self.net_margin      = self.pnl.get("net_margin", 0) or 0
        self.revenue_growth  = self.pnl.get("revenue_growth_pct", 0) or 0

    def _estimate_headcount(self) -> int:
        if self.existing.get("total_headcount"):
            return int(self.existing["total_headcount"])
        if self.monthly_revenue > 0:
            annual_rev = self.monthly_revenue * 12
            return max(3, round(annual_rev / CHRO_BENCHMARKS["revenue_per_employee"]))
        if self.monthly_opex > 0:
            monthly_payroll = self.monthly_opex * CHRO_BENCHMARKS["personnel_pct_opex"]
            avg_sal = 35_000 * (1 + CHRO_BENCHMARKS["sgk_employer_rate"])
            return max(3, round(monthly_payroll / avg_sal))
        return 20  # fallback

    def _estimate_avg_salary(self, headcount: int) -> float:
        if self.existing.get("avg_monthly_salary_try"):
            return float(self.existing["avg_monthly_salary_try"])
        if self.monthly_opex > 0:
            monthly_payroll = self.monthly_opex * CHRO_BENCHMARKS["personnel_pct_opex"]
            total_cost_per_person = monthly_payroll / max(1, headcount)
            # SGK geri cikar -> brut maas
            return round(total_cost_per_person / (1 + CHRO_BENCHMARKS["sgk_employer_rate"]))
        # Sektör benchmark
        size_multiplier = {"startup": 0.85, "smb": 1.0, "enterprise": 1.3}.get(self.size, 1.0)
        return round(35_000 * size_multiplier)

    def _estimate_turnover(self) -> float:
        if self.existing.get("annual_turnover_rate"):
            return float(self.existing["annual_turnover_rate"])
        base = CHRO_BENCHMARKS["turkey_saas_turnover"]
        # Nakit sikintisi varsa turnover artar
        base_sc = (self.forecast.get("scenarios") or {}).get("base") or {}
        runway  = base_sc.get("runway_months") or 12
        if runway < 4:
            base += 0.08
        elif runway < 8:
            base += 0.03
        # Negatif marjda moral bozuk
        if self.net_margin < 0:
            base += 0.04
        return min(0.45, round(base, 3))

    def _estimate_engagement(self, turnover: float) -> float:
        if self.existing.get("engagement_score"):
            return float(self.existing["engagement_score"])
        # Turnover ile ters korelasyon
        score = CHRO_BENCHMARKS["engagement_healthy"] - (turnover - 0.15) * 100
        if self.revenue_growth > 0.15:
            score += 5  # hizli buyuyen sirket = yuksek moral
        if self.net_margin < 0:
            score -= 8
        return max(30.0, min(95.0, round(score, 1)))

    def _build_headcount_csv(self, hc: int, engineers: int, sales: int, ops: int) -> str:
        rows = [
            "department,headcount,avg_salary_try,open_roles",
            f"Engineering,{engineers},{round(self._estimate_avg_salary(hc)*1.15)},2",
            f"Sales,{sales},{round(self._estimate_avg_salary(hc)*0.9)},1",
            f"Operations,{ops},{round(self._estimate_avg_salary(hc)*0.85)},1",
            f"Other,{max(1,hc-engineers-sales-ops)},{round(self._estimate_avg_salary(hc)*0.8)},0",
        ]
        return "\n".join(rows)

    def _build_attrition_csv(self, hc: int, turnover: float) -> str:
        monthly = round(hc * turnover / 12)
        rows = [
            "month,voluntary_exits,involuntary_exits,new_hires,net_change",
        ]
        for m in range(1, 7):
            vol  = max(0, monthly + (m % 2))
            inv  = max(0, round(monthly * 0.2))
            hire = max(0, vol + inv - 1)
            rows.append(f"2024-{m:02d},{vol},{inv},{hire},{hire-vol-inv}")
        return "\n".join(rows)

    def _build_compensation_csv(self, hc: int, avg_salary: float) -> str:
        rows = [
            "band,headcount,avg_gross_try,total_cost_try",
            f"Senior,{round(hc*0.25)},{round(avg_salary*1.4)},{round(hc*0.25*avg_salary*1.4)}",
            f"Mid,{round(hc*0.45)},{round(avg_salary)},{round(hc*0.45*avg_salary)}",
            f"Junior,{round(hc*0.30)},{round(avg_salary*0.65)},{round(hc*0.30*avg_salary*0.65)}",
        ]
        return "\n".join(rows)

    def generate(self) -> CHROKernelOutput:
        headcount  = self._estimate_headcount()
        avg_salary = self._estimate_avg_salary(headcount)
        turnover   = self._estimate_turnover()
        engagement = self._estimate_engagement(turnover)

        monthly_attrition = round(turnover / 12, 4)
        at_risk           = round(headcount * turnover * 0.5)

        # Maliyet hesaplamalari
        total_payroll = avg_salary * headcount
        total_cost    = total_payroll * (1 + CHRO_BENCHMARKS["sgk_employer_rate"] +
                                          CHRO_BENCHMARKS["benefits_pct_salary"])
        turnover_cost = round(headcount * turnover * avg_salary *
                              CHRO_BENCHMARKS["replacement_cost_months"])
        training_budget = round(total_payroll * CHRO_BENCHMARKS["training_pct_salary"])

        # Departman dagilimi
        engineers = max(1, round(headcount * 0.30))
        sales     = max(1, round(headcount * 0.15))
        ops       = max(1, round(headcount * 0.20))

        # Skills gap riski
        if engagement < 55 or turnover > 0.25:
            skills_gap = "high"
        elif engagement < 65 or turnover > 0.18:
            skills_gap = "medium"
        else:
            skills_gap = "low"

        # Open critical roles (turnover'dan tahmin)
        open_roles = max(0, round(headcount * turnover * 0.3))

        # Compensation benchmark (sektör ortalamasina gore)
        comp_bench = avg_salary / 35_000  # 35K TRY sektör ortalama

        if self.existing and len(self.existing) > 3:
            data_source, confidence = "real", 0.90
        elif self.monthly_revenue > 0 or self.monthly_opex > 0:
            data_source, confidence = "estimated", 0.70
        else:
            data_source, confidence = "benchmark", 0.50

        narrative = (
            f"Toplam {headcount} calisan, ortalama brut maas ₺{avg_salary:,.0f}/ay. "
            f"Yillik turnover: %{turnover*100:.0f}. "
            f"Calisan bagliligi: {engagement}/100. "
            f"Yillik turnover maliyeti: ₺{turnover_cost:,.0f}."
        )

        return CHROKernelOutput(
            total_headcount=headcount,
            estimated_engineers=engineers,
            estimated_sales=sales,
            estimated_ops=ops,
            annual_turnover_rate=turnover,
            monthly_attrition=monthly_attrition,
            at_risk_employees=at_risk,
            turnover_cost_annual_try=float(turnover_cost),
            avg_monthly_salary_try=round(avg_salary),
            total_monthly_payroll_try=round(total_payroll),
            total_monthly_personnel_cost_try=round(total_cost),
            compensation_benchmark_pct=round(comp_bench, 2),
            engagement_score=engagement,
            open_critical_roles=open_roles,
            time_to_hire_days=CHRO_BENCHMARKS["time_to_hire_days"],
            monthly_training_budget_try=float(training_budget),
            skills_gap_risk=skills_gap,
            data_source=data_source,
            confidence=confidence,
            headcount_csv=self._build_headcount_csv(headcount, engineers, sales, ops),
            attrition_csv=self._build_attrition_csv(headcount, turnover),
            compensation_csv=self._build_compensation_csv(headcount, avg_salary),
            narrative=narrative,
        )


def get_chro_kernel(
    pnl:               dict[str, Any] | None = None,
    cashflow:          dict[str, Any] | None = None,
    forecast:          dict[str, Any] | None = None,
    existing_chro_data: dict[str, Any] | None = None,
    company_size:      str = "smb",
) -> CHROKernel:
    return CHROKernel(pnl=pnl, cashflow=cashflow, forecast=forecast,
                      existing_chro_data=existing_chro_data, company_size=company_size)


async def run_chro_kernel(
    pnl:               dict[str, Any] | None = None,
    cashflow:          dict[str, Any] | None = None,
    forecast:          dict[str, Any] | None = None,
    existing_chro_data: dict[str, Any] | None = None,
    company_size:      str = "smb",
) -> dict[str, Any]:
    kernel = get_chro_kernel(pnl=pnl, cashflow=cashflow, forecast=forecast,
                              existing_chro_data=existing_chro_data, company_size=company_size)
    output = kernel.generate()
    return {"ok": True, "output": output.to_dict(), "patch": output.to_chro_state_patch()}
