"""
Cross-Domain Intelligence Hub

Tum kernel'lari paralel olarak calistirir, sonuclari birlestirip
C-Suite genelinde capraz iliskileri (cross-domain insights) uretir.

Tek API cagriyla:
  1. CFO verisi mevcut mu? -> finansal metrikler
  2. CTO Kernel -> teknoloji sagligi
  3. CMO Kernel -> pazarlama verimliligi
  4. CHRO Kernel -> insan kaynakları
  5. COO Kernel -> operasyonel kapasite
  6. Audit Kernel -> denetim bulgulari
  7. Compliance Kernel -> yasal uyum
  8. Risk Kernel -> KRI + cascade tetikleyicileri

Capraz iliski ornekleri:
  - "Nakit < 4 ay + Attrition > %20 -> Talent-Cash Cascade"
  - "Tech debt > 7 + CMO buyume hedefi yüksek -> Delivery Risk"
  - "SLA < %90 + Attrition > %25 -> Ops Degradation Spiral"
  - "Compliance kritik + CFO ceza riski -> Regulatory Financial Exposure"
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CrossDomainInsight:
    """Birden fazla domain'in kesismesinden dogan govde bulgulari."""
    id:           str
    title:        str
    domains:      list[str]     # etkilenen domain'ler
    severity:     str           # critical | high | medium | low
    insight_type: str           # risk | opportunity | correlation | warning
    description:  str
    evidence:     list[str]     # her domain'den kanit
    actions:      list[str]     # oncelik sirali aksiyonlar
    financial_impact_try: float | None  # tahmini finansal etki


