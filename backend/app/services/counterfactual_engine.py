"""
Counterfactual Engine — S6: "Ne Olurdu?" Simülasyonu

Rakiplerin yapamadığı şey: şirketin gerçek verisiyle
"şu aksiyonu alsaydık ne olurdu?" sorusuna yanıt vermek.

Desteklenen senaryolar:
  - Personel artırımı / azaltımı
  - Maliyet kesintisi
  - Fiyat artışı
  - Yeni ürün/segment ekleme
  - Pazarlama yatırımı artışı
  - Kira optimizasyonu

Her simülasyon şunu döndürür:
  - Net gelir etkisi (TRY)
  - Break-even süre (ay)
  - Cashflow risk skoru
  - 3 senaryo (iyimser / baz / kötümser)
  - Tavsiye metni (Türkçe)

Kullanım:
    engine = CounterfactualEngine(pnl, cashflow)

    result = engine.simulate_headcount_change(
        delta=2,          # 2 kişi ekle
        avg_salary=50000, # aylık brüt (TRY)
        productivity_gain=0.15,  # %15 verimlilik artışı
    )
    print(result.net_impact_try)
    print(result.breakeven_months)
    print(result.recommendation)
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Simülasyon sonucu ─────────────────────────────────────────────────────────

@dataclass
class SimulationScenario:
    name: str          # "iyimser" | "baz" | "kötümser"
    net_impact_try: float    # 12 aylık net etki (TRY)
    cashflow_impact_monthly: float  # aylık nakit etkisi
    breakeven_months: float | None  # None = hiç break-even olmaz


@dataclass
class CounterfactualResult:
    action:            str                          # Alınan aksiyon
    description:       str                          # Detaylı açıklama
    scenarios:         list[SimulationScenario]     # 3 senaryo
    base_net_impact:   float                        # Baz senaryo 12ay net etki
    breakeven_months:  float | None                 # Baz senaryo break-even
    cashflow_risk:     str                          # "low" | "medium" | "high" | "critical"
    recommendation:    str                          # Türkçe tavsiye
    assumptions:       list[str]                    # Varsayımlar
    sensitivity:       dict[str, float]             # Parametre değişimine duyarlılık

    def to_dict(self) -> dict[str, Any]:
        return {
            "action":           self.action,
            "description":      self.description,
            "scenarios": [
                {
                    "name":                     s.name,
                    "net_impact_try":           round(s.net_impact_try),
                    "cashflow_impact_monthly":  round(s.cashflow_impact_monthly),
                    "breakeven_months":         round(s.breakeven_months, 1) if s.breakeven_months else None,
                }
                for s in self.scenarios
            ],
            "base_net_impact":   round(self.base_net_impact),
            "breakeven_months":  round(self.breakeven_months, 1) if self.breakeven_months else None,
            "cashflow_risk":     self.cashflow_risk,
            "recommendation":    self.recommendation,
            "assumptions":       self.assumptions,
            "sensitivity":       {k: round(v, 2) for k, v in self.sensitivity.items()},
        }


# ── Counterfactual Engine ─────────────────────────────────────────────────────

class CounterfactualEngine:
    """
    Şirket verisine dayalı "ne olurdu?" simülasyonu.

    Tüm hesaplamalar deterministik — LLM sadece tavsiye metnini yazar.
    """

    def __init__(
        self,
        pnl: dict[str, Any] | None = None,
        cashflow: dict[str, Any] | None = None,
        forecast: dict[str, Any] | None = None,
    ) -> None:
        self.pnl      = pnl or {}
        self.cashflow = cashflow or {}
        self.forecast = forecast or {}

        # Temel metrikler (kuruş → TRY dönüşümü)
        self.monthly_revenue  = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.monthly_opex     = (self.pnl.get("total_opex", 0) or 0) / 100 / 12
        self.net_margin       = self.pnl.get("net_margin", 0) or 0
        self.monthly_net_cash = (self.cashflow.get("net_change", 0) or 0) / 100 / 12

        # Nakit ömrü (runway)
        base_sc = (self.forecast.get("scenarios") or {}).get("base") or {}
        self.runway_months = base_sc.get("runway_months")

    # ── S6-2: Personel değişimi simülasyonu ──────────────────────────────────

    def simulate_headcount_change(
        self,
        delta: int,                        # pozitif = artış, negatif = azaltım
        avg_monthly_salary_try: float,     # brüt aylık maaş
        productivity_gain_pct: float = 0.10,  # verimlilik/gelir artışı tahmini
        onboarding_months: int = 2,        # tam verime ulaşma süresi
        horizon_months: int = 12,
    ) -> CounterfactualResult:
        """
        Personel artırımı veya azaltımı etkisini simüle et.

        Hesaplama:
          Maliyet = delta × maaş × (1 + SGK_işveren) × horizon
          Gelir artışı = mevcut_gelir × productivity_gain × ramp_up_faktörü
          Net etki = Gelir artışı - Maliyet artışı
        """
        SGK_RATE = 0.225  # işveren SGK payı
        monthly_cost = delta * avg_monthly_salary_try * (1 + SGK_RATE)
        total_cost_12m = monthly_cost * horizon_months

        # Ramp-up: onboarding döneminde tam verimde değil
        effective_months = max(0, horizon_months - onboarding_months)
        ramp_factor = effective_months / horizon_months if horizon_months > 0 else 0

        # Gelir etkisi (verimlilik)
        if delta > 0:
            revenue_gain_monthly = self.monthly_revenue * productivity_gain_pct * ramp_factor * abs(delta)
            total_revenue_gain = revenue_gain_monthly * horizon_months
        else:
            # Azaltımda: risk olarak velosity kaybı, tam kazanç değil
            revenue_gain_monthly = -(self.monthly_revenue * productivity_gain_pct * 0.5 * abs(delta))
            total_revenue_gain = revenue_gain_monthly * horizon_months

        # Baz senaryo net etki
        base_net = total_revenue_gain - total_cost_12m

        # Break-even
        if monthly_cost > 0 and revenue_gain_monthly > 0:
            be_months = monthly_cost / revenue_gain_monthly if revenue_gain_monthly > monthly_cost / horizon_months else None
            if be_months and be_months > 0:
                be_months = monthly_cost / max(revenue_gain_monthly - monthly_cost, 0.01)
        elif delta < 0:
            be_months = 0.0  # Azaltım = anlık tasarruf
        else:
            be_months = None  # Break-even yok (maliyet > gelir)

        # 3 senaryo
        scenarios = [
            SimulationScenario(
                name="iyimser",
                net_impact_try=base_net * 1.3,
                cashflow_impact_monthly=(monthly_cost - revenue_gain_monthly * 1.3) * -1,
                breakeven_months=be_months * 0.7 if be_months else None,
            ),
            SimulationScenario(
                name="baz",
                net_impact_try=base_net,
                cashflow_impact_monthly=(monthly_cost - revenue_gain_monthly) * -1,
                breakeven_months=be_months,
            ),
            SimulationScenario(
                name="kötümser",
                net_impact_try=base_net * 0.6,
                cashflow_impact_monthly=(monthly_cost - revenue_gain_monthly * 0.6) * -1,
                breakeven_months=be_months * 1.5 if be_months else None,
            ),
        ]

        # Cashflow risk
        new_monthly_cash = self.monthly_net_cash + scenarios[1].cashflow_impact_monthly
        if new_monthly_cash < 0 and (self.runway_months or 12) < 3:
            cf_risk = "critical"
        elif new_monthly_cash < 0:
            cf_risk = "high"
        elif abs(monthly_cost) > self.monthly_opex * 0.2:
            cf_risk = "medium"
        else:
            cf_risk = "low"

        # Türkçe tavsiye
        if delta > 0:
            if base_net > 0 and (be_months or 999) < 8:
                recommendation = (
                    f"{delta} kişilik işe alım önerilir. "
                    f"Baz senaryoda {horizon_months} ayda ₺{base_net:,.0f} net etki, "
                    f"tahmini break-even {be_months:.1f} ay. "
                    f"Cashflow riski: {cf_risk}."
                )
            else:
                recommendation = (
                    f"{delta} kişilik işe alım dikkatli değerlendirilmeli. "
                    f"Break-even {'belirsiz' if not be_months else f'{be_months:.1f} ay'} "
                    f"ve cashflow riski {cf_risk}. "
                    f"Önce freelance/contract deneyin."
                )
        else:
            recommendation = (
                f"{abs(delta)} kişilik kadro azaltımı aylık ₺{abs(monthly_cost):,.0f} tasarruf sağlar. "
                f"Ancak verimlilik kaybı ve moral etkisi göz önünde bulundurulmalı."
            )

        return CounterfactualResult(
            action=f"Personel {'Artırımı' if delta > 0 else 'Azaltımı'} ({delta:+d} kişi)",
            description=f"Aylık {abs(delta)} × ₺{avg_monthly_salary_try:,.0f} (brüt) maaş",
            scenarios=scenarios,
            base_net_impact=base_net,
            breakeven_months=be_months,
            cashflow_risk=cf_risk,
            recommendation=recommendation,
            assumptions=[
                f"Brüt maaş: ₺{avg_monthly_salary_try:,.0f}/ay",
                f"SGK işveren payı: %{SGK_RATE*100:.0f}",
                f"Verimlilik etkisi: %{productivity_gain_pct*100:.0f}",
                f"Onboarding süresi: {onboarding_months} ay",
                f"Ramp-up faktörü: {ramp_factor:.2f}",
            ],
            sensitivity={
                "salary_+10pct":       round((total_cost_12m * 1.1 - total_revenue_gain) * -1),
                "productivity_+5pct":  round((self.monthly_revenue * (productivity_gain_pct + 0.05) * ramp_factor * abs(delta) * horizon_months - total_cost_12m)),
                "horizon_6m":          round((self.monthly_revenue * productivity_gain_pct * ramp_factor * abs(delta) * 6 - monthly_cost * 6)),
            },
        )

    # ── S6-3: Maliyet kesintisi simülasyonu ───────────────────────────────────

    def simulate_cost_reduction(
        self,
        target_category: str,
        reduction_pct: float,              # kesinti yüzdesi (0.0-1.0)
        one_time_cost_try: float = 0.0,    # geçiş maliyeti (varsa)
        horizon_months: int = 12,
    ) -> CounterfactualResult:
        """
        Belirli bir gider kaleminde maliyet kesintisi simülasyonu.

        Örnek: Kira maliyetini %30 düşürme (ofis küçültme)
        """
        category_costs = (self.pnl.get("opex") or {})
        category_cost_monthly = (category_costs.get(target_category, 0) or 0) / 100 / 12

        if category_cost_monthly == 0:
            # Kategori bulunamadı — toplam opex'in oransal payını varsay
            category_cost_monthly = self.monthly_opex * 0.15

        monthly_saving = category_cost_monthly * reduction_pct
        total_saving_12m = monthly_saving * horizon_months - one_time_cost_try

        # Break-even (eğer geçiş maliyeti varsa)
        be_months = one_time_cost_try / monthly_saving if monthly_saving > 0 and one_time_cost_try > 0 else 0.0

        scenarios = [
            SimulationScenario(
                name="iyimser",
                net_impact_try=total_saving_12m * 1.1,
                cashflow_impact_monthly=monthly_saving,
                breakeven_months=be_months * 0.8 if be_months else 0.0,
            ),
            SimulationScenario(
                name="baz",
                net_impact_try=total_saving_12m,
                cashflow_impact_monthly=monthly_saving,
                breakeven_months=be_months,
            ),
            SimulationScenario(
                name="kötümser",
                net_impact_try=total_saving_12m * 0.7,
                cashflow_impact_monthly=monthly_saving * 0.7,
                breakeven_months=be_months * 1.3 if be_months else 0.0,
            ),
        ]

        # Cashflow risk — tasarruf işlemleri genelde düşük riskli
        cf_risk = "low" if monthly_saving > 0 else "medium"

        category_tr = {
            "rent": "kira", "salary": "personel", "marketing": "pazarlama",
            "technology": "teknoloji", "utilities": "faturalar",
        }.get(target_category, target_category)

        recommendation = (
            f"{category_tr.title()} giderlerinde %{reduction_pct*100:.0f} kesinti "
            f"aylık ₺{monthly_saving:,.0f} tasarruf sağlar. "
            f"12 aylık net etki: ₺{total_saving_12m:,.0f}. "
            + (f"Geçiş maliyeti {be_months:.1f} ayda geri dönüşü sağlanır." if one_time_cost_try > 0 else "Anlık tasarruf başlar.")
        )

        return CounterfactualResult(
            action=f"{target_category.title()} Maliyet Kesintisi (%{reduction_pct*100:.0f})",
            description=f"Aylık ₺{category_cost_monthly:,.0f} → ₺{category_cost_monthly*(1-reduction_pct):,.0f}",
            scenarios=scenarios,
            base_net_impact=total_saving_12m,
            breakeven_months=be_months if be_months > 0 else None,
            cashflow_risk=cf_risk,
            recommendation=recommendation,
            assumptions=[
                f"Mevcut {target_category} maliyeti: aylık ₺{category_cost_monthly:,.0f}",
                f"Kesinti oranı: %{reduction_pct*100:.0f}",
                f"Geçiş maliyeti: ₺{one_time_cost_try:,.0f}",
                "Kesintinin diğer giderlere yansıması modellenmedi",
            ],
            sensitivity={
                "reduction_-5pct":     round(monthly_saving * 0.95 * horizon_months - one_time_cost_try),
                "one_time_cost_+20pct": round(total_saving_12m - one_time_cost_try * 0.2),
                "horizon_6m":          round(monthly_saving * 6 - one_time_cost_try),
            },
        )

    def simulate_price_increase(
        self,
        increase_pct: float,               # fiyat artışı (0.0-1.0)
        churn_rate_increase: float = 0.05, # beklenen müşteri kaybı
        horizon_months: int = 12,
    ) -> CounterfactualResult:
        """Fiyat artışı simülasyonu — gelir artışı vs. müşteri kaybı dengesi."""
        current_monthly_revenue = self.monthly_revenue

        # Net gelir etkisi = (1 + fiyat_artışı) × (1 - churn) - 1
        net_revenue_factor = (1 + increase_pct) * (1 - churn_rate_increase) - 1
        monthly_net_gain = current_monthly_revenue * net_revenue_factor
        total_net_gain = monthly_net_gain * horizon_months

        be_months = None  # Fiyat artışı anlık etki

        scenarios = [
            SimulationScenario("iyimser", total_net_gain * 1.2, monthly_net_gain * 1.2, None),
            SimulationScenario("baz",     total_net_gain,       monthly_net_gain,       None),
            SimulationScenario("kötümser", total_net_gain * 0.6, monthly_net_gain * 0.6, None),
        ]

        if monthly_net_gain > 0:
            recommendation = (
                f"%{increase_pct*100:.0f} fiyat artışı tavsiye edilir. "
                f"Beklenen {churn_rate_increase*100:.0f}% müşteri kaybına rağmen "
                f"aylık ₺{monthly_net_gain:,.0f} net kazanç sağlanır."
            )
        else:
            recommendation = (
                f"%{increase_pct*100:.0f} fiyat artışı riskli. "
                f"Müşteri kaybı gelir artışını aşıyor. "
                f"Daha küçük bir artış (%{increase_pct*50:.0f}) veya değer paketi artırımı önerin."
            )

        return CounterfactualResult(
            action=f"Fiyat Artışı (%{increase_pct*100:.0f})",
            description=f"Net gelir faktörü: {net_revenue_factor:+.1%}",
            scenarios=scenarios,
            base_net_impact=total_net_gain,
            breakeven_months=be_months,
            cashflow_risk="low" if monthly_net_gain > 0 else "medium",
            recommendation=recommendation,
            assumptions=[
                f"Fiyat artışı: %{increase_pct*100:.0f}",
                f"Beklenen churn artışı: %{churn_rate_increase*100:.0f}",
                "Mevcut müşteri tabanı korunuyor varsayıldı",
                "Rekabet tepkisi modellenmedi",
            ],
            sensitivity={
                "churn_+5pct":     round((1 + increase_pct) * (1 - churn_rate_increase - 0.05) - 1) * int(current_monthly_revenue * horizon_months),
                "increase_-5pct":  round((1 + increase_pct - 0.05) * (1 - churn_rate_increase) - 1) * int(current_monthly_revenue * horizon_months),
            },
        )


# ── API giriş noktası ──────────────────────────────────────────────────────────

def get_counterfactual_engine(
    pnl: dict[str, Any] | None = None,
    cashflow: dict[str, Any] | None = None,
    forecast: dict[str, Any] | None = None,
) -> CounterfactualEngine:
    return CounterfactualEngine(pnl=pnl, cashflow=cashflow, forecast=forecast)
