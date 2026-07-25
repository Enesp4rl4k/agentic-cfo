"""
CEO Synthesis Agent — CEO Skill 1 of 3.

Responsibility: Cross-correlate CFO and CTO outputs to find risks that
neither pipeline can see alone.

Examples of cross-domain insights:
  - "Infra cost $50k/month waste + cash runway 4 months → fix infra first"
  - "Tech debt score 8/10 + revenue declining → engineering velocity risk"
  - "MTTR 12h + SaaS product → customer churn risk not in financials"
  - "Velocity declining + hiring budget cut → delivery at risk"

Input: financial_summary + tech_summary (both optional but at least one required)
Output: cross_risks list + condensed narratives

done_when: state['cross_risks'] is a list (may be empty = no cross-domain risks)
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.agents.ceo.state import CEOState, CEORunConfig, CEOSkillResult

logger = logging.getLogger(__name__)


# ── Pure rule-based cross-risk detection ──────────────────────────────────────

def _detect_cross_risks(
    fin: dict[str, Any],
    tech: dict[str, Any],
    mkt: dict[str, Any] | None = None,
    ops: dict[str, Any] | None = None,
    compliance: dict[str, Any] | None = None,
    risk: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Deterministic cross-domain risk rules.
    No LLM — fast, reproducible, auditable.
    Each risk gets a stable risk_id for deduplication.
    """
    risks: list[dict[str, Any]] = []

    runway = fin.get("cash_runway_months")
    infra_waste = tech.get("infra_waste_cents", 0)
    infra_cost  = tech.get("infra_cost_cents", 0)
    debt_score  = tech.get("debt_score", 0)
    mttr        = tech.get("mttr_hours")
    velocity_trend = tech.get("velocity_trend")
    net_margin  = fin.get("net_margin", 0)
    net_income  = fin.get("net_income_cents", 0)
    top_fin_alerts = fin.get("top_alerts", [])
    top_tech_risks = tech.get("top_risks", [])

    # CMO inputs (optional)
    mkt         = mkt or {}
    roas        = mkt.get("overall_roas", 0.0)
    ltv_cac     = mkt.get("ltv_cac_ratio", 0.0)
    churn_rate  = mkt.get("churn_rate", 0.0)
    cac_cents   = mkt.get("overall_cac_cents", 0)

    # COO inputs (optional)
    ops              = ops or {}
    sla_breach_rate  = ops.get("sla_breach_rate", 0.0)
    avg_utilization  = ops.get("avg_utilization_rate", 0.0)
    ops_score        = ops.get("overall_ops_score", 0.0)
    proc_eff_score   = ops.get("process_efficiency_score", 0.0)

    # Compliance inputs (optional)
    compliance           = compliance or {}
    compliance_score     = compliance.get("overall_health_score", 100.0)
    critical_violations  = compliance.get("critical_open_violations", 0)
    non_compliant_reqs   = compliance.get("non_compliant_requirements", 0)
    compliance_coverage  = compliance.get("compliance_coverage_pct", 100.0)

    # Risk Agent inputs (optional)
    risk                    = risk or {}
    enterprise_risk_score   = risk.get("enterprise_risk_score", 0.0)
    risk_posture            = risk.get("risk_posture", "acceptable")
    unmitigated_critical    = risk.get("unmitigated_critical_count", 0)
    kri_red_count           = risk.get("kri_red_count", 0)
    total_net_loss          = risk.get("total_net_loss_cents", 0)

    # Internal Audit inputs (optional)
    audit                   = audit or {}
    audit_health_score      = audit.get("audit_health_score", 100.0)
    audit_maturity          = audit.get("maturity_level", "optimised")
    open_critical_findings  = audit.get("open_critical_findings", 0)
    ineffective_controls    = audit.get("ineffective_controls_count", 0)
    audit_coverage          = audit.get("coverage_rate", 1.0)

    # ── Risk 1: Infra waste while cash is short ────────────────────────────────
    if infra_waste > 0 and runway is not None and runway <= 6:
        severity = "critical" if runway <= 3 else "high"
        monthly_savings = infra_waste / 100
        risks.append({
            "risk_id": "cross-infra-cash-runway",
            "title": "Cloud waste accelerating cash burn",
            "domains": ["cfo", "cto"],
            "severity": severity,
            "financial_impact_cents": infra_waste,
            "tech_impact": "None — pure cost reduction",
            "recommended_action": (
                f"Eliminate ${monthly_savings:,.0f}/month cloud waste immediately. "
                f"This extends cash runway by ~{infra_waste / max(fin.get('monthly_burn_cents', 1), 1):.1f} months."
            ),
            "urgency": "now" if severity == "critical" else "30d",
        })

    # ── Risk 2: High tech debt + declining revenue ─────────────────────────────
    if debt_score >= 7.0 and net_income < 0:
        risks.append({
            "risk_id": "cross-debt-revenue",
            "title": "Tech debt slowing revenue-generating feature delivery",
            "domains": ["cfo", "cto"],
            "severity": "high",
            "financial_impact_cents": abs(net_income),
            "tech_impact": f"Debt score {debt_score:.1f}/10 increases change failure rate",
            "recommended_action": (
                "Allocate 20% of engineering capacity to debt reduction. "
                "Target hotspot files first — highest ROI."
            ),
            "urgency": "30d",
        })

    # ── Risk 3: High MTTR + SaaS model (revenue risk) ─────────────────────────
    if mttr is not None and mttr > 4 and fin.get("revenue_cents", 0) > 0:
        # Estimate: 1h downtime = 0.5% of monthly revenue (rough SaaS benchmark)
        est_impact = int(fin["revenue_cents"] * 0.005 * (mttr / 4))
        severity = "critical" if mttr > 8 else "medium"
        risks.append({
            "risk_id": "cross-mttr-revenue",
            "title": "Slow incident recovery creating customer churn risk",
            "domains": ["cfo", "cto"],
            "severity": severity,
            "financial_impact_cents": est_impact,
            "tech_impact": f"MTTR {mttr:.1f}h — customer SLA likely breached during outages",
            "recommended_action": (
                "Implement on-call runbooks and automated rollback. "
                "Target MTTR < 1h for critical severity."
            ),
            "urgency": "30d" if severity == "critical" else "90d",
        })

    # ── Risk 4: Declining velocity + thin margins ──────────────────────────────
    if velocity_trend == "down" and net_margin is not None and net_margin < 0.10:
        risks.append({
            "risk_id": "cross-velocity-margin",
            "title": "Engineering slowdown threatening product competitiveness",
            "domains": ["cfo", "cto"],
            "severity": "medium",
            "financial_impact_cents": 0,  # indirect
            "tech_impact": "Declining velocity = slower feature delivery = revenue risk",
            "recommended_action": (
                "Review sprint bottlenecks and remove blockers. "
                "Consider reducing scope to recover velocity before adding headcount."
            ),
            "urgency": "30d",
        })

    # ── Risk 5: Critical fin alert + critical tech risk coincide ──────────────
    critical_fin = [a for a in top_fin_alerts if a.get("level") == "critical"]
    critical_tech = [r for r in top_tech_risks if r.get("severity") == "critical"]
    if critical_fin and critical_tech:
        risks.append({
            "risk_id": "cross-dual-critical",
            "title": "Simultaneous critical risks in Finance and Technology",
            "domains": ["cfo", "cto"],
            "severity": "critical",
            "financial_impact_cents": 0,
            "tech_impact": "Compound risk — both domains require immediate leadership attention",
            "recommended_action": (
                "Schedule emergency leadership review within 48 hours. "
                f"Finance: {critical_fin[0]['message'][:80]}. "
                f"Technology: {critical_tech[0]['message'][:80]}."
            ),
            "urgency": "now",
        })

    # ── Risk 6 (CMO): Negative unit economics — CAC > LTV ─────────────────────
    if ltv_cac > 0 and ltv_cac < 1.0 and runway is not None and runway <= 12:
        risks.append({
            "risk_id": "cross-cmo-negative-unit-econ",
            "title": "Negative unit economics accelerating cash burn",
            "domains": ["cfo", "cmo"],
            "severity": "critical",
            "financial_impact_cents": cac_cents,
            "tech_impact": "None — pure go-to-market issue",
            "recommended_action": (
                f"LTV:CAC ratio is {ltv_cac:.2f}x — pause paid acquisition. "
                "Fix retention first, then restart growth spend."
            ),
            "urgency": "now",
        })

    # ── Risk 7 (CMO): High churn eroding revenue base ─────────────────────────
    if churn_rate > 0.08 and fin.get("revenue_cents", 0) > 0:
        monthly_churn_rev = int(fin["revenue_cents"] * churn_rate)
        risks.append({
            "risk_id": "cross-cmo-high-churn",
            "title": "High customer churn eroding revenue base",
            "domains": ["cfo", "cmo"],
            "severity": "high" if churn_rate < 0.15 else "critical",
            "financial_impact_cents": monthly_churn_rev,
            "tech_impact": "Churn may indicate product-market fit or reliability issues",
            "recommended_action": (
                f"Monthly churn {churn_rate:.0%} costs ~${monthly_churn_rev / 100:,.0f}/month. "
                "Launch retention program and investigate exit reasons."
            ),
            "urgency": "30d",
        })

    # ── Risk 8 (CMO): Poor ROAS + low cash runway ─────────────────────────────
    if roas > 0 and roas < 1.5 and runway is not None and runway <= 6:
        ad_spend = mkt.get("total_spend_cents", 0)
        risks.append({
            "risk_id": "cross-cmo-roas-runway",
            "title": "Poor advertising ROI while cash is running out",
            "domains": ["cfo", "cmo"],
            "severity": "high",
            "financial_impact_cents": ad_spend,
            "tech_impact": "None",
            "recommended_action": (
                f"ROAS {roas:.2f}x with {runway:.1f} months cash runway. "
                "Pause underperforming campaigns immediately to conserve cash."
            ),
            "urgency": "now" if runway <= 3 else "30d",
        })

    # ── Risk 9 (COO): SLA breaches + revenue at risk ──────────────────────────
    if sla_breach_rate > 0.20 and fin.get("revenue_cents", 0) > 0:
        est_churn_rev = int(fin["revenue_cents"] * sla_breach_rate * 0.1)
        severity = "critical" if sla_breach_rate > 0.40 else "high"
        risks.append({
            "risk_id": "cross-coo-sla-revenue",
            "title": "High SLA breach rate threatening customer retention",
            "domains": ["cfo", "coo"],
            "severity": severity,
            "financial_impact_cents": est_churn_rev,
            "tech_impact": f"SLA breach rate {sla_breach_rate:.0%} — customers experiencing poor service",
            "recommended_action": (
                f"SLA breach rate {sla_breach_rate:.0%} risks ~${est_churn_rev / 100:,.0f}/month in churn. "
                "Investigate root-cause ticket categories and implement escalation playbooks."
            ),
            "urgency": "now" if severity == "critical" else "30d",
        })

    # ── Risk 10 (COO): Team overutilization + hiring freeze ───────────────────
    if avg_utilization > 1.0 and net_margin is not None and net_margin < 0.05:
        risks.append({
            "risk_id": "cross-coo-burnout-margin",
            "title": "Team burnout risk while margins are too thin to hire",
            "domains": ["cfo", "coo"],
            "severity": "high",
            "financial_impact_cents": 0,
            "tech_impact": f"Avg team utilization {avg_utilization:.0%} — burnout risk increases attrition",
            "recommended_action": (
                f"Teams at {avg_utilization:.0%} utilization with {net_margin:.0%} net margin. "
                "Reduce scope, automate repetitive work, or deprioritize low-value projects."
            ),
            "urgency": "30d",
        })

    # ── Risk 11 (COO): Ops crisis score + critical fin alert ──────────────────
    if ops_score >= 7.0 and runway is not None and runway <= 6:
        risks.append({
            "risk_id": "cross-coo-ops-runway",
            "title": "Operational breakdown while cash runway is short",
            "domains": ["cfo", "coo"],
            "severity": "critical",
            "financial_impact_cents": 0,
            "tech_impact": f"Ops health score {ops_score}/10 — operational execution at risk",
            "recommended_action": (
                f"Ops score {ops_score}/10 with {runway:.1f} months runway. "
                "Stabilize operations before growth: fix highest-severity operational issues first."
            ),
            "urgency": "now",
        })

    # ── Risk 12 (CHRO): High attrition + negative margin ──────────────────────────
    # Extracted from hr_summary
    if "chro" in locals() or "hr" in locals():
        hr = locals().get("chro") or locals().get("hr") or {}
        early_departure_rate = hr.get("early_departure_rate", 0.0)
        total_departures = hr.get("total_departures", 0)
        
        if early_departure_rate > 0.20 and net_margin is not None and net_margin < 0.05:
            risks.append({
                "risk_id": "cross-chro-attrition-margin",
                "title": "High early attrition while margins too thin for retention programs",
                "domains": ["chro", "cfo"],
                "severity": "high",
                "financial_impact_cents": int(total_departures * 75_000 * 100),  # replacement cost
                "tech_impact": f"Early departure rate {early_departure_rate:.0%} — culture or onboarding issue",
                "recommended_action": (
                    f"Early departures at {early_departure_rate:.0%}. "
                    "Conduct exit interviews to identify root cause. Consider structured onboarding program."
                ),
                "urgency": "30d",
            })

    # ── Risk 13 (CHRO): Below-market compensation + competitor hiring ────────────
    # Extracted from hr_summary
    if "chro" in locals() or "hr" in locals():
        hr = locals().get("chro") or locals().get("hr") or {}
        below_market_count = hr.get("below_market_count", 0)
        total_employees = hr.get("total_employees", 1)
        equity_penetration = hr.get("equity_penetration", 0.0)
        
        if below_market_count > (total_employees * 0.15) and equity_penetration < 0.50:
            risks.append({
                "risk_id": "cross-chro-comp-retention",
                "title": "Below-market compensation creating retention risk",
                "domains": ["chro", "cfo"],
                "severity": "medium",
                "financial_impact_cents": int(below_market_count * 50_000 * 100),  # salary adjustment cost
                "tech_impact": f"{below_market_count} employees at risk — below market with low equity",
                "recommended_action": (
                    f"{below_market_count} employees below market rate. "
                    "Prioritize salary adjustments for high-performers in critical roles."
                ),
                "urgency": "30d",
            })

    # ── Risk 14 (Compliance): Critical violations while cash is tight ─────────
    if critical_violations > 0 and runway is not None and runway <= 12:
        risks.append({
            "risk_id": "cross-compliance-violations-cash",
            "title": "Critical compliance violations creating regulatory penalty risk",
            "domains": ["compliance", "cfo"],
            "severity": "critical" if critical_violations > 2 else "high",
            "financial_impact_cents": critical_violations * 100_000 * 100,  # ~$100k per critical violation estimate
            "tech_impact": f"{critical_violations} critical violation(s) open — potential regulatory fines",
            "recommended_action": (
                f"{critical_violations} critical violation(s) unresolved with {runway:.0f} months runway. "
                "Prioritise compliance remediation to avoid regulatory penalties that could accelerate cash burn."
            ),
            "urgency": "now",
        })

    # ── Risk 15 (Compliance): Low coverage + revenue growth plans ─────────────
    if compliance_coverage < 70 and fin.get("revenue_cents", 0) > 0:
        risks.append({
            "risk_id": "cross-compliance-coverage-revenue",
            "title": "Low regulatory compliance coverage blocking enterprise sales",
            "domains": ["compliance", "cfo"],
            "severity": "high" if compliance_coverage >= 50 else "critical",
            "financial_impact_cents": 0,  # indirect — deal blockers
            "tech_impact": f"Compliance coverage {compliance_coverage:.0f}% — below enterprise customer threshold (80%)",
            "recommended_action": (
                f"Compliance coverage {compliance_coverage:.0f}% will block enterprise deals requiring SOC2/ISO certification. "
                "Launch compliance sprint to reach 85%+ before next sales cycle."
            ),
            "urgency": "30d",
        })

    # ── Risk 16 (Compliance): Poor compliance health + operational issues ─────
    if compliance_score < 60 and ops_score >= 6.0:
        risks.append({
            "risk_id": "cross-compliance-ops-risk",
            "title": "Compliance and operational failures creating compounding risk",
            "domains": ["compliance", "coo"],
            "severity": "critical",
            "financial_impact_cents": 0,
            "tech_impact": (
                f"Compliance score {compliance_score:.0f}/100 + ops score {ops_score:.1f}/10 — "
                "dual breakdown increasing audit failure risk"
            ),
            "recommended_action": (
                "Simultaneous compliance gaps and operational issues signal systemic process failures. "
                "Conduct root-cause analysis across both domains and implement unified remediation plan."
            ),
            "urgency": "now",
        })

    # ── Risk 17 (Compliance): Non-compliant reqs + upcoming fundraise/IPO signal ──
    if non_compliant_reqs > 5 and fin.get("revenue_cents", 0) > 500_000 * 100:
        risks.append({
            "risk_id": "cross-compliance-due-diligence",
            "title": "Compliance gaps creating due diligence risk for future fundraising",
            "domains": ["compliance", "cfo"],
            "severity": "medium",
            "financial_impact_cents": 0,
            "tech_impact": f"{non_compliant_reqs} non-compliant requirements — will surface in investor/acquirer due diligence",
            "recommended_action": (
                f"{non_compliant_reqs} open compliance gaps. "
                "Address before any fundraising or M&A process to avoid valuation haircuts."
            ),
            "urgency": "90d",
        })

    # ── Risk 18 (Enterprise Risk): Critical risk posture + short runway ───────
    if enterprise_risk_score >= 7.0 and runway is not None and runway <= 6:
        risks.append({
            "risk_id": "cross-risk-critical-runway",
            "title": "Critical enterprise risk posture while cash runway is short",
            "domains": ["risk", "cfo"],
            "severity": "critical",
            "financial_impact_cents": 0,
            "tech_impact": (
                f"Enterprise risk score {enterprise_risk_score}/10 "
                f"with {runway:.1f} months cash runway — compounding exposure"
            ),
            "recommended_action": (
                f"Risk posture '{risk_posture}' with {runway:.1f} months runway. "
                "Immediately address top unmitigated risks; defer non-essential spending."
            ),
            "urgency": "now",
        })

    # ── Risk 19 (Enterprise Risk): Unmitigated critical risks + revenue ───────
    if unmitigated_critical >= 2 and fin.get("revenue_cents", 0) > 0:
        risks.append({
            "risk_id": "cross-risk-unmitigated-revenue",
            "title": "Multiple unmitigated critical risks threatening revenue continuity",
            "domains": ["risk", "cfo"],
            "severity": "high",
            "financial_impact_cents": int(fin.get("revenue_cents", 0) * 0.05),
            "tech_impact": f"{unmitigated_critical} critical risks with no mitigation controls",
            "recommended_action": (
                f"{unmitigated_critical} critical risks unmitigated. "
                "Assign owners and implement at least basic controls within 30 days."
            ),
            "urgency": "30d",
        })

    # ── Risk 20 (Enterprise Risk): KRI red breaches + KPI degradation ────────
    if kri_red_count >= 2 and (net_margin is not None and net_margin < 0.10):
        risks.append({
            "risk_id": "cross-risk-kri-margin",
            "title": "Multiple KRI breaches coinciding with margin pressure",
            "domains": ["risk", "cfo"],
            "severity": "high",
            "financial_impact_cents": 0,
            "tech_impact": f"{kri_red_count} KRIs in red zone — leading indicators signal further deterioration",
            "recommended_action": (
                f"{kri_red_count} KRIs breaching red thresholds with {net_margin:.0%} margin. "
                "Activate risk response plans; review KRI targets against business reality."
            ),
            "urgency": "30d",
        })

    # ── Risk 21 (Internal Audit): Critical open findings + control failures ───
    if open_critical_findings >= 1 and ineffective_controls >= 1:
        risks.append({
            "risk_id": "cross-audit-findings-controls",
            "title": "Critical audit findings and ineffective controls — material weakness risk",
            "domains": ["audit", "cfo"],
            "severity": "critical",
            "financial_impact_cents": 0,
            "tech_impact": (
                f"{open_critical_findings} critical finding(s) + "
                f"{ineffective_controls} ineffective control(s) — audit opinion risk"
            ),
            "recommended_action": (
                "Material weakness indicators present. "
                "Escalate to Audit Committee; remediate critical findings within 30 days "
                "and redesign failed controls."
            ),
            "urgency": "now",
        })

    # ── Risk 22 (Internal Audit): Low audit coverage + high-risk business ─────
    if audit_coverage < 0.60 and fin.get("revenue_cents", 0) > 1_000_000 * 100:
        risks.append({
            "risk_id": "cross-audit-coverage-revenue",
            "title": "Insufficient audit coverage for revenue-generating business size",
            "domains": ["audit", "cfo"],
            "severity": "medium",
            "financial_impact_cents": 0,
            "tech_impact": f"Audit coverage {audit_coverage:.0%} — significant business areas unaudited",
            "recommended_action": (
                f"Audit coverage {audit_coverage:.0%} is below 60% threshold. "
                "Invest in internal audit capacity; prioritise high-risk unaudited units."
            ),
            "urgency": "90d",
        })

    # ── Risk 23 (Internal Audit): Poor audit maturity + scale risk ───────────
    if audit_maturity in ("initial", "developing") and fin.get("revenue_cents", 0) > 5_000_000 * 100:
        risks.append({
            "risk_id": "cross-audit-maturity-scale",
            "title": "Audit maturity too low for company revenue scale",
            "domains": ["audit", "cfo"],
            "severity": "high",
            "financial_impact_cents": 0,
            "tech_impact": f"Audit maturity '{audit_maturity}' insufficient for scale",
            "recommended_action": (
                "Company has outgrown its internal audit function. "
                "Invest in audit tools, talent, and processes to reach 'defined' maturity minimum."
            ),
            "urgency": "30d",
        })

    # Sort by urgency + severity
    urgency_order = {"now": 0, "30d": 1, "90d": 2}
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    risks.sort(key=lambda r: (
        urgency_order.get(r.get("urgency", "90d"), 2),
        severity_order.get(r.get("severity", "low"), 3),
    ))

    return risks