@dataclass
class CrossDomainReport:
    """Tam cross-domain analiz raporu."""
    # Kernel sonuclari
    cto_output:        dict[str, Any] | None
    cmo_output:        dict[str, Any] | None
    chro_output:       dict[str, Any] | None
    coo_output:        dict[str, Any] | None
    audit_output:      dict[str, Any] | None
    compliance_output: dict[str, Any] | None
    risk_output:       dict[str, Any] | None

    # Cross-domain bulgular
    insights:          list[CrossDomainInsight]
    critical_count:    int
    high_count:        int

    # Genel saglik skoru (0-100)
    overall_health_score: float
    health_label:         str   # excellent | good | fair | at_risk | critical

    # Ozet
    executive_summary:   str
    top_priorities:      list[str]
    quick_wins:          list[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class CrossDomainHub:
    """
    Tum kernel'lari paralel calistirir, sonuclari birlestirip
    cross-domain insight'lar uretir.

    Kullanim:
        hub = CrossDomainHub(pnl=..., cashflow=..., ...)
        report = await hub.run_full_analysis()
    """

    def __init__(
        self,
        pnl:              dict[str, Any] | None = None,
        cashflow:         dict[str, Any] | None = None,
        forecast:         dict[str, Any] | None = None,
        anomalies:        list[dict[str, Any]] | None = None,
        existing_cto:     dict[str, Any] | None = None,
        existing_cmo:     dict[str, Any] | None = None,
        existing_chro:    dict[str, Any] | None = None,
        existing_coo:     dict[str, Any] | None = None,
        company_size:     str = "smb",
        sector:           str = "saas",
        has_eu_customers: bool = False,
        is_fintech:       bool = False,
    ) -> None:
        self.pnl       = pnl or {}
        self.cashflow  = cashflow or {}
        self.forecast  = forecast or {}
        self.anomalies = anomalies or []
        self.existing_cto  = existing_cto or {}
        self.existing_cmo  = existing_cmo or {}
        self.existing_chro = existing_chro or {}
        self.existing_coo  = existing_coo or {}
        self.size     = company_size
        self.sector   = sector
        self.eu       = has_eu_customers
        self.fintech  = is_fintech

        self.monthly_revenue = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.net_margin      = self.pnl.get("net_margin", 0) or 0
        base_sc = (self.forecast.get("scenarios") or {}).get("base") or {}
        self.runway_months   = base_sc.get("runway_months") or 12.0

    # ── Paralel kernel calistirma ─────────────────────────────────────────────

    async def _run_all_kernels(self) -> dict[str, Any]:
        """Tum kernel'lari asyncio.gather ile paralel calistir."""
        from app.agents.cto.cto_kernel        import run_cto_kernel
        from app.agents.cmo.cmo_kernel        import run_cmo_kernel
        from app.agents.chro.chro_kernel      import run_chro_kernel
        from app.agents.coo.coo_kernel        import run_coo_kernel
        from app.agents.audit.audit_kernel    import run_audit_kernel
        from app.agents.compliance.compliance_kernel import run_compliance_kernel
        from app.agents.risk.risk_kernel      import run_risk_kernel

        # Temel CHRO verisi onceden hesaplanmali (COO buna bagimli)
        try:
            chro_result = await run_chro_kernel(
                pnl=self.pnl, cashflow=self.cashflow, forecast=self.forecast,
                existing_chro_data=self.existing_chro, company_size=self.size,
            )
            chro_out = chro_result.get("output", {})
        except Exception as exc:
            logger.warning("CHRO kernel hatasi: %s", exc)
            chro_out = self.existing_chro

        # Diger kernel'lari paralel calistir
        async def _cto() -> dict[str, Any]:
            try:
                r = await run_cto_kernel(
                    pnl=self.pnl, cashflow=self.cashflow, forecast=self.forecast,
                    chro_data=chro_out, existing_cto_data=self.existing_cto,
                    company_size=self.size,
                )
                return r.get("output", {})
            except Exception as exc:
                logger.warning("CTO kernel: %s", exc)
                return self.existing_cto

        async def _cmo() -> dict[str, Any]:
            try:
                r = await run_cmo_kernel(
                    pnl=self.pnl, cashflow=self.cashflow, forecast=self.forecast,
                    chro_data=chro_out, existing_cmo_data=self.existing_cmo,
                    industry=self.sector,
                )
                return r.get("output", {})
            except Exception as exc:
                logger.warning("CMO kernel: %s", exc)
                return self.existing_cmo

        async def _coo(cto_out: dict[str, Any]) -> dict[str, Any]:
            try:
                r = await run_coo_kernel(
                    pnl=self.pnl, cashflow=self.cashflow,
                    chro_data=chro_out, cto_data=cto_out,
                    existing_coo_data=self.existing_coo, company_size=self.size,
                )
                return r.get("output", {})
            except Exception as exc:
                logger.warning("COO kernel: %s", exc)
                return self.existing_coo

        async def _audit(cto_out: dict[str, Any], coo_out: dict[str, Any]) -> dict[str, Any]:
            try:
                r = await run_audit_kernel(
                    pnl=self.pnl, cashflow=self.cashflow, anomalies=self.anomalies,
                    chro_data=chro_out, cto_data=cto_out, coo_data=coo_out,
                )
                return r.get("output", {})
            except Exception as exc:
                logger.warning("Audit kernel: %s", exc)
                return {}

        async def _compliance(cto_out: dict[str, Any]) -> dict[str, Any]:
            try:
                r = await run_compliance_kernel(
                    pnl=self.pnl, chro_data=chro_out, cto_data=cto_out,
                    company_size=self.size, sector=self.sector,
                    has_eu_customers=self.eu, is_fintech=self.fintech,
                )
                return r.get("output", {})
            except Exception as exc:
                logger.warning("Compliance kernel: %s", exc)
                return {}

        async def _risk(cto_out: dict[str, Any], cmo_out: dict[str, Any], coo_out: dict[str, Any]) -> dict[str, Any]:
            try:
                r = await run_risk_kernel(
                    pnl=self.pnl, cashflow=self.cashflow, forecast=self.forecast,
                    chro_data=chro_out, cto_data=cto_out,
                    cmo_data=cmo_out, coo_data=coo_out,
                )
                return r.get("posture", {})
            except Exception as exc:
                logger.warning("Risk kernel: %s", exc)
                return {}

        # Sirali bagimlilik: CTO -> COO -> Audit
        cto_out, cmo_out = await asyncio.gather(_cto(), _cmo())
        coo_out          = await _coo(cto_out)
        audit_out, comp_out, risk_out = await asyncio.gather(
            _audit(cto_out, coo_out),
            _compliance(cto_out),
            _risk(cto_out, cmo_out, coo_out),
        )

        return {
            "chro": chro_out, "cto": cto_out, "cmo": cmo_out,
            "coo": coo_out, "audit": audit_out,
            "compliance": comp_out, "risk": risk_out,
        }

    # ── Cross-domain insight tespiti ──────────────────────────────────────────

    def _detect_insights(
        self,
        chro: dict[str, Any],
        cto:  dict[str, Any],
        cmo:  dict[str, Any],
        coo:  dict[str, Any],
        audit: dict[str, Any],
        compliance: dict[str, Any],
        risk: dict[str, Any],
    ) -> list[CrossDomainInsight]:
        insights: list[CrossDomainInsight] = []

        turnover = chro.get("annual_turnover_rate", 0) or 0
        tech_health = cto.get("overall_health_score", 7) or 7
        tech_debt   = cto.get("tech_debt_score", 3) or 3
        roas        = cmo.get("overall_roas", 2.5) or 2.5
        churn       = cmo.get("avg_monthly_churn", 0.025) or 0.025
        sla         = coo.get("sla_compliance", 0.95) or 0.95
        audit_critical = audit.get("critical_count", 0) or 0
        comp_critical  = compliance.get("critical_violations", 0) or 0
        risk_score  = risk.get("kri_score", 0) or 0

        # ── 1. Talent-Cash Cascade ────────────────────────────────────────────
        if self.runway_months < 4 and turnover > 0.20:
            insights.append(CrossDomainInsight(
                id="talent_cash_cascade",
                title="Talent-Cash Cascade: Kritik Risk",
                domains=["cfo", "chro"],
                severity="critical",
                insight_type="risk",
                description=(
                    f"Nakit omru {self.runway_months:.1f} ay + yillik %{turnover*100:.0f} turnover. "
                    "Nakit sikintisi belirsizlik yaratir, yetenekler ayrilir, "
                    "bu da teslim kapasitesini ve geliri daha da dusurebilir."
                ),
                evidence=[
                    f"CFO: Runway {self.runway_months:.1f} ay",
                    f"CHRO: Yillik turnover %{turnover*100:.0f}",
                ],
                actions=[
                    "Kritik ekip uyelerine acil retention plani uygula",
                    "Nakit durumunu ekiple seffaf paylasarak belirsizligi azalt",
                    "Yedek plan: hangi roller dagitilabilir (freelance)?",
                ],
                financial_impact_try=round(self.monthly_revenue * 3 * turnover),
            ))

        # ── 2. Delivery Risk to Revenue ───────────────────────────────────────
        if tech_debt > 6 and roas > 2.5:
            insights.append(CrossDomainInsight(
                id="delivery_risk_revenue",
                title="Delivery Riski Geliri Tehdit Ediyor",
                domains=["cto", "cmo"],
                severity="high",
                insight_type="risk",
                description=(
                    f"Tech debt {tech_debt}/10 iken CMO buyume hedefleri yuksek (ROAS {roas:.1f}x). "
                    "Pazarlama vaatleri teslim kapasitesini asabilir."
                ),
                evidence=[
                    f"CTO: Tech debt skoru {tech_debt}/10",
                    f"CMO: ROAS {roas:.1f}x (agresif buyume)",
                ],
                actions=[
                    "Tech debt azaltma icin sprint kapasitesinin %20'sini ayir",
                    "CMO ile urun roadmap'i hizala, gercekci taahhutte bulun",
                    "Teknik borcu musteri teslim riskiyle board'a sun",
                ],
                financial_impact_try=round(self.monthly_revenue * 2),
            ))

        # ── 3. Ops Degradation Spiral ─────────────────────────────────────────
        if sla < 0.90 and turnover > 0.22:
            insights.append(CrossDomainInsight(
                id="ops_degradation_spiral",
                title="Operasyonel Bozulma Sarmalı",
                domains=["coo", "chro"],
                severity="high",
                insight_type="risk",
                description=(
                    f"SLA %{sla*100:.1f} + Turnover %{turnover*100:.0f}. "
                    "Personel kaybi surec bilgisini yok eder, "
                    "bu SLA'yi dusurur, bu da musteri kaybina yol acar."
                ),
                evidence=[
                    f"COO: SLA uyumu %{sla*100:.1f}",
                    f"CHRO: Turnover %{turnover*100:.0f}",
                ],
                actions=[
                    "Kritik surecleri dokumante et (bilgi transferi programi)",
                    "Yedek personel belirle, onlari kritik konularda egit",
                    "SLA ihlallerinin kok nedenini analiz et",
                ],
                financial_impact_try=None,
            ))

        # ── 4. Regulatory Financial Exposure ─────────────────────────────────
        if comp_critical >= 1 or audit_critical >= 1:
            exposure = compliance.get("regulatory_exposure_try", 0) or 0
            insights.append(CrossDomainInsight(
                id="regulatory_exposure",
                title="Yasal ve Mali Maruziyet Riski",
                domains=["compliance", "audit", "cfo"],
                severity="critical" if comp_critical >= 1 else "high",
                insight_type="warning",
                description=(
                    f"{comp_critical} kritik uyumluluk ihlali + {audit_critical} kritik denetim bulgusus. "
                    f"Tahmini ceza riski: ₺{exposure:,.0f}."
                ),
                evidence=[
                    f"Compliance: {comp_critical} kritik ihla",
                    f"Audit: {audit_critical} kritik bulgu",
                    f"CFO: Tahmini ceza maruziyeti ₺{exposure:,.0f}",
                ],
                actions=[
                    "Hukuk danismanini devreye al",
                    "Kritik uyumluluk eksikliklerini 7 gun icinde kapat",
                    "Ceza riskini CFO bütcesine ekle",
                ],
                financial_impact_try=float(exposure),
            ))

        # ── 5. Growth-Churn Imbalance ─────────────────────────────────────────
        if churn > 0.05 and roas > 2.0:
            monthly_lost = self.monthly_revenue * churn
            insights.append(CrossDomainInsight(
                id="growth_churn_imbalance",
                title="Buyume-Churn Dengesizligi",
                domains=["cmo", "cfo"],
                severity="medium",
                insight_type="correlation",
                description=(
                    f"Aylik %{churn*100:.1f} churn orani yuksek. "
                    "Yeni musteri kazanma hizi churn'u telafi edemiyor."
                ),
                evidence=[
                    f"CMO: Aylik churn %{churn*100:.1f}",
                    f"CFO: Aylik gelir kaybi tahmini ₺{monthly_lost:,.0f}",
                ],
                actions=[
                    "Musteri basari (customer success) programi baslat",
                    "En cok ayrilan musteri segmentini analiz et",
                    "Net Revenue Retention (NRR) hedefini belirle",
                ],
                financial_impact_try=round(monthly_lost * 12),
            ))

        # ── 6. Tech + Ops Alignment Opportunity ──────────────────────────────
        if tech_health >= 8 and sla >= 0.97:
            insights.append(CrossDomainInsight(
                id="tech_ops_strength",
                title="Teknoloji + Operasyon Gucu -- Ölçekleme Firsati",
                domains=["cto", "coo"],
                severity="low",
                insight_type="opportunity",
                description=(
                    f"Tech health {tech_health}/10 ve SLA %{sla*100:.1f}. "
                    "Teknik altyapi guclu -- agresif ölçekleme mumkun."
                ),
                evidence=[
                    f"CTO: Saglik skoru {tech_health}/10",
                    f"COO: SLA %{sla*100:.1f}",
                ],
                actions=[
                    "Pazarlama yatirimini artirarak buyumeyi hizlandir",
                    "Yeni pazar veya urun segmenti icin roadmap hazirla",
                ],
                financial_impact_try=round(self.monthly_revenue * 6),
            ))

        # Onceliklere gore sirala
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        insights.sort(key=lambda x: sev_order.get(x.severity, 4))
        return insights

    # ── Genel saglik skoru ────────────────────────────────────────────────────

    def _compute_health_score(
        self,
        cto: dict[str, Any],
        cmo: dict[str, Any],
        chro: dict[str, Any],
        coo: dict[str, Any],
        risk: dict[str, Any],
    ) -> tuple[float, str]:
        scores = []
        # CTO
        tech_h = cto.get("overall_health_score", 7) or 7
        scores.append(tech_h * 10)
        # CMO
        roas = cmo.get("overall_roas", 2.5) or 2.5
        scores.append(min(100, roas / 3 * 100))
        # CHRO
        eng  = chro.get("engagement_score", 65) or 65
        scores.append(eng)
        # COO
        sla  = (coo.get("sla_compliance", 0.95) or 0.95) * 100
        scores.append(sla)
        # CFO
        margin = self.net_margin
        scores.append(max(0, min(100, 50 + margin * 200)))
        # Risk (ters: yuksek risk = dusuk saglik)
        risk_s = risk.get("kri_score", 3) or 3
        scores.append(max(0, 100 - risk_s * 10))

        health = sum(scores) / len(scores)
        if health >= 80:
            label = "excellent"
        elif health >= 65:
            label = "good"
        elif health >= 50:
            label = "fair"
        elif health >= 35:
            label = "at_risk"
        else:
            label = "critical"
        return round(health, 1), label

    # ── Ana analiz metodu ─────────────────────────────────────────────────────

    async def run_full_analysis(self) -> CrossDomainReport:
        """Tum kernel'lari calistir, cross-domain raporu uret."""
        results = await self._run_all_kernels()

        chro_out  = results["chro"]
        cto_out   = results["cto"]
        cmo_out   = results["cmo"]
        coo_out   = results["coo"]
        audit_out = results["audit"]
        comp_out  = results["compliance"]
        risk_out  = results["risk"]

        insights = self._detect_insights(
            chro_out, cto_out, cmo_out, coo_out, audit_out, comp_out, risk_out
        )

        critical = sum(1 for i in insights if i.severity == "critical")
        high     = sum(1 for i in insights if i.severity == "high")

        health_score, health_label = self._compute_health_score(
            cto_out, cmo_out, chro_out, coo_out, risk_out
        )

        # Yonetici ozeti
        summary = (
            f"Genel saglik: {health_score:.0f}/100 ({health_label}). "
            f"{len(insights)} cross-domain bulgu ({critical} kritik, {high} yuksek). "
        )
        if insights:
            summary += f"En kritik: {insights[0].title}."

        # Oncelikli aksiyonlar (en kritik insight'lardan)
        top_priorities = [
            f"[{ins.severity.upper()}] {ins.actions[0]}"
            for ins in insights[:3]
            if ins.actions
        ]

        # Hizli kazanim (dusuk effort, yuksek etki)
        quick_wins: list[str] = []
        if cto_out.get("infra_waste_try", 0) > 5000:
            waste = cto_out.get("infra_waste_try", 0)
            quick_wins.append(f"Cloud optimizasyonu: aylik ₺{waste:,.0f} tasarruf potansiyeli")
        if comp_out.get("unknown_count", 0) > 3:
            quick_wins.append("Uyumluluk dokumantasyonu guncelle -- dusuk efor, yuksek risk azaltimi")
        if chro_out.get("open_critical_roles", 0) > 2:
            quick_wins.append("Kritik rolleri doldurmak icin is ilanlarini yayinla")

        return CrossDomainReport(
            cto_output=cto_out,
            cmo_output=cmo_out,
            chro_output=chro_out,
            coo_output=coo_out,
            audit_output=audit_out,
            compliance_output=comp_out,
            risk_output=risk_out,
            insights=insights,
            critical_count=critical,
            high_count=high,
            overall_health_score=health_score,
            health_label=health_label,
            executive_summary=summary,
            top_priorities=top_priorities,
            quick_wins=quick_wins,
        )


# ── Public factory ─────────────────────────────────────────────────────────────

async def run_cross_domain_analysis(
    pnl:              dict[str, Any] | None = None,
    cashflow:         dict[str, Any] | None = None,
    forecast:         dict[str, Any] | None = None,
    anomalies:        list[dict[str, Any]] | None = None,
    existing_cto:     dict[str, Any] | None = None,
    existing_cmo:     dict[str, Any] | None = None,
    existing_chro:    dict[str, Any] | None = None,
    existing_coo:     dict[str, Any] | None = None,
    company_size:     str = "smb",
    sector:           str = "saas",
    has_eu_customers: bool = False,
    is_fintech:       bool = False,
) -> dict[str, Any]:
    hub = CrossDomainHub(
        pnl=pnl, cashflow=cashflow, forecast=forecast, anomalies=anomalies,
        existing_cto=existing_cto, existing_cmo=existing_cmo,
        existing_chro=existing_chro, existing_coo=existing_coo,
        company_size=company_size, sector=sector,
        has_eu_customers=has_eu_customers, is_fintech=is_fintech,
    )
    report = await hub.run_full_analysis()
    return report.to_dict()
