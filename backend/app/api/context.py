"""
Context API — /api/v1/context/*

GET    /context/{org_id}         → Get full company context
POST   /context/{org_id}         → Update agent result (called by each agent on completion)
DELETE /context/{org_id}         → Reset context (start fresh)
GET    /context/{org_id}/summary → Lightweight agent status summary
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import load_owned_job
from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.company_context import (
    get_cache_stats,
    get_company_context,
    invalidate_company_context,
    invalidate_kernel_cache,
    save_company_context,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_org_id(org_id: str, current_user: User) -> str:
    """
    If org_id is 'me', resolve to the current user's org.
    Raises 403 if the user is trying to access a different org.
    """
    if org_id == "me":
        if not current_user.org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Henüz bir organizasyona üye değilsiniz.",
            )
        return current_user.org_id

    # Users can only access their own org context. The test used to be
    # skipped for a user with no organisation, who could read any org's.
    if not current_user.org_id or current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu organizasyonun context'ine erişim yetkiniz yok.",
        )
    return org_id


# ── Request schemas ───────────────────────────────────────────────────────────

class UpdateContextRequest(BaseModel):
    """Update a single agent's result in the company context."""
    agent: str          # cfo | cto | cmo | coo | chro | risk | audit | compliance | ceo
    result: dict[str, Any]
    company_name: str | None = None
    reporting_period: str | None = None
    job_id: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/context/{org_id}")
