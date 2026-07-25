"""
CHRO Orchestrator

LangGraph-based orchestrator for the CHRO agent pipeline.
Flow: headcount → attrition → compensation → chro_summary → END

Uses pure computation (no LLM required for synthesis).
"""

from langgraph.graph import StateGraph, END
from typing import Any

from app.agents.chro.state import CHROState, CHROStepLog
from app.agents.chro.headcount_agent import run_headcount_agent
from app.agents.chro.attrition_agent import run_attrition_agent
from app.agents.chro.compensation_agent import run_compensation_agent


def _append_log(state: CHROState, log: CHROStepLog) -> dict[str, Any]:
    """Append a step log to the state."""
    logs = state.get("logs") or []
    logs.append(log)
    return {"logs": logs}


async def node_headcount(state: CHROState, config: dict) -> CHROState:
    """Headcount analysis node."""
    result = await run_headcount_agent(state, config)
    return {
        **state,
        "headcount": result["headcount"],
        "logs": result["logs"],
        "error": result["error"],
    }


async def node_attrition(state: CHROState, config: dict) -> CHROState:
    """Attrition analysis node."""
    result = await run_attrition_agent(state, config)
    return {
        **state,
        "attrition": result["attrition"],
        "logs": result["logs"],
        "error": result["error"],
    }


async def node_compensation(state: CHROState, config: dict) -> CHROState:
    """Compensation analysis node."""
    result = await run_compensation_agent(state, config)
    return {
        **state,
        "compensation": result["compensation"],
        "logs": result["logs"],
        "error": result["error"],
    }


async def node_chro_summary(state: CHROState, config: dict) -> CHROState:
    """
    Synthesize headcount + attrition + compensation into CHRO summary.
    Pure computation — no LLM.
    """
    
    hc = state.get("headcount") or {}
    att = state.get("attrition") or {}
    comp = state.get("compensation") or {}
    logs = state.get("logs") or []
    
    # Compute CHRO health score (0-10, lower is better)
    # Factors:
    # - Org structure risk: +1 if present
    # - Early departures: +attrition_rate * 5
    # - Salary compression: +1 if any level > 1.5x
    # - Below market: +below_count/total * 3
    # - Low equity penetration: +1 if < 50%
    
    chro_score = 3.0  # Base
    
    # Org structure penalty
    if hc.get("org_structure_risk"):
        chro_score += 1.0
    
    # Early departure penalty
    early_rate = hc.get("early_departure_rate", 0) if not att else att.get("early_departure_rate", 0)
    chro_score += early_rate * 4.0
    
    # Salary compression penalty
    compression_risks = 0
    for ratio in comp.get("salary_compression_ratios", {}).values():
        if ratio > 1.5:
            compression_risks += 1
    chro_score += compression_risks * 0.5
    
    # Below market penalty
    below_market = comp.get("below_market_count", 0)
    total_emp = comp.get("total_employees", 1)
    chro_score += (below_market / total_emp) * 2.0 if total_emp > 0 else 0
    
    # Low equity penetration penalty
    equity_pen = comp.get("equity_penetration", 1.0)
    if equity_pen < 0.50:
        chro_score += 1.0
    
    # Cap at 10
    chro_score = min(10.0, max(0.0, chro_score))
    
    # Aggregate alerts
    all_alerts = []
    all_alerts.extend(hc.get("alerts", []))
    all_alerts.extend(att.get("alerts", []))
    all_alerts.extend(comp.get("alerts", []))
    
    # Top risks
    critical_alerts = [a for a in all_alerts if a.get("level") == "critical"]
    warning_alerts = [a for a in all_alerts if a.get("level") == "warning"]
    
    top_risks = []
    for alert in critical_alerts[:3]:
        top_risks.append({
            "title": alert["message"][:50],
            "severity": "critical",
            "description": alert["message"],
        })
    for alert in warning_alerts[:2]:
        top_risks.append({
            "title": alert["message"][:50],
            "severity": "warning",
            "description": alert["message"],
        })
    
    # Quick wins (Türkçe)
    quick_wins = []
    if hc.get("total_headcount", 0) > 0 and att.get("replaced_rate", 0) < 0.5:
        quick_wins.append({
            "action": "Açık pozisyonlar için işe alım sürecini hızlandır",
            "effort": "orta",
            "impact": f"Yerini doldurmada gecikmeyi {int(att.get('recent_departures_count', 0) * 0.3)} pozisyon azalt",
        })

    if comp.get("below_market_count", 0) > 0:
        quick_wins.append({
            "action": "Piyasanın altında kalan pozisyonlar için ücret düzenlemesi yap",
            "effort": "orta",
            "impact": f"Risk altındaki {comp.get('below_market_count', 0)} çalışanın tutunmasını iyileştir",
        })

    if early_rate > 0.15:
        quick_wins.append({
            "action": "İşe alış (onboarding) programını geliştir",
            "effort": "düşük",
            "impact": f"Erken ayrılmaları %30 azalt (~{int(early_rate * hc.get('total_headcount', 0) * 0.3)} FTE tasarruf)",
        })

    if equity_pen < 0.50:
        quick_wins.append({
            "action": "Hisse senedi katılım programını genişlet",
            "effort": "düşük",
            "impact": "Geniş çalışan kitlesinde tutunma ve bağlılığı artır",
        })

    # Narrative — LLM ile Türkçe özet
    total_comp_millions = comp.get("total_annual_comp", 0) / 100 / 1_000_000
    narrative = (
        f"Organizasyonda {hc.get('total_headcount', 0)} çalışan var, ortalama kıdem {hc.get('avg_tenure_years', 0):.1f} yıl. "
        f"Yıllık ücret taahhüdü: {total_comp_millions:.1f}M ₺, %{comp.get('equity_penetration', 0)*100:.0f} hisse katılımı. "
        f"{'Dikkat: %' + str(int(early_rate*100)) + ' erken ayrılma oranı tespit edildi. ' if early_rate > 0.10 else ''}"
        f"{str(len(top_risks)) + ' önemli İK riski mevcut.' if top_risks else 'Kritik İK riski tespit edilmedi.'}"
    )

    # LLM ile zenginleştir (non-fatal)
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
        risks_text = "\n".join(
            f"- [{r['severity'].upper()}] {r['description']}"
            for r in top_risks[:4]
        ) or "Kritik risk tespit edilmedi."

        response = await llm.ainvoke([
            SystemMessage(content=(
                "Sen deneyimli bir CHRO'sun. İnsan kaynakları sağlık verilerini analiz et ve "
                "Türkçe olarak kısa, eyleme dönüştürülebilir bir yönetici özeti yaz. "
                "Yanıt şu yapıda olsun:\n"
                "1. Organizasyonel sağlığın 1-2 cümlelik değerlendirmesi (başkanlık ve ayrılma odaklı)\n"
                "2. En kritik 1-2 İK riski (yüksek ayrılma, piyasa altı ücret, organizasyonel darboğaz)\n"
                "3. İK ekibinin hemen yapması gereken 2-3 somut eylem (öncelik sırasıyla)\n"
                "People-first bakış açısıyla pratik öneriler ekle."
            )),
            HumanMessage(content=(
                f"Toplam Çalışan: {hc.get('total_headcount', 0)}\n"
                f"Ortalama Kıdem: {hc.get('avg_tenure_years', 0):.1f} yıl\n"
                f"Erken Ayrılma Oranı: %{early_rate*100:.0f}\n"
                f"Piyasa Altı Ücret Sayısı: {comp.get('below_market_count', 0)}\n"
                f"Hisse Katılımı: %{comp.get('equity_penetration', 0)*100:.0f}\n"
                f"Ücret Sıkışması Riski: {'var' if compression_risks > 0 else 'yok'}\n\n"
                f"Önemli Riskler:\n{risks_text}"
            )),
        ])
        narrative = response.content.strip()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("CHRO narrative LLM failed: %s", exc)
    
    summary = {
        "chro_health_score": round(chro_score, 1),
        "total_headcount": hc.get("total_headcount", 0),
        "total_departures": att.get("total_departures", 0),
        "total_annual_comp": comp.get("total_annual_comp", 0),
        "top_risks": top_risks,
        "quick_wins": quick_wins,
        "narrative": narrative,
        "component_scores": {
            "headcount_org_health": 10.0 - (1.0 if hc.get("org_structure_risk") else 0),
            "attrition_health": 10.0 - (early_rate * 4.0),
            "compensation_market_alignment": 10.0 - ((comp.get("below_market_count", 0) / total_emp) * 2.0 if total_emp > 0 else 0),
        },
    }
    
    log = CHROStepLog(
        node="chro_summary",
        status="completed",
        message=f"CHRO synthesis complete — health score: {summary['chro_health_score']}/10",
        metrics={"chro_health_score": summary["chro_health_score"]},
    )
    logs.append(log)
    
    return {
        **state,
        "chro_summary": summary,
        "logs": logs,
    }


