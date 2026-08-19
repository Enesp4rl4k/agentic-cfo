"""
ConsensusEngine — Multi-Agent Consensus Protocol (Sprint L2)

Detects conflicting claims between agents and resolves via weighted voting.

Problem:
  CFO says "cash risk is low" → Risk says "cash risk is critical"
  User doesn't know who to trust.

Solution:
  1. Extract claims from CompanyContext agent results
  2. ConflictDetector: find claims that differ > CONFLICT_THRESHOLD
  3. WeightedVoting: each agent has topic-specific weight
  4. ConsensusResult: winning view + dissenting views + evidence map

Topic weights (see TOPIC_WEIGHTS below):
  cash_risk:       cfo=0.45, risk=0.40, audit=0.15
  growth_forecast: cfo=0.35, cmo=0.40, ceo=0.25
  headcount:       chro=0.50, cfo=0.35, coo=0.15
  tech_risk:       cto=0.50, risk=0.30, cfo=0.20

Usage:
    engine = ConsensusEngine()
    result = await engine.run_consensus(
        org_id="org-1",
        topic="cash_risk",
        resolution_mode="weighted",
        ctx=company_context,
    )
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Minimum relative difference to declare a conflict (20%)
CONFLICT_THRESHOLD = 0.20

# Topic-based agent weights (must sum to 1.0 per topic)
TOPIC_WEIGHTS: dict[str, dict[str, float]] = {
    "cash_risk": {
        "cfo":   0.45,
        "risk":  0.40,
        "audit": 0.15,
    },
    "growth_forecast": {
        "cfo": 0.35,
        "cmo": 0.40,
        "ceo": 0.25,
    },
    "headcount": {
        "chro": 0.50,
        "cfo":  0.35,
        "coo":  0.15,
    },
    "tech_risk": {
        "cto":  0.50,
        "risk": 0.30,
        "cfo":  0.20,
    },
    "revenue_outlook": {
        "cfo": 0.40,
        "cmo": 0.35,
        "ceo": 0.25,
    },
    "operational_risk": {
        "coo":  0.45,
        "risk": 0.35,
        "cfo":  0.20,
    },
}

# Fallback equal weights when topic not defined
_EQUAL_WEIGHT = 1.0 / 9  # 9 agents


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class AgentClaim:
    """A single agent's position on a topic."""
    agent:     str          # "cfo" | "cto" | etc.
    topic:     str
    value:     float        # normalized 0–1 (0=best, 1=worst for risks)
    label:     str          # human-readable verdict ("düşük", "kritik", etc.)
    evidence:  dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class Conflict:
    """A detected conflict between two agents."""
    agent_a:      str
    agent_b:      str
    claim_a:      AgentClaim
    claim_b:      AgentClaim
    magnitude:    float   # absolute difference in value
    topic:        str
    fingerprint:  str     # stable hash for deduplication


@dataclass
class ConsensusResult:
    """Result of the consensus process."""
    topic:           str
    resolution_mode: str
    agreement_score: float          # 0=total disagreement, 1=full agreement
    winning_agent:   str
    winning_view:    AgentClaim
    dissenting_views: list[AgentClaim]
    conflicts:       list[Conflict]
    evidence_map:    dict[str, Any]
    narrative:       str
    escalated:       bool = False


# ── Conflict detection ────────────────────────────────────────────────────────