async def get_context(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return the full CompanyContext for this org.
    Use org_id='me' as a shortcut for the caller's org.
    """
    resolved_id = _resolve_org_id(org_id, current_user)
    ctx = await get_company_context(resolved_id, db)
    return {"data": ctx.to_dict(), "error": None}


@router.post("/context/{org_id}")
async def update_context(
    org_id: str,
    body: UpdateContextRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Store (or overwrite) an agent's result in the company context.
    Called automatically by each agent pipeline on completion.
    Also triggers auto-chain if the agent has downstream dependencies.
    """
    resolved_id = _resolve_org_id(org_id, current_user)
    ctx = await get_company_context(resolved_id, db)

    # Update agent result
    ctx.update_agent_result(body.agent, body.result)

    # Update job tracking
    if body.job_id:
        # A job id from the request body, loaded without asking whose it was.
        if body.job_id:
            await load_owned_job(db, body.job_id, current_user)
        ctx.set_active_job(body.agent, body.job_id)

    # Update company metadata if provided
    if body.company_name:
        ctx.company_name = body.company_name
    if body.reporting_period:
        ctx.reporting_period = body.reporting_period

    await save_company_context(ctx, db)

    # Rebuild canonical semantic snapshot (non-blocking best-effort)
    try:
        from app.services.semantic.rebuild import rebuild_semantic_snapshot

        await rebuild_semantic_snapshot(resolved_id, db, include_brief=True)
    except Exception as exc:
        logger.warning("Semantic rebuild after context update failed (non-fatal): %s", exc)

    # Trigger auto-chain (non-blocking — fire and forget)
    try:
        import asyncio

        from app.agents.orchestration.auto_chain import on_agent_complete
        asyncio.create_task(on_agent_complete(body.agent, resolved_id, body.result, db))
    except Exception as exc:
        logger.warning("Auto-chain trigger failed (non-fatal): %s", exc)

    return {
        "data": {
            "org_id": resolved_id,
            "agent": body.agent,
            "updated": True,
            "agent_summary": ctx.agent_summary(),
        },
        "error": None,
    }


@router.delete("/context/{org_id}", status_code=status.HTTP_200_OK)
async def reset_context(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Completely reset the company context for this org.
    Useful when starting a new reporting period.
    """
    resolved_id = _resolve_org_id(org_id, current_user)
    await invalidate_company_context(resolved_id, db)
    logger.info("Context reset for org=%s by user=%s", resolved_id, current_user.email)
    return {"data": {"org_id": resolved_id, "reset": True}, "error": None}


@router.get("/context/{org_id}/summary")
async def get_context_summary(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return a lightweight summary of which agents have run and their status.
    Used by Command Center to show platform health without fetching full results.
    """
    resolved_id = _resolve_org_id(org_id, current_user)
    ctx = await get_company_context(resolved_id, db)

    return {
        "data": {
            "org_id": resolved_id,
            "company_name": ctx.company_name,
            "reporting_period": ctx.reporting_period,
            "updated_at": ctx.updated_at,
            "agents": ctx.agent_summary(),
            "active_jobs": {
                "cfo":  ctx.active_cfo_job_id,
                "cto":  ctx.active_cto_job_id,
                "cmo":  ctx.active_cmo_job_id,
                "coo":  ctx.active_coo_job_id,
                "chro": ctx.active_chro_job_id,
            },
        },
        "error": None,
    }


@router.get("/context/{org_id}/cache-stats")
async def get_context_cache_stats(
    org_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return Redis cache diagnostics for this org.

    Response includes:
      - redis_available: bool
      - context_cached: bool + TTL
      - kernels_cached: list of {kernel, ttl_seconds}
    """
    # Took the org straight from the URL, unresolved.
    stats = await get_cache_stats(_resolve_org_id(org_id, current_user))
    return {"data": stats, "error": None}


@router.delete("/context/{org_id}/cache")
async def invalidate_context_cache(
    org_id:  str,
    kernel:  str | None = None,   # If provided, only invalidate this kernel
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Invalidate Redis cache for an org.

    - DELETE /context/{org_id}/cache          → invalidate full context + all kernels
    - DELETE /context/{org_id}/cache?kernel=cto → invalidate only CTO kernel cache
    """
    # Took the org straight from the URL: anyone could flush anyone's cache.
    org_id = _resolve_org_id(org_id, current_user)
    if kernel:
        await invalidate_kernel_cache(org_id, kernel)
        return {"data": {"invalidated": f"kernel:{kernel}", "org_id": org_id}, "error": None}

    # Full invalidation: context + all kernels
    await invalidate_kernel_cache(org_id)   # all kernels
    # Note: full context invalidation is handled by DELETE /context/{org_id}
    return {"data": {"invalidated": "all_kernels", "org_id": org_id}, "error": None}


# ── F5: Per-agent lazy result endpoint ────────────────────────────────────────

_VALID_AGENTS = frozenset({
    "cfo", "cto", "cmo", "coo", "chro",
    "risk", "audit", "compliance", "ceo",
})


@router.get("/context/{org_id}/agent/{agent}")
async def get_agent_result(
    org_id: str,
    agent:  str,
    current_user: User = Depends(get_current_user),
    db:     AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return a single agent's last result from CompanyContext.

    More efficient than GET /context/{org_id} when you only need one agent's
    data — avoids loading the full (potentially large) context payload.

    GET /context/{org_id}/agent/cfo   → last CFO result
    GET /context/{org_id}/agent/cto   → last CTO result
    etc.
    """
    if agent.lower() not in _VALID_AGENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent '{agent}'. Valid: {sorted(_VALID_AGENTS)}",
        )

    resolved_id = _resolve_org_id(org_id, current_user)
    ctx = await get_company_context(resolved_id, db)

    result = getattr(ctx, f"last_{agent.lower()}_result", None)

    return {
        "data": {
            "org_id":     resolved_id,
            "agent":      agent.lower(),
            "has_result": result is not None,
            "result":     result,
            "updated_at": ctx.updated_at,
        },
        "error": None,
    }


@router.get("/context/{org_id}/payload-size")
async def get_context_payload_size(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db:     AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return payload size breakdown for the context — useful for debugging
    unbounded growth and tuning the trim thresholds.

    Returns:
      - total_bytes: full context JSON size
      - per_agent: {agent_name: size_in_bytes} sorted by size desc
      - trim_threshold_bytes: current critical threshold
    """
    import json as _json

    resolved_id = _resolve_org_id(org_id, current_user)
    ctx = await get_company_context(resolved_id, db)

    full_payload = _json.dumps(ctx.to_dict())
    total_bytes  = len(full_payload.encode("utf-8"))

    agents = ["cfo", "cto", "cmo", "coo", "chro", "risk", "audit", "compliance", "ceo"]
    per_agent: dict[str, int] = {}
    for a in agents:
        result = getattr(ctx, f"last_{a}_result", None)
        if result is not None:
            per_agent[a] = len(_json.dumps(result).encode("utf-8"))

    per_agent_sorted = dict(
        sorted(per_agent.items(), key=lambda x: -x[1])
    )

    return {
        "data": {
            "org_id":                resolved_id,
            "total_bytes":           total_bytes,
            "total_kb":              round(total_bytes / 1024, 1),
            "per_agent_bytes":       per_agent_sorted,
            "trim_threshold_bytes":  2 * 1024 * 1024,
            "warn_threshold_bytes":  512 * 1024,
            "exceeds_warn":          total_bytes >= 512 * 1024,
            "exceeds_trim":          total_bytes >= 2 * 1024 * 1024,
        },
        "error": None,
    }
