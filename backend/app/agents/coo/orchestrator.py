"""
COO Orchestrator -- LangGraph pipeline for operational intelligence.

Graph:
  process -> resource -> sla -> coo_summary -> END

Each node runs its skill independently; coo_summary synthesizes all three.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph

from app.agents.coo.state import (
    COOState,
    COOStepLog,
    DEFAULT_COO_RUN_CONFIG,
)
from app.agents.coo.process_agent  import run_process_agent
from app.agents.coo.resource_agent import run_resource_agent
from app.agents.coo.sla_agent      import run_sla_agent

logger = logging.getLogger(__name__)


# -- Helpers ------------------------------------------------------------------

def _append_log(state: COOState, log: COOStepLog) -> dict[str, Any]:
    existing = list(state.get("logs") or [])
    existing.append(log)
    return {"logs": existing}


# -- LangGraph Nodes ----------------------------------------------------------

async def node_process(state: COOState, config: dict) -> COOState:
    result = await run_process_agent(state, config)
    proc   = result.get("processes")
    patch  = _append_log(state, COOStepLog(
        step="process",
        ok=proc is not None,
        detail=f"efficiency={proc and proc.get('efficiency_score')}",
    ))
    return {**state, **patch, **result}  # type: ignore[return-value]


async def node_resource(state: COOState, config: dict) -> COOState:
    result = await run_resource_agent(state, config)
    res    = result.get("resources")
    patch  = _append_log(state, COOStepLog(
        step="resource",
        ok=res is not None,
        detail=f"utilization={res and res.get('avg_utilization_rate')}",
    ))
    return {**state, **patch, **result}  # type: ignore[return-value]


async def node_sla(state: COOState, config: dict) -> COOState:
    result = await run_sla_agent(state, config)
    sla    = result.get("sla")
    patch  = _append_log(state, COOStepLog(
        step="sla",
        ok=sla is not None,
        detail=f"breach_rate={sla and sla.get('sla_breach_rate')}",
    ))
    return {**state, **patch, **result}  # type: ignore[return-value]


async def node_coo_summary(state: COOState, config: dict) -> COOState:
    """
    COO Summary node -- synthesizes all available agent outputs into a
    holistic operational health score and top-risk list.
    """
    processes = state.get("processes") or {}
    resources = state.get("resources") or {}
    sla       = state.get("sla") or {}

    scores: dict[str, float] = {}
    top_risks: list[dict[str, str]] = []

    # -- Process score ---------------------------------------------------------
    if processes:
        eff_score = processes.get("efficiency_score", 0.0)
        scores["process"] = round(eff_score, 1)
        for alert in processes.get("alerts") or []:
            if alert["level"] in ("critical", "high"):
                top_risks.append({
                    "domain":   "Process",
                    "severity": alert["level"],
                    "message":  alert["message"],
                })

    # -- Resource score --------------------------------------------------------
    if resources:
        util = resources.get("avg_utilization_rate", 0.5)
        # Score: 10 = terrible (>110% or <30%), 0 = ideal (70-85%)
        if util > 1.1:
            res_score = 10.0
        elif util > 0.90:
            res_score = 6.0 + (util - 0.90) * 40  # 6-10 range
        elif util < 0.30:
            res_score = 7.0
        elif util < 0.50:
            res_score = 4.0
        else:
            res_score = max(0.0, (util - 0.70) * 20) if util > 0.70 else 0.0
        scores["resource"] = round(min(10.0, max(0.0, res_score)), 1)
        for alert in resources.get("alerts") or []:
            if alert["level"] in ("critical", "high"):
                top_risks.append({
                    "domain":   "Resource",
                    "severity": alert["level"],
                    "message":  alert["message"],
                })

    # -- SLA score -------------------------------------------------------------
    if sla:
        breach   = sla.get("sla_breach_rate", 0.0)
        nps      = sla.get("avg_nps_score", 50.0)
        # Score: breach 0% + NPS 70+ = 0, breach 30%+ + NPS negative = 10
        sla_score = min(10.0, (breach * 20) + max(0.0, (0 - nps) / 10))
        scores["sla"] = round(sla_score, 1)
        for alert in sla.get("alerts") or []:
            if alert["level"] in ("critical", "high"):
                top_risks.append({
                    "domain":   "SLA",
                    "severity": alert["level"],
                    "message":  alert["message"],
                })

    overall_score = (
        round(sum(scores.values()) / len(scores), 1) if scores else 0.0
    )
    ops_efficiency = _compute_ops_efficiency(processes, resources, sla)

    # Sort critical first
    top_risks.sort(key=lambda r: 0 if r["severity"] == "critical" else 1)

    # -- Quick wins ------------------------------------------------------------
    quick_wins: list[dict[str, str]] = []

    overloaded = (processes.get("overloaded_processes") or [])
    if overloaded:
        quick_wins.append({
            "action":           f"Reduce WIP in {len(overloaded)} overloaded process(es)",
            "estimated_impact": "Improve throughput and reduce cycle time 15-25%",
            "effort":           "medium",
        })

    over_teams = (resources.get("overutilized_teams") or [])
    under_teams = (resources.get("underutilized_teams") or [])
    if over_teams and under_teams:
        quick_wins.append({
            "action":           f"Kapasite yeniden dengele: {under_teams[0]['team']} ekibini {over_teams[0]['team']} ekibine yönlendir",
            "estimated_impact": "Burnout riskini azalt ve genel verimliliği artır",
            "effort":           "düşük",
        })

    if sla.get("trend") == "degrading":
        quick_wins.append({
            "action":           "En sık tekrarlayan SLA ihlal kategorileri için kök neden analizi yap",
            "estimated_impact": "İhlal oranını %20-30 azalt",
            "effort":           "orta",
        })

    bn = processes.get("bottleneck_process")
    if bn:
        quick_wins.append({
            "action":           f"Darboğazı çöz: '{bn}' (Kısıtlar Teorisi)",
            "estimated_impact": "Sistem genelinde iş akışını iyileştir",
            "effort":           "yüksek",
        })

    # ── LLM Narrative (Türkçe + actionable) ──────────────────────────────────
    narrative = _build_fallback_narrative(overall_score, processes, resources, sla)
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
        eff    = processes.get("efficiency_score", 0.0)
        util   = resources.get("avg_utilization_rate", 0.0)
        breach = sla.get("sla_breach_rate", 0.0)
        nps    = sla.get("avg_nps_score", 0.0)

        response = await llm.ainvoke([
            SystemMessage(content=(
                "Sen deneyimli bir COO'sun. Operasyonel sağlık verilerini analiz et ve "
                "Türkçe olarak kısa, eyleme dönüştürülebilir bir yönetici özeti yaz. "
                "Yanıt şu yapıda olsun:\n"
                "1. Operasyonel verimliliğin 1-2 cümlelik değerlendirmesi (SLA ihlali ve kaynak kullanımı odaklı)\n"
                "2. En kritik 1-2 operasyonel sorun (darboğaz, aşırı kullanım, NPS düşüklüğü)\n"
                "3. Operasyon ekibinin hemen yapması gereken 2-3 somut iyileştirme (öncelik sırasıyla)\n"
                "Lean operasyon perspektifinden pratik öneriler ekle."
            )),
            HumanMessage(content=(
                f"Operasyonel Sağlık Skoru: {overall_score}/10\n"
                f"Süreç Verimliliği: {eff}/10 | Kaynak Kullanımı: %{util*100:.0f} | "
                f"SLA İhlal Oranı: %{breach*100:.0f} | NPS: {nps:.0f}\n"
                f"Önemli Risk Sayısı: {len(top_risks)}"
            )),
        ])
        narrative = response.content.strip()
    except Exception as exc:
        logger.warning("COO summary narrative failed: %s", exc)

    summary = {
        "overall_ops_score":           overall_score,
        "operational_efficiency_score": ops_efficiency,
        "component_scores":            scores,
        "top_risks":                   top_risks[:8],
        "quick_wins":                  quick_wins[:5],
        "narrative":                   narrative,
    }

    patch = _append_log(state, COOStepLog(
        step="coo_summary",
        ok=True,
        detail=f"Ops score: {overall_score}/10, risks: {len(top_risks)}",
        confidence=0.88,
    ))
    patch["coo_summary"] = summary
    return {**state, **patch}  # type: ignore[return-value]


def _compute_ops_efficiency(
    processes: dict[str, Any],
    resources: dict[str, Any],
    sla: dict[str, Any],
) -> float:
    """
    Operational efficiency score (0-10, higher = better).
    Combines process throughput, resource utilization balance, and SLA compliance.
    """
    scores: list[float] = []

    if processes:
        eff = processes.get("efficiency_score", 5.0)
        # Invert: efficiency_score 0 = perfect, 10 = terrible
        scores.append(10.0 - eff)

    if resources:
        util = resources.get("avg_utilization_rate", 0.5)
        # Ideal utilization 70-85% = score 10, too low or too high penalized
        if 0.70 <= util <= 0.85:
            util_score = 10.0
        elif util > 0.85:
            util_score = max(0.0, 10.0 - (util - 0.85) * 50)
        else:
            util_score = util / 0.70 * 10.0
        scores.append(min(10.0, util_score))

    if sla:
        breach = sla.get("sla_breach_rate", 0.5)
        sla_score = max(0.0, 10.0 - breach * 30)
        scores.append(min(10.0, sla_score))

    return round(sum(scores) / len(scores), 1) if scores else 0.0


def _build_fallback_narrative(
    score: float,
    processes: dict[str, Any],
    resources: dict[str, Any],
    sla: dict[str, Any],
) -> str:
    eff    = processes.get("efficiency_score", 0.0) if processes else 0.0
    util   = resources.get("avg_utilization_rate", 0.0) if resources else 0.0
    breach = sla.get("sla_breach_rate", 0.0) if sla else 0.0
    return (
        f"Operations health score: {score}/10. "
        f"Process efficiency {eff}/10, resource utilization {util:.0%}, "
        f"SLA breach rate {breach:.0%}."
    )


# -- Graph Builder ------------------------------------------------------------

def build_coo_graph() -> StateGraph:
    g = StateGraph(COOState)

    g.add_node("process",     node_process)
    g.add_node("resource",    node_resource)
    g.add_node("sla",         node_sla)
    g.add_node("coo_summary", node_coo_summary)

    g.set_entry_point("process")
    g.add_edge("process",     "resource")
    g.add_edge("resource",    "sla")
    g.add_edge("sla",         "coo_summary")
    g.add_edge("coo_summary", "__end__")

    return g.compile()


_coo_graph = build_coo_graph()


# -- Public Entry Point -------------------------------------------------------

async def run_coo_pipeline(
    job_id: str,
    company_name: str | None = None,
    period: str | None = None,
    process_csv: str | None = None,
    resource_csv: str | None = None,
    sla_csv: str | None = None,
) -> COOState:
    """
    Run the full COO pipeline.
    At least one of process_csv, resource_csv, sla_csv must be provided.
    Returns the final COOState.
    """
    if not any([process_csv, resource_csv, sla_csv]):
        raise ValueError(
            "At least one of process_csv, resource_csv, or sla_csv is required."
        )

    initial: COOState = {
        "job_id":       job_id,
        "company_name": company_name,
        "period":       period,
        "process_csv":  process_csv,
        "resource_csv": resource_csv,
        "sla_csv":      sla_csv,
        "logs":         [],
        "min_confidence": DEFAULT_COO_RUN_CONFIG.auto_proceed_min_confidence,
        "awaiting_review": False,
        "halted":       False,
        "error":        None,
    }

    result: COOState = await _coo_graph.ainvoke(
        initial,
        config={"configurable": {"job_id": job_id}},
    )
    return result
