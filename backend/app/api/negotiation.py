"""
Negotiation API — Sprint L2

POST /negotiation/consensus       → Run consensus for a topic
GET  /negotiation/conflicts/{org_id} → List open conflicts for org
POST /negotiation/resolve/{conflict_id} → Mark conflict as resolved
GET  /negotiation/topics          → List available topics with weights
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter(tags=["negotiation"])
logger = logging.getLogger(__name__)


# ── Request schemas ───────────────────────────────────────────────────────────

class ConsensusRequest(BaseModel):
    org_id:          str | None = None   # defaults to current user's org
    topic:           str                  # "cash_risk" | "growth_forecast" | etc.
    resolution:      Literal["weighted", "majority", "escalate"] = "weighted"


class ResolveRequest(BaseModel):
    resolution:      str          # "accept_a" | "accept_b" | "custom"
    note:            str = ""     # optional resolution note


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/negotiation/consensus")
async def run_consensus(
    body: ConsensusRequest,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Run consensus protocol for a topic across all relevant agents.

    Topics: cash_risk, growth_forecast, headcount, tech_risk,
            revenue_outlook, operational_risk

    Resolution modes:
    - weighted:  Topic-specific agent weights determine winner
    - majority:  Simple majority vote
    - escalate:  Force escalation (human review required)

    Response includes:
    - agreement_score: 0–1 (higher = more agreement)
    - winning_view: the dominant claim
    - dissenting_views: minority claims
    - conflicts: list of detected claim conflicts
    - narrative: human-readable explanation
    """
    from app.services.negotiation import ConsensusEngine, TOPIC_WEIGHTS

    org_id = body.org_id or (str(user.org_id) if user.org_id else None)
    if not org_id:
        raise HTTPException(status_code=400, detail="Organizasyon bulunamadı.")

    # Validate topic
    valid_topics = list(TOPIC_WEIGHTS.keys())
    if body.topic not in valid_topics:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz konu: '{body.topic}'. Geçerli konular: {valid_topics}",
        )

    engine = ConsensusEngine()
    result = await engine.run_consensus(
        org_id          = org_id,
        topic           = body.topic,
        resolution_mode = body.resolution,
        db              = db,
    )

    # Serialize result
    def _claim_dict(c: Any) -> dict:
        return {
            "agent":      c.agent,
            "topic":      c.topic,
            "value":      round(c.value, 3),
            "label":      c.label,
            "evidence":   c.evidence,
            "confidence": c.confidence,
        }

    def _conflict_dict(c: Any) -> dict:
        return {
            "agent_a":     c.agent_a,
            "agent_b":     c.agent_b,
            "claim_a":     _claim_dict(c.claim_a),
            "claim_b":     _claim_dict(c.claim_b),
            "magnitude":   c.magnitude,
            "fingerprint": c.fingerprint,
        }

    return {
        "data": {
            "topic":            result.topic,
            "resolution_mode":  result.resolution_mode,
            "agreement_score":  result.agreement_score,
            "winning_agent":    result.winning_agent,
            "winning_view":     _claim_dict(result.winning_view),
            "dissenting_views": [_claim_dict(c) for c in result.dissenting_views],
            "conflicts":        [_conflict_dict(c) for c in result.conflicts],
            "evidence_map":     result.evidence_map,
            "narrative":        result.narrative,
            "escalated":        result.escalated,
        },
        "error": None,
    }


