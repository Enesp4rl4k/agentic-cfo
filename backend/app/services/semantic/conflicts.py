"""Load open agent conflicts + detect metric-level contradictions."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.semantic.types import MetricPoint

logger = logging.getLogger(__name__)

REVENUE_INFLOW_REL_THRESHOLD = 0.25
GROWTH_VS_CASH_ROAS_MIN = 3.0
GROWTH_VS_CASH_RUNWAY_MAX = 4.0


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rel_diff(a: float, b: float) -> float:
    denom = max(abs(a), abs(b), 1.0)
    return abs(a - b) / denom


def detect_metric_conflicts(metrics: list[MetricPoint]) -> list[dict[str, Any]]:
    """
    Deterministic contradictions between semantic metrics.

    - CFO revenue vs canonical inflow (live ledger) diverge > 25%
    - CMO ROAS healthy while runway is critically short
    """
    mmap = {m.metric_id: m for m in metrics}
    found: list[dict[str, Any]] = []

    revenue = mmap.get("finance.revenue")
    inflow = mmap.get("finance.canonical_inflow")
    rev_n = _num(revenue.value) if revenue else None
    in_n = _num(inflow.value) if inflow else None
    if rev_n is not None and in_n is not None and in_n > 0 and _rel_diff(rev_n, in_n) > REVENUE_INFLOW_REL_THRESHOLD:
        found.append(
            {
                "topic": "revenue_vs_canonical_inflow",
                "agent_a": (revenue.source_agent if revenue else None) or "cfo",
                "agent_b": (inflow.data_source if inflow else None) or "canonical",
                "claim_a": {"metric_id": "finance.revenue", "value": rev_n},
                "claim_b": {"metric_id": "finance.canonical_inflow", "value": in_n},
                "consensus_score": round(1.0 - _rel_diff(rev_n, in_n), 4),
                "status": "open",
            }
        )

    roas = mmap.get("growth.overall_roas")
    runway = mmap.get("finance.runway_months")
    roas_n = _num(roas.value) if roas else None
    run_n = _num(runway.value) if runway else None
    if (
        roas_n is not None
        and run_n is not None
        and roas_n >= GROWTH_VS_CASH_ROAS_MIN
        and run_n < GROWTH_VS_CASH_RUNWAY_MAX
    ):
        found.append(
            {
                "topic": "growth_vs_cash",
                "agent_a": (roas.source_agent if roas else None) or "cmo",
                "agent_b": (runway.source_agent if runway else None) or "cfo",
                "claim_a": {"metric_id": "growth.overall_roas", "value": roas_n},
                "claim_b": {"metric_id": "finance.runway_months", "value": run_n},
                "consensus_score": 0.35,
                "status": "open",
            }
        )
    return found


async def persist_metric_conflicts(
    org_id: str,
    conflicts: list[dict[str, Any]],
    db: AsyncSession | None,
) -> int:
    """Insert newly detected metric conflicts (ORM, non-fatal, skip duplicates)."""
    if not db or not org_id or not conflicts:
        return 0
    try:
        from app.models.agent_conflict import AgentConflict

        existing = await db.execute(
            select(AgentConflict.topic, AgentConflict.agent_a, AgentConflict.agent_b).where(
                AgentConflict.org_id == str(org_id),
                AgentConflict.status.in_(("open", "escalated")),
            )
        )
        seen = {(row[0], row[1], row[2]) for row in existing.all()}
        added = 0
        for conflict in conflicts:
            key = (
                str(conflict.get("topic") or ""),
                str(conflict.get("agent_a") or ""),
                str(conflict.get("agent_b") or ""),
            )
            if key in seen:
                continue
            row = AgentConflict(
                id=uuid.uuid4().hex,
                org_id=str(org_id),
                topic=key[0][:100],
                agent_a=key[1][:50],
                agent_b=key[2][:50],
                claim_a=json.dumps(conflict.get("claim_a") or {}),
                claim_b=json.dumps(conflict.get("claim_b") or {}),
                consensus_score=float(conflict.get("consensus_score") or 0.5),
                status="open",
            )
            db.add(row)
            seen.add(key)
            added += 1
        if added:
            await db.flush()
        return added
    except Exception as exc:
        logger.warning("persist_metric_conflicts failed org=%s: %s", org_id, exc)
        return 0


async def list_org_conflicts(
    org_id: str,
    db: AsyncSession | None,
    *,
    status: str = "open",
    topic: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List agent_conflicts for an org via ORM (Command Center / negotiation API)."""
    if not db or not org_id:
        return []
    from app.models.agent_conflict import AgentConflict

    stmt = select(AgentConflict).where(AgentConflict.org_id == str(org_id))
    if status != "all":
        stmt = stmt.where(AgentConflict.status == status)
    if topic:
        stmt = stmt.where(AgentConflict.topic == topic)
    stmt = stmt.order_by(AgentConflict.created_at.desc()).limit(max(1, min(limit, 100)))
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": row.id,
            "topic": row.topic,
            "agent_a": row.agent_a,
            "agent_b": row.agent_b,
            "claim_a": _parse_json_field(row.claim_a),
            "claim_b": _parse_json_field(row.claim_b),
            "consensus_score": row.consensus_score,
            "resolution": _parse_json_field(row.resolution),
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }
        for row in rows
    ]


def _parse_json_field(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


async def load_open_conflicts(
    org_id: str,
    db: AsyncSession | None,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return open/escalated conflicts for org (ORM-only)."""
    if not db or not org_id:
        return []
    try:
        from app.models.agent_conflict import AgentConflict

        result = await db.execute(
            select(AgentConflict)
            .where(
                AgentConflict.org_id == str(org_id),
                AgentConflict.status.in_(("open", "escalated")),
            )
            .order_by(AgentConflict.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": row.id,
                "topic": row.topic,
                "agent_a": row.agent_a,
                "agent_b": row.agent_b,
                "claim_a": _parse_json_field(row.claim_a),
                "claim_b": _parse_json_field(row.claim_b),
                "consensus_score": row.consensus_score,
                "resolution": _parse_json_field(row.resolution),
                "status": row.status,
            }
            for row in rows
        ]
    except Exception as exc:
        logger.debug("load_open_conflicts failed org=%s: %s", org_id, exc)
        return []
