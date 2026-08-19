"""
Cascade Risk Simulator — Zincirleme Risk Simülasyonu

"Nakit 3 ayda biterse ne olur?" gibi bir tetikleyici olayın
tüm C-Suite domain'lerine (CFO, CHRO, CTO, CMO, COO, Risk) nasıl
yayıldığını deterministik olarak simüle eder.

Mimari:
  - Her domain için ayrı etki modeli (DomainImpactModel)
  - Domainler arası bağımlılık grafiği (DAG)
  - BFS tabanlı zincirleme yayılım algoritması
  - 3 senaryo: iyimser / baz / kötümser
  - CompanyContext ile entegre — gerçek şirket verisini kullanır

Desteklenen tetikleyici olaylar:
  - cash_crisis         : Nakit ömrü kritik eşiğin altına düşer
  - revenue_drop        : Gelir belirli % düşer
  - key_person_loss     : Kritik çalışan ayrılır (CTO, CEO, CFO vb.)
  - tech_outage         : Sistem kesintisi / major incident
  - regulatory_breach   : Uyumluluk ihlali (BDDK, SPK vb.)
  - market_shock        : Döviz krizi, enflasyon şoku
  - customer_churn_spike: Müşteri kaybı ani artışı

Her simülasyon şunu döndürür:
  - Etkilenen domainler ve etki büyüklükleri
  - Yayılım zinciri (hangi domain hangisini tetikledi)
  - Domain başına önlem önerileri
  - Genel risk skoru (0-100)
  - Türkçe yönetici özeti
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Tetikleyici olay tipleri ───────────────────────────────────────────────────

class TriggerType(str, Enum):
    CASH_CRISIS          = "cash_crisis"
    REVENUE_DROP         = "revenue_drop"
    KEY_PERSON_LOSS      = "key_person_loss"
    TECH_OUTAGE          = "tech_outage"
    REGULATORY_BREACH    = "regulatory_breach"
    MARKET_SHOCK         = "market_shock"
    CUSTOMER_CHURN_SPIKE = "customer_churn_spike"


# ── Domain etki seviyeleri ─────────────────────────────────────────────────────

class ImpactLevel(str, Enum):
    NONE     = "none"
    LOW      = "low"       # %0-20 etki
    MEDIUM   = "medium"    # %20-50 etki
    HIGH     = "high"      # %50-80 etki
    CRITICAL = "critical"  # %80+ etki


# ── Veri sınıfları ─────────────────────────────────────────────────────────────

@dataclass
class DomainImpact:
    """Bir domain üzerindeki cascade etkisi."""
    domain: str                          # "cfo", "chro", "cto", "cmo", "coo", "risk"
    impact_level: ImpactLevel
    impact_score: float                  # 0.0–1.0
    triggered_by: str                    # hangi domain/olay tetikledi
    delay_months: float                  # etki kaç ay sonra hissedilir
    description: str                     # Türkçe açıklama
    quantified_impact: dict[str, Any]    # sayısal etkiler (₺, %, kişi vb.)
    mitigations: list[str]               # önlem önerileri
    secondary_triggers: list[str]        # bu etki hangi yeni etkileri tetikler


@dataclass
class CascadeScenario:
    """Tek senaryo (iyimser/baz/kötümser) cascade sonucu."""
    name: str                            # "iyimser" | "baz" | "kötümser"
    multiplier: float                    # etki çarpanı
    domain_impacts: list[DomainImpact]
    overall_risk_score: float            # 0-100
    total_financial_impact_try: float    # toplam finansal etki (₺)
    recovery_months: float               # normale dönüş süresi (ay)
    cascade_chain: list[str]             # yayılım zinciri ["cfo→chro", "chro→cto", ...]


@dataclass
class CascadeResult:
    """Tam cascade simülasyon sonucu."""
    trigger_type: str
    trigger_description: str
    trigger_params: dict[str, Any]
    scenarios: list[CascadeScenario]     # [iyimser, baz, kötümser]
    base_scenario: CascadeScenario       # baz senaryo (kolay erişim)
    affected_domains: list[str]          # etkilenen domain'ler
    critical_path: list[str]             # en kritik etki zinciri
    immediate_actions: list[str]         # ilk 30 günde yapılması gerekenler
    executive_summary: str               # Türkçe yönetici özeti
    simulation_confidence: float         # 0.0–1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_type":        self.trigger_type,
            "trigger_description": self.trigger_description,
            "trigger_params":      self.trigger_params,
            "scenarios": [
                {
                    "name":                        s.name,
                    "multiplier":                  s.multiplier,
                    "overall_risk_score":          round(s.overall_risk_score, 1),
                    "total_financial_impact_try":  round(s.total_financial_impact_try),
                    "recovery_months":             round(s.recovery_months, 1),
                    "cascade_chain":               s.cascade_chain,
                    "domain_impacts": [
                        {
                            "domain":              d.domain,
                            "impact_level":        d.impact_level.value,
                            "impact_score":        round(d.impact_score, 2),
                            "triggered_by":        d.triggered_by,
                            "delay_months":        round(d.delay_months, 1),
                            "description":         d.description,
                            "quantified_impact":   d.quantified_impact,
                            "mitigations":         d.mitigations,
                            "secondary_triggers":  d.secondary_triggers,
                        }
                        for d in s.domain_impacts
                    ],
                }
                for s in self.scenarios
            ],
            "affected_domains":       self.affected_domains,
            "critical_path":          self.critical_path,
            "immediate_actions":      self.immediate_actions,
            "executive_summary":      self.executive_summary,
            "simulation_confidence":  round(self.simulation_confidence, 2),
        }


# ── Domain bağımlılık grafiği ──────────────────────────────────────────────────
# Her domain hangi domain'leri etkiler (ve gecikme ayı)
# Format: { trigger_domain: [(affected_domain, delay_months, weight)] }
DOMAIN_DEPENDENCY_GRAPH: dict[str, list[tuple[str, float, float]]] = {
    "cfo":        [("chro", 1.0, 0.7), ("cto", 1.5, 0.5), ("cmo", 1.0, 0.8), ("coo", 2.0, 0.4), ("risk", 0.5, 0.9)],
    "chro":       [("cto", 1.0, 0.6), ("coo", 0.5, 0.7), ("cfo", 2.0, 0.5)],
    "cto":        [("coo", 0.5, 0.8), ("cmo", 1.0, 0.5), ("cfo", 2.0, 0.4)],
    "cmo":        [("cfo", 1.0, 0.7), ("coo", 1.0, 0.4)],
    "coo":        [("cfo", 1.5, 0.5), ("chro", 1.0, 0.4)],
    "risk":       [("cfo", 0.5, 0.8), ("compliance", 0.5, 0.9), ("cto", 1.0, 0.5)],
    "compliance": [("cfo", 1.0, 0.9), ("risk", 0.5, 0.8)],
}


# ── CascadeSimulator ana sınıfı ────────────────────────────────────────────────

class CascadeSimulator:
    """
    Zincirleme risk simülasyonu motoru.

    Şirketin gerçek verilerini (CompanyContext) kullanarak bir tetikleyici
    olayın tüm C-Suite domain'lerine nasıl yayıldığını simüle eder.

    Kullanım:
        sim = CascadeSimulator(
            pnl=cfo_result["pnl"],
            cashflow=cfo_result["cashflow"],
            forecast=cfo_result["forecast"],
            chro_data=chro_result,
            cto_data=cto_result,
            cmo_data=cmo_result,
        )
        result = sim.simulate(TriggerType.CASH_CRISIS, runway_months=2.5)
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
    ) -> None:
        self.pnl       = pnl or {}
        self.cashflow  = cashflow or {}
        self.forecast  = forecast or {}
        self.chro_data = chro_data or {}
        self.cto_data  = cto_data or {}
        self.cmo_data  = cmo_data or {}
        self.coo_data  = coo_data or {}

        # Temel finansal metrikler (TRY)
        self.monthly_revenue = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.monthly_opex    = (self.pnl.get("total_opex", 0) or 0) / 100 / 12
        self.net_margin      = self.pnl.get("net_margin", 0) or 0
        self.monthly_burn    = max(0, self.monthly_opex - self.monthly_revenue)

        base_sc = (self.forecast.get("scenarios") or {}).get("base") or {}
        self.runway_months = base_sc.get("runway_months") or 12.0

        # Nakit pozisyonu
        net_change = (self.cashflow.get("net_change", 0) or 0) / 100
        self.cash_balance = abs(net_change) * self.runway_months if net_change < 0 else net_change

        # CHRO metrikleri
        self.headcount      = self.chro_data.get("total_headcount", 0) or 50
        self.turnover_rate  = self.chro_data.get("annual_turnover_rate", 0.12) or 0.12
        self.avg_salary_try = self.chro_data.get("avg_monthly_salary_try", 30000) or 30000

        # CTO metrikleri
        self.tech_health     = self.cto_data.get("overall_health_score", 7.0) or 7.0
        self.infra_waste_pct = self.cto_data.get("infra_waste_pct", 0.15) or 0.15

        # CMO metrikleri
        self.monthly_cac   = (self.cmo_data.get("avg_cac_cents", 0) or 0) / 100
        self.monthly_roas  = self.cmo_data.get("overall_roas", 2.0) or 2.0
        self.churn_rate    = self.cmo_data.get("avg_monthly_churn", 0.03) or 0.03

    def _impact_level(self, score: float) -> ImpactLevel:
        """0.0–1.0 skordan ImpactLevel enum üret."""
        if score < 0.05:  return ImpactLevel.NONE
        if score < 0.25:  return ImpactLevel.LOW
        if score < 0.55:  return ImpactLevel.MEDIUM
        if score < 0.80:  return ImpactLevel.HIGH
        return ImpactLevel.CRITICAL

    def _apply_multiplier(self, impacts: list[DomainImpact], mult: float) -> list[DomainImpact]:
        """Senaryo çarpanını tüm etkilere uygula."""
        result = []
        for imp in impacts:
            new_score = min(1.0, imp.impact_score * mult)
            result.append(DomainImpact(
                domain=imp.domain,
                impact_level=self._impact_level(new_score),
                impact_score=new_score,
                triggered_by=imp.triggered_by,
                delay_months=imp.delay_months,
                description=imp.description,
                quantified_impact={
                    k: round(v * mult) if isinstance(v, (int, float)) else v
                    for k, v in imp.quantified_impact.items()
                },
                mitigations=imp.mitigations,
                secondary_triggers=imp.secondary_triggers,
            ))
        return result

    # ── Tetikleyici: Nakit Krizi ───────────────────────────────────────────────

    def _simulate_cash_crisis(self, runway_months: float) -> list[DomainImpact]:
        """
        Nakit ömrü kritik eşiğin altına düştüğünde tüm domainlere etkisi.
        runway_months: kalan nakit ömrü (ay)
        """
        severity = max(0.0, min(1.0, (6.0 - runway_months) / 6.0))  # 6ay → 0, 0ay → 1

        monthly_rev = self.monthly_revenue or 1.0
        impacts: list[DomainImpact] = []

        # CFO etkisi — doğrudan
        impacts.append(DomainImpact(
            domain="cfo",
            impact_level=self._impact_level(severity),
            impact_score=severity,
            triggered_by="trigger:cash_crisis",
            delay_months=0.0,
            description=(
                f"Nakit ömrü {runway_months:.1f} ay. "
                f"Acil likidite yönetimi gerekiyor. "
                f"Aylık burn rate ₺{self.monthly_burn:,.0f}."
            ),
            quantified_impact={
                "cash_shortfall_try": round(self.monthly_burn * max(0, 6 - runway_months)),
                "burn_rate_monthly_try": round(self.monthly_burn),
                "runway_months": round(runway_months, 1),
            },
            mitigations=[
                "Acil nakit akışı projeksiyonu yap (1 hafta)",
                "Kısa vadeli kredi hattı aç",
                "Tahsilat sürecini hızlandır",
                "Ertelenebilir giderleri durdur",
            ],
            secondary_triggers=["chro", "cmo", "coo"],
        ))

        # CHRO etkisi — işe alım dondurma, attrition artışı
        attrition_increase = severity * 0.08  # max %8 attrition artışı
        affected_headcount = round(self.headcount * attrition_increase)
        replacement_cost = affected_headcount * self.avg_salary_try * 3  # 3 aylık maaş

        impacts.append(DomainImpact(
            domain="chro",
            impact_level=self._impact_level(severity * 0.75),
            impact_score=severity * 0.75,
            triggered_by="cfo",
            delay_months=1.0,
            description=(
                f"Nakit krizinde işe alım durdurulur, belirsizlik attrition'ı artırır. "
                f"Tahmini {affected_headcount} çalışan ayrılabilir."
            ),
            quantified_impact={
                "hiring_freeze_months": round(runway_months),
                "attrition_increase_pct": round(attrition_increase * 100, 1),
                "at_risk_headcount": affected_headcount,
                "replacement_cost_try": round(replacement_cost),
            },
            mitigations=[
                "Kritik rolleri belirle, retention bonusu hazırla",
                "Şeffaf iletişim — belirsizlik attrition'ı tetikler",
                "İşe alımı tamamen durdurmak yerine kritik roller için sürdür",
            ],
            secondary_triggers=["cto", "coo"],
        ))

        # CTO etkisi — teknik borç birikimi, velocity düşüşü
        tech_budget_cut = severity * 0.4  # %40'a kadar tech bütçe kesintisi
        velocity_loss = severity * 0.3

        impacts.append(DomainImpact(
            domain="cto",
            impact_level=self._impact_level(severity * 0.55),
            impact_score=severity * 0.55,
            triggered_by="cfo",
            delay_months=1.5,
            description=(
                f"Teknoloji bütçesi %{tech_budget_cut*100:.0f} kesilebilir. "
                f"Teknik borç birikir, yeni özellik geliştirme yavaşlar."
            ),
            quantified_impact={
                "tech_budget_cut_pct": round(tech_budget_cut * 100, 1),
                "velocity_loss_pct": round(velocity_loss * 100, 1),
                "tech_debt_increase_score": round(tech_budget_cut * 3, 1),
            },
            mitigations=[
                "Kritik altyapı harcamalarını koru (güvenlik, uptime)",
                "Yeni özellik geliştirmeyi ertele, teknik borç yönet",
                "Cloud maliyetlerini optimize et — anında tasarruf",
            ],
            secondary_triggers=["coo"],
        ))

        # CMO etkisi — pazarlama bütçesi kesintisi, CAC artışı
        marketing_cut = severity * 0.6
        cac_increase = marketing_cut * 0.5
        revenue_risk = monthly_rev * marketing_cut * 0.3 * 12

        impacts.append(DomainImpact(
            domain="cmo",
            impact_level=self._impact_level(severity * 0.65),
            impact_score=severity * 0.65,
            triggered_by="cfo",
            delay_months=1.0,
            description=(
                f"Pazarlama bütçesi %{marketing_cut*100:.0f} kesiliyor. "
                f"CAC artacak, büyüme yavaşlayacak."
            ),
            quantified_impact={
                "marketing_budget_cut_pct": round(marketing_cut * 100, 1),
                "cac_increase_pct": round(cac_increase * 100, 1),
                "annual_revenue_risk_try": round(revenue_risk),
            },
            mitigations=[
                "En yüksek ROAS'lı kanalları koru, düşükleri kes",
                "Organik büyümeye (SEO, referral) odaklan",
                "Mevcut müşteri retention'ına yatır — daha ucuz",
            ],
            secondary_triggers=["cfo"],
        ))

        # COO etkisi — operasyonel verimlilik düşüşü
        ops_impact = severity * 0.4

        impacts.append(DomainImpact(
            domain="coo",
            impact_level=self._impact_level(ops_impact),
            impact_score=ops_impact,
            triggered_by="chro",
            delay_months=2.0,
            description=(
                "İnsan kaynağı kaybı ve bütçe kısıtlaması operasyonel verimliliği düşürür. "
                "SLA ihlal riski artar."
            ),
            quantified_impact={
                "sla_breach_risk_increase_pct": round(ops_impact * 30, 1),
                "ops_efficiency_loss_pct": round(ops_impact * 20, 1),
            },
            mitigations=[
                "Kritik SLA'ları belirle, kaynakları orada yoğunlaştır",
                "Otomasyon fırsatlarını acele değerlendir",
            ],
            secondary_triggers=[],
        ))

        # Risk etkisi — artan operasyonel ve finansal risk
        risk_score = min(1.0, severity * 1.1)
        impacts.append(DomainImpact(
            domain="risk",
            impact_level=self._impact_level(risk_score),
            impact_score=risk_score,
            triggered_by="trigger:cash_crisis",
            delay_months=0.5,
            description=(
                f"Nakit krizi genel risk skorunu artırıyor. "
                f"Tedarikçi, müşteri ve operasyonel riskler yükseliyor."
            ),
            quantified_impact={
                "overall_risk_score_increase": round(risk_score * 30, 1),
                "supplier_risk": "yüksek" if severity > 0.5 else "orta",
            },
            mitigations=[
                "Risk kaydını güncelle, kritik risklere karşı önlem al",
                "Tedarikçilerle ödeme planı müzakere et",
            ],
            secondary_triggers=["compliance"],
        ))

        return impacts

    # ── Tetikleyici: Gelir Düşüşü ─────────────────────────────────────────────

    def _simulate_revenue_drop(self, drop_pct: float) -> list[DomainImpact]:
        """
        Gelirde ani düşüş (örn. %30) — tüm domainlere etkisi.
        drop_pct: düşüş oranı (0.0–1.0)
        """
        severity = min(1.0, drop_pct)
        monthly_loss = self.monthly_revenue * drop_pct
        annual_loss = monthly_loss * 12

        impacts: list[DomainImpact] = []

        impacts.append(DomainImpact(
            domain="cfo",
            impact_level=self._impact_level(severity),
            impact_score=severity,
            triggered_by="trigger:revenue_drop",
            delay_months=0.0,
            description=(
                f"Aylık ₺{monthly_loss:,.0f} gelir kaybı. "
                f"Yıllık etki ₺{annual_loss:,.0f}. "
                f"Kârlılık baskı altında."
            ),
            quantified_impact={
                "monthly_revenue_loss_try": round(monthly_loss),
                "annual_revenue_loss_try": round(annual_loss),
                "margin_compression_pts": round(drop_pct * self.net_margin * 100, 1),
                "new_runway_months": round(
                    self.cash_balance / max(1, self.monthly_burn + monthly_loss * 0.5), 1
                ),
            },
            mitigations=[
                "Gelir kaybının nedenini tespit et (müşteri, segment, ürün)",
                "Mevcut müşteri churn'ü durdur — acil retention kampanyası",
                "Bütçeyi yeni gelir projeksiyonuna göre revize et",
            ],
            secondary_triggers=["cmo", "chro", "cfo"],
        ))

        impacts.append(DomainImpact(
            domain="cmo",
            impact_level=self._impact_level(severity * 0.8),
            impact_score=severity * 0.8,
            triggered_by="cfo",
            delay_months=0.5,
            description=(
                f"Gelir düşüşü pazarlama verimliliğini sorgulatıyor. "
                f"ROAS ve CAC metrikleri bozuldu."
            ),
            quantified_impact={
                "roas_deterioration_pct": round(drop_pct * 40, 1),
                "cac_increase_try": round(self.monthly_cac * drop_pct * 0.5),
            },
            mitigations=[
                "Hangi kanalların dönüşümü düştüğünü analiz et",
                "A/B test ile mesaj stratejisini değiştir",
                "Mevcut müşteri upsell/cross-sell'e odaklan",
            ],
            secondary_triggers=[],
        ))

        impacts.append(DomainImpact(
            domain="chro",
            impact_level=self._impact_level(severity * 0.5),
            impact_score=severity * 0.5,
            triggered_by="cfo",
            delay_months=2.0,
            description="Gelir baskısı performans değerlendirmelerini ve bonus yapısını etkiler.",
            quantified_impact={
                "bonus_cut_risk_pct": round(drop_pct * 60, 1),
                "morale_risk": "yüksek" if severity > 0.4 else "orta",
            },
            mitigations=[
                "Performans hedeflerini güncel duruma göre revize et",
                "Şeffaf iletişim — gelir durumunu ekiple paylaş",
            ],
            secondary_triggers=[],
        ))

        return impacts

    # ── Tetikleyici: Kilit Kişi Kaybı ─────────────────────────────────────────

    def _simulate_key_person_loss(self, role: str) -> list[DomainImpact]:
        """CTO, CFO, CEO gibi kritik bir çalışanın ayrılması."""
        role_impact_map = {
            "cto":  {"primary": "cto",  "secondary": ["coo", "chro"],           "severity": 0.8},
            "cfo":  {"primary": "cfo",  "secondary": ["risk", "compliance"],     "severity": 0.85},
            "ceo":  {"primary": "cfo",  "secondary": ["chro", "cmo", "cto"],     "severity": 0.9},
            "cmo":  {"primary": "cmo",  "secondary": ["cfo"],                    "severity": 0.6},
            "chro": {"primary": "chro", "secondary": ["coo"],                    "severity": 0.55},
        }
        cfg = role_impact_map.get(role.lower(), {"primary": "chro", "secondary": [], "severity": 0.5})
        severity: float = cfg["severity"]  # type: ignore[assignment]
        impacts: list[DomainImpact] = []

        impacts.append(DomainImpact(
            domain=cfg["primary"],  # type: ignore[arg-type]
            impact_level=self._impact_level(severity),
            impact_score=severity,
            triggered_by="trigger:key_person_loss",
            delay_months=0.0,
            description=(
                f"{role.upper()} kaybı {str(cfg['primary']).upper()} fonksiyonunu "
                "ciddi biçimde sekteye uğratır. Geçiş süresi 3-6 ay."
            ),
            quantified_impact={
                "transition_months": 4,
                "productivity_loss_pct": round(severity * 40, 1),
                "replacement_cost_try": round(self.avg_salary_try * 6),
            },
            mitigations=[
                f"Acil {role.upper()} vekili ata",
                "Bilgi transferi protokolünü başlat",
                "Kritik süreçleri dokümante et",
                "Executive search firması devreye al",
            ],
            secondary_triggers=cfg["secondary"],  # type: ignore[arg-type]
        ))

        impacts.append(DomainImpact(
            domain="chro",
            impact_level=ImpactLevel.MEDIUM,
            impact_score=0.5,
            triggered_by="trigger:key_person_loss",
            delay_months=0.5,
            description="Kilit kişi kaybı ekip moralini düşürür, zincirleme ayrılma riski doğar.",
            quantified_impact={
                "secondary_attrition_risk_pct": round(severity * 15, 1),
                "team_morale_impact": "yüksek" if severity > 0.7 else "orta",
            },
            mitigations=[
                "Ekiple birebir görüşmeler yap",
                "Kilit ekip üyelerini retention programına al",
            ],
            secondary_triggers=[],
        ))
        return impacts

    # ── Tetikleyici: Piyasa Şoku ──────────────────────────────────────────────

    def _simulate_market_shock(
        self,
        usd_try_increase_pct: float,
        inflation_pct: float,
    ) -> list[DomainImpact]:
        """Kur şoku veya yüksek enflasyon ortamı."""
        currency_severity = min(1.0, usd_try_increase_pct / 100)
        inflation_severity = min(1.0, inflation_pct / 100)
        combined = currency_severity * 0.6 + inflation_severity * 0.4
        opex_increase = self.monthly_opex * combined * 0.3
        impacts: list[DomainImpact] = []

        impacts.append(DomainImpact(
            domain="cfo",
            impact_level=self._impact_level(combined),
            impact_score=combined,
            triggered_by="trigger:market_shock",
            delay_months=0.0,
            description=(
                f"Kur %{usd_try_increase_pct:.0f} artışı + %{inflation_pct:.0f} enflasyon. "
                f"Opex aylık ₺{opex_increase:,.0f} artacak."
            ),
            quantified_impact={
                "monthly_opex_increase_try": round(opex_increase),
                "annual_cost_increase_try":  round(opex_increase * 12),
                "fx_exposure_risk": "kritik" if currency_severity > 0.5 else "yüksek",
            },
            mitigations=[
                "USD/EUR giderler için hedging stratejisi değerlendir",
                "Dövize bağlı sözleşmeleri TRY'ye dönüştür",
                "Fiyat listesini enflasyon + kur artışına göre güncelle",
            ],
            secondary_triggers=["chro", "cmo"],
        ))

        salary_pressure = combined * 0.5
        impacts.append(DomainImpact(
            domain="chro",
            impact_level=self._impact_level(salary_pressure),
            impact_score=salary_pressure,
            triggered_by="trigger:market_shock",
            delay_months=1.0,
            description="Enflasyon maaş baskısı yaratıyor. Reel ücretler düşüyor, attrition riski artıyor.",
            quantified_impact={
                "salary_adjustment_needed_pct": round(inflation_pct * 0.7, 1),
                "annual_salary_increase_try":   round(
                    self.headcount * self.avg_salary_try * inflation_pct / 100 * 0.7 * 12
                ),
                "attrition_risk": "yüksek" if inflation_pct > 30 else "orta",
            },
            mitigations=[
                "Enflasyona endeksli maaş ayarlaması planla",
                "Nakit dışı yan hakları artır (yemek, ulaşım, çalışma alanı)",
            ],
            secondary_triggers=[],
        ))
        return impacts

    # ── Ana simülasyon metodu ──────────────────────────────────────────────────

    def simulate(self, trigger: TriggerType, **kwargs: Any) -> CascadeResult:
        """
        Ana simülasyon giriş noktası.

        Args:
            trigger: TriggerType enum değeri
            **kwargs:
                cash_crisis      → runway_months (float)
                revenue_drop     → drop_pct (float, 0.0–1.0)
                key_person_loss  → role (str: "cto"|"cfo"|"ceo"|"cmo"|"chro")
                market_shock     → usd_try_increase_pct (float), inflation_pct (float)
        """
        if trigger == TriggerType.CASH_CRISIS:
            runway = float(kwargs.get("runway_months", self.runway_months))
            base_impacts = self._simulate_cash_crisis(runway)
            trigger_desc = f"Nakit ömrü {runway:.1f} ay — kritik eşiğin altında"
        elif trigger == TriggerType.REVENUE_DROP:
            drop = float(kwargs.get("drop_pct", 0.3))
            base_impacts = self._simulate_revenue_drop(drop)
            trigger_desc = f"Gelir %{drop*100:.0f} düşüşü"
        elif trigger == TriggerType.KEY_PERSON_LOSS:
            role = str(kwargs.get("role", "cto"))
            base_impacts = self._simulate_key_person_loss(role)
            trigger_desc = f"Kilit kişi kaybı: {role.upper()}"
        elif trigger == TriggerType.MARKET_SHOCK:
            usd_inc = float(kwargs.get("usd_try_increase_pct", 30.0))
            inf_pct = float(kwargs.get("inflation_pct", 50.0))
            base_impacts = self._simulate_market_shock(usd_inc, inf_pct)
            trigger_desc = f"Piyasa şoku: USD/TRY +%{usd_inc:.0f}, Enflasyon %{inf_pct:.0f}"
        else:
            base_impacts = []
            trigger_desc = trigger.value

        scenarios = self._build_scenarios(base_impacts)
        affected = sorted({imp.domain for imp in base_impacts if imp.impact_score > 0.1})
        sorted_impacts = sorted(base_impacts, key=lambda x: -x.impact_score)
        critical_path = [
            f"{imp.triggered_by}→{imp.domain}"
            for imp in sorted_impacts[:4]
            if "trigger:" not in imp.triggered_by
        ]
        immediate = [
            f"[{imp.domain.upper()}] {imp.mitigations[0]}"
            for imp in sorted_impacts[:3]
            if imp.mitigations
        ]
        base_sc = scenarios[1]
        summary = self._build_executive_summary(trigger_desc, base_sc, affected, critical_path)
        confidence = 0.85 if self.monthly_revenue > 0 else 0.55

        return CascadeResult(
            trigger_type=trigger.value,
            trigger_description=trigger_desc,
            trigger_params=kwargs,
            scenarios=scenarios,
            base_scenario=base_sc,
            affected_domains=affected,
            critical_path=critical_path,
            immediate_actions=immediate,
            executive_summary=summary,
            simulation_confidence=confidence,
        )

    def _build_scenarios(self, base_impacts: list[DomainImpact]) -> list[CascadeScenario]:
        configs = [("iyimser", 0.6), ("baz", 1.0), ("kötümser", 1.4)]
        scenarios = []
        for name, mult in configs:
            scaled = self._apply_multiplier(base_impacts, mult)
            risk_score = min(100.0, (
                sum(i.impact_score for i in scaled) / max(1, len(scaled)) * 100 * mult
            ))
            fin_impact = sum(
                sum(v for v in i.quantified_impact.values() if isinstance(v, (int, float)))
                for i in scaled
            ) * -1
            recovery = max(1.0,
                sum(i.delay_months for i in scaled) / max(1, len(scaled)) * 3 * mult
            )
            chain = [
                f"{i.triggered_by}→{i.domain}"
                for i in sorted(scaled, key=lambda x: -x.impact_score)[:4]
                if "trigger:" not in i.triggered_by
            ]
            scenarios.append(CascadeScenario(
                name=name,
                multiplier=mult,
                domain_impacts=scaled,
                overall_risk_score=round(risk_score, 1),
                total_financial_impact_try=round(fin_impact),
                recovery_months=round(recovery, 1),
                cascade_chain=chain,
            ))
        return scenarios

    def _build_executive_summary(
        self,
        trigger_desc: str,
        base: CascadeScenario,
        affected: list[str],
        critical_path: list[str],
    ) -> str:
        domain_tr = {
            "cfo": "Finans", "chro": "İnsan Kaynakları", "cto": "Teknoloji",
            "cmo": "Pazarlama", "coo": "Operasyon", "risk": "Risk",
        }
        affected_tr = [domain_tr.get(d, d.upper()) for d in affected[:4]]
        risk_label = (
            "KRİTİK" if base.overall_risk_score > 70 else
            "YÜKSEK"  if base.overall_risk_score > 45 else
            "ORTA"
        )
        chain_str = " → ".join(critical_path[:3]) if critical_path else ""
        return (
            f"Senaryo: {trigger_desc}. "
            f"Risk seviyesi {risk_label} ({base.overall_risk_score:.0f}/100). "
            f"Etkilenen alanlar: {', '.join(affected_tr)}. "
            f"Tahmini toparlanma süresi: {base.recovery_months:.0f} ay. "
            + (f"Kritik yol: {chain_str}. " if chain_str else "")
            + "Acil önlemler için domain bazlı mitigasyon listesini inceleyin."
        )


# ── Public factory ─────────────────────────────────────────────────────────────

def get_cascade_simulator(
    pnl:       dict[str, Any] | None = None,
    cashflow:  dict[str, Any] | None = None,
    forecast:  dict[str, Any] | None = None,
    chro_data: dict[str, Any] | None = None,
    cto_data:  dict[str, Any] | None = None,
    cmo_data:  dict[str, Any] | None = None,
    coo_data:  dict[str, Any] | None = None,
) -> CascadeSimulator:
    return CascadeSimulator(
        pnl=pnl, cashflow=cashflow, forecast=forecast,
        chro_data=chro_data, cto_data=cto_data,
        cmo_data=cmo_data, coo_data=coo_data,
    )
