"""
COO Agent Enhanced Orchestrator

Mevcut COO pipeline'ini kernel entegrasyonu ve negotiation
kabiliyetiyle guclendirir.

Gelistirmeler:
  1. Kernel Inject: CSV yoksa COO Kernel'den otomatik veri uret
  2. Negotiation: SLA ihlali → CFO'ya maliyet + CHRO'ya personel sorusu
  3. Temporal: Her analiz sonucu temporal log'a otomatik kaydet
  4. Cross-Domain: CFO nakit durumunu COO SLA kararlarına yansit

DDIA: bu dosya mevcut orchestrator.py'yi degistirmiyor,
onun uzerine bir wrapper olarak calisir.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── COO Kernel Inject ─────────────────────────────────────────────────────────

async def inject_kernel_if_needed(
    state: dict[str, Any],
    org_id: str | None = None,
) -> dict[str, Any]:
    """
    COO state'inde CSV yoksa COO Kernel'den otomatik veri uret.
    Ureilen veri sintetik CSV olarak state'e inject edilir.

    DDIA: bu bir "derived data" — kaynak veriden hesaplanir,
    kaydetmeye gerek yok, her zaman yeniden uretilir.
    """
    has_data = any([
        state.get("process_csv"),
        state.get("resource_csv"),
        state.get("sla_csv"),
    ])

    if has_data:
        return state  # Gercek veri var, kernel'e gerek yok

    if not org_id:
        return state  # org_id yok, kernel calistiramaziz

    try:
        # CompanyContext'ten veri al
        from app.services.company_context import get_company_context
        ctx     = await get_company_context(org_id) or {}
        results = ctx.get("agent_results") or {}
        cfo_r   = results.get("cfo") or {}

        # COO Kernel calistir
        from app.agents.coo.coo_kernel import run_coo_kernel
        kernel_result = await run_coo_kernel(
            pnl       = cfo_r.get("pnl"),
            cashflow  = cfo_r.get("cashflow"),
            chro_data = results.get("chro"),
            cto_data  = results.get("cto"),
            existing_coo_data = results.get("coo"),
        )
        output = kernel_result.get("output", {})

        # Sintetik CSV'leri state'e inject et
        enriched = dict(state)
        if output.get("process_csv"):
            enriched["process_csv"] = output["process_csv"]
        if output.get("resource_csv"):
            enriched["resource_csv"] = output["resource_csv"]
        if output.get("sla_csv"):
            enriched["sla_csv"] = output["sla_csv"]

        # Kernel ozet verilerini de ekle (summary node icin)
        enriched["_kernel_output"] = output
        enriched["_data_source"]   = "kernel_estimated"

        logger.info(
            "COO kernel inject: org=%s sla=%.1f%% ops_score=%.1f",
            org_id,
            output.get("sla_compliance", 0) * 100,
            output.get("overall_ops_score", 0),
        )
        return enriched

    except Exception as exc:
        logger.debug("COO kernel inject hatasi (non-fatal): %s", exc)
        return state


# ── COO Negotiation Scenarios ─────────────────────────────────────────────────

class COONegotiationScenarios:
    """
    COO'nun diger agent'larla muzakere senaryolari.

    SLA ihlali tespitinde CFO ve CHRO'ya paralel bildirim.
    """

    agent_name = "coo"

    async def negotiate_sla_breach(
        self,
        sla_compliance:   float,   # mevcut SLA uyum orani (0-1)
        breach_rate:      float,   # ihlal orani
        org_id:           str,
        job_id:           str | None = None,
    ) -> dict[str, Any]:
        """
        SLA ihlali durumunda CFO ve CHRO'ya bildirim.
        CFO: maliyet etkisi nedir?
        CHRO: ek personel gerekli mi?
        """
        from app.services.agent_bus import QueryType, get_agent_bus

        bus = get_agent_bus()

        # CFO'ya SLA ihlalinin maliyet etkisini sor
        cfo_response = await bus.ask(
            from_agent = "coo",
            to_agent   = "cfo",
            query_type = QueryType.RISK_ASSESSMENT,
            payload    = {
                "context":         "sla_breach",
                "sla_compliance":  sla_compliance,
                "breach_rate":     breach_rate,
                "ask":             "estimated_revenue_impact",
            },
            org_id  = org_id,
            job_id  = job_id,
            timeout = 8.0,
        )

        # CHRO'ya ek personel gerekip gerekmedigini sor
        chro_response = await bus.ask(
            from_agent = "coo",
            to_agent   = "chro",
            query_type = QueryType.HEADCOUNT_IMPACT,
            payload    = {
                "context":        "sla_breach",
                "sla_compliance": sla_compliance,
                "ask":            "support_team_capacity",
            },
            org_id  = org_id,
            job_id  = job_id,
            timeout = 8.0,
        )

        # Broadcast: SLA sorunu tum C-Suite'e bildirildi
        await bus.broadcast(
            from_agent = "coo",
            query_type = "sla_breach_alert",
            payload    = {
                "sla_compliance": sla_compliance,
                "breach_rate":    breach_rate,
                "severity":       "critical" if sla_compliance < 0.85 else "high",
                "cfo_response":   cfo_response.payload if cfo_response else {},
                "chro_response":  chro_response.payload if chro_response else {},
            },
            org_id = org_id,
            job_id = job_id,
        )

        return {
            "sla_compliance": sla_compliance,
            "breach_rate":    breach_rate,
            "cfo_response":   cfo_response.payload if cfo_response else {"revenue_impact": "unknown"},
            "chro_response":  chro_response.payload if chro_response else {"support_capacity": "unknown"},
            "action":         "SLA ihlali C-Suite'e bildirildi, kapsamli analiz baslatildi.",
        }

    async def negotiate_resource_constraint(
        self,
        utilization:     float,   # kaynak kullanim orani (0-1)
        bottlenecks:     list[str],
        org_id:          str,
        job_id:          str | None = None,
    ) -> dict[str, Any]:
        """
        Kaynak kisintisi durumunda CHRO ve CFO'ya bildirim.
        """
        from app.services.agent_bus import QueryType, get_agent_bus

        bus = get_agent_bus()

        chro_response = await bus.ask(
            from_agent = "coo",
            to_agent   = "chro",
            query_type = QueryType.HIRING_PLAN,
            payload    = {
                "context":          "resource_constraint",
                "utilization":      utilization,
                "bottlenecks":      bottlenecks[:3],
                "months_ahead":     3,
            },
            org_id  = org_id,
            job_id  = job_id,
            timeout = 8.0,
        )

        return {
            "utilization":    utilization,
            "bottlenecks":    bottlenecks,
            "chro_response":  chro_response.payload if chro_response else {},
            "action":         f"Kaynak kisintisi CHRO'ya bildirildi. Bottleneck'ler: {', '.join(bottlenecks[:2])}",
        }


# ── COO Enhanced Pipeline ──────────────────────────────────────────────────────

async def run_enhanced_coo_pipeline(
    job_id:       str,
    org_id:       str | None = None,
    process_csv:  str | None = None,
    resource_csv: str | None = None,
    sla_csv:      str | None = None,
    company_name: str | None = None,
    enable_negotiation: bool = True,
    enable_temporal:    bool = True,
) -> dict[str, Any]:
    """
    Guclendirilmis COO pipeline:
    1. Kernel inject (CSV yoksa)
    2. Mevcut COO pipeline calistir
    3. Negotiation (SLA ihlali varsa)
    4. Temporal kayit
    """
    from app.agents.coo.orchestrator import run_coo_pipeline

    # 1. Baslangic state
    initial_state: dict[str, Any] = {
        "job_id":       job_id,
        "company_name": company_name,
        "process_csv":  process_csv,
        "resource_csv": resource_csv,
        "sla_csv":      sla_csv,
    }

    # 2. Kernel inject (gerekirse)
    enhanced_state = await inject_kernel_if_needed(initial_state, org_id=org_id)

    # 3. Mevcut COO pipeline calistir
    result = await run_coo_pipeline(
        process_csv  = enhanced_state.get("process_csv"),
        resource_csv = enhanced_state.get("resource_csv"),
        sla_csv      = enhanced_state.get("sla_csv"),
        company_name = company_name,
    )

    # 4. Negotiation — SLA ihlali varsa
    if enable_negotiation and org_id:
        sla_data = result.get("sla") or {}
        sla_compliance = sla_data.get("sla_breach_rate", 0)
        # sla_breach_rate = ihlal orani, compliance = 1 - breach_rate
        actual_compliance = 1.0 - sla_compliance

        if actual_compliance < 0.95:  # SLA %95 altinda → negotiate
            neg = COONegotiationScenarios()
            negotiation_result = await neg.negotiate_sla_breach(
                sla_compliance = actual_compliance,
                breach_rate    = sla_compliance,
                org_id         = org_id,
                job_id         = job_id,
            )
            result["_negotiation"] = negotiation_result
            logger.info(
                "COO negotiation tamamlandi: sla=%.1f%% org=%s",
                actual_compliance * 100, org_id,
            )

        # Kaynak kisintisi varsa
        coo_summary = result.get("coo_summary") or {}
        if coo_summary.get("overall_ops_score", 10) < 6:
            bottlenecks = [r.get("title", "") for r in (coo_summary.get("top_risks") or [])[:3]]
            resources   = result.get("resources") or {}
            utilization = resources.get("avg_utilization_rate", 0.75)
            if utilization > 0.88 or bottlenecks:
                neg = COONegotiationScenarios()
                resource_neg = await neg.negotiate_resource_constraint(
                    utilization  = utilization,
                    bottlenecks  = bottlenecks,
                    org_id       = org_id,
                    job_id       = job_id,
                )
                result["_resource_negotiation"] = resource_neg

    # 5. Temporal kayit
    if enable_temporal and org_id:
        try:
            from app.services.temporal_intelligence import get_temporal_engine
            engine  = get_temporal_engine()
            summary = result.get("coo_summary") or {}
            await engine.record_analysis(
                org_id     = org_id,
                agent      = "coo",
                period     = "current",
                metrics    = {
                    "overall_ops_score": summary.get("overall_ops_score", 0),
                    "sla_compliance":    1.0 - (result.get("sla") or {}).get("sla_breach_rate", 0),
                    "resource_utilization": (result.get("resources") or {}).get("avg_utilization_rate", 0),
                },
                confidence  = 0.80,
                data_source = enhanced_state.get("_data_source", "csv"),
            )
        except Exception as exc:
            logger.debug("COO temporal kayit hatasi (non-fatal): %s", exc)

    # Kernel output'unu result'a ekle
    if enhanced_state.get("_kernel_output"):
        result["_kernel_data"] = enhanced_state["_kernel_output"]
        result["_data_source"] = enhanced_state.get("_data_source", "csv")

    return result