def _condense_financial_summary(cfo_state: dict[str, Any]) -> dict[str, Any]:
    """Extract CEO-relevant financial KPIs from CFO pipeline output."""
    pnl      = cfo_state.get("pnl") or {}
    cashflow = cfo_state.get("cashflow") or {}
    forecast = cfo_state.get("forecast") or {}
    alerts   = []

    # Collect all CFO alerts
    for src in [cashflow.get("alerts", []), forecast.get("alerts", [])]:
        alerts.extend(src or [])

    base_scenario = (forecast.get("scenarios") or {}).get("base", {})
    runway = base_scenario.get("runway_months")

    # Estimate monthly burn: total expenses / months
    monthly_burn = 0
    monthly_series = cashflow.get("monthly_series", [])
    if monthly_series:
        import statistics as stats
        monthly_burn = int(stats.mean(s["out"] for s in monthly_series))

    return {
        "revenue_cents":         pnl.get("revenue", 0),
        "net_income_cents":      pnl.get("net_income", 0),
        "net_margin":            pnl.get("net_margin", 0),
        "gross_margin":          pnl.get("gross_margin", 0),
        "cash_flow_net_cents":   cashflow.get("net_change", 0),
        "cash_runway_months":    runway,
        "monthly_burn_cents":    monthly_burn,
        "forecast_base_12m_cents": base_scenario.get("twelve_month_net", 0),
        "top_alerts":            alerts[:5],
        "narrative":             pnl.get("narrative", ""),
    }