@router.get("/negotiation/conflicts/{org_id}")
async def list_conflicts(
    org_id:  str,
    status:  str = "open",    # "open" | "resolved" | "escalated" | "all"
    topic:   str | None = None,
    user:    User = Depends(get_current_user),
    db:      AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List agent conflicts for an organization.

    Conflicts are created when ConsensusEngine detects that two agents
    disagree by more than 20% on a topic.

    Query params:
    - status: "open" | "resolved" | "escalated" | "all"
    - topic:  filter by topic (optional)
    """
    try:
        from sqlalchemy import text

        query = (
            "SELECT id, topic, agent_a, agent_b, claim_a, claim_b, "
            "consensus_score, resolution, status, created_at, resolved_at "
            "FROM agent_conflicts WHERE org_id = :org_id"
        )
        params: dict[str, Any] = {"org_id": org_id}

        if status != "all":
            query += " AND status = :status"
            params["status"] = status

        if topic:
            query += " AND topic = :topic"
            params["topic"] = topic

        query += " ORDER BY created_at DESC LIMIT 50"

        result = await db.execute(text(query), params)
        rows   = result.fetchall()

        conflicts = []
        for row in rows:
            claim_a = row[4]
            claim_b = row[5]
            resolution_data = row[7]

            # Parse JSON fields
            if isinstance(claim_a, str):
                try: claim_a = json.loads(claim_a)
                except Exception: pass
            if isinstance(claim_b, str):
                try: claim_b = json.loads(claim_b)
                except Exception: pass
            if isinstance(resolution_data, str):
                try: resolution_data = json.loads(resolution_data)
                except Exception: pass

            conflicts.append({
                "id":              row[0],
                "topic":           row[1],
                "agent_a":         row[2],
                "agent_b":         row[3],
                "claim_a":         claim_a,
                "claim_b":         claim_b,
                "consensus_score": row[6],
                "resolution":      resolution_data,
                "status":          row[8],
                "created_at":      row[9].isoformat() if row[9] else None,
                "resolved_at":     row[10].isoformat() if row[10] else None,
            })

        return {
            "data": {
                "org_id":    org_id,
                "count":     len(conflicts),
                "conflicts": conflicts,
            },
            "error": None,
        }

    except Exception as exc:
        logger.error("Failed to list conflicts for org=%s: %s", org_id, exc)
        return {"data": {"org_id": org_id, "count": 0, "conflicts": []}, "error": None}


@router.post("/negotiation/resolve/{conflict_id}")
async def resolve_conflict(
    conflict_id: str,
    body:        ResolveRequest,
    user:        User = Depends(get_current_user),
    db:          AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Mark a conflict as resolved.

    Resolution choices:
    - accept_a: accept agent_a's view
    - accept_b: accept agent_b's view
    - custom:   provide a custom resolution note

    The conflict is marked as resolved and a resolved_at timestamp is set.
    """
    try:
        from sqlalchemy import text

        await db.execute(
            text(
                "UPDATE agent_conflicts "
                "SET status = 'resolved', "
                "    resolved_at = :now, "
                "    resolution = JSON_SET(COALESCE(resolution, '{}'), "
                "                          '$.user_resolution', :user_res, "
                "                          '$.note', :note, "
                "                          '$.resolved_by', :user_id) "
                "WHERE id = :id"
            ),
            {
                "now":      datetime.now(timezone.utc),
                "user_res": body.resolution,
                "note":     body.note[:500] if body.note else "",
                "user_id":  str(user.id),
                "id":       conflict_id,
            },
        )
        await db.commit()

        return {
            "data": {
                "conflict_id": conflict_id,
                "status":      "resolved",
                "resolution":  body.resolution,
                "resolved_by": str(user.id),
            },
            "error": None,
        }

    except Exception as exc:
        logger.error("Failed to resolve conflict=%s: %s", conflict_id, exc)
        raise HTTPException(status_code=500, detail="Çelişki çözülemedi.") from exc


@router.get("/negotiation/topics")
async def list_topics(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    List available consensus topics with their agent weights.

    Use topic names in POST /negotiation/consensus requests.
    """
    from app.services.negotiation import TOPIC_WEIGHTS

    topics = []
    for topic, weights in TOPIC_WEIGHTS.items():
        topics.append({
            "topic":        topic,
            "agents":       list(weights.keys()),
            "weights":      weights,
            "description":  _topic_description(topic),
        })

    return {"data": {"topics": topics}, "error": None}


def _topic_description(topic: str) -> str:
    descriptions = {
        "cash_risk":        "Nakit riski — CFO vs Risk ajanı çelişkisi",
        "growth_forecast":  "Büyüme tahmini — CFO vs CMO görüş farkı",
        "headcount":        "Personel kararları — CHRO vs CFO bütçe çelişkisi",
        "tech_risk":        "Teknoloji riski — CTO vs Risk ajanı değerlendirmesi",
        "revenue_outlook":  "Gelir görünümü — CFO vs CMO vs CEO beklentileri",
        "operational_risk": "Operasyonel risk — COO vs Risk vs CFO",
    }
    return descriptions.get(topic, topic)
