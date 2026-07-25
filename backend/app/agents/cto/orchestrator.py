"""
CTO Orchestrator — LangGraph StateGraph.

Pipeline:
  START
  → infra          (non-fatal: no billing data → skip)
  → tech_debt      (non-fatal: no git log → skip)
  → incidents      (non-fatal: no incident data → skip)
  → velocity       (non-fatal: no sprint data → skip)
  → cto_summary    (always runs — synthesizes all available signals)
  → END

  hold_for_review  (terminal if confidence < 0.80 on any node)

All nodes are non-fatal: missing data → skip gracefully.
At least one data source required to produce a meaningful summary.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import StateGraph, END

from app.agents.cto.state import (
    CTOState,
    CTOStepLog,
    CTOSkillResult,
    CTORunConfig,
    DEFAULT_CTO_RUN_CONFIG,
    CTO_ROUTE_HOLD,
    CTO_ROUTE_END,
    CTO_ROUTE_SUMMARY,
)
from app.agents.cto.infra_agent      import run_infra_agent
from app.agents.cto.tech_debt_agent  import run_tech_debt_agent
from app.agents.cto.incident_agent   import run_incident_agent
from app.agents.cto.velocity_agent   import run_velocity_agent

logger = logging.getLogger(__name__)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _append_log(state: CTOState, log: CTOStepLog) -> dict[str, Any]:
    existing = list(state.get("logs") or [])
    existing.append(log)
    min_conf = state.get("min_confidence", 1.0)
    if log.confidence is not None:
        min_conf = min(min_conf, log.confidence)
    return {"logs": existing, "min_confidence": min_conf}


def _run_config(config: dict) -> CTORunConfig:
    return config.get("configurable", {}).get("cto_run_config", DEFAULT_CTO_RUN_CONFIG)


# ── Node builders ──────────────────────────────────────────────────────────────

async def node_infra(state: CTOState, config: dict) -> CTOState:
    result = await run_infra_agent(state, _run_config(config))
    patch = _append_log(state, CTOStepLog(
        step="infra", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if result.needs_review:
        patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]


async def node_tech_debt(state: CTOState, config: dict) -> CTOState:
    result = await run_tech_debt_agent(state, _run_config(config))
    patch = _append_log(state, CTOStepLog(
        step="tech_debt", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if result.needs_review:
        patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]


async def node_incidents(state: CTOState, config: dict) -> CTOState:
    result = await run_incident_agent(state, _run_config(config))
    patch = _append_log(state, CTOStepLog(
        step="incidents", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if result.needs_review:
        patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]


async def node_velocity(state: CTOState, config: dict) -> CTOState:
    result = await run_velocity_agent(state, _run_config(config))
    patch = _append_log(state, CTOStepLog(
        step="velocity", ok=result.ok, detail=result.detail, confidence=result.confidence
    ))
    patch.update(result.patch)
    if result.needs_review:
        patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]


async def node_cto_summary(state: CTOState, config: dict) -> CTOState:
    """
    CTO Summary node — synthesizes all available agent outputs into a
    holistic tech health score and top-risk list.
    """
    from app.config import get_settings
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    settings = get_settings()
    infra     = state.get("infra") or {}
    tech_debt = state.get("tech_debt") or {}
    incidents = state.get("incidents") or {}
    velocity  = state.get("velocity") or {}

    # ── Component health scores (0-10, higher = worse) ────────────────────────
    scores: dict[str, float] = {}
    top_risks: list[dict[str, str]] = []

    if infra:
        mom = infra.get("mom_change_pct") or 0
        waste_pct = (
            infra["waste_estimate_cents"] / infra["total_cost_cents"] * 100
            if infra.get("total_cost_cents") else 0
        )
        infra_score = min(10.0, (max(0, mom) / 10) + (waste_pct / 5))
        scores["infra"] = round(infra_score, 1)
        for alert in infra.get("alerts") or []:
            if alert["level"] in ("critical", "warning"):
                top_risks.append({"domain": "Infrastructure", "severity": alert["level"], "message": alert["message"]})

    if tech_debt:
        scores["tech_debt"] = tech_debt.get("debt_score", 0)
        if tech_debt.get("debt_score", 0) >= 6:
            top_risks.append({
                "domain": "Tech Debt",
                "severity": "high" if tech_debt["debt_score"] >= 7 else "medium",
                "message": f"Debt score {tech_debt['debt_score']:.1f}/10 — {len(tech_debt.get('hotspot_files',[]))} hotspot files detected",
            })

    if incidents:
        mttr = incidents.get("mttr_hours") or 0
        breach_pct = incidents.get("sla_breach_pct", 0)
        incident_score = min(10.0, (mttr / 2) + (breach_pct / 10))
        scores["incidents"] = round(incident_score, 1)
        for alert in incidents.get("alerts") or []:
            if alert["level"] in ("critical", "warning"):
                top_risks.append({"domain": "Reliability", "severity": alert["level"], "message": alert["message"]})

    if velocity:
        pred = velocity.get("predictability_score", 1.0)
        trend_penalty = {"down": 3.0, "flat": 1.0, "up": 0.0}.get(velocity.get("velocity_trend", "flat"), 1.0)
        velocity_score = min(10.0, (1 - pred) * 5 + trend_penalty)
        scores["velocity"] = round(velocity_score, 1)
        for alert in velocity.get("alerts") or []:
            if alert["level"] in ("critical", "warning"):
                top_risks.append({"domain": "Engineering Velocity", "severity": alert["level"], "message": alert["message"]})

    overall_health = round(sum(scores.values()) / len(scores), 1) if scores else 0.0
    top_risks.sort(key=lambda r: 0 if r["severity"] == "critical" else 1)

    # ── Quick wins (Türkçe) ───────────────────────────────────────────────────
    quick_wins: list[dict[str, str]] = []
    if infra.get("waste_estimate_cents", 0) > 0:
        quick_wins.append({
            "action": "Non-production bulut ortamlarını rightsize et",
            "estimated_impact": f"Aylık {infra['waste_estimate_cents']/100:,.0f} ₺ tasarruf",
            "effort": "düşük",
        })
    if tech_debt.get("refactor_priorities"):
        priority = tech_debt["refactor_priorities"][0]
        quick_wins.append({
            "action": f"Hotspot refactoring: {priority['area']}",
            "estimated_impact": "Bu bileşen için değişiklik başarısızlık oranını azalt",
            "effort": f"~{priority.get('estimated_days', 3)} gün",
        })
    if incidents.get("trend") == "degrading":
        quick_wins.append({
            "action": "En sık olay yaşanan 3 servis için post-mortem yap",
            "estimated_impact": "Olay sıklığını %20-30 azalt",
            "effort": "orta",
        })

    # ── LLM narrative (Türkçe + actionable) ──────────────────────────────────
    try:
        llm = ChatOpenAI(
            model=settings.llm_model,
            temperature=0.2,
            max_tokens=800,
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,
        )
        risks_text = "\n".join(
            f"- [{r['severity'].upper()}] {r['domain']}: {r['message']}"
            for r in top_risks[:5]
        ) or "Kritik risk tespit edilmedi."
        scores_text = " | ".join(f"{k}: {v}/10" for k, v in scores.items())

        response = await llm.ainvoke([
            SystemMessage(content=(
                "Sen deneyimli bir CTO'sun. Aşağıdaki teknoloji sağlık verilerini analiz et ve "
                "Türkçe olarak kısa bir yönetici özeti yaz. "
                "Yanıt şu yapıda olsun:\n"
                "1. Genel teknoloji sağlık durumunun 1-2 cümlelik değerlendirmesi (skor odaklı)\n"
                "2. En kritik 1-2 risk (altyapı, teknik borç veya olay)\n"
                "3. Yönetimin hemen yapması gereken 2-3 somut eylem (öncelik sırasıyla)\n"
                "Teknik jargonu azalt, CEO'nun anlayacağı dilde yaz."
            )),
            HumanMessage(content=(
                f"Genel Teknoloji Sağlık Skoru: {overall_health}/10\n"
                f"Bileşen Skorları: {scores_text}\n\n"
                f"Önemli Riskler:\n{risks_text}"
            )),
        ])
        narrative = response.content.strip()
    except Exception as exc:
        logger.warning("CTO summary narrative failed: %s", exc)
        narrative = f"Teknoloji sağlık skoru: {overall_health}/10. {len(scores)} alanda {len(top_risks)} risk tespit edildi."

    summary = {
        "overall_health_score": overall_health,
        "component_scores": scores,
        "top_risks": top_risks[:8],
        "quick_wins": quick_wins[:5],
        "narrative": narrative,
    }

    patch = _append_log(state, CTOStepLog(
        step="cto_summary", ok=True,
        detail=f"Health score: {overall_health}/10, risks: {len(top_risks)}, quick wins: {len(quick_wins)}",
        confidence=0.90,
    ))
    patch["cto_summary"] = summary
    return {**state, **patch}  # type: ignore[return-value]


async def node_hold_for_review(state: CTOState, config: dict) -> CTOState:
    patch = _append_log(state, CTOStepLog(
        step="review_gate",
        ok=True,
        detail=(
            f"Held for review — confidence={state.get('min_confidence', 0):.2f}, "
            f"awaiting_review={state.get('awaiting_review')}"
        ),
    ))
    patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]


# ── Routing ────────────────────────────────────────────────────────────────────

def route_after_velocity(state: CTOState) -> str:
    """After all data agents, check if review is needed before summary."""
    if state.get("awaiting_review"):
        cfg = DEFAULT_CTO_RUN_CONFIG
        if cfg.require_review:
            return CTO_ROUTE_HOLD
    if (state.get("min_confidence") or 1.0) < 0.80:
        return CTO_ROUTE_HOLD
    return CTO_ROUTE_SUMMARY


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_cto_graph() -> StateGraph:
    graph = StateGraph(CTOState)

    graph.add_node("infra",           node_infra)
    graph.add_node("tech_debt",       node_tech_debt)
    graph.add_node("incidents",       node_incidents)
    graph.add_node("velocity",        node_velocity)
    graph.add_node("cto_summary",     node_cto_summary)
    graph.add_node("hold_for_review", node_hold_for_review)

    graph.set_entry_point("infra")

    # All data agents are non-fatal → linear pipeline
    graph.add_edge("infra",      "tech_debt")
    graph.add_edge("tech_debt",  "incidents")
    graph.add_edge("incidents",  "velocity")

    # After velocity → review gate OR summary
    graph.add_conditional_edges(
        "velocity",
        route_after_velocity,
        {
            CTO_ROUTE_SUMMARY: "cto_summary",
            CTO_ROUTE_HOLD:    "hold_for_review",
        },
    )

    graph.add_edge("cto_summary",     END)
    graph.add_edge("hold_for_review", END)

    return graph


# Compiled graph — reused across requests
cto_graph = build_cto_graph().compile()


# ── Public entry point ─────────────────────────────────────────────────────────

async def run_cto_pipeline(
    job_id: str,
    cloud_billing_csv: str | None = None,
    git_log_text: str | None = None,
    incident_csv: str | None = None,
    sprint_csv: str | None = None,
    company_name: str | None = None,
    run_config: CTORunConfig | None = None,
) -> CTOState:
    """
    Run the full CTO analysis pipeline.

    At least one data source required; others are optional.
    All agents gracefully skip when their input is absent.

    Returns final CTOState — caller persists to DB.
    """
    cfg = run_config or DEFAULT_CTO_RUN_CONFIG
    initial_state: CTOState = {
        "job_id": job_id,
        "company_name": company_name,
        "cloud_billing_csv": cloud_billing_csv,
        "git_log_text": git_log_text,
        "incident_csv": incident_csv,
        "sprint_csv": sprint_csv,
        "logs": [],
        "min_confidence": 1.0,
        "awaiting_review": False,
        "halted": False,
        "error": None,
    }

    result: CTOState = await cto_graph.ainvoke(
        initial_state,
        config={"configurable": {"cto_run_config": cfg}},
    )

    logger.info(
        "CTO pipeline finished: job=%s health=%.1f awaiting_review=%s",
        job_id,
        (result.get("cto_summary") or {}).get("overall_health_score", 0),
        result.get("awaiting_review"),
    )
    return result