def _condense_tech_summary(cto_state: dict[str, Any]) -> dict[str, Any]:
    """Extract CEO-relevant tech KPIs from CTO pipeline output."""
    infra     = cto_state.get("infra") or {}
    tech_debt = cto_state.get("tech_debt") or {}
    incidents = cto_state.get("incidents") or {}
    velocity  = cto_state.get("velocity") or {}
    summary   = cto_state.get("cto_summary") or {}

    return {
        "overall_health_score":  summary.get("overall_health_score", 0),
        "infra_cost_cents":      infra.get("total_cost_cents", 0),
        "infra_waste_cents":     infra.get("waste_estimate_cents", 0),
        "debt_score":            tech_debt.get("debt_score", 0),
        "mttr_hours":            incidents.get("mttr_hours"),
        "sla_breach_pct":        incidents.get("sla_breach_pct", 0),
        "avg_velocity":          velocity.get("avg_velocity", 0),
        "velocity_trend":        velocity.get("velocity_trend", "flat"),
        "top_risks":             summary.get("top_risks", [])[:5],
        "narrative":             summary.get("narrative", ""),
    }


def _condense_marketing_summary(cmo_state: dict[str, Any]) -> dict[str, Any]:
    """Extract CEO-relevant marketing KPIs from CMO pipeline output."""
    campaigns = cmo_state.get("campaigns") or {}
    funnel    = cmo_state.get("funnel") or {}
    cohorts   = cmo_state.get("cohorts") or {}
    summary   = cmo_state.get("cmo_summary") or {}

    return {
        "overall_marketing_score":  summary.get("overall_marketing_score", 0),
        "overall_roas":             campaigns.get("overall_roas", 0.0),
        "total_spend_cents":        campaigns.get("total_spend_cents", 0),
        "overall_cac_cents":        campaigns.get("overall_cac_cents", 0),
        "overall_conversion_rate":  funnel.get("overall_conversion_rate", 0.0),
        "ltv_cac_ratio":            cohorts.get("ltv_cac_ratio", 0.0),
        "churn_rate":               cohorts.get("churn_rate", 0.0),
        "retention_trend":          cohorts.get("retention_trend", "stable"),
        "top_risks":                summary.get("top_risks", [])[:5],
        "narrative":                summary.get("narrative", ""),
    }