class ConflictDetector:
    """
    Detects conflicting claims between agents on a common topic.
    A conflict exists when |value_a - value_b| > CONFLICT_THRESHOLD.
    """

    def detect(
        self,
        claims: dict[str, AgentClaim],
        threshold: float = CONFLICT_THRESHOLD,
    ) -> list[Conflict]:
        agents   = list(claims.keys())
        conflicts: list[Conflict] = []

        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                a_name, b_name = agents[i], agents[j]
                ca, cb = claims[a_name], claims[b_name]

                magnitude = abs(ca.value - cb.value)
                if magnitude > threshold:
                    fingerprint = hashlib.md5(
                        f"{ca.topic}:{a_name}:{b_name}".encode()
                    ).hexdigest()[:10]

                    conflicts.append(Conflict(
                        agent_a     = a_name,
                        agent_b     = b_name,
                        claim_a     = ca,
                        claim_b     = cb,
                        magnitude   = round(magnitude, 3),
                        topic       = ca.topic,
                        fingerprint = fingerprint,
                    ))

        # Sort by magnitude descending
        conflicts.sort(key=lambda c: -c.magnitude)
        return conflicts


# ── Claim extraction from CompanyContext ──────────────────────────────────────

def _extract_claims(
    topic: str,
    ctx: Any,  # CompanyContext
) -> dict[str, AgentClaim]:
    """
    Extract agent claims from CompanyContext for a given topic.
    Maps topic to relevant agent result fields.
    """
    claims: dict[str, AgentClaim] = {}

    def _safe(result: Any, *keys: str) -> float | None:
        """Safely navigate nested dict."""
        node = result
        for k in keys:
            if not isinstance(node, dict):
                return None
            node = node.get(k)
        if isinstance(node, (int, float)):
            return float(node)
        return None

    if topic == "cash_risk":
        # CFO: cash runway months
        cfo = getattr(ctx, "last_cfo_result", None) or {}
        runway = _safe(cfo, "forecast", "scenarios", "base", "runway_months")
        if runway is not None:
            # Normalize: 0 months = 1.0 risk, 12+ months = 0.0 risk
            risk_val = max(0.0, min(1.0, 1.0 - runway / 12.0))
            label    = "kritik" if risk_val > 0.75 else "yüksek" if risk_val > 0.50 else "orta" if risk_val > 0.25 else "düşük"
            claims["cfo"] = AgentClaim("cfo", topic, risk_val, label,
                                       {"runway_months": runway})

        # Risk agent
        risk = getattr(ctx, "last_risk_result", None) or {}
        risk_score = _safe(risk, "risk_summary", "overall_score")
        if risk_score is not None:
            nval = min(1.0, risk_score / 10.0)
            label = "kritik" if nval > 0.75 else "yüksek" if nval > 0.50 else "orta" if nval > 0.25 else "düşük"
            claims["risk"] = AgentClaim("risk", topic, nval, label,
                                        {"overall_score": risk_score})

    elif topic == "growth_forecast":
        cfo = getattr(ctx, "last_cfo_result", None) or {}
        rev_growth = _safe(cfo, "pnl", "revenue_growth_pct")
        if rev_growth is not None:
            # Normalize: -50%=1.0 bad, +50%=0.0 bad (inverted for risk)
            nval = max(0.0, min(1.0, 0.5 - rev_growth / 100.0))
            label = "yüksek büyüme" if rev_growth > 20 else "orta" if rev_growth > 0 else "düşüş"
            claims["cfo"] = AgentClaim("cfo", topic, nval, label,
                                       {"revenue_growth_pct": rev_growth})

        cmo = getattr(ctx, "last_cmo_result", None) or {}
        cac_trend = _safe(cmo, "campaigns", "cac_trend_pct")
        if cac_trend is not None:
            nval = max(0.0, min(1.0, (cac_trend + 50) / 100.0))
            label = "büyüme" if cac_trend < 0 else "yavaşlama"
            claims["cmo"] = AgentClaim("cmo", topic, nval, label,
                                       {"cac_trend_pct": cac_trend})

    elif topic == "headcount":
        chro = getattr(ctx, "last_chro_result", None) or {}
        attrition = _safe(chro, "attrition", "rate_pct")
        if attrition is not None:
            nval = min(1.0, attrition / 30.0)  # >30% = max risk
            label = "kritik" if attrition > 20 else "yüksek" if attrition > 10 else "normal"
            claims["chro"] = AgentClaim("chro", topic, nval, label,
                                        {"attrition_rate": attrition})

        cfo = getattr(ctx, "last_cfo_result", None) or {}
        labor_pct = _safe(cfo, "pnl", "labor_cost_pct")
        if labor_pct is not None:
            nval = min(1.0, labor_pct / 0.5)  # >50% of revenue = max
            label = "yüksek maliyet" if labor_pct > 0.35 else "normal"
            claims["cfo"] = AgentClaim("cfo", topic, nval, label,
                                       {"labor_cost_pct": labor_pct})

    elif topic == "tech_risk":
        cto = getattr(ctx, "last_cto_result", None) or {}
        health = _safe(cto, "cto_summary", "overall_health_score")
        if health is not None:
            nval = max(0.0, min(1.0, 1.0 - health / 10.0))
            label = "kritik" if nval > 0.7 else "orta" if nval > 0.4 else "iyi"
            claims["cto"] = AgentClaim("cto", topic, nval, label,
                                       {"health_score": health})

        risk = getattr(ctx, "last_risk_result", None) or {}
        tech_risk_score = _safe(risk, "risk_summary", "tech_risk_score")
        if tech_risk_score is not None:
            nval = min(1.0, tech_risk_score / 10.0)
            label = "yüksek" if nval > 0.6 else "orta" if nval > 0.3 else "düşük"
            claims["risk"] = AgentClaim("risk", topic, nval, label,
                                        {"tech_risk_score": tech_risk_score})

    return claims