def build_chro_graph() -> StateGraph:
    """Build the CHRO orchestrator graph."""
    
    builder = StateGraph(CHROState)
    
    builder.add_node("headcount", node_headcount)
    builder.add_node("attrition", node_attrition)
    builder.add_node("compensation", node_compensation)
    builder.add_node("chro_summary", node_chro_summary)
    
    # Flow: headcount → attrition → compensation → chro_summary → END
    builder.add_edge("headcount", "attrition")
    builder.add_edge("attrition", "compensation")
    builder.add_edge("compensation", "chro_summary")
    builder.add_edge("chro_summary", END)
    
    builder.set_entry_point("headcount")
    
    return builder.compile()


_chro_graph = build_chro_graph()


async def run_chro_pipeline(
    headcount_csv: str,
    attrition_csv: str,
    compensation_csv: str,
    company_name: str | None = None,
    analysis_period: str | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    """
    Run complete CHRO pipeline.
    Returns: { headcount, attrition, compensation, chro_summary, logs, error }
    """
    
    initial_state: CHROState = {
        "headcount_csv": headcount_csv,
        "attrition_csv": attrition_csv,
        "compensation_csv": compensation_csv,
        "company_name": company_name,
        "analysis_period": analysis_period,
        "headcount": None,
        "attrition": None,
        "compensation": None,
        "chro_summary": None,
        "logs": [],
        "error": None,
    }
    
    config = {
        "settings": settings,
    }
    
    result: CHROState = await _chro_graph.ainvoke(initial_state, config=config)
    
    return {
        "headcount": result.get("headcount"),
        "attrition": result.get("attrition"),
        "compensation": result.get("compensation"),
        "chro_summary": result.get("chro_summary"),
        "logs": result.get("logs"),
        "error": result.get("error"),
    }