def _condense_ops_summary(coo_state: dict[str, Any]) -> dict[str, Any]:
    """Extract CEO-relevant ops KPIs from COO pipeline output."""
    processes = coo_state.get("processes") or {}
    resources = coo_state.get("resources") or {}
    sla       = coo_state.get("sla") or {}
    summary   = coo_state.get("coo_summary") or {}

    return {
        "overall_ops_score":           summary.get("overall_ops_score", 0.0),
        "operational_efficiency_score": summary.get("operational_efficiency_score", 0.0),
        "process_efficiency_score":    processes.get("efficiency_score", 0.0),
        "avg_utilization_rate":        resources.get("avg_utilization_rate", 0.0),
        "sla_breach_rate":             sla.get("sla_breach_rate", 0.0),
        "avg_nps_score":               sla.get("avg_nps_score", 0.0),
        "bottleneck_process":          processes.get("bottleneck_process"),
        "overutilized_teams":          resources.get("overutilized_teams", []),
        "top_risks":                   summary.get("top_risks", [])[:5],
        "narrative":                   summary.get("narrative", ""),
    }


def _condense_hr_summary(chro_state: dict[str, Any]) -> dict[str, Any]:
    """Extract CEO-relevant HR KPIs from CHRO pipeline output."""
    headcount = chro_state.get("headcount") or {}
    attrition = chro_state.get("attrition") or {}
    compensation = chro_state.get("compensation") or {}
    summary = chro_state.get("chro_summary") or {}

    return {
        "chro_health_score": summary.get("chro_health_score", 0.0),
        "total_headcount": headcount.get("total_headcount", 0),
        "avg_tenure_years": headcount.get("avg_tenure_years", 0.0),
        "total_departures": attrition.get("total_departures", 0),
        "early_departure_rate": attrition.get("early_departure_rate", 0.0),
        "replaced_rate": attrition.get("replaced_rate", 0.0),
        "total_annual_comp": compensation.get("total_annual_comp", 0),
        "equity_penetration": compensation.get("equity_penetration", 0.0),
        "below_market_count": compensation.get("below_market_count", 0),
        "above_market_count": compensation.get("above_market_count", 0),
        "top_risks": summary.get("top_risks", [])[:5],
        "narrative": summary.get("narrative", ""),
    }


