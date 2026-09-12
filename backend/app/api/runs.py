"""Agent run ledger API (Faz 14).

    GET  /runs                 — recent runs for the caller's org (filter by status/pipeline)
    GET  /runs/slo             — latency / cost / success-rate rollup per pipeline
    GET  /runs/{run_id}        — one run
    POST /runs/{run_id}/resume — re-drive a failed/interrupted run (tr_vertical)
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import current_user_org_matches
from app.api.auth import get_current_user
from app.database import get_db
from app.models.agent_run import AgentRun
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


def _org_id(user: User) -> str:
    if not user.org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")
    return str(user.org_id)


def _run_dict(r: AgentRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "pipeline": r.pipeline,
        "job_id": r.job_id,
        "status": r.status,
        "current_node": r.current_node,
        "node_history": r.node_history or [],
        "attempt": r.attempt,
        "error": r.error,
        "latency_ms": r.latency_ms,
        "cost_usd": r.cost_usd,
        "result_ref": r.result_ref,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


@router.get("/runs")
async def list_runs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None),
    pipeline: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    stmt = select(AgentRun).where(AgentRun.org_id == org_id)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    if pipeline:
        stmt = stmt.where(AgentRun.pipeline == pipeline)
    stmt = stmt.order_by(AgentRun.started_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return {"data": {"runs": [_run_dict(r) for r in rows]}, "error": None}


@router.get("/runs/slo")
async def runs_slo(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    org_id = _org_id(current_user)
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.org_id == org_id, AgentRun.started_at >= since
            )
        )
    ).scalars().all()

    by_pipeline: dict[str, dict[str, Any]] = {}
    for r in rows:
        b = by_pipeline.setdefault(
            r.pipeline,
            {"runs": 0, "completed": 0, "failed": 0, "awaiting_review": 0,
             "halted": 0, "_lat": [], "cost_usd": 0.0},
        )
        b["runs"] += 1
        if r.status in b:
            b[r.status] += 1
        if r.latency_ms is not None:
            b["_lat"].append(r.latency_ms)
        if r.cost_usd:
            b["cost_usd"] = round(b["cost_usd"] + r.cost_usd, 6)

    def _pct(vals: list[float], p: float) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        idx = min(len(s) - 1, round((p / 100) * (len(s) - 1)))
        return round(s[idx], 1)

    out = {}
    for name, b in by_pipeline.items():
        lat = b.pop("_lat")
        done = b["completed"]
        out[name] = {
            **b,
            "success_rate": round(done / b["runs"], 3) if b["runs"] else None,
            "p50_latency_ms": _pct(lat, 50),
            "p95_latency_ms": _pct(lat, 95),
            "avg_cost_usd": round(b["cost_usd"] / b["runs"], 6) if b["runs"] else None,
        }

    return {
        "data": {"window_days": days, "total_runs": len(rows), "by_pipeline": out},
        "error": None,
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(AgentRun, run_id)
    # A run with no organisation used to be visible to everyone.
    if row is None or not current_user_org_matches(current_user, row.org_id):
        raise HTTPException(status_code=404, detail="Run bulunamadı.")
    return {"data": _run_dict(row), "error": None}


@router.post("/runs/{run_id}/resume")
async def resume_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(AgentRun, run_id)
    if row is None or not current_user_org_matches(current_user, row.org_id):
        raise HTTPException(status_code=404, detail="Run bulunamadı.")
    if row.status == "completed":
        raise HTTPException(status_code=409, detail="Run zaten tamamlanmış.")
    if row.pipeline != "tr_vertical":
        raise HTTPException(
            status_code=400, detail=f"'{row.pipeline}' resume desteklenmiyor."
        )

    from app.agents.run_ledger import resume_run
    from app.agents.tr_vertical import run_tr_vertical
    from app.models.analysis_job import AnalysisJob

    job = await db.get(AnalysisJob, row.job_id) if row.job_id else None
    if job is None or not job.file_path:
        raise HTTPException(status_code=400, detail="Kaynak job/dosya bulunamadı.")

    _, result = await resume_run(
        db, run_id, run_tr_vertical,
        job_id=row.job_id, file_path=job.file_path, file_type=job.file_type,
        org_id=row.org_id,
    )
    return {
        "data": {"run": _run_dict(row), "stage": getattr(result, "stage", None)},
        "error": None,
    }
