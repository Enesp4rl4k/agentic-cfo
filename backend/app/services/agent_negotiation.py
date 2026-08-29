"""
Agent Negotiation Protocol

Agent'larin birbirleriyle muzakere etmesini saglayan mixin ve
somut negotiation senaryolari.

Mimari:
  AgentNegotiator: her agent'a eklenen mixin
    - ask_agent(): baska bir agent'a soru sor, cevap bekle
    - broadcast_finding(): kritik bulguyu tum agent'lara duyur
    - register_responder(): bu agent'in cevaplayabilecegi soru tiplerini kaydet

Somut Senaryolar:
  1. CFO↔CHRO: Nakit krizi → ise alim plani soru/cevap
  2. CFO↔CTO:  Tech butce kisintisi → velocity etkisi soru/cevap
  3. CFO↔CMO:  Dusuk runway → pazarlama ROI sorgusu
  4. CEO←All:  Revize senaryo oncesi tum agent'lardan ozet toplama

Her negotiation round max 10 saniye surer (timeout).
Agent cevap vermezse son bilinen degeri kullanir.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.services.agent_bus import QueryType, get_agent_bus

logger = logging.getLogger(__name__)


# ── Negotiation sonucu ────────────────────────────────────────────────────────

@dataclass
class NegotiationResult:
    """Bir negotiation round'unun sonucu."""
    query_type:    str
    from_agent:    str
    to_agent:      str
    success:       bool
    response_data: dict[str, Any]
    fallback_used: bool   = False   # True ise timeout → fallback kullanildi
    latency_ms:    float  = 0.0


# ── AgentNegotiator Mixin ─────────────────────────────────────────────────────

class AgentNegotiator:
    """
    Her agent'a eklenen negotiation kabiliyeti.

    Kullanim (herhangi bir agent sinifina):
        class CFOAgent(AgentNegotiator):
            ...
            async def run(self, state, config):
                # CHRO'ya sor
                result = await self.ask_agent(
                    to_agent="chro",
                    query_type=QueryType.HIRING_PLAN,
                    payload={"months_ahead": 3, "runway_months": 2.1},
                    org_id=state["org_id"],
                )
                if result.success:
                    planned_hires = result.response_data.get("planned_hires", 0)
    """

    # Alt siniflar bu ozelligi set etmeli
    agent_name: str = "unknown"

    async def ask_agent(
        self,
        to_agent:   str,
        query_type: str,
        payload:    dict[str, Any],
        org_id:     str,
        job_id:     str | None = None,
        timeout:    float = 10.0,
        fallback:   dict[str, Any] | None = None,
    ) -> NegotiationResult:
        """
        Baska bir agent'a soru sor, cevabini bekle.

        fallback: timeout olursa kullanilacak varsayilan deger
        """
        import time
        bus   = get_agent_bus()
        start = time.time()

        try:
            response = await bus.ask(
                from_agent = self.agent_name,
                to_agent   = to_agent,
                query_type = query_type,
                payload    = payload,
                org_id     = org_id,
                job_id     = job_id,
                timeout    = timeout,
            )

            latency = (time.time() - start) * 1000

            if response is not None:
                logger.debug(
                    "Negotiation OK: %s → %s [%s] %.0fms",
                    self.agent_name, to_agent, query_type, latency,
                )
                return NegotiationResult(
                    query_type    = query_type,
                    from_agent    = self.agent_name,
                    to_agent      = to_agent,
                    success       = True,
                    response_data = response.payload,
                    latency_ms    = latency,
                )
            else:
                # Timeout
                logger.debug(
                    "Negotiation timeout: %s → %s [%s]",
                    self.agent_name, to_agent, query_type,
                )
                return NegotiationResult(
                    query_type    = query_type,
                    from_agent    = self.agent_name,
                    to_agent      = to_agent,
                    success       = False,
                    response_data = fallback or {},
                    fallback_used = True,
                    latency_ms    = latency,
                )

        except Exception as exc:
            logger.warning("Negotiation error: %s → %s: %s", self.agent_name, to_agent, exc)
            return NegotiationResult(
                query_type    = query_type,
                from_agent    = self.agent_name,
                to_agent      = to_agent,
                success       = False,
                response_data = fallback or {},
                fallback_used = True,
            )

    async def broadcast_finding(
        self,
        query_type: str,
        payload:    dict[str, Any],
        org_id:     str,
        job_id:     str | None = None,
    ) -> None:
        """Kritik bulguyu tum agent'lara duyur."""
        bus = get_agent_bus()
        await bus.broadcast(
            from_agent = self.agent_name,
            query_type = query_type,
            payload    = payload,
            org_id     = org_id,
            job_id     = job_id,
        )
        logger.debug("Broadcast: %s [%s]", self.agent_name, query_type)

    async def multi_ask(
        self,
        queries: list[dict[str, Any]],
        org_id:  str,
        job_id:  str | None = None,
        timeout: float = 10.0,
    ) -> list[NegotiationResult]:
        """
        Birden fazla agent'a ayni anda sor (paralel).
        queries: [{"to": "chro", "type": "...", "payload": {...}}, ...]
        """
        tasks = [
            self.ask_agent(
                to_agent   = q["to"],
                query_type = q["type"],
                payload    = q.get("payload", {}),
                org_id     = org_id,
                job_id     = job_id,
                timeout    = timeout,
                fallback   = q.get("fallback"),
            )
            for q in queries
        ]
        return list(await asyncio.gather(*tasks))


