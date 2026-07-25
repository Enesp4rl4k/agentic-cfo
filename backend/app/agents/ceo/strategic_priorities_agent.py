"""
Strategic Priorities Agent — CEO Skill 2 of 3.

Responsibility: Turn cross-domain risks + financial/tech signals into a
ranked, actionable priority list for the CEO.

Ranking algorithm (pure, no LLM):
  1. Urgency: now > 30d > 90d
  2. Financial impact (higher = more urgent)
  3. Effort inverse: low effort + high impact = top priority (quick win)

LLM adds strategic framing to each priority.

done_when: state['strategic_priorities'] is a non-empty list.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.ceo.state import CEOState, CEORunConfig, CEOSkillResult

logger = logging.getLogger(__name__)

URGENCY_SCORE = {"now": 100, "30d": 50, "90d": 10}
SEVERITY_SCORE = {"critical": 40, "high": 20, "medium": 10, "low": 2}
EFFORT_MULTIPLIER = {"low": 2.0, "medium": 1.0, "high": 0.5}
IMPACT_SCORE = {"critical": 40, "high": 20, "medium": 10, "low": 2}


def _score_priority(risk: dict[str, Any]) -> float:
    """Composite priority score — higher = act first."""
    urgency  = URGENCY_SCORE.get(risk.get("urgency", "90d"), 10)
    severity = SEVERITY_SCORE.get(risk.get("severity", "low"), 2)
    fin_impact = min(30, risk.get("financial_impact_cents", 0) / 1_000_00)  # cap at $1M
    return urgency + severity + fin_impact


def _build_priorities_from_risks(
    cross_risks: list[dict[str, Any]],
    fin: dict[str, Any],
    tech: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Convert cross-domain risks into ranked strategic priorities.
    Also adds domain-specific priorities not captured in cross_risks.
    """
    priorities: list[dict[str, Any]] = []

    # ── From cross-domain risks ────────────────────────────────────────────────
    for risk in cross_risks:
        effort = "low" if risk.get("urgency") == "now" else "medium"
        priorities.append({
            "title":            risk["title"],
            "rationale":        risk["recommended_action"],
            "domains":          risk.get("domains", ["cfo", "cto"]),
            "urgency":          risk.get("urgency", "90d"),
            "severity":         risk.get("severity", "medium"),
            "financial_impact_cents": risk.get("financial_impact_cents", 0),
            "owner_role":       "CEO",
            "effort":           effort,
            "impact":           risk.get("severity", "medium"),
            "_score":           _score_priority(risk),
        })

    # ── CFO-only priorities ────────────────────────────────────────────────────
    runway = fin.get("cash_runway_months")
    if runway is not None and runway <= 3 and not any(
        "runway" in p["title"].lower() for p in priorities
    ):
        priorities.append({
            "title":        "Emergency cash conservation plan",
            "rationale":    f"Cash runway is {runway} months. Immediate OpEx review required.",
            "domains":      ["cfo"],
            "urgency":      "now",
            "severity":     "critical",
            "financial_impact_cents": fin.get("monthly_burn_cents", 0),
            "owner_role":   "CFO",
            "effort":       "medium",
            "impact":       "critical",
            "_score":       150,
        })

    if fin.get("net_margin", 0) < -0.05:
        priorities.append({
            "title":        "Path to profitability — 90-day plan",
            "rationale":    f"Net margin {fin['net_margin']*100:.1f}%. Define concrete cost reduction or revenue targets.",
            "domains":      ["cfo"],
            "urgency":      "30d",
            "severity":     "high",
            "financial_impact_cents": abs(fin.get("net_income_cents", 0)),
            "owner_role":   "CFO",
            "effort":       "medium",
            "impact":       "high",
            "_score":       70,
        })

    # ── CTO-only priorities ────────────────────────────────────────────────────
    health = tech.get("overall_health_score", 0)
    if health >= 7.0:
        priorities.append({
            "title":        "Technology health intervention",
            "rationale":    f"Tech health score {health:.1f}/10 indicates systemic issues. Architecture review needed.",
            "domains":      ["cto"],
            "urgency":      "30d",
            "severity":     "high",
            "financial_impact_cents": 0,
            "owner_role":   "CTO",
            "effort":       "high",
            "impact":       "high",
            "_score":       60,
        })

    waste = tech.get("infra_waste_cents", 0)
    if waste > 5_000_00 and not any("cloud waste" in p["title"].lower() for p in priorities):
        priorities.append({
            "title":        f"Cloud cost optimization — save ${waste/100:,.0f}/month",
            "rationale":    "Reduce identified cloud waste with immediate rightsizing and unused resource cleanup.",
            "domains":      ["cto"],
            "urgency":      "30d",
            "severity":     "medium",
            "financial_impact_cents": waste,
            "owner_role":   "CTO",
            "effort":       "low",
            "impact":       "medium",
            "_score":       55,
        })

    # Sort by score descending, assign ranks
    priorities.sort(key=lambda p: p.get("_score", 0), reverse=True)
    for i, p in enumerate(priorities):
        p["rank"] = i + 1
        p.pop("_score", None)

    return priorities[:8]  # top 8


