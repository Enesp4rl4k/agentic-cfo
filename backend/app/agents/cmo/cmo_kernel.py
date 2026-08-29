"""
CMO Kernel -- Otomatik CMO Veri Uretimi

CFO gelir verisi, CHRO headcount ve sektör benchmark'larindan
CMO pipeline'ina beslenecek otomatik input uretir.

Veri onceligi:
  1. Dogrudan gecilen CMO verisi
  2. CFO gelir trendi -> ROAS/CAC hesaplama
  3. CHRO satis ekibi boyutu -> pipeline kapasitesi
  4. Sektör benchmark (SaaS: CAC/LTV oranlari)

Cikti:
  - overall_roas, avg_cac_cents, avg_monthly_churn
  - ltv_cac_ratio, funnel metrikler
  - Sintetik campaign/funnel CSV (pipeline icin)
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── Sektör benchmark sabitleri ────────────────────────────────────────────────

CMO_BENCHMARKS = {
    "saas_roas":              2.5,    # tipik SaaS ROAS
    "saas_cac_pct_arpu":      3.0,    # CAC = 3x ARPU (aylik)
    "saas_monthly_churn":     0.025,  # %2.5 aylik churn
    "saas_ltv_cac":           3.5,    # LTV/CAC 3.5x
    "marketing_pct_revenue":  0.12,   # gelirin %12'si marketing
    "sales_pct_headcount":    0.15,   # personetin %15'i satis
    "trial_conversion":       0.25,   # trial->paid donusum %25
    "lead_to_opp":            0.30,   # lead -> opportunity %30
    "opp_to_close":           0.25,   # opportunity -> close %25
}


@dataclass
class CMOKernelOutput:
    """CMO Kernel'in urettigi senkronize cikti."""

    # Core pazarlama metrikleri
    overall_roas:       float   # Return on Ad Spend
    avg_cac_cents:      int     # Customer Acquisition Cost (kurus)
    avg_monthly_churn:  float   # 0-1
    ltv_cac_ratio:      float
    monthly_marketing_budget_try: float

    # Funnel metrikleri
    estimated_monthly_leads:  int
    lead_to_opp_rate:         float
    opp_to_close_rate:        float
    trial_conversion_rate:    float
    estimated_new_customers:  int

    # Kanal dagilimi (tahmini)
    top_channel:   str
    channel_mix:   dict[str, float]   # kanal: butce payi

    # Satis ekibi
    estimated_sales_reps: int
    revenue_per_rep_try:  float

    # Buyume metrikleri
    mrr_try:          float
    arr_try:          float
    growth_rate:      float

    # Meta
    data_source: str    # "real" | "estimated" | "benchmark"
    confidence:  float

    # Sintetik CSV'ler (pipeline icin)
    campaign_csv: str | None = None
    funnel_csv:   str | None = None
    narrative:    str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self).items())

    def to_cmo_state_patch(self) -> dict[str, Any]:
        return {
            "overall_roas":      self.overall_roas,
            "avg_cac_cents":     self.avg_cac_cents,
            "avg_monthly_churn": self.avg_monthly_churn,
            "ltv_cac_ratio":     self.ltv_cac_ratio,
        }