# ── Weighted voting ───────────────────────────────────────────────────────────

def _weighted_vote(
    claims: dict[str, AgentClaim],
    topic: str,
) -> tuple[str, float]:
    """
    Compute weighted consensus value.
    Returns (winning_agent, consensus_value).
    """
    weights = TOPIC_WEIGHTS.get(topic, {})

    weighted_sum = 0.0
    total_weight = 0.0

    for agent, claim in claims.items():
        w = weights.get(agent, _EQUAL_WEIGHT)
        weighted_sum += claim.value * w
        total_weight  += w

    if total_weight == 0:
        return (list(claims.keys())[0], 0.5)

    consensus_value = weighted_sum / total_weight

    # Winning agent: claim closest to consensus value with highest weight
    best_agent   = ""
    best_score   = float("inf")
    best_weight  = 0.0

    for agent, claim in claims.items():
        distance = abs(claim.value - consensus_value)
        w = weights.get(agent, _EQUAL_WEIGHT)
        score    = distance - w * 0.1  # tie-break by weight

        if score < best_score:
            best_score  = score
            best_agent  = agent
            best_weight = w

    return best_agent, consensus_value


# ── Agreement score ───────────────────────────────────────────────────────────

def _compute_agreement_score(claims: dict[str, AgentClaim]) -> float:
    """
    Agreement score = 1 - mean pairwise distance.
    1.0 = full agreement, 0.0 = total disagreement.
    """
    values = [c.value for c in claims.values()]
    if len(values) < 2:
        return 1.0

    pairwise = []
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            pairwise.append(abs(values[i] - values[j]))

    mean_dist = sum(pairwise) / len(pairwise)
    return max(0.0, min(1.0, 1.0 - mean_dist))


# ── ConsensusEngine ───────────────────────────────────────────────────────────