async def run_strategic_priorities_agent(
    state: CEOState,
    config: CEORunConfig,
) -> CEOSkillResult:
    """
    StrategicPriorities Skill.
    done_when: state['strategic_priorities'] is a non-empty list.
    """
    cross_risks = state.get("cross_risks") or []
    fin  = state.get("financial_summary") or {}
    tech = state.get("tech_summary") or {}

    try:
        from app.config import get_settings
        settings = get_settings()

        priorities = _build_priorities_from_risks(cross_risks, fin, tech)

        if not priorities:
            return CEOSkillResult(
                ok=True,
                patch={"strategic_priorities": []},
                confidence=1.0,
                detail="No priorities generated — insufficient input data.",
            )

        # ── LLM: enrich top 3 with strategic rationale ────────────────────────
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = ChatOpenAI(
                model=settings.llm_model,
                temperature=0.2,
                max_tokens=768,
                api_key=settings.openai_api_key,
                base_url=settings.llm_base_url or None,
            )
            top3_text = "\n".join(
                f"{p['rank']}. [{p['severity'].upper()}] {p['title']}: {p['rationale'][:120]}"
                for p in priorities[:3]
            )
            response = await llm.ainvoke([
                SystemMessage(content=(
                    "Sen deneyimli bir CEO koçusun. Aşağıdaki her stratejik öncelik için "
                    "yönetim kuruluna sunulacak düzeyde tek bir Türkçe cümle ekle. "
                    "SADECE geliştirilmiş gerekçe satırlarını döndür, her öncelik için bir tane, numaralı. "
                    "Sade, doğrudan ve eylem odaklı yaz."
                )),
                HumanMessage(content=f"İlk 3 öncelik:\n{top3_text}"),
            ])
            lines = [l.strip() for l in response.content.strip().splitlines() if l.strip()]
            for i, line in enumerate(lines[:3]):
                # Strip leading number/dot if present
                clean = line.lstrip("0123456789. ")
                if clean:
                    priorities[i]["rationale"] = clean
        except Exception as llm_exc:
            logger.warning("CEO priorities LLM enrichment failed: %s", llm_exc)
            # Non-fatal: rule-based priorities still valid

        logger.info(
            "CEO StrategicPriorities: job=%s priorities=%d",
            state.get("job_id"), len(priorities),
        )

        return CEOSkillResult(
            ok=True,
            patch={"strategic_priorities": priorities},
            confidence=0.88,
            detail=f"Generated {len(priorities)} strategic priorities",
        )

    except Exception as exc:
        logger.exception("CEO StrategicPriorities failed for job=%s", state.get("job_id"))
        return CEOSkillResult(ok=False, detail=f"StrategicPriorities error: {exc}")
