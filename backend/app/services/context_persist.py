"""
Persist agent results to CompanyContext + trigger semantic rebuild / auto-chain.

Single write path for agent_jobs, sync analyze APIs, and worker completions.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# Auto-chain lives in app/agents/orchestration (it coordinates agent kernels).
# A service must not import upward into agents, so callers in the api / worker
# layer pass the hook in. Kept optional so existing call sites keep working.
AutoChainHook = Callable[[str, str, dict[str, Any], AsyncSession], Awaitable[None]]

logger = logging.getLogger(__name__)

_REBUILD_DEBOUNCE_SEC = 30.0
_last_rebuild_at: dict[str, float] = {}
_trailing_tasks: dict[str, asyncio.Task[None]] = {}


def _serialize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Make pipeline state JSON-safe for context storage."""
    out: dict[str, Any] = {}
    for key, val in result.items():
        if key == "logs":
            logs = []
            for lg in val or []:
                if hasattr(lg, "step"):
                    logs.append(
                        {
                            "step": getattr(lg, "step", None),
                            "ok": getattr(lg, "ok", None),
                            "detail": getattr(lg, "detail", None),
                            "confidence": getattr(lg, "confidence", None),
                        }
                    )
                elif isinstance(lg, dict):
                    logs.append(lg)
            out["logs"] = logs
        elif hasattr(val, "__dict__") and not isinstance(val, (str, int, float, bool)):
            try:
                out[key] = dict(val.__dict__)
            except Exception:
                out[key] = str(val)
        else:
            out[key] = val
    return out


async def enqueue_trailing_semantic_rebuild(org_id: str, delay_sec: float | None = None) -> None:
    """
    After a debounce skip, schedule a trailing rebuild so the last agent blob is not lost.

    Prefers ARQ maintenance job; falls back to an in-process delayed task.
    """
    delay = _REBUILD_DEBOUNCE_SEC if delay_sec is None else max(0.0, delay_sec)
    try:
        from app.worker import enqueue_semantic_rebuild_job

        if await enqueue_semantic_rebuild_job(org_id, defer_by=delay):
            return
    except Exception as exc:
        logger.debug("ARQ trailing semantic rebuild enqueue failed org=%s: %s", org_id, exc)

    prev = _trailing_tasks.get(org_id)
    if prev is not None and not prev.done():
        prev.cancel()

    async def _run() -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        try:
            from app.database import session_factory
            from app.services.semantic.rebuild import rebuild_semantic_snapshot

            async with session_factory()() as db:
                await rebuild_semantic_snapshot(org_id, db, include_brief=True)
            _last_rebuild_at[org_id] = time.monotonic()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Trailing semantic rebuild failed org=%s: %s", org_id, exc)

    _trailing_tasks[org_id] = asyncio.create_task(
        _run(),
        name=f"trailing-rebuild-{org_id[:8]}",
    )


async def persist_agent_completion(
    org_id: str,
    agent: str,
    result: dict[str, Any],
    db: AsyncSession | None,
    *,
    job_id: str | None = None,
    company_name: str | None = None,
    reporting_period: str | None = None,
    trigger_auto_chain: bool = True,
    auto_chain_hook: AutoChainHook | None = None,
    force_rebuild: bool = False,
) -> None:
    """
    Write last_*_result to CompanyContext, rebuild semantic snapshot, optional auto-chain.
    Non-fatal — logs warnings on failure.
    """
    if not org_id:
        return

    agent_lower = agent.lower()
    payload = _serialize_result(result)

    try:
        from app.services.company_context import (
            get_company_context,
            save_company_context,
        )

        ctx = await get_company_context(org_id, db)
        ctx.update_agent_result(agent_lower, payload)
        if job_id:
            ctx.set_active_job(agent_lower, job_id)
        if company_name:
            ctx.company_name = company_name
        if reporting_period:
            ctx.reporting_period = reporting_period
        await save_company_context(ctx, db)
        logger.info("Context persisted agent=%s org=%s job=%s", agent_lower, org_id, job_id)
    except Exception as exc:
        logger.warning("persist_agent_completion context save failed: %s", exc)
        return

    now = time.monotonic()
    last = _last_rebuild_at.get(org_id, 0.0)
    if force_rebuild or (now - last) >= _REBUILD_DEBOUNCE_SEC:
        _last_rebuild_at[org_id] = now
        pending = _trailing_tasks.pop(org_id, None)
        if pending is not None and not pending.done():
            pending.cancel()
        try:
            from app.services.semantic.rebuild import rebuild_semantic_snapshot

            await rebuild_semantic_snapshot(org_id, db, include_brief=True)
        except Exception as exc:
            logger.warning("persist_agent_completion semantic rebuild failed: %s", exc)
    else:
        remaining = _REBUILD_DEBOUNCE_SEC - (now - last)
        logger.debug("Semantic rebuild debounced org=%s remaining=%.1fs", org_id, remaining)
        await enqueue_trailing_semantic_rebuild(org_id, delay_sec=remaining)

    if trigger_auto_chain and auto_chain_hook is not None and db is not None:
        try:
            asyncio.create_task(
                auto_chain_hook(agent_lower, org_id, payload, db),
                name=f"auto-chain-{agent_lower}-{org_id[:8]}",
            )
        except Exception as exc:
            logger.warning("persist_agent_completion auto_chain failed: %s", exc)
    elif trigger_auto_chain and auto_chain_hook is None:
        logger.debug(
            "persist_agent_completion: no auto_chain_hook passed — chain not triggered "
            "for agent=%s org=%s", agent_lower, org_id,
        )