class ConsensusEngine:
    """
    Multi-agent consensus protocol.

    Steps:
    1. Extract relevant claims from CompanyContext
    2. ConflictDetector: find conflicting claims
    3. Weighted voting or majority resolution
    4. Return ConsensusResult + persist conflict to DB
    """

    def __init__(self) -> None:
        self._detector = ConflictDetector()

    async def run_consensus(
        self,
        org_id:          str,
        topic:           str,
        resolution_mode: Literal["weighted", "majority", "escalate"] = "weighted",
        ctx:             Any = None,   # CompanyContext
        db:              Any = None,   # AsyncSession
    ) -> ConsensusResult:
        """
        Run consensus for a topic across all relevant agents.

        Args:
            org_id:          Organization ID
            topic:           Topic to resolve (see TOPIC_WEIGHTS)
            resolution_mode: "weighted" | "majority" | "escalate"
            ctx:             CompanyContext (loaded if not provided)
            db:              AsyncSession for persistence

        Returns:
            ConsensusResult with winning view + dissenting views
        """
        # Load context if not provided
        if ctx is None:
            try:
                from app.services.company_context import get_company_context
                ctx = await get_company_context(org_id, db)
            except Exception as exc:
                logger.warning("ConsensusEngine: could not load context: %s", exc)
                return self._empty_result(topic, resolution_mode)

        # Extract claims
        claims = _extract_claims(topic, ctx)

        if len(claims) < 2:
            logger.debug(
                "ConsensusEngine: insufficient claims for topic=%s (found %d)",
                topic, len(claims),
            )
            return self._empty_result(topic, resolution_mode)

        # Detect conflicts
        conflicts = self._detector.detect(claims)

        # Compute agreement
        agreement_score = _compute_agreement_score(claims)

        # Escalate if too much disagreement
        if resolution_mode == "escalate" or (
            resolution_mode == "weighted" and agreement_score < 0.3 and len(conflicts) > 1
        ):
            result = self._escalate(topic, claims, conflicts, agreement_score)
        elif resolution_mode == "majority":
            result = self._majority_vote(topic, claims, conflicts, agreement_score)
        else:
            result = self._weighted_resolution(topic, claims, conflicts, agreement_score)

        # Persist conflict to DB if conflicts found
        if conflicts and db is not None:
            await self._persist_conflicts(org_id, topic, claims, conflicts, result, db)

        return result

    def _weighted_resolution(
        self,
        topic: str,
        claims: dict[str, AgentClaim],
        conflicts: list[Conflict],
        agreement_score: float,
    ) -> ConsensusResult:
        winning_agent, consensus_value = _weighted_vote(claims, topic)
        winning_claim = claims[winning_agent]
        dissenting    = [c for name, c in claims.items() if name != winning_agent]

        narrative = self._build_narrative(
            topic, winning_agent, winning_claim, dissenting, conflicts, agreement_score
        )

        return ConsensusResult(
            topic            = topic,
            resolution_mode  = "weighted",
            agreement_score  = round(agreement_score, 3),
            winning_agent    = winning_agent,
            winning_view     = winning_claim,
            dissenting_views = dissenting,
            conflicts        = conflicts,
            evidence_map     = {name: c.evidence for name, c in claims.items()},
            narrative        = narrative,
        )

    def _majority_vote(
        self,
        topic: str,
        claims: dict[str, AgentClaim],
        conflicts: list[Conflict],
        agreement_score: float,
    ) -> ConsensusResult:
        # Simple majority: split claims into high (>0.5) and low (<=0.5)
        high = {n: c for n, c in claims.items() if c.value > 0.5}
        low  = {n: c for n, c in claims.items() if c.value <= 0.5}
        winning_side = high if len(high) >= len(low) else low

        # Pick the claim closest to the group mean
        group_mean = sum(c.value for c in winning_side.values()) / len(winning_side)
        winning_agent = min(winning_side.keys(), key=lambda n: abs(claims[n].value - group_mean))
        winning_claim = claims[winning_agent]
        dissenting    = [c for name, c in claims.items() if name != winning_agent]

        narrative = f"Çoğunluk oyu ({len(winning_side)}/{len(claims)} ajan): " + winning_claim.label

        return ConsensusResult(
            topic            = topic,
            resolution_mode  = "majority",
            agreement_score  = round(agreement_score, 3),
            winning_agent    = winning_agent,
            winning_view     = winning_claim,
            dissenting_views = dissenting,
            conflicts        = conflicts,
            evidence_map     = {name: c.evidence for name, c in claims.items()},
            narrative        = narrative,
        )

    def _escalate(
        self,
        topic: str,
        claims: dict[str, AgentClaim],
        conflicts: list[Conflict],
        agreement_score: float,
    ) -> ConsensusResult:
        # No winner — needs human review
        all_claims = list(claims.values())
        narrative  = (
            f"Ajan görüşleri çok çelişkili (uyum skoru: {agreement_score:.0%}). "
            f"CEO/CFO incelemesi gerekiyor. "
            f"{len(conflicts)} çelişki tespit edildi."
        )

        return ConsensusResult(
            topic            = topic,
            resolution_mode  = "escalate",
            agreement_score  = round(agreement_score, 3),
            winning_agent    = "none",
            winning_view     = all_claims[0] if all_claims else AgentClaim("none", topic, 0.5, "belirsiz"),
            dissenting_views = all_claims[1:],
            conflicts        = conflicts,
            evidence_map     = {name: c.evidence for name, c in claims.items()},
            narrative        = narrative,
            escalated        = True,
        )

    def _empty_result(self, topic: str, resolution_mode: str) -> ConsensusResult:
        return ConsensusResult(
            topic            = topic,
            resolution_mode  = resolution_mode,
            agreement_score  = 1.0,
            winning_agent    = "none",
            winning_view     = AgentClaim("none", topic, 0.5, "veri yok"),
            dissenting_views = [],
            conflicts        = [],
            evidence_map     = {},
            narrative        = "Bu konu için yeterli ajan verisi bulunamadı.",
        )

    def _build_narrative(
        self,
        topic: str,
        winning_agent: str,
        winning_claim: AgentClaim,
        dissenting: list[AgentClaim],
        conflicts: list[Conflict],
        agreement_score: float,
    ) -> str:
        if agreement_score >= 0.8:
            return f"Ajanlar büyük ölçüde hemfikir: {winning_claim.label} ({agreement_score:.0%} uyum)."

        dissent_text = ""
        if dissenting:
            names = ", ".join(c.agent.upper() for c in dissenting[:2])
            dissent_text = f" {names} farklı görüşe sahip."

        return (
            f"{winning_agent.upper()} ağırlıklı karar: {winning_claim.label}. "
            f"Uyum skoru: {agreement_score:.0%}.{dissent_text}"
        )

    async def _persist_conflicts(
        self,
        org_id: str,
        topic: str,
        claims: dict[str, AgentClaim],
        conflicts: list[Conflict],
        result: ConsensusResult,
        db: Any,
    ) -> None:
        """Persist top conflict to DB for frontend display."""
        try:
            import json, uuid as _uuid
            from sqlalchemy import text

            for conflict in conflicts[:3]:  # persist top 3
                await db.execute(
                    text(
                        "INSERT INTO agent_conflicts "
                        "(id, org_id, topic, agent_a, agent_b, claim_a, claim_b, "
                        " consensus_score, resolution, status, created_at) "
                        "VALUES (:id, :org_id, :topic, :agent_a, :agent_b, "
                        ":claim_a, :claim_b, :score, :resolution, 'open', :now)"
                    ),
                    {
                        "id":         _uuid.uuid4().hex,
                        "org_id":     org_id,
                        "topic":      topic,
                        "agent_a":    conflict.agent_a,
                        "agent_b":    conflict.agent_b,
                        "claim_a":    json.dumps({"value": conflict.claim_a.value,
                                                   "label": conflict.claim_a.label}),
                        "claim_b":    json.dumps({"value": conflict.claim_b.value,
                                                   "label": conflict.claim_b.label}),
                        "score":      result.agreement_score,
                        "resolution": json.dumps({
                            "winner":    result.winning_agent,
                            "narrative": result.narrative[:500],
                        }),
                        "now":        datetime.now(timezone.utc),
                    },
                )
            await db.commit()
        except Exception as exc:
            logger.debug("ConsensusEngine: conflict persistence failed (non-fatal): %s", exc)
