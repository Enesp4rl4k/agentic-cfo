"""
Risk Kernel -- Otomatik KRI Uretim Motoru

CFO, CHRO, CTO, CMO ve COO verilerinden otomatik olarak
Key Risk Indicators (KRI) uretir. Artik CSV zorunlu degil.

Veri onceligi:
  1. CompanyContext'ten gelen agent sonuclari
  2. Dogrudan gecilen domain verileri
  3. Hicbir veri yoksa -- bos KRI listesi (graceful degradation)

Urettigi KRI kategorileri:
  financial    -- CFO: nakit omru, marj, burn rate, gelir trendi
  operational  -- COO: SLA, verimlilik, kapasite
  people       -- CHRO: attrition, morale, critical roles
  technology   -- CTO: tech health, debt, velocity, uptime
  market       -- CMO: churn, CAC trend, ROAS
  compliance   -- Compliance/Risk kayitlarindan

Her KRI:
  - name, category, current_value, unit
  - threshold_amber, threshold_red  (asildikta uyari/alarm)
  - status: green | amber | red
  - trend: improving | stable | deteriorating
  - trajectory_months: kac ayda kirmiziya duser (None = zaten kirmizi)
  - evidence: nereden geldi
  - cascade_trigger: kirmiziya dusunce hangi cascade tetiklenir
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


# ── KRI Veri Modeli ───────────────────────────────────────────────────────────

@dataclass
class KRI:
    name:             str
    category:         str           # financial | operational | people | technology | market | compliance
    current_value:    float
    unit:             str           # "ay", "TRY", "%", "skor/10", "adet"
    threshold_amber:  float
    threshold_red:    float
    higher_is_worse:  bool = True   # True: yuksek = kotu (attrition). False: dusuk = kotu (runway)
    status:           str = "green" # green | amber | red
    trend:            str = "stable"
    trend_delta:      float = 0.0   # son doneme gore degisim
    trajectory_months: float | None = None  # kirmiziya kac ayda duser
    evidence:         str = ""
    cascade_trigger:  str | None = None   # TriggerType degeri
    cascade_params:   dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.status = self._compute_status()
        if self.trajectory_months is None:
            self.trajectory_months = self._estimate_trajectory()

    def _compute_status(self) -> str:
        v = self.current_value
        if self.higher_is_worse:
            if v >= self.threshold_red:   return "red"
            if v >= self.threshold_amber: return "amber"
            return "green"
        else:
            # Lower is worse (runway, marj, skor)
            if v <= self.threshold_red:   return "red"
            if v <= self.threshold_amber: return "amber"
            return "green"

    def _estimate_trajectory(self) -> float | None:
        """Trend'e gore kirmiziya kac ayda duser tahmini."""
        if self.status == "red":
            return None  # zaten kirmizi
        if self.trend_delta == 0 or self.trend == "stable":
            return None  # degismiyor
        if self.higher_is_worse:
            if self.trend_delta <= 0:
                return None  # iyilesiyyor
            gap = self.threshold_red - self.current_value
            return round(gap / self.trend_delta, 1) if gap > 0 else None
        else:
            if self.trend_delta >= 0:
                return None  # iyilesiyyor
            gap = self.current_value - self.threshold_red
            return round(gap / abs(self.trend_delta), 1) if gap > 0 else None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # trajectory_months serializasyonu
        if d["trajectory_months"] is not None:
            d["trajectory_months"] = round(d["trajectory_months"], 1)
        return d


# ── KRI Fabrikasi ──────────────────────────────────────────────────────────────