def _condense_compliance_summary(compliance_state: dict[str, Any]) -> dict[str, Any]:
    """Extract CEO-relevant compliance KPIs from Compliance pipeline output."""
    summary     = compliance_state.get("compliance_summary") or {}
    violations  = compliance_state.get("violations") or {}
    regulations = compliance_state.get("regulations") or {}
    policies    = compliance_state.get("policies") or {}

    return {
        "overall_health_score":       summary.get("overall_health_score", 0.0),
        "health_status":              summary.get("health_status", "unknown"),
        "critical_open_violations":   violations.get("critical_open", 0),
        "open_violations":            violations.get("open_violations", 0),
        "overdue_violations":         violations.get("overdue_violations", 0),
        "remediation_rate":           violations.get("remediation_rate", 0.0),
        "compliance_coverage_pct":    regulations.get("compliance_coverage_pct", 0.0),
        "non_compliant_requirements": regulations.get("non_compliant_count", 0),
        "frameworks":                 regulations.get("frameworks", []),
        "active_policies":            policies.get("active_policies", 0),
        "policies_needing_review":    policies.get("policies_needing_review", 0),
        "top_risks":                  summary.get("top_risks", [])[:5],
        "narrative":                  summary.get("narrative", ""),
    }


def _condense_risk_summary(risk_state: dict[str, Any]) -> dict[str, Any]:
    """Extract CEO-relevant risk KPIs from Risk pipeline output."""
    register = risk_state.get("register") or {}
    losses   = risk_state.get("losses") or {}
    kris     = risk_state.get("kris") or {}
    summary  = risk_state.get("risk_summary") or {}

    return {
        "enterprise_risk_score":     summary.get("enterprise_risk_score", 0.0),
        "risk_posture":              summary.get("risk_posture", "acceptable"),
        "unmitigated_critical_count": len(register.get("unmitigated_critical", [])),
        "mitigation_coverage":       register.get("mitigation_coverage", 1.0),
        "total_net_loss_cents":      losses.get("total_net_loss", 0),
        "loss_trend":                losses.get("loss_trend", "stable"),
        "kri_red_count":             len(kris.get("breached_red", [])),
        "kri_amber_count":           len(kris.get("breached_amber", [])),
        "composite_kri_score":       kris.get("composite_kri_score", 0.0),
        "top_risks":                 summary.get("top_risks", [])[:5],
        "narrative":                 summary.get("narrative", ""),
    }