# ── CFO Negotiation Scenarios ─────────────────────────────────────────────────

class CFONegotiationScenarios(AgentNegotiator):
    """
    CFO'nun diger agent'larla muzakere senaryolari.

    Kullanim (CFO pipeline icinde):
        cfo_neg = CFONegotiationScenarios()
        result = await cfo_neg.negotiate_cash_crisis(
            runway_months=2.1,
            org_id=state["org_id"],
        )
    """

    agent_name = "cfo"

    async def negotiate_cash_crisis(
        self,
        runway_months: float,
        org_id:        str,
        job_id:        str | None = None,
    ) -> dict[str, Any]:
        """
        Nakit krizi tespitinde tum C-Suite'e paralel soru sor.
        Her birinden kritere gore bilgi al, revize senaryo uret.

        Returns:
            {
              "hiring_plan": {...},    # CHRO'dan
              "tech_savings": {...},   # CTO'dan
              "marketing_roi": {...},  # CMO'dan
              "revised_runway": float, # revize hesaplama
              "negotiation_logs": [...],
            }
        """
        # Paralel sorgular
        results = await self.multi_ask(
            queries=[
                {
                    "to":      "chro",
                    "type":    QueryType.HIRING_PLAN,
                    "payload": {
                        "runway_months": runway_months,
                        "context":       "cash_crisis",
                        "months_ahead":  3,
                    },
                    "fallback": {"planned_hires": 0, "deferrable": True},
                },
                {
                    "to":      "cto",
                    "type":    QueryType.TECH_BUDGET_CUT,
                    "payload": {
                        "runway_months": runway_months,
                        "max_cut_pct":   0.30,
                    },
                    "fallback": {"savings_try": 0, "velocity_impact_pct": 0},
                },
                {
                    "to":      "cmo",
                    "type":    QueryType.MARKETING_ROI,
                    "payload": {
                        "runway_months": runway_months,
                        "ask":           "can_reduce_spend",
                    },
                    "fallback": {"reducible_pct": 0.20, "revenue_impact_pct": 0.05},
                },
            ],
            org_id = org_id,
            job_id = job_id,
        )

        chro_data  = results[0].response_data
        cto_data   = results[1].response_data
        cmo_data   = results[2].response_data

        # Revize senaryo hesapla
        monthly_savings = (
            cto_data.get("savings_try", 0) +
            cmo_data.get("monthly_savings_try", 0)
        )
        hire_delay_months = chro_data.get("deferrable_months", 0)

        # Nakit omru revizyonu (basit yaklaşim)
        revised_runway = runway_months + (monthly_savings / max(1, 100_000)) * 0.5 + hire_delay_months * 0.3

        # Broadcast: revize senaryo hazir
        await self.broadcast_finding(
            query_type = QueryType.SCENARIO_UPDATE,
            payload    = {
                "trigger":         "cash_crisis",
                "original_runway": runway_months,
                "revised_runway":  round(revised_runway, 1),
                "actions_taken":   [
                    f"CHRO: {chro_data.get('planned_hires', 0)} ise alim ertelendi",
                    f"CTO: aylık ₺{cto_data.get('savings_try', 0):,.0f} tasarruf",
                    f"CMO: pazarlama %{cmo_data.get('reducible_pct', 0)*100:.0f} azaltildi",
                ],
            },
            org_id = org_id,
            job_id = job_id,
        )

        return {
            "hiring_plan":  chro_data,
            "tech_savings": cto_data,
            "marketing_roi": cmo_data,
            "revised_runway": round(revised_runway, 1),
            "monthly_savings_total": round(monthly_savings),
            "negotiation_logs": [
                {
                    "query":     r.query_type,
                    "to":        r.to_agent,
                    "success":   r.success,
                    "fallback":  r.fallback_used,
                    "latency_ms": round(r.latency_ms),
                }
                for r in results
            ],
        }

    async def negotiate_budget_revision(
        self,
        cut_target_pct: float,
        org_id:         str,
        job_id:         str | None = None,
    ) -> dict[str, Any]:
        """
        Bütçe revizyon sürecinde tüm domainlerden etki analizi al.
        cut_target_pct: hedeflenen tasarruf oranı (0.0-1.0)
        """
        results = await self.multi_ask(
            queries=[
                {
                    "to":      "chro",
                    "type":    QueryType.HEADCOUNT_IMPACT,
                    "payload": {"cut_target_pct": cut_target_pct},
                    "fallback": {"headcount_risk": "medium", "attrition_increase": 0.03},
                },
                {
                    "to":      "cto",
                    "type":    QueryType.VELOCITY_IMPACT,
                    "payload": {"cut_target_pct": cut_target_pct},
                    "fallback": {"velocity_loss_pct": cut_target_pct * 0.4, "tech_debt_increase": 1.0},
                },
                {
                    "to":      "cmo",
                    "type":    QueryType.REVENUE_FORECAST,
                    "payload": {"marketing_cut_pct": cut_target_pct * 0.5},
                    "fallback": {"revenue_impact_pct": -cut_target_pct * 0.15},
                },
            ],
            org_id = org_id,
            job_id = job_id,
        )

        return {
            "hr_impact":      results[0].response_data,
            "tech_impact":    results[1].response_data,
            "revenue_impact": results[2].response_data,
            "negotiation_logs": [
                {"query": r.query_type, "success": r.success}
                for r in results
            ],
        }


