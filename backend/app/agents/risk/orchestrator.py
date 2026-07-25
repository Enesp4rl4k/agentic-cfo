"""
Risk Orchestrator

LangGraph pipeline: register → loss → kri → risk_summary → END
Synthesises all three risk signals into an enterprise risk posture report.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph, END

from app.agents.risk.state import RiskState, RiskStepLog
from app.agents.risk.register_agent import run_register_agent
from app.agents.risk.loss_agent import run_loss_agent
from app.agents.risk.kri_agent import run_kri_agent

logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _append_log(state: RiskState, log: RiskStepLog) -> dict[str, Any]:
    logs = list(state.get("logs") or [])
    logs.append(log)
    return {"logs": logs}


# ── Nodes ──────────────────────────────────────────────────────────────────────

async def node_register(state: RiskState, config: dict) -> RiskState:
    result = await run_register_agent(state, config)
    return {**state, "register": result["register"],
            "logs": result["logs"], "error": result.get("error")}


async def node_loss(state: RiskState, config: dict) -> RiskState:
    result = await run_loss_agent(state, config)
    return {**state, "losses": result["losses"],
            "logs": result["logs"], "error": result.get("error")}


async def node_kri(state: RiskState, config: dict) -> RiskState:
    result = await run_kri_agent(state, config)
    return {**state, "kris": result["kris"],
            "logs": result["logs"], "error": result.get("error")}


async def node_risk_summary(state: RiskState, config: dict) -> RiskState:  # noqa: C901
    """
    Synthesise register + loss + kri into enterprise risk posture.
    Enterprise Risk Score (0-10, higher = worse).
    """
    reg  = state.get("register") or {}
    loss = state.get("losses")   or {}
    kri  = state.get("kris")     or {}
    logs: list[RiskStepLog] = list(state.get("logs") or [])

    # ── Enterprise Risk Score ─────────────────────────────────────────────────
    # Weighted average of three sub-scores, each 0-10:
    #   register score  (35 %) — residual risk portfolio
    #   loss score      (35 %) — realised losses (normalised vs $1M ceiling)
    #   kri score       (30 %) — leading indicator breaches

    reg_score  = float(reg.get("enterprise_risk_score", 0.0))
    net_loss   = float(loss.get("total_net_loss", 0))
    loss_score = min(10.0, (net_loss / (1_000_000 * 100)) * 10.0)  # $1M ceiling
    kri_score  = float(kri.get("composite_kri_score", 0.0))

    enterprise_score = round(
        reg_score  * 0.35 +
        loss_score * 0.35 +
        kri_score  * 0.30,
        1,
    )

    # ── Risk Posture Label ────────────────────────────────────────────────────
    if enterprise_score >= 7.0:
        posture = "critical"
    elif enterprise_score >= 5.0:
        posture = "elevated"
    elif enterprise_score >= 3.0:
        posture = "moderate"
    else:
        posture = "acceptable"

    # ── Top Risks ─────────────────────────────────────────────────────────────
    top_risks: list[dict[str, Any]] = []

    # From register — unmitigated critical
    for r in reg.get("unmitigated_critical", [])[:3]:
        top_risks.append({
            "source": "risk_register",
            "title":  r.get("title", "Unknown risk"),
            "severity": r.get("band", "critical"),
            "recommended_action": "Assign owner and implement mitigation immediately.",
        })

    # From KRI — red breaches
    for k in kri.get("breached_red", [])[:2]:
        top_risks.append({
            "source": "kri",
            "title":  f"KRI Breach: {k.get('name', 'Unknown KRI')}",
            "severity": "critical",
            "recommended_action": f"KRI value {k.get('value')} exceeds red threshold {k.get('threshold_red')} — escalate.",
        })

    # From losses — top loss event
    for ev in loss.get("top_loss_events", [])[:1]:
        top_risks.append({
            "source": "loss_events",
            "title":  f"Loss Event: {ev.get('description', '')[:60]}",
            "severity": "high",
            "recommended_action": f"Root cause: {ev.get('root_cause', 'unknown')} — close and prevent recurrence.",
        })

    # ── Quick Wins (Türkçe) ───────────────────────────────────────────────────
    quick_wins: list[dict[str, str]] = []

    no_mitigation = len(reg.get("unmitigated_critical", []))
    if no_mitigation:
        quick_wins.append({
            "action": f"{no_mitigation} kritik risk için azaltım planı hazırla",
            "effort": "düşük",
            "impact": "Kurumsal risk skorunu hemen iyileştirir",
        })

    amber_kris = len(kri.get("breached_amber", []))
    if amber_kris:
        quick_wins.append({
            "action": f"{amber_kris} amber KRI'yı kırmızıya dönmeden önce ele al",
            "effort": "orta",
            "impact": "Öncü göstergelerin kayba dönüşmesini önle",
        })

    if loss.get("open_events", 0):
        quick_wins.append({
            "action": f"{loss['open_events']} açık kayıp olayını kapat",
            "effort": "orta",
            "impact": "Kuyruk riskini azalt ve kurtarma oranını iyileştir",
        })

    coverage = reg.get("mitigation_coverage", 1.0)
    if coverage < 0.70:
        quick_wins.append({
            "action": "Kapsama dışı orta riskler için kontrol geliştir",
            "effort": "yüksek",
            "impact": f"Azaltım kapsamını %{coverage*100:.0f}'dan %80 hedefine çıkar",
        })

    # ── Cross-KRI correlation analysis ───────────────────────────────────────
    cross_correlation: dict[str, Any] | None = None
    try:
        kri_list = kri.get("kri_list") or kri.get("kris") or []
        if kri_list and len(kri_list) >= 2:
            from app.agents.risk.cross_correlation import CrossKRIAnalyzer
            analyzer = CrossKRIAnalyzer(kri_list)
            cross_correlation = analyzer.compute_cross_correlations()

            # Add systemic risk quick wins
            if cross_correlation.get("systemic_risks"):
                sys_names = ", ".join(
                    f"'{s['kri']}'" for s in cross_correlation["systemic_risks"][:2]
                )
                quick_wins.append({
                    "action": f"Sistemik risk KRI'larını öncelikli izle: {sys_names}",
                    "effort": "düşük",
                    "impact": "Zincirleme risk etkisini erkenden tespit et",
                })
    except Exception as cross_exc:
        logger.debug("Cross-KRI correlation skipped: %s", cross_exc)

    # ── Narrative (Türkçe + LLM) ──────────────────────────────────────────────
    posture_tr = {
        "critical":   "KRİTİK",
        "elevated":   "YÜKSELMİŞ",
        "moderate":   "ORTA",
        "acceptable": "KABUL EDİLEBİLİR",
    }.get(posture, posture.upper())

    narrative = (
        f"Kurumsal risk skoru: {enterprise_score}/10 — risk duruşu {posture_tr}. "
        f"Risk kaydı: {reg.get('total_risks', 0)} risk, "
        f"{reg.get('by_band', {}).get('critical', 0)} kritik. "
        f"Operasyonel kayıplar: {loss.get('total_net_loss', 0) / 100:,.0f} ₺ net. "
        f"KRI: {len(kri.get('breached_red', []))} kırmızı, "
        f"{len(kri.get('breached_amber', []))} amber."
    )
    if top_risks:
        narrative += f" Öncelikli risk: {top_risks[0]['title'][:60]}."

    # LLM enrichment (non-fatal)
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
        cross_context = ""
        if cross_correlation and cross_correlation.get("systemic_risks"):
            sys_names = ", ".join(s["kri"] for s in cross_correlation["systemic_risks"][:2])
            cross_context = f"\nSistemik risk KRI'ları: {sys_names}"
        if cross_correlation and cross_correlation.get("leading_indicators"):
            li = cross_correlation["leading_indicators"][0]
            cross_context += f"\nÖncü gösterge: {li['interpretation']}"

        llm_response = await llm.ainvoke([
            SystemMessage(content=(
                "Sen deneyimli bir Risk Yöneticisisin. Kurumsal risk verilerini analiz et ve "
                "Türkçe olarak kısa, eyleme dönüştürülebilir bir yönetici özeti yaz.\n"
                "Yanıt yapısı:\n"
                "1. Genel risk duruşunun 1-2 cümlelik değerlendirmesi\n"
                "2. En kritik 1-2 risk\n"
                "3. Yönetimin hemen yapması gereken 2-3 somut eylem\n"
                "Risk profesyoneli bakışıyla pratik öneriler ekle."
            )),
            HumanMessage(content=narrative + cross_context),
        ])
        narrative = llm_response.content.strip()
    except Exception as llm_exc:
        logger.debug("Risk summary LLM failed: %s", llm_exc)

    summary = {
        "enterprise_risk_score": enterprise_score,
        "risk_posture":          posture,
        "risk_posture_tr":       posture_tr,
        "component_scores": {
            "register":  round(reg_score, 1),
            "losses":    round(loss_score, 1),
            "kri":       round(kri_score, 1),
        },
        "top_risks":        top_risks[:6],
        "quick_wins":       quick_wins[:5],
        "narrative":        narrative,
        "cross_correlation": cross_correlation,
    }

    log = RiskStepLog(
        node="risk_summary", status="completed",
        message=f"Risk posture: {posture} ({enterprise_score}/10)",
        metrics={"enterprise_risk_score": enterprise_score},
    )
    logs.append(log)

    return {**state, "risk_summary": summary, "logs": logs}


# ── Graph ──────────────────────────────────────────────────────────────────────

def build_risk_graph() -> StateGraph:
    builder = StateGraph(RiskState)
    builder.add_node("register", node_register)
    builder.add_node("loss",     node_loss)
    builder.add_node("kri",      node_kri)
    builder.add_node("risk_summary", node_risk_summary)

    builder.add_edge("register",     "loss")
    builder.add_edge("loss",         "kri")
    builder.add_edge("kri",          "risk_summary")
    builder.add_edge("risk_summary", END)

    builder.set_entry_point("register")
    return builder.compile()


_risk_graph = build_risk_graph()


# ── Public Entry Point ─────────────────────────────────────────────────────────

async def run_risk_pipeline(
    register_csv: str,
    loss_csv: str,
    kri_csv: str,
    company_name: str | None = None,
    reporting_period: str | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    """
    Run the complete Risk pipeline.
    Returns: { register, losses, kris, risk_summary, logs, error }
    """
    initial: RiskState = {
        "register_csv":     register_csv,
        "loss_csv":         loss_csv,
        "kri_csv":          kri_csv,
        "company_name":     company_name,
        "reporting_period": reporting_period,
        "register":         None,
        "losses":           None,
        "kris":             None,
        "risk_summary":     None,
        "logs":             [],
        "error":            None,
    }

    result: RiskState = await _risk_graph.ainvoke(
        initial, config={"configurable": {"settings": settings}}
    )

    return {
        "register":     result.get("register"),
        "losses":       result.get("losses"),
        "kris":         result.get("kris"),
        "risk_summary": result.get("risk_summary"),
        "logs":         result.get("logs"),
        "error":        result.get("error"),
    }
