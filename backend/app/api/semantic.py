"""
Semantic company model API.

GET  /semantic/me                     — current period snapshot + catalog
GET  /semantic/me/metrics/{metric_id} — single metric
POST /semantic/me/rebuild             — reproject from context + canonical txs (admin+)
GET  /semantic/me/brief               — latest DecisionBrief
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_role
from app.database import get_db
from app.models.user import User
from app.services.semantic.catalog import catalog_list, is_known_metric
from app.services.semantic.rebuild import rebuild_semantic_snapshot
from app.services.semantic.store import (
    approve_semantic_brief,
    get_latest_semantic_snapshot,
    get_semantic_snapshot,
    list_semantic_snapshots,
    resolve_period_key,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _org_id(user: User) -> str:
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a member of an organization",
        )
    return str(user.org_id)


@router.get("/semantic/me")
async def get_my_semantic(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    from app.services.company_context import get_company_context

    ctx = await get_company_context(org_id, db)
    period = resolve_period_key(ctx.reporting_period)
    snap = await get_semantic_snapshot(org_id, period.key, db)
    if snap is None:
        snap = await get_latest_semantic_snapshot(org_id, db)
    return {
        "data": {
            "snapshot": snap.to_dict() if snap else None,
            "catalog": catalog_list(),
            "period_key": period.key,
        },
        "error": None,
    }


@router.get("/semantic/me/metrics/{metric_id:path}")
async def get_my_metric(
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    if not is_known_metric(metric_id):
        raise HTTPException(status_code=404, detail=f"Unknown metric_id: {metric_id}")
    from app.services.company_context import get_company_context

    ctx = await get_company_context(org_id, db)
    period = resolve_period_key(ctx.reporting_period)
    snap = await get_semantic_snapshot(org_id, period.key, db)
    if snap is None:
        snap = await get_latest_semantic_snapshot(org_id, db)
    if snap is None:
        return {"data": None, "error": "No semantic snapshot"}
    point = snap.metric_map().get(metric_id)
    return {
        "data": point.to_dict() if point else None,
        "error": None if point else "Metric not present in snapshot",
    }


@router.post("/semantic/me/rebuild")
async def rebuild_my_semantic(
    current_user: User = Depends(require_role("admin", "owner", "cfo")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    snap = await rebuild_semantic_snapshot(org_id, db, include_brief=True)
    if snap is None:
        raise HTTPException(status_code=500, detail="Semantic rebuild failed")
    return {"data": snap.to_dict(), "error": None}


@router.get("/semantic/me/brief")
async def get_my_brief(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    period_key: str | None = None,
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    from app.services.company_context import get_company_context

    ctx = await get_company_context(org_id, db)
    period = resolve_period_key(period_key or ctx.reporting_period)
    snap = await get_semantic_snapshot(org_id, period.key, db)
    if snap is None:
        snap = await get_latest_semantic_snapshot(org_id, db)
    brief = snap.brief.to_dict() if snap and snap.brief else None
    if brief is None and ctx.last_ceo_result:
        brief = (ctx.last_ceo_result or {}).get("decision_brief")
    return {
        "data": {
            "brief": brief,
            "period_key": period.key,
            "awaiting_review": bool(brief.get("awaiting_review")) if isinstance(brief, dict) else False,
        },
        "error": None,
    }


@router.post("/semantic/me/brief/approve")
async def approve_my_brief(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    period_key: str | None = None,
) -> dict[str, Any]:
    """Human approval — clear awaiting_review on the DecisionBrief (confidence gate)."""
    org_id = _org_id(current_user)
    from app.services.company_context import get_company_context

    ctx = await get_company_context(org_id, db)
    period = resolve_period_key(period_key or ctx.reporting_period)
    snap = await approve_semantic_brief(org_id, period.key, db)
    if snap is None or snap.brief is None:
        raise HTTPException(status_code=404, detail="No decision brief to approve")
    return {
        "data": {
            "brief": snap.brief.to_dict(),
            "period_key": period.key,
            "awaiting_review": snap.brief.awaiting_review,
        },
        "error": None,
    }


@router.get("/semantic/me/history")
async def get_my_semantic_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 12,
) -> dict[str, Any]:
    """List recent semantic snapshots (period keys + health scores)."""
    org_id = _org_id(current_user)
    snaps = await list_semantic_snapshots(org_id, db, limit=limit)
    items = []
    for snap in snaps:
        items.append(
            {
                "period_key": snap.period.key,
                "period_start": snap.period.start,
                "period_end": snap.period.end,
                "currency": snap.currency,
                "health_score": snap.brief.health_score if snap.brief else None,
                "awaiting_review": snap.brief.awaiting_review if snap.brief else False,
                "metric_count": len(snap.metrics),
                "updated_at": snap.updated_at,
            }
        )
    return {"data": {"periods": items, "count": len(items)}, "error": None}


@router.get("/semantic/me/live-status")
async def get_live_data_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Whether org has live sync + fresh semantic brief (golden path readiness)."""
    org_id = _org_id(current_user)
    from app.models.canonical_transaction import CanonicalTransaction
    from app.models.sync_run import SyncRun

    snap = await get_latest_semantic_snapshot(org_id, db)
    sync_row = None
    try:
        result = await db.execute(
            select(SyncRun)
            .where(SyncRun.org_id == org_id, SyncRun.status == "success")
            .order_by(SyncRun.completed_at.desc())
            .limit(1)
        )
        sync_row = result.scalar_one_or_none()
    except Exception:
        pass

    canonical_count = 0
    try:
        count_result = await db.execute(
            select(func.count())
            .select_from(CanonicalTransaction)
            .where(CanonicalTransaction.org_id == org_id)
        )
        canonical_count = int(count_result.scalar_one() or 0)
    except Exception:
        pass

    has_live_sync = sync_row is not None and (sync_row.row_count_canonical or 0) > 0
    has_brief = snap is not None and snap.brief is not None
    baseline_source = "semantic" if snap and snap.metrics else "none"

    return {
        "data": {
            "live_sync_enabled": has_live_sync,
            "last_sync": {
                "provider": sync_row.provider if sync_row else None,
                "completed_at": sync_row.completed_at.isoformat() if sync_row and sync_row.completed_at else None,
                "row_count_canonical": sync_row.row_count_canonical if sync_row else 0,
                "quality_score": sync_row.quality_score if sync_row else None,
                "triggered_job_id": sync_row.triggered_job_id if sync_row else None,
            }
            if sync_row
            else None,
            "canonical_transaction_count": canonical_count,
            "semantic_snapshot": {
                "period_key": snap.period.key if snap else None,
                "metric_count": len(snap.metrics) if snap else 0,
                "health_score": snap.brief.health_score if snap and snap.brief else None,
                "awaiting_review": snap.brief.awaiting_review if snap and snap.brief else False,
                "updated_at": snap.updated_at if snap else None,
            },
            "baseline_source": baseline_source,
            "golden_path_ready": has_live_sync and has_brief and canonical_count > 0,
        },
        "error": None,
    }