# ── CHRO Negotiation Responder ────────────────────────────────────────────────

class CHRONegotiationResponder(AgentNegotiator):
    """
    CHRO'nun CFO ve CEO'dan gelen sorulara cevap uretici.

    Gercek CHRO verisi yoksa mevcut CHRO kernel'i kullanir.
    """

    agent_name = "chro"

    def build_hiring_plan_response(
        self,
        chro_data:     dict[str, Any],
        runway_months: float,
        months_ahead:  int = 3,
    ) -> dict[str, Any]:
        """
        Ise alim plani sorusuna cevap hazirla.
        Nakit durumuna gore dinamik olarak uyarlanir.
        """
        open_roles     = chro_data.get("open_critical_roles", 0) or 0
        turnover_rate  = chro_data.get("annual_turnover_rate", 0.15) or 0.15
        avg_salary     = chro_data.get("avg_monthly_salary_try", 30_000) or 30_000

        # Nakit durumuna gore plan
        if runway_months < 3:
            # Kritik: tum ise alimi durdur
            planned_hires   = 0
            deferrable      = True
            deferrable_months = 6
            recommendation  = "Tum ise alimlar 6 ay ertelenebilir. Kritik roller icin freelance degerlendir."
        elif runway_months < 6:
            # Dikkatli: sadece kritik roller
            planned_hires   = max(0, round(open_roles * 0.3))
            deferrable      = True
            deferrable_months = 3
            recommendation  = f"Sadece {planned_hires} kritik rol doldurulabilir. Diger {open_roles - planned_hires} rol ertelenmeli."
        else:
            # Normal: plana devam
            planned_hires   = open_roles
            deferrable      = False
            deferrable_months = 0
            recommendation  = f"{open_roles} acigin doldurulmasi oncelikli."

        monthly_hire_cost = planned_hires * avg_salary * 1.225  # SGK dahil

        return {
            "planned_hires":         planned_hires,
            "deferrable":            deferrable,
            "deferrable_months":     deferrable_months,
            "monthly_hire_cost_try": round(monthly_hire_cost),
            "open_critical_roles":   open_roles,
            "attrition_risk":        "high" if turnover_rate > 0.20 else "medium",
            "recommendation":        recommendation,
        }