class CMOKernel:
    """
    CMO Kernel -- Otomatik pazarlama metrikleri uretir.

    Kullanim:
        kernel = CMOKernel(pnl=..., chro_data=..., existing_cmo_data=...)
        output = kernel.generate()
    """

    def __init__(
        self,
        pnl:              dict[str, Any] | None = None,
        cashflow:         dict[str, Any] | None = None,
        forecast:         dict[str, Any] | None = None,
        chro_data:        dict[str, Any] | None = None,
        existing_cmo_data: dict[str, Any] | None = None,
        industry:         str = "saas",  # saas | ecommerce | services
    ) -> None:
        self.pnl       = pnl or {}
        self.cashflow  = cashflow or {}
        self.forecast  = forecast or {}
        self.chro_data = chro_data or {}
        self.existing  = existing_cmo_data or {}
        self.industry  = industry

        self.monthly_revenue = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.monthly_opex    = (self.pnl.get("total_opex", 0) or 0) / 100 / 12
        self.net_margin      = self.pnl.get("net_margin", 0) or 0
        self.headcount       = self.chro_data.get("total_headcount", 0) or 0
        self.revenue_growth  = (self.pnl.get("revenue_growth_pct", 0) or 0)

    def _estimate_marketing_budget(self) -> float:
        """Aylik pazarlama butcesi tahmini (TRY)."""
        if self.monthly_opex > 0:
            return self.monthly_opex * CMO_BENCHMARKS["marketing_pct_revenue"]
        if self.monthly_revenue > 0:
            return self.monthly_revenue * CMO_BENCHMARKS["marketing_pct_revenue"]
        return 30_000

    def _estimate_cac(self) -> int:
        """Musteri edinme maliyeti tahmini (kurus)."""
        if self.existing.get("avg_cac_cents"):
            return int(self.existing["avg_cac_cents"])
        if self.monthly_revenue > 0:
            # ARPU tahmini: gelir / tahmini musteri sayisi
            est_customers = max(10, round(self.monthly_revenue / 5_000))  # 5K TRY ARPU
            arpu = self.monthly_revenue / est_customers
            cac_try = arpu * CMO_BENCHMARKS["saas_cac_pct_arpu"]
            return int(cac_try * 100)
        return 150_000  # 1500 TRY fallback

    def _estimate_roas(self) -> float:
        """ROAS tahmini."""
        if self.existing.get("overall_roas"):
            return float(self.existing["overall_roas"])
        # Yuksek buyume -> yuksek pazarlama harcamasi -> dusuk ROAS
        if self.revenue_growth > 0.3:
            return 1.8
        if self.revenue_growth > 0.1:
            return CMO_BENCHMARKS["saas_roas"]
        if self.net_margin < 0:
            return 1.5  # zarar eden sirket muhtemelen harcama yapamadi
        return CMO_BENCHMARKS["saas_roas"]

    def _estimate_churn(self) -> float:
        """Aylik churn orani tahmini."""
        if self.existing.get("avg_monthly_churn"):
            return float(self.existing["avg_monthly_churn"])
        # Net marj dusukse churn riski artar
        if self.net_margin < 0:
            return 0.04
        if self.net_margin < 0.05:
            return 0.03
        return CMO_BENCHMARKS["saas_monthly_churn"]

    def _build_campaign_csv(self, marketing_budget: float) -> str:
        """Tahmini kampanya verisi CSV olarak uret."""
        channels = {
            "Google Ads":    0.35,
            "LinkedIn":      0.20,
            "Content/SEO":   0.20,
            "Email":         0.10,
            "Events":        0.10,
            "Other":         0.05,
        }
        lines = ["campaign,channel,spend_try,impressions,clicks,conversions,roas"]
        for channel, pct in channels.items():
            spend = round(marketing_budget * pct)
            roas  = self._estimate_roas() * (0.8 + pct)
            conv  = max(1, round(spend / (self._estimate_cac() / 100) * 0.3))
            lines.append(
                f"{channel} Campaign,{channel},{spend},"
                f"{spend*20},{spend//50},{conv},{roas:.2f}"
            )
        return "\n".join(lines)

    def _build_funnel_csv(self, leads: int) -> str:
        """Tahmini funnel verisi CSV olarak uret."""
        opps  = round(leads * CMO_BENCHMARKS["lead_to_opp"])
        closes = round(opps * CMO_BENCHMARKS["opp_to_close"])
        lines = [
            "stage,count,conversion_rate,avg_days",
            f"Lead,{leads},100,0",
            f"Qualified Lead,{round(leads*0.6)},60,3",
            f"Opportunity,{opps},30,7",
            f"Proposal,{round(opps*0.6)},60,14",
            f"Close,{closes},25,21",
        ]
        return "\n".join(lines)

    def generate(self) -> CMOKernelOutput:
        """Tum CMO metriklerini hesapla."""
        marketing_budget = self._estimate_marketing_budget()
        cac_cents        = self._estimate_cac()
        roas             = self._estimate_roas()
        churn            = self._estimate_churn()

        # LTV hesaplama: ARPU / churn
        cac_try     = cac_cents / 100
        arpu_try    = max(1_000, self.monthly_revenue / max(1, round(self.monthly_revenue / 5_000)))
        ltv_try     = arpu_try / max(0.001, churn)
        ltv_cac     = round(ltv_try / max(1, cac_try), 2)

        # Satis ekibi
        sales_reps  = max(1, round(self.headcount * CMO_BENCHMARKS["sales_pct_headcount"]))
        rev_per_rep = self.monthly_revenue / sales_reps if sales_reps > 0 else 0

        # Lead / funnel tahmini
        monthly_leads    = max(10, round(marketing_budget / (cac_try * 0.1)))
        new_customers    = round(monthly_leads * CMO_BENCHMARKS["lead_to_opp"] * CMO_BENCHMARKS["opp_to_close"])
        mrr              = self.monthly_revenue
        arr              = mrr * 12

        # Kanal karisimlari
        channel_mix = {
            "Google Ads":  0.35,
            "LinkedIn":    0.20,
            "Content/SEO": 0.20,
            "Email":       0.10,
            "Events":      0.10,
            "Other":       0.05,
        }
        top_channel = max(channel_mix, key=lambda k: channel_mix[k])

        # Veri kaynagi
        if self.existing and len(self.existing) > 2:
            data_source = "real"
            confidence  = 0.90
        elif self.monthly_revenue > 0:
            data_source = "estimated"
            confidence  = 0.65
        else:
            data_source = "benchmark"
            confidence  = 0.50

        narrative = (
            f"Aylik pazarlama butcesi: ₺{marketing_budget:,.0f}. "
            f"Tahmini ROAS: {roas:.1f}x, CAC: ₺{cac_try:,.0f}. "
            f"Aylik churn: %{churn*100:.1f}, LTV/CAC: {ltv_cac:.1f}x. "
            f"Tahmini {monthly_leads} lead/ay, {new_customers} yeni musteri."
        )

        return CMOKernelOutput(
            overall_roas=round(roas, 2),
            avg_cac_cents=cac_cents,
            avg_monthly_churn=round(churn, 4),
            ltv_cac_ratio=ltv_cac,
            monthly_marketing_budget_try=round(marketing_budget),
            estimated_monthly_leads=monthly_leads,
            lead_to_opp_rate=CMO_BENCHMARKS["lead_to_opp"],
            opp_to_close_rate=CMO_BENCHMARKS["opp_to_close"],
            trial_conversion_rate=CMO_BENCHMARKS["trial_conversion"],
            estimated_new_customers=new_customers,
            top_channel=top_channel,
            channel_mix=channel_mix,
            estimated_sales_reps=sales_reps,
            revenue_per_rep_try=round(rev_per_rep),
            mrr_try=round(mrr),
            arr_try=round(arr),
            growth_rate=round(self.revenue_growth, 3),
            data_source=data_source,
            confidence=confidence,
            campaign_csv=self._build_campaign_csv(marketing_budget),
            funnel_csv=self._build_funnel_csv(monthly_leads),
            narrative=narrative,
        )


