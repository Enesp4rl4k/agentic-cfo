"""
Multi-Domain Counterfactual Engine

Tek bir aksiyonun (ornegin "5 kisi ise al") tum C-Suite domain'lerine
etkisini birlesik olarak hesaplar.

Fark: CounterfactualEngine sadece CFO boyutunda hesaplar.
Bu engine CFO + CHRO + CTO + CMO etkilerini ayni anda gosterir.

Desteklenen aksiyonlar:
  headcount_change   -- ise alim veya kadro azaltimi
  marketing_invest   -- pazarlama yatirimi artisi/azaltisi
  tech_investment    -- teknoloji/altyapi yatirimi
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DomainEffect:
    domain: str
    label: str
    impact_score: float
    financial_impact_try: float
    key_metrics: dict[str, Any]
    risks: list[str]
    opportunities: list[str]
    timeline_months: float


@dataclass
class MultidomainScenario:
    name: str
    multiplier: float
    domain_effects: list[DomainEffect]
    net_financial_impact_try: float
    overall_score: float
    recommendation: str


@dataclass
class MultidomainCFResult:
    action_type: str
    action_description: str
    action_params: dict[str, Any]
    scenarios: list[MultidomainScenario]
    base_scenario: MultidomainScenario
    executive_summary: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type":        self.action_type,
            "action_description": self.action_description,
            "action_params":      self.action_params,
            "scenarios": [
                {
                    "name":                     s.name,
                    "multiplier":               s.multiplier,
                    "net_financial_impact_try": round(s.net_financial_impact_try),
                    "overall_score":            round(s.overall_score, 2),
                    "recommendation":           s.recommendation,
                    "domain_effects": [
                        {
                            "domain":               e.domain,
                            "label":                e.label,
                            "impact_score":         round(e.impact_score, 2),
                            "financial_impact_try": round(e.financial_impact_try),
                            "key_metrics":          e.key_metrics,
                            "risks":                e.risks,
                            "opportunities":        e.opportunities,
                            "timeline_months":      round(e.timeline_months, 1),
                        }
                        for e in s.domain_effects
                    ],
                }
                for s in self.scenarios
            ],
            "executive_summary": self.executive_summary,
            "confidence":        round(self.confidence, 2),
        }


class MultidomainCounterfactual:
    """
    CFO + CHRO + CTO + CMO birlesik aksiyon analizi.

    Kullanim:
        engine = MultidomainCounterfactual(pnl=..., chro_data=..., cto_data=..., cmo_data=...)
        result = engine.analyze_headcount_change(delta=5, avg_monthly_salary_try=45000)
    """

    SGK_RATE = 0.225

    def __init__(
        self,
        pnl:       dict[str, Any] | None = None,
        cashflow:  dict[str, Any] | None = None,
        forecast:  dict[str, Any] | None = None,
        chro_data: dict[str, Any] | None = None,
        cto_data:  dict[str, Any] | None = None,
        cmo_data:  dict[str, Any] | None = None,
        coo_data:  dict[str, Any] | None = None,
    ) -> None:
        self.pnl       = pnl or {}
        self.cashflow  = cashflow or {}
        self.forecast  = forecast or {}
        self.chro_data = chro_data or {}
        self.cto_data  = cto_data or {}
        self.cmo_data  = cmo_data or {}
        self.coo_data  = coo_data or {}

        self.monthly_revenue = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.monthly_opex    = (self.pnl.get("total_opex", 0) or 0) / 100 / 12
        self.net_margin      = self.pnl.get("net_margin", 0) or 0
        self.headcount       = self.chro_data.get("total_headcount", 0) or 50
        self.avg_salary      = self.chro_data.get("avg_monthly_salary_try", 30000) or 30000
        self.turnover_rate   = self.chro_data.get("annual_turnover_rate", 0.12) or 0.12
        self.tech_health     = self.cto_data.get("overall_health_score", 7.0) or 7.0
        self.monthly_cac     = (self.cmo_data.get("avg_cac_cents", 0) or 0) / 100
        self.monthly_roas    = self.cmo_data.get("overall_roas", 2.0) or 2.0

        base_sc = (self.forecast.get("scenarios") or {}).get("base") or {}
        self.runway_months = base_sc.get("runway_months") or 12.0

    def _build_scenarios(
        self,
        base_effects: list[DomainEffect],
        action_desc: str,
    ) -> list[MultidomainScenario]:
        configs = [("iyimser", 1.3), ("baz", 1.0), ("kotumser", 0.65)]
        scenarios = []
        for name, mult in configs:
            scaled: list[DomainEffect] = []
            for e in base_effects:
                scaled.append(DomainEffect(
                    domain=e.domain,
                    label=e.label,
                    impact_score=max(-1.0, min(1.0, e.impact_score * mult)),
                    financial_impact_try=round(e.financial_impact_try * mult),
                    key_metrics={
                        k: round(v * mult) if isinstance(v, (int, float)) else v
                        for k, v in e.key_metrics.items()
                    },
                    risks=e.risks,
                    opportunities=e.opportunities,
                    timeline_months=e.timeline_months,
                ))
            net_fin = sum(e.financial_impact_try for e in scaled)
            overall = sum(e.impact_score for e in scaled) / max(1, len(scaled)) * 10
            if overall > 3:
                rec = f"{action_desc} onerilir. Net etki TRY {net_fin:,.0f}/yil."
            elif overall > 0:
                rec = f"{action_desc} dikkatli degerlendirilmeli."
            else:
                rec = f"{action_desc} su an icin yuksek risk tasiyor."
            scenarios.append(MultidomainScenario(
                name=name,
                multiplier=mult,
                domain_effects=scaled,
                net_financial_impact_try=round(net_fin),
                overall_score=round(overall, 2),
                recommendation=rec,
            ))
        return scenarios

    def analyze_headcount_change(
        self,
        delta: int,
        avg_monthly_salary_try: float | None = None,
        productivity_gain_pct: float = 0.10,
        onboarding_months: int = 2,
        horizon_months: int = 12,
        role_type: str = "general",
    ) -> MultidomainCFResult:
        """Personel degisimi -- CFO + CHRO + CTO + CMO birlesik analizi."""
        salary = avg_monthly_salary_try or self.avg_salary
        monthly_cost = delta * salary * (1 + self.SGK_RATE)
        annual_cost  = monthly_cost * horizon_months
        ramp = max(0.0, (horizon_months - onboarding_months)) / horizon_months

        role_velocity = {"engineer": 0.15, "sales": 0.05, "ops": 0.08, "general": 0.10}
        role_revenue  = {"engineer": 0.08, "sales": 0.20, "ops": 0.05, "general": 0.10}
        vel_boost = role_velocity.get(role_type, 0.10)
        rev_boost = role_revenue.get(role_type, 0.10)

        # CFO
        rev_gain = self.monthly_revenue * rev_boost * ramp * abs(delta) * horizon_months
        cfo_net  = (rev_gain - abs(annual_cost)) * (1 if delta > 0 else -1)
        cfo_score = max(-1.0, min(1.0, cfo_net / max(1, abs(annual_cost))))
        cfo_effect = DomainEffect(
            domain="cfo", label="Finansal Etki",
            impact_score=cfo_score,
            financial_impact_try=round(cfo_net),
            key_metrics={
                "annual_cost_try":   round(abs(annual_cost)),
                "revenue_gain_try":  round(rev_gain),
                "net_impact_try":    round(cfo_net),
                "payback_months":    round(abs(annual_cost) / max(1, rev_gain / horizon_months), 1),
            },
            risks=["Verimlilik ramp-up beklenenden uzun surebilir"],
            opportunities=["Dogru kisi alimi revenue'yu ongoruden fazla artirir"],
            timeline_months=float(onboarding_months),
        )

        # CHRO
        if delta > 0:
            culture_risk = min(1.0, delta / max(1, self.headcount) * 5)
            chro_score   = 0.6 - culture_risk * 0.4
            chro_fin     = -(delta * salary * onboarding_months * 0.5)
            chro_risks   = [
                "Kulturel uyum riski: yeni kisiler ekip dinamigini degistirebilir",
                f"Onboarding yuku: mevcut ekip {onboarding_months} ay daha az uretken olabilir",
            ]
            chro_opps = ["Yeni bakis acilari", "Cross-training firsati"]
        else:
            chro_score = max(-1.0, delta / max(1, self.headcount) * 3)
            chro_fin   = abs(delta) * salary * 12
            chro_risks = ["Survivor syndrome -- kalan ekip morali dusebilir", "Attrition zincir olabilir"]
            chro_opps  = ["Organizasyonel verimlilik artisi mumkun"]

        chro_effect = DomainEffect(
            domain="chro", label="Insan Kaynaklari Etkisi",
            impact_score=chro_score,
            financial_impact_try=round(chro_fin),
            key_metrics={
                "headcount_delta":     delta,
                "new_total":           self.headcount + delta,
                "onboarding_cost_try": round(abs(delta) * salary * 0.5),
            },
            risks=chro_risks, opportunities=chro_opps,
            timeline_months=float(onboarding_months),
        )

        # CTO
        tech_score = vel_boost * (1 if delta > 0 else -1) * ramp
        tech_fin   = self.monthly_revenue * vel_boost * ramp * abs(delta) * (0.5 if delta > 0 else -0.3) * horizon_months
        cto_effect = DomainEffect(
            domain="cto", label="Teknoloji & Velocity Etkisi",
            impact_score=tech_score,
            financial_impact_try=round(tech_fin),
            key_metrics={
                "velocity_change_pct": round(vel_boost * abs(delta) * 100, 1),
                "tech_health_delta":   round(tech_score * 2, 1),
            },
            risks=[] if delta > 0 else ["Teknik borc birikimi hizlanabilir"],
            opportunities=["Sprint kapasitesi artar"] if delta > 0 else [],
            timeline_months=float(onboarding_months + 1),
        )

        # CMO
        sales_mult = 2.0 if role_type == "sales" else 0.2
        cmo_rev    = self.monthly_revenue * rev_boost * sales_mult * ramp * abs(delta) * horizon_months
        cmo_score  = min(1.0, cmo_rev / max(1, abs(annual_cost)) * 0.5) * (1 if delta > 0 else -0.5)
        cmo_effect = DomainEffect(
            domain="cmo", label="Pazarlama & Buyume Etkisi",
            impact_score=cmo_score,
            financial_impact_try=round(cmo_rev * (1 if delta > 0 else -0.3)),
            key_metrics={"cac_impact_pct": round((1 - ramp * rev_boost * abs(delta) * 0.1) * 100 - 100, 1)},
            risks=[] if delta > 0 else ["Satis kapasitesi azalir"],
            opportunities=["Pipeline kapasitesi artar"] if role_type == "sales" and delta > 0 else [],
            timeline_months=float(onboarding_months + 2),
        )

        base_effects = [cfo_effect, chro_effect, cto_effect, cmo_effect]
        scenarios    = self._build_scenarios(base_effects, f"{delta:+d} kisi")
        base_sc      = scenarios[1]
        sign = "+" if delta > 0 else ""
        summary = (
            f"{sign}{delta} kisi {'ise alim' if delta > 0 else 'kadro azaltimi'} analizi. "
            f"Baz senaryoda yillik net etki TRY {base_sc.net_financial_impact_try:,.0f}. "
            f"Genel skor: {base_sc.overall_score:.1f}/10."
        )
        return MultidomainCFResult(
            action_type="headcount_change",
            action_description=f"{sign}{delta} kisi, TRY {salary:,.0f}/ay, rol: {role_type}",
            action_params={
                "delta": delta, "avg_monthly_salary_try": salary,
                "productivity_gain_pct": productivity_gain_pct,
                "onboarding_months": onboarding_months,
                "horizon_months": horizon_months, "role_type": role_type,
            },
            scenarios=scenarios, base_scenario=base_sc,
            executive_summary=summary,
            confidence=0.80 if self.monthly_revenue > 0 else 0.55,
        )

    def analyze_marketing_investment(
        self,
        monthly_increase_try: float,
        expected_roas: float = 2.5,
        horizon_months: int = 12,
    ) -> MultidomainCFResult:
        """Pazarlama yatirimi artisinin cok boyutlu etkisi."""
        annual_invest    = monthly_increase_try * horizon_months
        expected_revenue = annual_invest * expected_roas
        cfo_net          = expected_revenue - annual_invest

        cfo_effect = DomainEffect(
            domain="cfo", label="Finansal Etki",
            impact_score=max(-1.0, min(1.0, cfo_net / max(1, annual_invest))),
            financial_impact_try=round(cfo_net),
            key_metrics={
                "annual_investment_try": round(annual_invest),
                "expected_revenue_try":  round(expected_revenue),
                "net_roas":              round(expected_roas, 2),
                "payback_months":        round(annual_invest / max(1, expected_revenue / horizon_months), 1),
            },
            risks=["ROAS hedefine ulasilamamasi durumunda nakit etkisi"],
            opportunities=["Pazar payi artisi", "Brand awareness yatirimi"],
            timeline_months=2.0,
        )
        cmo_score = min(1.0, (expected_roas - 1.0) / 3.0)
        cmo_effect = DomainEffect(
            domain="cmo", label="Pazarlama Performansi",
            impact_score=cmo_score,
            financial_impact_try=round(expected_revenue),
            key_metrics={
                "roas_target":    round(expected_roas, 2),
                "current_roas":   round(self.monthly_roas, 2),
                "monthly_budget": round(monthly_increase_try),
            },
            risks=["Kanal doygunlugu ROAS'i dusebilir"],
            opportunities=["Olcekleme firsati"],
            timeline_months=1.5,
        )
        coo_effect = DomainEffect(
            domain="coo", label="Operasyonel Kapasite",
            impact_score=0.3, financial_impact_try=0,
            key_metrics={"demand_risk": "orta" if expected_revenue > self.monthly_revenue * 12 * 0.3 else "dusuk"},
            risks=["Artan musteri talebi kapasiteyi zorlayabilir"],
            opportunities=["Verimlilik olcegini artirma firsati"],
            timeline_months=3.0,
        )
        base_effects = [cfo_effect, cmo_effect, coo_effect]
        scenarios    = self._build_scenarios(base_effects, f"Pazarlama TRY {monthly_increase_try:,.0f}/ay")
        base_sc      = scenarios[1]
        summary = (
            f"Aylik TRY {monthly_increase_try:,.0f} pazarlama yatirimi. "
            f"Hedef ROAS {expected_roas:.1f}x, yillik gelir TRY {expected_revenue:,.0f}. "
            f"Net etki: TRY {cfo_net:,.0f}."
        )
        return MultidomainCFResult(
            action_type="marketing_investment",
            action_description=f"Pazarlama: +TRY {monthly_increase_try:,.0f}/ay, hedef ROAS {expected_roas}x",
            action_params={"monthly_increase_try": monthly_increase_try, "expected_roas": expected_roas, "horizon_months": horizon_months},
            scenarios=scenarios, base_scenario=base_sc,
            executive_summary=summary, confidence=0.70,
        )

    def analyze_tech_investment(
        self,
        one_time_invest_try: float,
        monthly_ops_increase_try: float = 0.0,
        velocity_gain_pct: float = 0.15,
        horizon_months: int = 12,
    ) -> MultidomainCFResult:
        """Teknoloji/altyapi yatiriminin cok boyutlu etkisi."""
        total_cost    = one_time_invest_try + monthly_ops_increase_try * horizon_months
        revenue_up    = self.monthly_revenue * velocity_gain_pct * horizon_months
        cfo_net       = revenue_up - total_cost

        cfo_effect = DomainEffect(
            domain="cfo", label="Finansal Etki",
            impact_score=max(-1.0, min(1.0, cfo_net / max(1, total_cost))),
            financial_impact_try=round(cfo_net),
            key_metrics={
                "total_investment_try": round(total_cost),
                "revenue_upside_try":   round(revenue_up),
                "payback_months":       round(total_cost / max(1, revenue_up / horizon_months), 1),
            },
            risks=["Yatirim geri donusu beklenenden uzun surebilir"],
            opportunities=["Operasyonel maliyet azalimi mumkun"],
            timeline_months=2.0,
        )
        cto_effect = DomainEffect(
            domain="cto", label="Teknoloji Sagligi & Velocity",
            impact_score=min(1.0, velocity_gain_pct * 3),
            financial_impact_try=round(revenue_up * 0.6),
            key_metrics={
                "velocity_gain_pct":    round(velocity_gain_pct * 100, 1),
                "tech_debt_reduction":  round(velocity_gain_pct * 50, 1),
            },
            risks=["Entegrasyon riski -- migration suresi uzayabilir"],
            opportunities=["Teknik borc azalir", "Gelistirme hizi artar"],
            timeline_months=3.0,
        )
        coo_effect = DomainEffect(
            domain="coo", label="Operasyonel Verimlilik",
            impact_score=0.5, financial_impact_try=0,
            key_metrics={"sla_improvement": "orta-yuksek"},
            risks=["Gecis donemi operasyonel aksakhk riski"],
            opportunities=["Otomasyon artisi", "SLA iyilestirmesi"],
            timeline_months=4.0,
        )
        base_effects = [cfo_effect, cto_effect, coo_effect]
        scenarios    = self._build_scenarios(base_effects, f"Tech yatirim TRY {one_time_invest_try:,.0f}")
        base_sc      = scenarios[1]
        summary = (
            f"TRY {one_time_invest_try:,.0f} teknoloji yatirimi. "
            f"Beklenen velocity artisi %{velocity_gain_pct*100:.0f}. "
            f"Net etki: TRY {cfo_net:,.0f} ({horizon_months} ay)."
        )
        return MultidomainCFResult(
            action_type="tech_investment",
            action_description=f"Tech: TRY {one_time_invest_try:,.0f} one-time + TRY {monthly_ops_increase_try:,.0f}/ay",
            action_params={
                "one_time_invest_try": one_time_invest_try,
                "monthly_ops_increase_try": monthly_ops_increase_try,
                "velocity_gain_pct": velocity_gain_pct,
                "horizon_months": horizon_months,
            },
            scenarios=scenarios, base_scenario=base_sc,
            executive_summary=summary, confidence=0.65,
        )


def get_multidomain_cf(
    pnl:       dict[str, Any] | None = None,
    cashflow:  dict[str, Any] | None = None,
    forecast:  dict[str, Any] | None = None,
    chro_data: dict[str, Any] | None = None,
    cto_data:  dict[str, Any] | None = None,
    cmo_data:  dict[str, Any] | None = None,
    coo_data:  dict[str, Any] | None = None,
) -> MultidomainCounterfactual:
    return MultidomainCounterfactual(
        pnl=pnl, cashflow=cashflow, forecast=forecast,
        chro_data=chro_data, cto_data=cto_data,
        cmo_data=cmo_data, coo_data=coo_data,
    )
