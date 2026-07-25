"""
CMO Orchestrator -- LangGraph pipeline for marketing intelligence.

Graph:
  campaigns -> funnel -> cohort -> cmo_summary -> END

Each node runs its skill independently; cmo_summary synthesizes all three.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph

from app.agents.cmo.state import (
    CMOState,
    CMOStepLog,
    DEFAULT_CMO_RUN_CONFIG,
)
from app.agents.cmo.campaign_agent import run_campaign_agent
from app.agents.cmo.funnel_agent   import run_funnel_agent
from app.agents.cmo.cohort_agent   import run_cohort_agent

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _append_log(state: CMOState, log: CMOStepLog) -> dict[str, Any]:
    existing = list(state.get("logs") or [])
    existing.append(log)
    return {"logs": existing}


# ── LangGraph Nodes ───────────────────────────────────────────────────────────

async def node_campaigns(state: CMOState, config: dict) -> CMOState:
    result = await run_campaign_agent(state, config)
    patch  = _append_log(state, CMOStepLog(
        step="campaigns",
        ok=result.get("campaigns") is not None,
        detail=f"roas={result.get('campaigns', {}) and result['campaigns'].get('overall_roas')}",
    ))
    return {**state, **patch, **result}  # type: ignore[return-value]


async def node_funnel(state: CMOState, config: dict) -> CMOState:
    result = await run_funnel_agent(state, config)
    patch  = _append_log(state, CMOStepLog(
        step="funnel",
        ok=result.get("funnel") is not None,
        detail=f"conversion={result.get('funnel', {}) and result['funnel'].get('overall_conversion_rate')}",
    ))
    return {**state, **patch, **result}  # type: ignore[return-value]


async def node_cohort(state: CMOState, config: dict) -> CMOState:
    result = await run_cohort_agent(state, config)
    patch  = _append_log(state, CMOStepLog(
        step="cohort",
        ok=result.get("cohorts") is not None,
        detail=f"ltv_cac={result.get('cohorts', {}) and result['cohorts'].get('ltv_cac_ratio')}",
    ))
    return {**state, **patch, **result}  # type: ignore[return-value]


async def node_cmo_summary(state: CMOState, config: dict) -> CMOState:
    """
    CMO Summary node -- synthesizes all available agent outputs into a
    holistic marketing health score and top-risk list.
    """
    campaigns = state.get("campaigns") or {}
    funnel    = state.get("funnel") or {}
    cohorts   = state.get("cohorts") or {}

    scores: dict[str, float] = {}
    top_risks: list[dict[str, str]] = []

    # ── Campaign score ─────────────────────────────────────────────────────────
    if campaigns:
        roas = campaigns.get("overall_roas", 0.0)
        # Score: 10 = terrible (ROAS < 0.5), 0 = excellent (ROAS > 5)
        campaign_score = max(0.0, min(10.0, 10.0 - (roas * 2.0)))
        scores["campaigns"] = round(campaign_score, 1)
        for alert in campaigns.get("alerts") or []:
            if alert["level"] in ("critical", "high"):
                top_risks.append({
                    "domain":   "Campaigns",
                    "severity": alert["level"],
                    "message":  alert["message"],
                })

    # ── Funnel score ───────────────────────────────────────────────────────────
    if funnel:
        conv = funnel.get("overall_conversion_rate", 0.0)
        # Score: 10 = terrible (< 1%), 0 = excellent (> 10%)
        funnel_score = max(0.0, min(10.0, 10.0 - (conv * 100)))
        scores["funnel"] = round(funnel_score, 1)
        for alert in funnel.get("alerts") or []:
            if alert["level"] in ("critical", "high"):
                top_risks.append({
                    "domain":   "Funnel",
                    "severity": alert["level"],
                    "message":  alert["message"],
                })

    # ── Cohort / retention score ───────────────────────────────────────────────
    if cohorts:
        ltv_cac = cohorts.get("ltv_cac_ratio", 0.0)
        churn   = cohorts.get("churn_rate", 0.0)
        # Score: 10 = terrible (ltv_cac < 1 OR churn > 15%)
        cohort_score = max(0.0, min(10.0,
            (max(0, 3.0 - ltv_cac) * 2.0) + (churn * 30.0)
        ))
        scores["retention"] = round(cohort_score, 1)
        for alert in cohorts.get("alerts") or []:
            if alert["level"] in ("critical", "high"):
                top_risks.append({
                    "domain":   "Retention",
                    "severity": alert["level"],
                    "message":  alert["message"],
                })

    overall_score = (
        round(sum(scores.values()) / len(scores), 1) if scores else 0.0
    )
    growth_efficiency = _compute_growth_efficiency(campaigns, cohorts)

    # Sort critical first
    top_risks.sort(key=lambda r: 0 if r["severity"] == "critical" else 1)

    # ── Quick wins ─────────────────────────────────────────────────────────────
    quick_wins: list[dict[str, str]] = []

    underperforming = (campaigns.get("underperforming") or [])
    if underperforming:
        waste = sum(c["spend_cents"] for c in underperforming)
        quick_wins.append({
            "action":           f"Pause {len(underperforming)} underperforming campaign(s)",
            "estimated_impact": f"Boşa harcanan reklam bütçesinden {waste / 100:,.0f} ₺ tasarruf",
            "effort":           "düşük",
        })

    bottleneck = funnel.get("bottleneck_stage")
    if bottleneck:
        quick_wins.append({
            "action":           f"Dönüşüm hunisi darboğazını çöz: {bottleneck.replace('_', ' ')} aşaması",
            "estimated_impact": "Dönüşüm oranını artır ve CAC'yi düşür",
            "effort":           "orta",
        })

    if cohorts.get("retention_trend") == "degrading":
        quick_wins.append({
            "action":           "Yeni kohortlar için müşteri başarı programı başlat",
            "estimated_impact": "30 günlük tutunmayı %10-15 artır",
            "effort":           "orta",
        })

    # ── LLM Narrative (Türkçe + actionable) ───────────────────────────────────
    narrative = _build_fallback_narrative(overall_score, campaigns, funnel, cohorts)
    try:
        from app.config import get_settings
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.llm_model,
            temperature=0.2,
            max_tokens=700,
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,
        )
        roas    = campaigns.get("overall_roas", 0.0)
        conv    = funnel.get("overall_conversion_rate", 0.0)
        ltv_cac = cohorts.get("ltv_cac_ratio", 0.0)
        churn   = cohorts.get("churn_rate", 0.0)

        response = await llm.ainvoke([
            SystemMessage(content=(
                "Sen deneyimli bir CMO'sun. Pazarlama sağlık verilerini analiz et ve "
                "Türkçe olarak kısa, eyleme dönüştürülebilir bir yönetici özeti yaz. "
                "Yanıt şu yapıda olsun:\n"
                "1. Pazarlama verimliliğinin 1-2 cümlelik değerlendirmesi (ROAS ve LTV:CAC odaklı)\n"
                "2. En kritik 1-2 sorun (churn, dönüşüm darboğazı, düşük ROAS)\n"
                "3. Pazarlama ekibinin hemen yapması gereken 2-3 somut eylem (öncelik sırasıyla)\n"
                "Growth hacker bakış açısıyla pratik öneriler ekle."
            )),
            HumanMessage(content=(
                f"Pazarlama Sağlık Skoru: {overall_score}/10\n"
                f"ROAS: {roas:.2f}x | Dönüşüm Oranı: %{conv*100:.1f} | "
                f"LTV:CAC: {ltv_cac:.2f}x | Aylık Churn: %{churn*100:.1f}\n"
                f"Önemli Risk Sayısı: {len(top_risks)}"
            )),
        ])
        narrative = response.content.strip()
    except Exception as exc:
        logger.warning("CMO summary narrative failed: %s", exc)

    summary = {
        "overall_marketing_score":  overall_score,
        "growth_efficiency_score":  growth_efficiency,
        "component_scores":         scores,
        "top_risks":                top_risks[:8],
        "quick_wins":               quick_wins[:5],
        "narrative":                narrative,
    }

    patch = _append_log(state, CMOStepLog(
        step="cmo_summary",
        ok=True,
        detail=f"Marketing score: {overall_score}/10, risks: {len(top_risks)}",
        confidence=0.88,
    ))
    patch["cmo_summary"] = summary
    return {**state, **patch}  # type: ignore[return-value]


def _compute_growth_efficiency(
    campaigns: dict[str, Any],
    cohorts: dict[str, Any],
) -> float:
    """
    Growth efficiency score (0-10, higher = better).
    Combines ROAS and LTV:CAC into a single metric.
    """
    roas    = campaigns.get("overall_roas", 0.0) if campaigns else 0.0
    ltv_cac = cohorts.get("ltv_cac_ratio", 0.0) if cohorts else 0.0

    scores: list[float] = []
    if roas > 0:
        # ROAS 4x = score 10, ROAS 1x = score 2.5
        scores.append(min(10.0, roas * 2.5))
    if ltv_cac > 0:
        # LTV:CAC 4x = score 10, LTV:CAC 1x = score 2.5
        scores.append(min(10.0, ltv_cac * 2.5))

    return round(sum(scores) / len(scores), 1) if scores else 0.0


def _build_fallback_narrative(
    score: float,
    campaigns: dict[str, Any],
    funnel: dict[str, Any],
    cohorts: dict[str, Any],
) -> str:
    roas  = campaigns.get("overall_roas", 0.0) if campaigns else 0.0
    conv  = funnel.get("overall_conversion_rate", 0.0) if funnel else 0.0
    ltv   = cohorts.get("ltv_cac_ratio", 0.0) if cohorts else 0.0
    return (
        f"Marketing health score: {score}/10. "
        f"Campaign ROAS {roas:.2f}x, funnel conversion {conv:.1%}, LTV:CAC {ltv:.2f}x."
    )


# ── Graph Builder ──────────────────────────────────────────────────────────────

def build_cmo_graph() -> StateGraph:
    g = StateGraph(CMOState)

    g.add_node("campaigns",   node_campaigns)
    g.add_node("funnel",      node_funnel)
    g.add_node("cohort",      node_cohort)
    g.add_node("cmo_summary", node_cmo_summary)

    g.set_entry_point("campaigns")
    g.add_edge("campaigns",   "funnel")
    g.add_edge("funnel",      "cohort")
    g.add_edge("cohort",      "cmo_summary")
    g.add_edge("cmo_summary", "__end__")

    return g.compile()


_cmo_graph = build_cmo_graph()


# ── Public Entry Point ────────────────────────────────────────────────────────

async def run_cmo_pipeline(
    job_id: str,
    company_name: str | None = None,
    period: str | None = None,
    campaign_csv: str | None = None,
    funnel_csv: str | None = None,
    cohort_csv: str | None = None,
) -> CMOState:
    """
    Run the full CMO pipeline.
    At least one of campaign_csv, funnel_csv, cohort_csv must be provided.
    Returns the final CMOState.
    """
    if not any([campaign_csv, funnel_csv, cohort_csv]):
        raise ValueError("At least one of campaign_csv, funnel_csv, or cohort_csv is required.")

    initial: CMOState = {
        "job_id":       job_id,
        "company_name": company_name,
        "period":       period,
        "campaign_csv": campaign_csv,
        "funnel_csv":   funnel_csv,
        "cohort_csv":   cohort_csv,
        "logs":         [],
        "min_confidence": DEFAULT_CMO_RUN_CONFIG.auto_proceed_min_confidence,
        "awaiting_review": False,
        "halted":       False,
        "error":        None,
    }

    result: CMOState = await _cmo_graph.ainvoke(
        initial,
        config={"configurable": {"job_id": job_id}},
    )
    return result