class RiskKernel:
    """
    C-Suite verilerinden KRI uretir.

    Kullanim:
        kernel = RiskKernel(
            pnl=cfo_result["pnl"],
            cashflow=cfo_result["cashflow"],
            forecast=cfo_result["forecast"],
            chro_data=chro_result,
            cto_data=cto_result,
            cmo_data=cmo_result,
            coo_data=coo_result,
        )
        kris = kernel.generate_all()
        summary = kernel.compute_risk_posture(kris)
    """

    def __init__(
        self,
        pnl:         dict[str, Any] | None = None,
        cashflow:    dict[str, Any] | None = None,
        forecast:    dict[str, Any] | None = None,
        chro_data:   dict[str, Any] | None = None,
        cto_data:    dict[str, Any] | None = None,
        cmo_data:    dict[str, Any] | None = None,
        coo_data:    dict[str, Any] | None = None,
        risk_data:   dict[str, Any] | None = None,  # mevcut risk kayit
    ) -> None:
        self.pnl       = pnl or {}
        self.cashflow  = cashflow or {}
        self.forecast  = forecast or {}
        self.chro_data = chro_data or {}
        self.cto_data  = cto_data or {}
        self.cmo_data  = cmo_data or {}
        self.coo_data  = coo_data or {}
        self.risk_data = risk_data or {}

        # Temel hesaplamalar
        self.monthly_revenue = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.monthly_opex    = (self.pnl.get("total_opex", 0) or 0) / 100 / 12
        self.net_margin      = self.pnl.get("net_margin", 0) or 0
        base_sc = (self.forecast.get("scenarios") or {}).get("base") or {}
        self.runway_months   = base_sc.get("runway_months") or 12.0

    # ── Finansal KRI'lar ──────────────────────────────────────────────────────

    def _financial_kris(self) -> list[KRI]:
        kris: list[KRI] = []

        # 1. Nakit Omru (Runway)
        runway = self.runway_months
        kris.append(KRI(
            name="Nakit Omru",
            category="financial",
            current_value=round(runway, 1),
            unit="ay",
            threshold_amber=6.0,
            threshold_red=3.0,
            higher_is_worse=False,
            trend=("deteriorating" if runway < 8 else "stable"),
            trend_delta=(-0.5 if self.monthly_opex > self.monthly_revenue else 0),
            evidence=f"Forecast baz senaryo: {runway:.1f} ay runway",
            cascade_trigger="cash_crisis",
            cascade_params={"runway_months": runway},
        ))

        # 2. Net Kar Marji
        margin_pct = round(self.net_margin * 100, 1)
        kris.append(KRI(
            name="Net Kar Marji",
            category="financial",
            current_value=margin_pct,
            unit="%",
            threshold_amber=5.0,
            threshold_red=0.0,
            higher_is_worse=False,
            trend=("deteriorating" if margin_pct < 5 else "stable"),
            trend_delta=0.0,
            evidence=f"P&L net marj: %{margin_pct}",
            cascade_trigger="revenue_drop" if margin_pct < 0 else None,
            cascade_params={"drop_pct": abs(self.net_margin)} if self.net_margin < 0 else {},
        ))

        # 3. Burn Rate / Gelir Orani
        if self.monthly_revenue > 0:
            burn_ratio = round((self.monthly_opex / self.monthly_revenue) * 100, 1)
            kris.append(KRI(
                name="Burn / Gelir Orani",
                category="financial",
                current_value=burn_ratio,
                unit="%",
                threshold_amber=90.0,
                threshold_red=110.0,
                higher_is_worse=True,
                trend=("deteriorating" if burn_ratio > 95 else "stable"),
                trend_delta=0.0,
                evidence=f"Opex/Revenue: %{burn_ratio}",
                cascade_trigger="cash_crisis" if burn_ratio > 100 else None,
                cascade_params={"runway_months": self.runway_months},
            ))

        # 4. Gelir Buyume Trendi
        rev_growth = (self.pnl.get("revenue_growth_pct", 0) or 0) * 100
        kris.append(KRI(
            name="Gelir Buyume Orani",
            category="financial",
            current_value=round(rev_growth, 1),
            unit="%",
            threshold_amber=0.0,
            threshold_red=-10.0,
            higher_is_worse=False,
            trend=("deteriorating" if rev_growth < 0 else "improving" if rev_growth > 5 else "stable"),
            trend_delta=round(rev_growth / 12, 2),
            evidence=f"Gelir buyume: %{rev_growth:.1f}",
            cascade_trigger="revenue_drop" if rev_growth < -10 else None,
            cascade_params={"drop_pct": abs(rev_growth) / 100} if rev_growth < 0 else {},
        ))

        return kris

    # ── Insan Kaynaklari KRI'lari ─────────────────────────────────────────────

    def _people_kris(self) -> list[KRI]:
        if not self.chro_data:
            return []
        kris: list[KRI] = []

        turnover = (self.chro_data.get("annual_turnover_rate", 0) or 0) * 100
        if turnover > 0:
            kris.append(KRI(
                name="Yillik Personel Devir Hizi",
                category="people",
                current_value=round(turnover, 1),
                unit="%",
                threshold_amber=15.0,
                threshold_red=25.0,
                higher_is_worse=True,
                trend=("deteriorating" if turnover > 20 else "stable"),
                trend_delta=0.5 if turnover > 15 else 0,
                evidence=f"CHRO: yillik turnover %{turnover:.1f}",
                cascade_trigger="key_person_loss" if turnover > 30 else None,
                cascade_params={"role": "chro"},
            ))

        engagement = self.chro_data.get("engagement_score", 0) or 0
        if engagement > 0:
            kris.append(KRI(
                name="Calisan Baglilik Skoru",
                category="people",
                current_value=round(engagement, 1),
                unit="skor/100",
                threshold_amber=60.0,
                threshold_red=45.0,
                higher_is_worse=False,
                trend=("deteriorating" if engagement < 55 else "stable"),
                trend_delta=-1.0 if engagement < 60 else 0,
                evidence=f"CHRO engagement: {engagement}/100",
            ))

        open_roles = self.chro_data.get("open_critical_roles", 0) or 0
        if open_roles > 0:
            kris.append(KRI(
                name="Acik Kritik Roller",
                category="people",
                current_value=int(open_roles),
                unit="adet",
                threshold_amber=3.0,
                threshold_red=6.0,
                higher_is_worse=True,
                trend="stable",
                trend_delta=0,
                evidence=f"CHRO: {open_roles} kritik pozisyon acik",
            ))

        return kris

    # ── Teknoloji KRI'lari ────────────────────────────────────────────────────

    def _technology_kris(self) -> list[KRI]:
        if not self.cto_data:
            return []
        kris: list[KRI] = []

        health = self.cto_data.get("overall_health_score", 0) or 0
        if health > 0:
            kris.append(KRI(
                name="Teknoloji Saglik Skoru",
                category="technology",
                current_value=round(health, 1),
                unit="skor/10",
                threshold_amber=6.0,
                threshold_red=4.0,
                higher_is_worse=False,
                trend=("deteriorating" if health < 6 else "stable"),
                trend_delta=-0.2 if health < 6 else 0,
                evidence=f"CTO health score: {health}/10",
            ))

        debt = self.cto_data.get("tech_debt_score", 0) or 0
        if debt > 0:
            kris.append(KRI(
                name="Teknik Borc Skoru",
                category="technology",
                current_value=round(debt, 1),
                unit="skor/10",
                threshold_amber=6.0,
                threshold_red=8.0,
                higher_is_worse=True,
                trend=("deteriorating" if debt > 6 else "stable"),
                trend_delta=0.1 if debt > 5 else 0,
                evidence=f"CTO tech debt: {debt}/10",
            ))

        infra_waste = (self.cto_data.get("infra_waste_pct", 0) or 0) * 100
        if infra_waste > 0:
            kris.append(KRI(
                name="Altyapi Israf Orani",
                category="technology",
                current_value=round(infra_waste, 1),
                unit="%",
                threshold_amber=20.0,
                threshold_red=35.0,
                higher_is_worse=True,
                trend="stable",
                trend_delta=0,
                evidence=f"CTO infra waste: %{infra_waste:.1f}",
            ))

        mttr = self.cto_data.get("avg_mttr_hours", 0) or 0
        if mttr > 0:
            kris.append(KRI(
                name="Ortalama Onarim Suresi (MTTR)",
                category="technology",
                current_value=round(mttr, 1),
                unit="saat",
                threshold_amber=4.0,
                threshold_red=12.0,
                higher_is_worse=True,
                trend=("deteriorating" if mttr > 6 else "stable"),
                trend_delta=0.5 if mttr > 4 else 0,
                evidence=f"CTO MTTR: {mttr:.1f} saat",
                cascade_trigger="tech_outage" if mttr > 12 else None,
                cascade_params={},
            ))

        return kris

    # ── Pazarlama KRI'lari ────────────────────────────────────────────────────

    def _market_kris(self) -> list[KRI]:
        if not self.cmo_data:
            return []
        kris: list[KRI] = []

        churn = (self.cmo_data.get("avg_monthly_churn", 0) or 0) * 100
        if churn > 0:
            kris.append(KRI(
                name="Aylik Musteri Kayip Orani",
                category="market",
                current_value=round(churn, 2),
                unit="%",
                threshold_amber=3.0,
                threshold_red=7.0,
                higher_is_worse=True,
                trend=("deteriorating" if churn > 4 else "stable"),
                trend_delta=0.2 if churn > 3 else 0,
                evidence=f"CMO monthly churn: %{churn:.2f}",
                cascade_trigger="customer_churn_spike" if churn > 7 else None,
                cascade_params={},
            ))

        roas = self.cmo_data.get("overall_roas", 0) or 0
        if roas > 0:
            kris.append(KRI(
                name="Pazarlama ROAS",
                category="market",
                current_value=round(roas, 2),
                unit="x",
                threshold_amber=2.0,
                threshold_red=1.0,
                higher_is_worse=False,
                trend=("deteriorating" if roas < 2 else "stable"),
                trend_delta=-0.1 if roas < 2.5 else 0,
                evidence=f"CMO ROAS: {roas:.2f}x",
            ))

        ltv_cac = self.cmo_data.get("ltv_cac_ratio", 0) or 0
        if ltv_cac > 0:
            kris.append(KRI(
                name="LTV/CAC Orani",
                category="market",
                current_value=round(ltv_cac, 2),
                unit="x",
                threshold_amber=3.0,
                threshold_red=1.5,
                higher_is_worse=False,
                trend=("deteriorating" if ltv_cac < 3 else "stable"),
                trend_delta=-0.05 if ltv_cac < 3 else 0,
                evidence=f"CMO LTV/CAC: {ltv_cac:.2f}x",
            ))

        return kris

    # ── Operasyonel KRI'lar ───────────────────────────────────────────────────

    def _operational_kris(self) -> list[KRI]:
        if not self.coo_data:
            return []
        kris: list[KRI] = []

        sla = (self.coo_data.get("sla_compliance", 0) or 0) * 100
        if sla > 0:
            kris.append(KRI(
                name="SLA Uyum Orani",
                category="operational",
                current_value=round(sla, 1),
                unit="%",
                threshold_amber=90.0,
                threshold_red=80.0,
                higher_is_worse=False,
                trend=("deteriorating" if sla < 90 else "stable"),
                trend_delta=-0.5 if sla < 90 else 0,
                evidence=f"COO SLA compliance: %{sla:.1f}",
            ))

        ops_score = self.coo_data.get("overall_ops_score", 0) or 0
        if ops_score > 0:
            kris.append(KRI(
                name="Operasyonel Verimlilik Skoru",
                category="operational",
                current_value=round(ops_score, 1),
                unit="skor/10",
                threshold_amber=6.0,
                threshold_red=4.0,
                higher_is_worse=False,
                trend=("deteriorating" if ops_score < 6 else "stable"),
                trend_delta=-0.1 if ops_score < 6 else 0,
                evidence=f"COO ops score: {ops_score}/10",
            ))

        return kris

    # ── Tum KRI'lari uret ────────────────────────────────────────────────────

    def generate_all(self) -> list[KRI]:
        """Tum domain'lerden KRI uretir ve oncelik sirasi ile doner."""
        all_kris: list[KRI] = []
        all_kris.extend(self._financial_kris())
        all_kris.extend(self._people_kris())
        all_kris.extend(self._technology_kris())
        all_kris.extend(self._market_kris())
        all_kris.extend(self._operational_kris())

        # Sirala: red > amber > green, iceride trend=deteriorating once
        priority = {"red": 0, "amber": 1, "green": 2}
        trend_p  = {"deteriorating": 0, "stable": 1, "improving": 2}
        all_kris.sort(key=lambda k: (priority[k.status], trend_p.get(k.trend, 1)))

        return all_kris

    # ── Risk Pozisyonu Ozeti ─────────────────────────────────────────────────

    def compute_risk_posture(self, kris: list[KRI]) -> dict[str, Any]:
        """
        KRI listesinden kurumsal risk pozisyonu ozeti uretir.
        Mevcut risk_summary ile uyumlu format.
        """
        red_kris    = [k for k in kris if k.status == "red"]
        amber_kris  = [k for k in kris if k.status == "amber"]
        green_kris  = [k for k in kris if k.status == "green"]

        # KRI Skoru (0-10, yuksek = kotu)
        kri_score = min(10.0, len(red_kris) * 2.5 + len(amber_kris) * 0.8)

        # Trajectory uyarilari (yaklasan kirmizi)
        upcoming_red = [
            k for k in amber_kris
            if k.trajectory_months is not None and k.trajectory_months <= 3
        ]

        # Cascade tetikleyebilecek KRI'lar
        cascade_ready = [
            k for k in kris
            if k.cascade_trigger and k.status in ("red", "amber")
        ]

        # Genel risk durusu
        if kri_score >= 7:
            posture = "critical"
        elif kri_score >= 5:
            posture = "elevated"
        elif kri_score >= 3:
            posture = "moderate"
        else:
            posture = "acceptable"

        posture_tr = {
            "critical":   "KRITIK",
            "elevated":   "YUKSELMUS",
            "moderate":   "ORTA",
            "acceptable": "KABUL EDILEBILIR",
        }[posture]

        return {
            "kri_score":       round(kri_score, 1),
            "posture":         posture,
            "posture_tr":      posture_tr,
            "counts": {
                "red":   len(red_kris),
                "amber": len(amber_kris),
                "green": len(green_kris),
                "total": len(kris),
            },
            "red_kris":         [k.to_dict() for k in red_kris],
            "amber_kris":       [k.to_dict() for k in amber_kris],
            "upcoming_red":     [k.to_dict() for k in upcoming_red],
            "cascade_ready":    [k.to_dict() for k in cascade_ready],
            "all_kris":         [k.to_dict() for k in kris],
            "by_category": {
                cat: [k.to_dict() for k in kris if k.category == cat]
                for cat in {"financial", "people", "technology", "market", "operational"}
            },
            "narrative": (
                f"Risk pozisyonu {posture_tr} (KRI skoru {kri_score:.1f}/10). "
                f"{len(red_kris)} kirmizi, {len(amber_kris)} amber KRI aktif. "
                + (f"{len(upcoming_red)} KRI 3 ay icinde kirmiziya donebilir. " if upcoming_red else "")
                + (f"{len(cascade_ready)} KRI zincirleme risk tetikleyebilir." if cascade_ready else "")
            ),
        }


