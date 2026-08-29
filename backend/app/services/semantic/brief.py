"""Deterministic Decision Brief builder from semantic snapshot."""
from __future__ import annotations

from typing import Any

from app.services.semantic.catalog import HEALTH_WEIGHTS
from app.services.semantic.types import (
    BriefFinding,
    BriefOption,
    BriefRecommendation,
    CompanySemanticSnapshot,
    DecisionBrief,
)

CONFIDENCE_GATE = 0.80


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_health_score(snapshot: CompanySemanticSnapshot) -> tuple[int, float]:
    """Weighted health 0–100. Returns (score, min_confidence_among_used)."""
    mmap = snapshot.metric_map()
    total_w = 0.0
    acc = 0.0
    min_conf = 1.0
    used = 0

    for mid, weight in HEALTH_WEIGHTS.items():
        m = mmap.get(mid)
        if not m or m.value is None:
            continue
        used += 1
        min_conf = min(min_conf, float(m.confidence))
        val = m.value
        if mid == "finance.runway_months":
            n = _num(val)
            contrib = 0.0 if n is None else min(max(n / 18.0, 0.0), 1.0)
        elif mid == "finance.net_margin":
            n = _num(val)
            contrib = 0.0 if n is None else min(max((n + 0.1) / 0.4, 0.0), 1.0)
        elif mid == "finance.critical_anomalies":
            n = _num(val) or 0.0
            contrib = 1.0 if n <= 0 else max(0.0, 1.0 - n * 0.25)
        elif mid == "growth.overall_roas":
            n = _num(val)
            contrib = 0.0 if n is None else min(max(n / 3.0, 0.0), 1.0)
        elif mid == "tech.health_score":
            n = _num(val)
            if n is None:
                contrib = 0.5
            elif n <= 10:
                contrib = n / 10.0
            else:
                contrib = n / 100.0
        elif mid == "people.attrition_rate":
            n = _num(val)
            if n is None:
                contrib = 0.5
            else:
                contrib = max(0.0, 1.0 - (n if n <= 1 else n / 100.0) / 0.3)
        elif mid == "risk.overall_score":
            n = _num(val)
            if n is None:
                contrib = 0.5
            elif n <= 10:
                contrib = 1.0 - (n / 10.0)
            else:
                contrib = 1.0 - min(n / 100.0, 1.0)
        else:
            contrib = 0.5
        acc += weight * contrib
        total_w += weight

    if total_w <= 0 or used == 0:
        return 50, 0.5
    score = round(100 * (acc / total_w))
    return max(0, min(100, score)), min_conf


