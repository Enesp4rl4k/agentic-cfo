"""
Compliance Orchestrator — LangGraph StateGraph.

Pipeline:
  START
  → policies     (non-fatal: no data → skip)
  → violations   (non-fatal: no data → skip)
  → regulations  (non-fatal: no data → skip)
  → compliance_summary  (always runs — synthesizes all signals)
  → END

At least one data source required to produce a meaningful summary.
All agents gracefully skip when their input is absent.

Compliance health score: 0–100 (100 = fully compliant, no violations).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from langgraph.graph import StateGraph, END

from app.agents.compliance.state import (
    ComplianceState,
    ComplianceStepLog,
)
from app.agents.compliance.policies_agent    import run_policies_agent
from app.agents.compliance.violations_agent  import run_violations_agent
from app.agents.compliance.regulations_agent import run_regulations_agent

logger = logging.getLogger(__name__)

# Routing constants
_ROUTE_SUMMARY = "compliance_summary"
_ROUTE_END     = "__end__"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _append_log(state: ComplianceState, log: ComplianceStepLog) -> dict[str, Any]:
    existing = list(state.get("logs") or [])
    existing.append(log)
    return {"logs": existing}


# ── Nodes ──────────────────────────────────────────────────────────────────────

async def node_policies(state: ComplianceState, config: dict) -> ComplianceState:
    if not state.get("policy_csv", "").strip():
        patch = _append_log(state, ComplianceStepLog(
            node="policies_agent",
            status="skipped",
            message="No policy_csv provided — PoliciesAgent skipped.",
        ))
        patch["policies"] = None
        return {**state, **patch}  # type: ignore[return-value]

    result = await run_policies_agent(state, config)
    patch  = _append_log(state, result["logs"][-1] if result.get("logs") else ComplianceStepLog(
        node="policies_agent", status="completed", message="done"
    ))
    patch["policies"] = result.get("policies")
    if result.get("error"):
        patch["error"] = result["error"]
    return {**state, **patch}  # type: ignore[return-value]


async def node_violations(state: ComplianceState, config: dict) -> ComplianceState:
    if not state.get("violations_csv", "").strip():
        patch = _append_log(state, ComplianceStepLog(
            node="violations_agent",
            status="skipped",
            message="No violations_csv provided — ViolationsAgent skipped.",
        ))
        patch["violations"] = None
        return {**state, **patch}  # type: ignore[return-value]

    result = await run_violations_agent(state, config)
    patch  = _append_log(state, result["logs"][-1] if result.get("logs") else ComplianceStepLog(
        node="violations_agent", status="completed", message="done"
    ))
    patch["violations"] = result.get("violations")
    if result.get("error"):
        patch["error"] = result["error"]
    return {**state, **patch}  # type: ignore[return-value]


async def node_regulations(state: ComplianceState, config: dict) -> ComplianceState:
    if not state.get("regulations_csv", "").strip():
        patch = _append_log(state, ComplianceStepLog(
            node="regulations_agent",
            status="skipped",
            message="No regulations_csv provided — RegulationsAgent skipped.",
        ))
        patch["regulations"] = None
        return {**state, **patch}  # type: ignore[return-value]

    result = await run_regulations_agent(state, config)
    patch  = _append_log(state, result["logs"][-1] if result.get("logs") else ComplianceStepLog(
        node="regulations_agent", status="completed", message="done"
    ))
    patch["regulations"] = result.get("regulations")
    if result.get("error"):
        patch["error"] = result["error"]
    return {**state, **patch}  # type: ignore[return-value]


async def node_compliance_summary(state: ComplianceState, config: dict) -> ComplianceState:
    """
    Synthesize all three skill outputs into a unified compliance health score
    and actionable risk list. Pure calculation — no LLM required.
    """
    policies   = state.get("policies")   or {}
    violations = state.get("violations") or {}
    regulations = state.get("regulations") or {}

    company = state.get("company_name") or "the organisation"

    # ── Component health scores (0–100, higher = better) ─────────────────────

    scores: dict[str, float] = {}
    all_alerts: list[dict[str, str]] = []
    all_recommendations: list[dict[str, str]] = []

    # Policies score (based on active policies, no stale reviews)
    if policies:
        total_p  = policies.get("total_policies", 0)
        active_p = policies.get("active_policies", 0)
        overdue_p = policies.get("policies_needing_review", 0)
        if total_p > 0:
            active_ratio = active_p / total_p
            overdue_ratio = overdue_p / total_p
            policy_score = max(0.0, min(100.0, (active_ratio * 60) + ((1 - overdue_ratio) * 40)))
        else:
            policy_score = 0.0
        scores["policies"] = round(policy_score, 1)
        all_alerts.extend(policies.get("alerts", []))

    # Violations score (based on open/overdue violations)
    if violations:
        total_v   = violations.get("total_violations", 0)
        open_v    = violations.get("open_violations", 0)
        overdue_v = violations.get("overdue_violations", 0)
        critical  = violations.get("critical_open", 0)
        rem_rate  = violations.get("remediation_rate", 100.0)

        if total_v > 0:
            # Heavily penalise critical open and overdue
            viol_score = min(100.0, max(0.0,
                rem_rate
                - (critical * 15)
                - (overdue_v / max(total_v, 1) * 30)
            ))
        else:
            viol_score = 100.0  # no violations = perfect
        scores["violations"] = round(viol_score, 1)
        all_alerts.extend(violations.get("alerts", []))
        all_recommendations.extend(violations.get("recommendations", []))

    # Regulations score (compliance coverage)
    if regulations:
        coverage = regulations.get("compliance_coverage_pct", 0.0)
        # Add penalty for critical non-compliant frameworks
        fw_scores = regulations.get("framework_scores", {})
        critical_fw_penalty = sum(
            max(0, 70 - score) * 0.3
            for score in fw_scores.values()
            if score < 70
        )
        reg_score = max(0.0, min(100.0, coverage - critical_fw_penalty))
        scores["regulations"] = round(reg_score, 1)
        all_alerts.extend(regulations.get("alerts", []))
        all_recommendations.extend(regulations.get("recommendations", []))

    # Overall health score: weighted average
    weights = {"policies": 0.25, "violations": 0.40, "regulations": 0.35}
    if scores:
        weighted_sum = sum(scores[k] * weights.get(k, 0.33) for k in scores)
        weight_total = sum(weights.get(k, 0.33) for k in scores)
        overall_health = round(weighted_sum / weight_total, 1)
    else:
        overall_health = 0.0

    # ── Risk classification ───────────────────────────────────────────────────

    critical_alerts = [a for a in all_alerts if a.get("level") == "critical"]
    warning_alerts  = [a for a in all_alerts if a.get("level") == "warning"]

    if overall_health >= 90:
        health_status = "excellent"
    elif overall_health >= 75:
        health_status = "good"
    elif overall_health >= 60:
        health_status = "fair"
    elif overall_health >= 40:
        health_status = "poor"
    else:
        health_status = "critical"

    # ── Top risks list (Türkçe) ───────────────────────────────────────────────

    top_risks: list[dict[str, str]] = []

    if violations:
        crit_open = violations.get("critical_open", 0)
        if crit_open > 0:
            top_risks.append({
                "domain": "İhlaller",
                "severity": "critical",
                "message": f"{crit_open} kritik ihlal açık — acil giderim gerekiyor.",
            })
        overdue_v = violations.get("overdue_violations", 0)
        if overdue_v > 0:
            top_risks.append({
                "domain": "İhlaller",
                "severity": "high",
                "message": f"{overdue_v} ihlal vadesi geçmiş — sorumluya eskalasyon gerekli.",
            })

    if regulations:
        non_comp = regulations.get("non_compliant_count", 0)
        if non_comp > 0:
            top_risks.append({
                "domain": "Mevzuat",
                "severity": "high" if non_comp < 5 else "critical",
                "message": (
                    f"{non_comp} mevzuat gereksinimi uyumsuz — "
                    f"{len(regulations.get('frameworks', []))} çerçevede."
                ),
            })

    if policies:
        overdue_p = policies.get("policies_needing_review", 0)
        if overdue_p > 0:
            top_risks.append({
                "domain": "Politikalar",
                "severity": "medium",
                "message": f"{overdue_p} politika gözden geçirilmeli (>1 yıl eski).",
            })

    # ── Türkiye regulatory mapping ────────────────────────────────────────────
    turkey_reg_mapping: dict[str, Any] | None = None
    try:
        from app.agents.compliance.turkey_regulations import get_applicable_requirements

        company_size = state.get("company_size") or "all"
        applicable = get_applicable_requirements(company_size=company_size, min_severity="high")

        # Check against existing violations/frameworks
        existing_violation_regs = set()
        for v in (violations.get("violations_list") or []):
            reg = v.get("framework") or v.get("regulation", "")
            if reg:
                existing_violation_regs.add(reg.upper())

        # Flag requirements that are not covered in the company's data
        unchecked: list[dict[str, Any]] = []
        for req in applicable:
            reg_key = req["regulation"].upper()
            # If no data about this regulation AND it's critical, flag as unchecked
            if reg_key not in existing_violation_regs and req["severity"] == "critical":
                unchecked.append({
                    "id":          req["id"],
                    "regulation":  req["regulation"],
                    "requirement": req["requirement"],
                    "penalty":     req["penalty"],
                    "checklist":   req["checklist"],
                })

        turkey_reg_mapping = {
            "applicable_requirements": len(applicable),
            "unchecked_critical":      unchecked[:5],
            "message": (
                f"{len(unchecked)} kritik yasal gereksinim kontrol edilmedi."
                if unchecked else
                "Temel yasal gereksinimler kapsanmış görünüyor."
            ),
        }

        # Add Turkey-specific risks to top risks
        if unchecked:
            top_risks.append({
                "domain": "Türkiye Mevzuatı",
                "severity": "critical",
                "message": (
                    f"{len(unchecked)} kritik yasal gereksinim ({', '.join(r['regulation'] for r in unchecked[:3])}) "
                    f"kontrol edilmemiş — cezai risk: {unchecked[0]['penalty']}"
                ),
            })
    except Exception as tr_exc:
        logger.debug("Turkey regulatory mapping skipped: %s", tr_exc)

    # Sort: critical first
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    top_risks.sort(key=lambda r: sev_order.get(r["severity"], 3))

    # ── Deduplicate & prioritise recommendations ──────────────────────────────
    seen_actions: set[str] = set()
    deduped_recs: list[dict[str, str]] = []
    for rec in sorted(all_recommendations, key=lambda r: r.get("priority", "P9")):
        key = rec.get("action", "")[:60]
        if key not in seen_actions:
            seen_actions.add(key)
            deduped_recs.append(rec)
    deduped_recs = deduped_recs[:8]

    # ── Executive narrative (Türkçe + LLM) ────────────────────────────────────
    health_tr = {
        "excellent": "MÜKEMMEL",
        "good":      "İYİ",
        "fair":      "ORTA",
        "poor":      "ZAYIF",
        "critical":  "KRİTİK",
    }.get(health_status, health_status.upper())

    narrative = (
        f"{company} uyum sağlığı: {overall_health:.0f}/100 ({health_tr}). "
        f"Mevzuat kapsamı: %{regulations.get('compliance_coverage_pct', 0):.0f}. "
        f"Açık ihlal: {violations.get('open_violations', 0)} ({violations.get('critical_open', 0)} kritik). "
    )
    if critical_alerts:
        narrative += f"{len(critical_alerts)} kritik uyarı acil dikkat gerektiriyor."

    # LLM enrichment
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
        turkey_context = ""
        if turkey_reg_mapping and turkey_reg_mapping.get("unchecked_critical"):
            reqs = [r["regulation"] for r in turkey_reg_mapping["unchecked_critical"][:3]]
            turkey_context = f"\nKontrol edilmemiş kritik yasal gereksinimler: {', '.join(reqs)}"

        llm_response = await llm.ainvoke([
            SystemMessage(content=(
                "Sen deneyimli bir Compliance Yöneticisisin. Uyum verilerini analiz et ve "
                "Türkçe olarak kısa, eyleme dönüştürülebilir bir yönetici özeti yaz.\n"
                "Yanıt yapısı:\n"
                "1. Genel uyum durumunun 1-2 cümlelik değerlendirmesi (Türkiye mevzuatı odaklı)\n"
                "2. En kritik 1-2 uyum riski (KVKK, SGK, Vergi vb.)\n"
                "3. Ekibin hemen yapması gereken 2-3 somut eylem\n"
                "Türkiye mevzuatına özgü riskler varsa özellikle vurgula."
            )),
            HumanMessage(content=narrative + turkey_context),
        ])
        narrative = llm_response.content.strip()
    except Exception as llm_exc:
        logger.debug("Compliance narrative LLM failed: %s", llm_exc)

    # ── Assemble summary ──────────────────────────────────────────────────────
    summary: dict[str, Any] = {
        "overall_health_score":    overall_health,
        "health_status":           health_status,
        "health_status_tr":        health_tr,
        "component_scores":        scores,
        "top_risks":               top_risks[:6],
        "critical_alert_count":    len(critical_alerts),
        "warning_alert_count":     len(warning_alerts),
        "all_alerts":              all_alerts,
        "recommendations":         deduped_recs,
        "narrative":               narrative,
        "turkey_reg_mapping":      turkey_reg_mapping,
    }

    patch = _append_log(state, ComplianceStepLog(
        node="compliance_summary",
        status="completed",
        message=(
            f"Health: {overall_health:.1f}/100 ({health_status}), "
            f"risks: {len(top_risks)}, "
            f"critical_alerts: {len(critical_alerts)}"
        ),
        metrics={"overall_health_score": overall_health},
    ))
    patch["compliance_summary"] = summary
    return {**state, **patch}  # type: ignore[return-value]


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_compliance_graph() -> StateGraph:
    graph = StateGraph(ComplianceState)

    graph.add_node("policies",            node_policies)
    graph.add_node("violations",          node_violations)
    graph.add_node("regulations",         node_regulations)
    graph.add_node("compliance_summary",  node_compliance_summary)

    graph.set_entry_point("policies")

    # Linear pipeline — all non-fatal
    graph.add_edge("policies",   "violations")
    graph.add_edge("violations", "regulations")
    graph.add_edge("regulations", "compliance_summary")
    graph.add_edge("compliance_summary", END)

    return graph


# Compiled graph — reused across requests
compliance_graph = build_compliance_graph().compile()


# ── Public entry point ─────────────────────────────────────────────────────────

async def run_compliance_pipeline(
    job_id: str,
    policy_csv: str | None = None,
    violations_csv: str | None = None,
    regulations_csv: str | None = None,
    company_name: str | None = None,
    audit_period: str | None = None,
) -> ComplianceState:
    """
    Run the full Compliance analysis pipeline.

    At least one data source required; others are optional.
    All agents gracefully skip when their input is absent.

    Returns final ComplianceState — caller serialises to API response.
    """
    if not any([policy_csv, violations_csv, regulations_csv]):
        raise ValueError(
            "At least one data source required: "
            "policy_csv, violations_csv, or regulations_csv."
        )

    initial_state: ComplianceState = {
        "policy_csv":      policy_csv or "",
        "violations_csv":  violations_csv or "",
        "regulations_csv": regulations_csv or "",
        "company_name":    company_name,
        "audit_period":    audit_period,
        "policies":        None,
        "violations":      None,
        "regulations":     None,
        "compliance_summary": None,
        "logs":            [],
        "error":           None,
    }

    result: ComplianceState = await compliance_graph.ainvoke(
        initial_state,
        config={"configurable": {}},
    )

    logger.info(
        "Compliance pipeline finished: job=%s health=%.1f",
        job_id,
        (result.get("compliance_summary") or {}).get("overall_health_score", 0),
    )
    return result