# ── Public factory ─────────────────────────────────────────────────────────────

def get_cmo_kernel(
    pnl:              dict[str, Any] | None = None,
    cashflow:         dict[str, Any] | None = None,
    forecast:         dict[str, Any] | None = None,
    chro_data:        dict[str, Any] | None = None,
    existing_cmo_data: dict[str, Any] | None = None,
    industry:         str = "saas",
) -> CMOKernel:
    return CMOKernel(
        pnl=pnl, cashflow=cashflow, forecast=forecast,
        chro_data=chro_data, existing_cmo_data=existing_cmo_data,
        industry=industry,
    )


async def run_cmo_kernel(
    pnl:              dict[str, Any] | None = None,
    cashflow:         dict[str, Any] | None = None,
    forecast:         dict[str, Any] | None = None,
    chro_data:        dict[str, Any] | None = None,
    existing_cmo_data: dict[str, Any] | None = None,
    industry:         str = "saas",
) -> dict[str, Any]:
    kernel = get_cmo_kernel(
        pnl=pnl, cashflow=cashflow, forecast=forecast,
        chro_data=chro_data, existing_cmo_data=existing_cmo_data,
        industry=industry,
    )
    output = kernel.generate()
    from app.platform.provenance import attach_provenance

    return attach_provenance({
        "ok":     True,
        "output": output.to_dict(),
        "patch":  output.to_cmo_state_patch(),
    })
