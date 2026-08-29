"""
Risk Cascade Bridge -- KRI Ihlali -> Otomatik Cascade Simulasyonu

Risk Kernel'in tespit ettigi KRI ihlallerini (kirmizi/amber)
Cascade Simulator'a otomatik olarak besler.

Isleyis:
  1. Risk Kernel tum KRI'lari uretir
  2. Bridge kirmizi/amber KRI'lari tarar
  3. cascade_trigger alani olan KRI'lari tespit eder
  4. Her KRI icin Cascade Simulator'i calistirir
  5. Sonuclari birlestirir: KRI + cascade etkisi tek raporda

Ornek:
  "Nakit Omru = 2.1 ay (RED)" -> cash_crisis cascade -> CHRO, CTO, CMO etkileri
  "Attrition = %28 (RED)"     -> key_person_loss cascade -> CTO velocity, COO SLA
  "Aylik Churn = %8 (RED)"    -> customer_churn_spike -> CFO, CMO etkileri
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KRICascadeLink:
    """Bir KRI ile onun tetikledigi cascade sonucunu baglayan kayit."""
    kri_name:       str
    kri_category:   str
    kri_status:     str         # red | amber
    kri_value:      float
    kri_unit:       str
    trigger_type:   str         # TriggerType degeri
    trigger_params: dict[str, Any]
    cascade_result: dict[str, Any] | None   # CascadeResult.to_dict()
    cascade_error:  str | None = None


@dataclass
class RiskCascadeReport:
    """Tam Risk + Cascade analiz raporu."""
    kri_posture:      dict[str, Any]         # Risk Kernel posture ozeti
    cascade_links:    list[KRICascadeLink]   # KRI -> Cascade baglantilari
    total_cascades:   int
    critical_count:   int                    # kirmizi KRI sayisi
    cascade_summary:  str                    # Turkce ozet
    domains_at_risk:  list[str]              # etkilenen domain'ler
    top_cascade:      KRICascadeLink | None  # en kritik cascade

    def to_dict(self) -> dict[str, Any]:
        links = [
            {
                "kri_name":       lnk.kri_name,
                "kri_category":   lnk.kri_category,
                "kri_status":     lnk.kri_status,
                "kri_value":      lnk.kri_value,
                "kri_unit":       lnk.kri_unit,
                "trigger_type":   lnk.trigger_type,
                "trigger_params": lnk.trigger_params,
                "cascade_result": lnk.cascade_result,
                "cascade_error":  lnk.cascade_error,
            }
            for lnk in self.cascade_links
        ]
        return {
            "kri_posture":     self.kri_posture,
            "cascade_links":   links,
            "total_cascades":  self.total_cascades,
            "critical_count":  self.critical_count,
            "cascade_summary": self.cascade_summary,
            "domains_at_risk": self.domains_at_risk,
            "top_cascade": {
                "kri_name":     self.top_cascade.kri_name,
                "trigger_type": self.top_cascade.trigger_type,
                "cascade_result": self.top_cascade.cascade_result,
            } if self.top_cascade else None,
        }


class RiskCascadeBridge:
    """
    Risk Kernel + Cascade Simulator koprusu.

    Kullanim:
        bridge = RiskCascadeBridge(
            pnl=..., cashflow=..., forecast=...,
            chro_data=..., cto_data=..., cmo_data=...
        )
        report = await bridge.run_full_analysis()
    """

    def __init__(
        self,
        pnl:       dict[str, Any] | None = None,
        cashflow:  dict[str, Any] | None = None,
        forecast:  dict[str, Any] | None = None,
        chro_data: dict[str, Any] | None = None,
        cto_data:  dict[str, Any] | None = None,
        cmo_data:  dict[str, Any] | None = None,
        coo_data:  dict[str, Any] | None = None,
        max_cascades: int = 5,        # performans: max kac cascade calistirilsin
        only_red: bool = False,       # sadece RED KRI'lar mi?
    ) -> None:
        self.pnl       = pnl or {}
        self.cashflow  = cashflow or {}
        self.forecast  = forecast or {}
        self.chro_data = chro_data or {}
        self.cto_data  = cto_data or {}
        self.cmo_data  = cmo_data or {}
        self.coo_data  = coo_data or {}
        self.max_cascades = max_cascades
        self.only_red     = only_red

    async def _run_single_cascade(
        self,
        kri_name:     str,
        kri_category: str,
        kri_status:   str,
        kri_value:    float,
        kri_unit:     str,
        trigger_type: str,
        trigger_params: dict[str, Any],
    ) -> KRICascadeLink:
        """Tek bir KRI icin cascade simulasyonu calistir."""
        from app.services.cascade_simulator import TriggerType, get_cascade_simulator

        try:
            trigger = TriggerType(trigger_type)
        except ValueError:
            return KRICascadeLink(
                kri_name=kri_name, kri_category=kri_category,
                kri_status=kri_status, kri_value=kri_value, kri_unit=kri_unit,
                trigger_type=trigger_type, trigger_params=trigger_params,
                cascade_result=None, cascade_error=f"Bilinmeyen trigger: {trigger_type}",
            )

        try:
            sim = get_cascade_simulator(
                pnl=self.pnl, cashflow=self.cashflow, forecast=self.forecast,
                chro_data=self.chro_data, cto_data=self.cto_data,
                cmo_data=self.cmo_data, coo_data=self.coo_data,
            )
            result = sim.simulate(trigger, **trigger_params)
            return KRICascadeLink(
                kri_name=kri_name, kri_category=kri_category,
                kri_status=kri_status, kri_value=kri_value, kri_unit=kri_unit,
                trigger_type=trigger_type, trigger_params=trigger_params,
                cascade_result=result.to_dict(),
            )
        except Exception as exc:
            logger.warning("Cascade simulasyon hatasi KRI=%s: %s", kri_name, exc)
            return KRICascadeLink(
                kri_name=kri_name, kri_category=kri_category,
                kri_status=kri_status, kri_value=kri_value, kri_unit=kri_unit,
                trigger_type=trigger_type, trigger_params=trigger_params,
                cascade_result=None, cascade_error=str(exc),
            )

    async def run_full_analysis(self) -> RiskCascadeReport:
        """
        1. Risk Kernel ile KRI'lari uret
        2. Cascade tetikleyebilecek KRI'lari bul
        3. Paralel cascade simulasyonlari calistir
        4. Birlestirip rapor uret
        """
        from app.agents.risk.risk_kernel import get_risk_kernel

        # Step 1: KRI uretimi
        kernel  = get_risk_kernel(
            pnl=self.pnl, cashflow=self.cashflow, forecast=self.forecast,
            chro_data=self.chro_data, cto_data=self.cto_data,
            cmo_data=self.cmo_data, coo_data=self.coo_data,
        )
        kris    = kernel.generate_all()
        posture = kernel.compute_risk_posture(kris)

        # Step 2: Cascade tetikleyebilecek KRI'lari filtrele
        statuses = ("red",) if self.only_red else ("red", "amber")
        trigger_kris = [
            k for k in kris
            if k.status in statuses and k.cascade_trigger
        ][:self.max_cascades]

        # Step 3: Paralel cascade simulasyonlari
        tasks = [
            self._run_single_cascade(
                kri_name=k.name,
                kri_category=k.category,
                kri_status=k.status,
                kri_value=k.current_value,
                kri_unit=k.unit,
                trigger_type=k.cascade_trigger,  # type: ignore[arg-type]
                trigger_params=k.cascade_params or {},
            )
            for k in trigger_kris
        ]
        cascade_links = list(await asyncio.gather(*tasks)) if tasks else []

        # Step 4: Etkilenen domain'ler
        domains_at_risk: set[str] = set()
        for lnk in cascade_links:
            if lnk.cascade_result:
                domains_at_risk.update(lnk.cascade_result.get("affected_domains", []))

        # En kritik cascade (baz senaryo risk skoru en yuksek)
        top_cascade: KRICascadeLink | None = None
        top_score = 0.0
        for lnk in cascade_links:
            if lnk.cascade_result:
                scenarios = lnk.cascade_result.get("scenarios", [])
                base = next((s for s in scenarios if s["name"] == "baz"), None)
                if base and base.get("overall_risk_score", 0) > top_score:
                    top_score = base["overall_risk_score"]
                    top_cascade = lnk

        # Ozet metin
        red_count   = posture["counts"]["red"]
        amber_count = posture["counts"]["amber"]
        cascade_count = len([l for l in cascade_links if l.cascade_result])
        summary = (
            f"Risk analizi tamamlandi: {posture['posture_tr']} pozisyon "
            f"(KRI skoru {posture['kri_score']}/10). "
            f"{red_count} kirmizi, {amber_count} amber KRI. "
            + (f"{cascade_count} KRI icin zincirleme etki simulasyonu yapildi. " if cascade_count else "")
            + (f"Etkilenen alanlar: {', '.join(sorted(domains_at_risk))}." if domains_at_risk else "")
        )

        return RiskCascadeReport(
            kri_posture=posture,
            cascade_links=cascade_links,
            total_cascades=cascade_count,
            critical_count=red_count,
            cascade_summary=summary,
            domains_at_risk=sorted(domains_at_risk),
            top_cascade=top_cascade,
        )


# ── Public factory ─────────────────────────────────────────────────────────────

async def run_risk_cascade_analysis(
    pnl:       dict[str, Any] | None = None,
    cashflow:  dict[str, Any] | None = None,
    forecast:  dict[str, Any] | None = None,
    chro_data: dict[str, Any] | None = None,
    cto_data:  dict[str, Any] | None = None,
    cmo_data:  dict[str, Any] | None = None,
    coo_data:  dict[str, Any] | None = None,
    max_cascades: int = 5,
    only_red:  bool = False,
) -> dict[str, Any]:
    """API endpoint icin tek giris noktasi."""
    bridge = RiskCascadeBridge(
        pnl=pnl, cashflow=cashflow, forecast=forecast,
        chro_data=chro_data, cto_data=cto_data,
        cmo_data=cmo_data, coo_data=coo_data,
        max_cascades=max_cascades, only_red=only_red,
    )
    report = await bridge.run_full_analysis()
    return report.to_dict()
