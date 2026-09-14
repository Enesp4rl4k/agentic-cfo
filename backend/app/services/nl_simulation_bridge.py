"""
NL → Simulation Bridge

Dogal dil sorgusunu uygun simulasyon motoruna yonlendirir.

Desteklenen intent'ler:
  simulation_headcount  : "5 muhendis isse alırsam ne olur?"
  simulation_marketing  : "Pazarlama butcesini 2 katina cikarsak?"
  simulation_cascade    : "Nakit 3 ayda biterse ne olur?"
  simulation_cost_cut   : "Giderleri %20 azaltırsak?"
  simulation_price      : "Fiyati %15 artırsak?"
  simulation_scenario   : "Kira ofisi kapatsak hibrite gecessek?"

DDIA: bu bridge bir "materialized view" gibi calisir.
NL query'yi parse eder, parametreleri cikarir, ilgili servise yonlendirir.
Sonucu kullaniciya Turkce olarak dondurur.

Kullanim:
    bridge = NLSimulationBridge()
    result = await bridge.process(
        query="5 muhendis isse alırsam 12 ayda ne olur?",
        org_id="org-123",
        job_id="cfo-456",
    )
    # result.simulation_type = "headcount"
    # result.answer = "5 mühendis eklenmesi durumunda..."
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class IntentResult(str):
    """String subclass that also behaves as a (intent, confidence) tuple when unpacked."""
    confidence: float

    def __new__(cls, intent: str, confidence: float = 0.0):
        obj = str.__new__(cls, intent)
        obj.confidence = confidence
        return obj

    def __iter__(self):
        yield str(self)
        yield self.confidence

    def __getitem__(self, item):
        if item == 0:
            return str(self)
        if item == 1:
            return self.confidence
        return super().__getitem__(item)


# ── Simulasyon sorgu sonucu ────────────────────────────────────────────────────


@dataclass
class SimulationQueryResult:
    """NL sorgusu → simulasyon sonucu."""
    original_query:  str
    simulation_type: str      # "headcount" | "marketing" | "cascade" | "cost_cut" | "price" | "unknown"
    intent_confidence: float  # 0-1
    extracted_params: dict[str, Any]
    simulation_result: dict[str, Any] | None
    answer:          str      # Turkce aciklama
    follow_up_questions: list[str]
    error:           str | None = None


# ── NL Simulation Bridge ──────────────────────────────────────────────────────

class NLSimulationBridge:
    """
    NL sorgusu → simulasyon motoru koprusu.

    Adimlar:
      1. Intent classification (rule-based, zero LLM cost)
      2. Entity extraction (sayi, yuzde, sure)
      3. Motor yonlendirme (CF engine veya cascade engine)
      4. Turkce yanit uretimi (LLM veya template)
    """

    # ── Intent tespiti ─────────────────────────────────────────────────────────

    _HEADCOUNT_PATTERNS = [
        r"(\d+)\s*(?:muhendis|mühendis|kisi|kişi|calisan|çalışan|personel|eleman|developer|yazilimci|yazılımcı|hire|işe\s*al|isse\s*al|alsak|alsam|alalım|alalim)",
        r"(?:kadro|headcount|ekip).{0,20}(?:artir|artır|buyut|büyüt|genislet|genişlet|ekle|al)",
        r"(?:yeni|ek).{0,10}(?:muhendis|mühendis|developer|yazilimci|yazılımcı|satis|satış)",
        r"(\d+)\s*(?:kisi|kişi|pers).{0,20}(?:cikar|çıkar|azalt|isik|layoff)",
        r"(?:kadro|headcount).{0,20}(?:azalt|kisalt|kısalt|dusur|düşür)",
    ]

    _MARKETING_PATTERNS = [
        r"(?:pazarlama|marketing|reklam|ads).{0,30}(?:artir|artır|yuksel|yüksel|artis|artış|\d+x|katina|katına)",
        r"(?:butce|bütçe|budget).{0,20}(?:pazarlama|marketing)",
        r"(?:roas|cac|musteri\s*edinme|müşteri\s*edinme).{0,20}(?:iyilestirsek|iyileştirsek|artirsa|artırsa)",
    ]

    _CASCADE_PATTERNS = [
        r"(?:nakit|para|cash).{0,20}(?:biterse|tukensek|tükensek|kalmazsa|kriz)",
        r"(?:runway|nakit\s*omru|nakit\s*ömrü).{0,20}(?:\d+|biterse)",
        r"(?:gelir|revenue).{0,20}(?:duserse|düşerse|azalirsa|azalırsa|kaybolursa)",
        r"(?:ayrılırsa|ayrilirsa|giderse|kaybetsek).{0,20}(?:cto|ceo|cfo|kto)",
        r"(?:kur|dolar|euro).{0,20}(?:artarsa|ciksa|çıksa|yukselirse|yükselirse)",
        r"(?:enflasyon|inflation).{0,20}(?:\d+|artarsa|devam)",
    ]

    _COST_CUT_PATTERNS = [
        r"(?:gider|maliyet|cost|harcama).{0,20}(?:azalt|kes|dusur|düşür|duşür|kisit|kısıt)",
        r"(?:%\d+|yuzde\s*\d+|yüzde\s*\d+).{0,20}(?:tasarruf|kes|azalt)",
        r"(?:ofis|kira|yazilim|yazılım|abonelik).{0,20}(?:kapat|iptal|vazgec|vazgeç)",
    ]

    _PRICE_PATTERNS = [
        r"(?:fiyat|price|ucret|ücret|abonelik).{0,20}(?:artir|artır|yuksel|yüksel|zam|raise)",
        r"(?:%\d+|yuzde\s*\d+|yüzde\s*\d+).{0,20}(?:fiyat|zam|artis|artış)",
    ]


    def classify_intent(self, query: str) -> IntentResult:
        """Intent siniflandir ve guven skoru dondur."""
        q = (query or "").replace("İ", "i").replace("I", "ı").replace("Ş", "ş").replace("Ğ", "ğ").replace("Ü", "ü").replace("Ö", "ö").replace("Ç", "ç").lower().strip()
        if not q:
            return IntentResult("unknown", 0.0)

        checks = [
            ("headcount", self._HEADCOUNT_PATTERNS, 0.85),
            ("cascade",   self._CASCADE_PATTERNS,   0.80),
            ("marketing", self._MARKETING_PATTERNS, 0.80),
            ("cost_cut",  self._COST_CUT_PATTERNS,  0.75),
            ("price",     self._PRICE_PATTERNS,     0.75),
        ]

        for intent, patterns, base_conf in checks:
            for pattern in patterns:
                if re.search(pattern, q, re.IGNORECASE):
                    return IntentResult(intent, base_conf)

        return IntentResult("unknown", 0.0)

    def extract_entities(self, query: str, intent: str | None = None) -> dict[str, Any]:
        """Extract entity parameters from query for compatibility."""
        if intent is None:
            intent = self.classify_intent(query)
        params = self.extract_params(query, str(intent))
        if "count" in params:
            params["headcount_delta"] = params["count"]
        if "pct" in params:
            params["increase_pct"] = params["pct"]
            params["budget_increase_pct"] = params["pct"]
        return params

    def extract_params(self, query: str, intent: str) -> dict[str, Any]:
        """Sorgudan sayisal parametreler cikar."""
        q      = (query or "").replace("İ", "i").replace("I", "ı").replace("Ş", "ş").replace("Ğ", "ğ").replace("Ü", "ü").replace("Ö", "ö").replace("Ç", "ç").lower()
        params: dict[str, Any] = {}

        # Kisi sayisi
        m = re.search(r"(\d+)\s*(?:muhendis|mühendis|kisi|kişi|calisan|çalışan|personel|eleman|developer|yazilimci|yazılımcı|satis|satış|hire)", q)
        if m:
            params["count"] = int(m.group(1))
        elif intent == "headcount":
            m2 = re.search(r"(\d+)", q)
            if m2:
                params["count"] = int(m2.group(1))


        # Yuzde
        m = re.search(r"(%|yuzde)\s*(\d+(?:\.\d+)?)", q)
        if m:
            params["pct"] = float(m.group(2)) / 100
        else:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|yuzde|katina|x)", q)
            if m:
                val = float(m.group(1))
                params["pct"] = val / 100 if val > 1 else val


        # Ay sayisi
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ay|month)", q)
        if m:
            params["months"] = float(m.group(1))

        # TRY tutari
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:k|bin|milyon|tl|try|lira)", q)
        if m:
            val = float(m.group(1))
            unit_str = m.group(0).lower()
            if "milyon" in unit_str:
                val *= 1_000_000
            elif "k" in unit_str or "bin" in unit_str:
                val *= 1_000
            params["amount_try"] = val

        # Rolu tahmin et
        if intent == "headcount":
            for role, keywords in [
                ("engineer", ["muhendis", "developer", "yazilimci", "backend", "frontend", "fullstack"]),
                ("sales",    ["satis", "sales", "account", "bdm"]),
                ("ops",      ["operasyon", "destek", "support", "ops"]),
            ]:
                if any(kw in q for kw in keywords):
                    params["role_type"] = role
                    break

        # Cascade tetikleyici
        if intent == "cascade":
            if any(w in q for w in ["nakit", "para", "cash", "runway"]):
                params["trigger"] = "cash_crisis"
            elif any(w in q for w in ["gelir", "revenue", "satis"]):
                params["trigger"] = "revenue_drop"
            elif any(w in q for w in ["ayrılırsa", "giderse", "cto", "ceo", "cfo"]):
                params["trigger"] = "key_person_loss"
            elif any(w in q for w in ["kur", "dolar", "enflasyon"]):
                params["trigger"] = "market_shock"

        return params

    # ── Motor yonlendirme ──────────────────────────────────────────────────────

    async def _run_headcount_simulation(
        self,
        params:  dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        from app.services.multidomain_counterfactual import get_multidomain_cf

        delta    = params.get("count", 3)
        if "azalt" in str(params.get("_raw_query", "")).lower() or delta < 0:
            delta = -abs(delta)

        engine = get_multidomain_cf(
            pnl      = context.get("pnl"),
            cashflow = context.get("cashflow"),
            forecast = context.get("forecast"),
            chro_data = context.get("chro"),
            cto_data  = context.get("cto"),
        )
        result = engine.analyze_headcount_change(
            delta        = delta,
            role_type    = params.get("role_type", "general"),
            horizon_months = int(params.get("months", 12)),
        )
        return result.to_dict()

    async def _run_marketing_simulation(
        self,
        params:  dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        from app.services.multidomain_counterfactual import get_multidomain_cf

        monthly_rev  = (context.get("pnl", {}).get("revenue", 0) or 0) / 100 / 12
        budget_inc   = params.get("amount_try") or (monthly_rev * params.get("pct", 0.20))
        expected_roas = params.get("pct", 1.0) * 2.5 if params.get("pct") else 2.5

        engine = get_multidomain_cf(
            pnl      = context.get("pnl"),
            cashflow = context.get("cashflow"),
            cmo_data = context.get("cmo"),
        )
        result = engine.analyze_marketing_investment(
            monthly_increase_try = max(budget_inc, 10_000),
            expected_roas        = expected_roas,
        )
        return result.to_dict()

    async def _run_cascade_simulation(
        self,
        params:  dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        from app.services.cascade_simulator import TriggerType, get_cascade_simulator

        trigger_str  = params.get("trigger", "cash_crisis")
        trigger_map  = {
            "cash_crisis":      TriggerType.CASH_CRISIS,
            "revenue_drop":     TriggerType.REVENUE_DROP,
            "key_person_loss":  TriggerType.KEY_PERSON_LOSS,
            "market_shock":     TriggerType.MARKET_SHOCK,
        }
        trigger = trigger_map.get(trigger_str, TriggerType.CASH_CRISIS)

        sim = get_cascade_simulator(
            pnl      = context.get("pnl"),
            cashflow = context.get("cashflow"),
            forecast = context.get("forecast"),
            chro_data = context.get("chro"),
            cto_data  = context.get("cto"),
            cmo_data  = context.get("cmo"),
        )

        kwargs: dict[str, Any] = {}
        if trigger == TriggerType.CASH_CRISIS:
            kwargs["runway_months"] = params.get("months", 3.0)
        elif trigger == TriggerType.REVENUE_DROP:
            kwargs["drop_pct"] = params.get("pct", 0.30)
        elif trigger == TriggerType.KEY_PERSON_LOSS:
            kwargs["role"] = params.get("role_type", "cto")
        elif trigger == TriggerType.MARKET_SHOCK:
            kwargs["usd_try_increase_pct"] = params.get("pct", 30) * 100
            kwargs["inflation_pct"]        = 50

        result = sim.simulate(trigger, **kwargs)
        return result.to_dict()

    async def _run_cost_cut_simulation(
        self,
        params:  dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        from app.services.counterfactual_engine import get_counterfactual_engine

        engine = get_counterfactual_engine(
            pnl      = context.get("pnl"),
            cashflow = context.get("cashflow"),
            forecast = context.get("forecast"),
        )
        result = engine.simulate_cost_reduction(
            target_category = "general",
            reduction_pct   = params.get("pct", 0.20),
        )
        return result.to_dict()

    async def _run_price_simulation(
        self,
        params:  dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        from app.services.counterfactual_engine import get_counterfactual_engine

        engine = get_counterfactual_engine(
            pnl      = context.get("pnl"),
            cashflow = context.get("cashflow"),
        )
        result = engine.simulate_price_increase(
            increase_pct        = params.get("pct", 0.15),
            churn_rate_increase = 0.04,
        )
        return result.to_dict()

    # ── Yanit uretimi ──────────────────────────────────────────────────────────

    def _build_answer(self, intent: str, params: dict[str, Any], result: dict[str, Any]) -> str:
        """Simulasyon sonucundan Turkce yanit uret."""
        if intent == "headcount":
            base = result.get("scenarios", [{}])[1] if result.get("scenarios") else {}
            net  = base.get("net_financial_impact_try", 0)
            sign = "+" if net >= 0 else ""
            count = params.get("count", "?")
            role  = params.get("role_type", "genel")
            answer = (
                f"{count:+d} kişi ({role}) değişiminin 12 aylık analizi tamamlandı. "
                f"Baz senaryoda yıllık net etki: **₺{net:,.0f}** ({sign}{net//1000}K TRY). "
            )
            domain_effects = base.get("domain_effects", [])
            for eff in domain_effects[:2]:
                label   = eff.get("label", "")
                fin_imp = eff.get("financial_impact_try", 0)
                answer += f"{label}: ₺{fin_imp:,.0f}. "

        elif intent == "cascade":
            base    = next((s for s in result.get("scenarios", []) if s.get("name") == "baz"), {})
            score   = base.get("overall_risk_score", 0)
            recovery = base.get("recovery_months", 0)
            answer  = (
                f"Bu risk senaryosunda genel risk skoru **{score:.0f}/100**. "
                f"Tahmini toparlanma: {recovery:.0f} ay. "
                f"{result.get('executive_summary', '')}"
            )

        elif intent == "marketing":
            base = result.get("scenarios", [{}])[1] if result.get("scenarios") else {}
            net  = base.get("net_financial_impact_try", 0)
            answer = (
                f"Pazarlama yatırımı analizi tamamlandı. "
                f"Baz senaryoda yıllık net etki: **₺{net:,.0f}**. "
                f"{result.get('executive_summary', '')}"
            )

        elif intent in ("cost_cut", "price"):
            net  = result.get("base_net_impact", 0)
            be   = result.get("breakeven_months")
            answer = (
                f"{'Maliyet kesintisi' if intent == 'cost_cut' else 'Fiyat artışı'} analizi tamamlandı. "
                f"12 aylık net etki: **₺{net:,.0f}**. "
                + (f"Break-even: {be:.1f} ay. " if be else "")
                + result.get("recommendation", "")
            )
        else:
            answer = "Simulasyon tamamlandı. Detaylar icin sonuclara bakiniz."

        return answer

    def _build_follow_ups(self, intent: str, params: dict[str, Any]) -> list[str]:
        """Takip sorulari oner."""
        suggestions: dict[str, list[str]] = {
            "headcount": [
                "Bu senaryonun CHRO üzerindeki etkisi nedir?",
                "Hangi roller öncelikli işe alınmalı?",
                "Farklı bir onboarding süresi ile ne değişir?",
            ],
            "cascade": [
                "En kötü senaryoda neleri yapabiliriz?",
                "Hangi maliyet kalemleri hızla kesilebilir?",
                "Bu riski azaltmak için ne kadar süre var?",
            ],
            "marketing": [
                "Hangi kanal en yüksek ROAS sağlıyor?",
                "Organik büyümeye odaklanırsak ne olur?",
                "Mevcut müşteri retention'ına yatırsak?",
            ],
            "cost_cut": [
                "Hangi gider kalemlerini kesmek en güvenli?",
                "Bu kesintinin çalışan moraline etkisi?",
                "6 ay yerine 12 ay vadede hesaplarsak?",
            ],
        }
        return suggestions.get(intent, ["Farklı bir senaryo denemek ister misiniz?"])

    # ── Ana işlem metodu ───────────────────────────────────────────────────────

    async def process(
        self,
        query:   str,
        org_id:  str,
        job_id:  str | None = None,
        context: dict[str, Any] | None = None,
    ) -> SimulationQueryResult:
        """
        NL sorguyu isle, simulasyon calistir, Turkce yanit dondur.

        context: CFO sonuclari (pnl, cashflow, forecast, chro, cto, cmo)
        """
        # 1. Intent sınıflandır
        intent, confidence = self.classify_intent(query)

        if intent == "unknown":
            return SimulationQueryResult(
                original_query     = query,
                simulation_type    = "unknown",
                intent_confidence  = 0.0,
                extracted_params   = {},
                simulation_result  = None,
                answer             = (
                    "Bu soruyu bir simülasyon olarak yorumlayamadım. "
                    "Örnek: 'Nakit 3 ayda biterse ne olur?' veya "
                    "'5 mühendis işe alırsam 12 ayda ne olur?'"
                ),
                follow_up_questions = [
                    "Nakit krizi senaryosu için soru sorun",
                    "İşe alım etkisini analiz edin",
                    "Pazarlama bütçesi değişikliği sorun",
                ],
            )

        # 2. Parametreleri cikar
        params = self.extract_params(query, intent)
        params["_raw_query"] = query

        # 3. Context'i yukle (yoksa CompanyContext'ten)
        if context is None and org_id:
            context = await self._load_context(org_id)
        context = context or {}

        # 4. Simulasyonu calistir
        try:
            sim_runners = {
                "headcount": self._run_headcount_simulation,
                "marketing": self._run_marketing_simulation,
                "cascade":   self._run_cascade_simulation,
                "cost_cut":  self._run_cost_cut_simulation,
                "price":     self._run_price_simulation,
            }
            runner         = sim_runners.get(intent)
            sim_result     = await runner(params, context) if runner else None
            answer         = self._build_answer(intent, params, sim_result or {})
            follow_ups     = self._build_follow_ups(intent, params)

            return SimulationQueryResult(
                original_query     = query,
                simulation_type    = intent,
                intent_confidence  = confidence,
                extracted_params   = {k: v for k, v in params.items() if not k.startswith("_")},
                simulation_result  = sim_result,
                answer             = answer,
                follow_up_questions = follow_ups,
            )

        except Exception as exc:
            logger.error("NL Simulation Bridge hatasi: intent=%s err=%s", intent, exc)
            return SimulationQueryResult(
                original_query     = query,
                simulation_type    = intent,
                intent_confidence  = confidence,
                extracted_params   = params,
                simulation_result  = None,
                answer             = f"Simülasyon çalıştırılırken hata oluştu: {exc}",
                follow_up_questions = [],
                error              = str(exc),
            )

    async def _load_context(self, org_id: str) -> dict[str, Any]:
        """CompanyContext'ten veri yukle."""
        try:
            from app.services.company_context import get_company_context
            ctx     = await get_company_context(org_id) or {}
            results = ctx.get("agent_results") or {}
            cfo_r   = results.get("cfo") or {}
            return {
                "pnl":      cfo_r.get("pnl"),
                "cashflow": cfo_r.get("cashflow"),
                "forecast": cfo_r.get("forecast"),
                "chro":     results.get("chro"),
                "cto":      results.get("cto"),
                "cmo":      results.get("cmo"),
            }
        except Exception:
            return {}


# ── Public factory ─────────────────────────────────────────────────────────────

def get_nl_simulation_bridge() -> NLSimulationBridge:
    return NLSimulationBridge()