def _condense_audit_summary(audit_state: dict[str, Any]) -> dict[str, Any]:
    """Extract CEO-relevant audit KPIs from Internal Audit pipeline output."""
    findings = audit_state.get("findings") or {}
    controls = audit_state.get("controls") or {}
    coverage = audit_state.get("coverage") or {}
    summary  = audit_state.get("audit_summary") or {}

    return {
        "audit_health_score":        summary.get("audit_health_score", 100.0),
        "maturity_level":            summary.get("maturity_level", "optimised"),
        "open_critical_findings":    findings.get("open_critical", 0),
        "overdue_findings":          findings.get("overdue_count", 0),
        "repeat_findings":           findings.get("repeat_findings", 0),
        "ineffective_controls_count": len(controls.get("ineffective_controls", [])),
        "overall_control_score":     controls.get("overall_control_score", 100.0),
        "coverage_rate":             coverage.get("coverage_rate", 1.0),
        "high_risk_coverage":        coverage.get("high_risk_coverage", 1.0),
        "top_issues":                summary.get("top_issues", [])[:5],
        "narrative":                 summary.get("narrative", ""),
    }


async def run_synthesis_agent(
    state: CEOState,
    config: CEORunConfig,
) -> CEOSkillResult:
    """
    CEO Synthesis Skill.
    done_when: state['cross_risks'] is a list.
    """
    fin        = state.get("financial_summary") or {}
    tech       = state.get("tech_summary") or {}
    mkt        = state.get("marketing_summary") or {}
    ops        = state.get("ops_summary") or {}
    hr         = state.get("hr_summary") or {}
    compliance = state.get("compliance_summary") or {}
    risk       = state.get("risk_summary") or {}
    audit_sum  = state.get("audit_summary_condensed") or {}

    if not fin and not tech:
        return CEOSkillResult(
            ok=False,
            detail="Both financial_summary and tech_summary are empty — cannot synthesize.",
        )

    try:
        cross_risks = _detect_cross_risks(
            fin, tech,
            mkt or None, ops or None, compliance or None,
            risk or None, audit_sum or None,
        )
        # Add HR (CHRO) context to risks for HR-related rules
        for risk in cross_risks:
            if "chro" in risk.get("risk_id", ""):
                risk["hr_context"] = hr

        critical_count = sum(1 for r in cross_risks if r["severity"] == "critical")
        needs_review = critical_count > 0

        logger.info(
            "CEO SynthesisAgent: job=%s cross_risks=%d critical=%d",
            state.get("job_id"), len(cross_risks), critical_count,
        )

        return CEOSkillResult(
            ok=True,
            patch={"cross_risks": cross_risks},
            confidence=0.90,
            needs_review=needs_review,
            detail=f"Cross-domain risks: {len(cross_risks)} ({critical_count} critical)",
        )

    except Exception as exc:
        logger.exception("CEO SynthesisAgent failed for job=%s", state.get("job_id"))
        return CEOSkillResult(ok=False, detail=f"SynthesisAgent error: {exc}")