def build_from_snapshot(
    snapshot: CompanySemanticSnapshot,
    *,
    conflicts: list[dict[str, Any]] | None = None,
) -> DecisionBrief:
    values = snapshot.values()
    mmap = snapshot.metric_map()
    health, _min_conf = compute_health_score(snapshot)
    findings: list[BriefFinding] = []

    runway = _num(values.get("finance.runway_months"))
    if runway is not None and runway < 6:
        findings.append(
            BriefFinding(
                severity="critical" if runway < 3 else "high",
                domain="finance",
                statement=f"Cash runway is {runway:.1f} months — below the 6-month safety threshold.",
                metric_ids=["finance.runway_months"],
                evidence_refs=list(mmap["finance.runway_months"].evidence_refs)
                if "finance.runway_months" in mmap
                else [],
                confidence=float(mmap["finance.runway_months"].confidence)
                if "finance.runway_months" in mmap
                else 0.85,
            )
        )

    crit = _num(values.get("finance.critical_anomalies")) or 0
    if crit > 0:
        findings.append(
            BriefFinding(
                severity="high",
                domain="finance",
                statement=f"{int(crit)} critical financial anomalies require review.",
                metric_ids=["finance.critical_anomalies"],
                confidence=1.0,
            )
        )

    roas = _num(values.get("growth.overall_roas"))
    if roas is not None and roas < 1.5:
        findings.append(
            BriefFinding(
                severity="medium",
                domain="growth",
                statement=f"Blended ROAS is {roas:.2f}x — marketing efficiency is under pressure.",
                metric_ids=["growth.overall_roas"],
                confidence=float(mmap["growth.overall_roas"].confidence)
                if "growth.overall_roas" in mmap
                else 0.8,
            )
        )

    attrition = _num(values.get("people.attrition_rate"))
    if attrition is not None:
        rate = attrition if attrition <= 1 else attrition / 100.0
        if rate > 0.2:
            findings.append(
                BriefFinding(
                    severity="high",
                    domain="people",
                    statement=f"Annualized attrition ~{rate * 100:.0f}% — retention risk elevated.",
                    metric_ids=["people.attrition_rate"],
                    confidence=float(mmap["people.attrition_rate"].confidence)
                    if "people.attrition_rate" in mmap
                    else 0.8,
                )
            )

    risk_score = _num(values.get("risk.overall_score"))
    if risk_score is not None and ((risk_score <= 10 and risk_score >= 7) or risk_score >= 70):
        findings.append(
            BriefFinding(
                severity="high",
                domain="risk",
                statement="Enterprise risk score is elevated.",
                metric_ids=["risk.overall_score"],
                confidence=float(mmap["risk.overall_score"].confidence)
                if "risk.overall_score" in mmap
                else 0.8,
            )
        )

    for conflict in conflicts or []:
        topic = str(conflict.get("topic") or "cross-domain topic")
        agent_a = str(conflict.get("agent_a") or conflict.get("agent_a") or "?")
        agent_b = str(conflict.get("agent_b") or conflict.get("agent_b") or "?")
        findings.append(
            BriefFinding(
                severity="high",
                domain="governance",
                statement=f"Open agent conflict on {topic} ({agent_a} vs {agent_b}).",
                metric_ids=[],
                confidence=float(conflict.get("consensus_score") or 0.75),
            )
        )

    if not findings:
        findings.append(
            BriefFinding(
                severity="info",
                domain="general",
                statement="No critical semantic alerts — monitor runway, ROAS, and attrition.",
                metric_ids=[],
                confidence=0.9,
            )
        )

    options: list[BriefOption] = [
        BriefOption(
            title="Protect runway",
            impact_summary="Defer non-critical opex; accelerate collections.",
            linked_cf_action="cost_cut",
        ),
        BriefOption(
            title="Reallocate growth spend",
            impact_summary="Shift budget from low-ROAS channels to proven cohorts.",
            linked_cf_action="marketing_invest",
        ),
        BriefOption(
            title="Hold hiring",
            impact_summary="Pause net-new headcount until runway > 9 months.",
            linked_cf_action="headcount_change",
        ),
    ]

    rec_idx = 0
    if runway is not None and runway < 6:
        rec_idx = 0
    elif roas is not None and roas < 1.5:
        rec_idx = 1
    elif attrition is not None and (attrition if attrition <= 1 else attrition / 100) > 0.2:
        rec_idx = 2

    finding_confs = [f.confidence for f in findings]
    min_finding_conf = min(finding_confs) if finding_confs else 1.0
    awaiting = min_finding_conf < CONFIDENCE_GATE
    if any(f.severity == "critical" for f in findings):
        awaiting = True

    if health >= 75:
        headline = f"Company health {health}/100 — stable trajectory for {snapshot.period.key}."
    elif health >= 50:
        headline = (
            f"Company health {health}/100 — mixed signals; prioritize cash and growth efficiency."
        )
    else:
        headline = f"Company health {health}/100 — elevated risk; executive action recommended."

    return DecisionBrief(
        period=snapshot.period.key,
        currency=snapshot.currency,
        locale=snapshot.locale,
        headline=headline,
        health_score=health,
        findings=findings,
        options=options,
        recommendation=BriefRecommendation(
            title=options[rec_idx].title,
            rationale=options[rec_idx].impact_summary,
            option_index=rec_idx,
        ),
        conflicts=list(conflicts or []),
        awaiting_review=awaiting,
    )


def enrich_brief_from_ceo_synthesis(
    brief: DecisionBrief,
    ceo_result: dict[str, Any] | None,
) -> DecisionBrief:
    """Map CEO synthesis narrative into options/findings without inventing numbers."""
    if not ceo_result:
        return brief
    priorities = ceo_result.get("strategic_priorities") or []
    if isinstance(priorities, list) and priorities:
        for p in priorities[:3]:
            if isinstance(p, dict):
                title = str(p.get("title") or p.get("priority") or "Strategic priority")
                impact = str(p.get("rationale") or p.get("description") or "")
                brief.options.append(
                    BriefOption(title=title, impact_summary=impact[:280], linked_cf_action=None)
                )
    cross = ceo_result.get("cross_risks") or []
    if isinstance(cross, list):
        for r in cross[:5]:
            if not isinstance(r, dict):
                continue
            sev = str(r.get("severity") or "medium")
            if sev not in {"critical", "high", "medium", "low", "info"}:
                sev = "medium"
            brief.findings.append(
                BriefFinding(
                    severity=sev,  # type: ignore[arg-type]
                    domain=str(r.get("domain") or "ceo"),
                    statement=str(r.get("description") or r.get("title") or "Cross-domain risk"),
                    metric_ids=[],
                    confidence=float(r.get("confidence") or 0.75),
                )
            )
    if any(f.confidence < CONFIDENCE_GATE for f in brief.findings):
        brief.awaiting_review = True
    return brief