# ── CTO Negotiation Responder ─────────────────────────────────────────────────

class CTONegotiationResponder(AgentNegotiator):
    """CTO'nun CFO'dan gelen butce sorularına cevap uretici."""

    agent_name = "cto"

    def build_budget_cut_response(
        self,
        cto_data:    dict[str, Any],
        max_cut_pct: float = 0.30,
    ) -> dict[str, Any]:
        """
        Tech butce kesintisi sorusuna cevap.
        Neleri kesebiliriz, velocity'ye etkisi ne?
        """
        monthly_tech   = cto_data.get("monthly_tech_budget_try", 50_000) or 50_000
        infra_waste    = cto_data.get("infra_waste_pct", 0.15) or 0.15
        tech_health    = cto_data.get("overall_health_score", 7.0) or 7.0

        # Onceden kesilebilecekler
        cloud_savings      = monthly_tech * infra_waste   # altyapi israfi
        tooling_savings    = monthly_tech * 0.05           # kullanilmayan araclar
        total_safe_savings = cloud_savings + tooling_savings

        target_savings = monthly_tech * max_cut_pct
        velocity_loss  = max(0.0, (target_savings - total_safe_savings) / monthly_tech * 0.8)

        return {
            "savings_try":             round(total_safe_savings),
            "max_safe_cut_pct":        round(infra_waste + 0.05, 2),
            "velocity_impact_pct":     round(velocity_loss * 100, 1),
            "cloud_savings_try":       round(cloud_savings),
            "tooling_savings_try":     round(tooling_savings),
            "tech_health_risk":        "high" if tech_health < 6 else "low",
            "recommendation": (
                f"Cloud optimizasyonu ile aylik ₺{cloud_savings:,.0f} tasarruf guvenli. "
                f"Bunun otesinde velocity %{velocity_loss*100:.0f} duser."
            ),
        }


# ── Negotiation Session (tam bir muzakere turu) ────────────────────────────────

class NegotiationSession:
    """
    Bir tam muzakere oturumunu yonetir.
    Birden fazla round'u koordine eder, sonuclari kaydeder.
    """

    def __init__(self, org_id: str, job_id: str | None = None) -> None:
        self.org_id  = org_id
        self.job_id  = job_id
        self.rounds: list[NegotiationResult] = []
        self._cfo    = CFONegotiationScenarios()

    async def run_cash_crisis_protocol(self, runway_months: float) -> dict[str, Any]:
        """
        Nakit krizi protokolu: CFO tespit eder, herkesle muzakere eder.
        """
        logger.info(
            "Nakit krizi protokolu baslatiliyor: org=%s runway=%.1f ay",
            self.org_id, runway_months,
        )
        result = await self._cfo.negotiate_cash_crisis(
            runway_months = runway_months,
            org_id        = self.org_id,
            job_id        = self.job_id,
        )
        return {
            "protocol":       "cash_crisis",
            "org_id":         self.org_id,
            "trigger_runway": runway_months,
            "result":         result,
        }

    async def run_budget_revision_protocol(self, cut_pct: float) -> dict[str, Any]:
        """Bütçe revizyon protokolu."""
        result = await self._cfo.negotiate_budget_revision(
            cut_target_pct = cut_pct,
            org_id         = self.org_id,
            job_id         = self.job_id,
        )
        return {
            "protocol":   "budget_revision",
            "org_id":     self.org_id,
            "cut_target": cut_pct,
            "result":     result,
        }


# ── Public factory ─────────────────────────────────────────────────────────────

def get_negotiation_session(org_id: str, job_id: str | None = None) -> NegotiationSession:
    return NegotiationSession(org_id=org_id, job_id=job_id)