# ── Public factory ─────────────────────────────────────────────────────────────

def get_risk_kernel(
    pnl:       dict[str, Any] | None = None,
    cashflow:  dict[str, Any] | None = None,
    forecast:  dict[str, Any] | None = None,
    chro_data: dict[str, Any] | None = None,
    cto_data:  dict[str, Any] | None = None,
    cmo_data:  dict[str, Any] | None = None,
    coo_data:  dict[str, Any] | None = None,
    risk_data: dict[str, Any] | None = None,
) -> RiskKernel:
    return RiskKernel(
        pnl=pnl, cashflow=cashflow, forecast=forecast,
        chro_data=chro_data, cto_data=cto_data,
        cmo_data=cmo_data, coo_data=coo_data,
        risk_data=risk_data,
    )


async def run_risk_kernel(
    pnl:       dict[str, Any] | None = None,
    cashflow:  dict[str, Any] | None = None,
    forecast:  dict[str, Any] | None = None,
    chro_data: dict[str, Any] | None = None,
    cto_data:  dict[str, Any] | None = None,
    cmo_data:  dict[str, Any] | None = None,
    coo_data:  dict[str, Any] | None = None,
    risk_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Tek cagri ile tum KRI'lari uret ve risk pozisyonunu hesapla.
    API endpoint icin ana giris noktasi.
    """
    kernel = get_risk_kernel(
        pnl=pnl, cashflow=cashflow, forecast=forecast,
        chro_data=chro_data, cto_data=cto_data,
        cmo_data=cmo_data, coo_data=coo_data,
        risk_data=risk_data,
    )
    kris    = kernel.generate_all()
    posture = kernel.compute_risk_posture(kris)

    return {
        "ok":      True,
        "posture": posture,
        "kri_count": len(kris),
    }
