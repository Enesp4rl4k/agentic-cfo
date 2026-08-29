"""Durable run ledger (Faz 14).

`agent_run(...)` is an async context manager that bookkeeps one pipeline
execution in `agent_runs`: opens a row on entry, lets the body record node
progress, and on exit stamps status / latency / cost (summed from
`LLMCallLog` for the run's job_id). Failures are recorded, then re-raised.

`resume_run(...)` re-drives a failed/interrupted run through the same entry
point. The resume contract is: **pipeline nodes are idempotent recomputes of
their inputs**, so re-invoking with the same `thread_id` either resumes from the
LangGraph checkpoint (durable backend) or re-runs cleanly (memory backend) — both
converge to the same result.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.llm_call_log import LLMCallLog

TERMINAL = {"completed", "failed", "halted", "awaiting_review"}


@dataclass
class RunHandle:
    row: AgentRun
    _nodes: list[str] = field(default_factory=list)

    @property
    def run_id(self) -> str:
        return self.row.id

    def node(self, name: str) -> None:
        """Mark the currently executing node (best-effort progress trail)."""
        self._nodes.append(name)
        self.row.current_node = name
        self.row.node_history = list(self._nodes)


async def _run_cost_usd(db: AsyncSession, job_id: str | None) -> float | None:
    if not job_id:
        return None
    total = (
        await db.execute(
            select(func.coalesce(func.sum(LLMCallLog.cost_usd), 0.0)).where(
                LLMCallLog.job_id == job_id
            )
        )
    ).scalar_one()
    return round(float(total or 0.0), 6)


@asynccontextmanager
async def agent_run(
    db: AsyncSession,
    *,
    pipeline: str,
    org_id: str | None,
    job_id: str | None = None,
    attempt: int = 1,
    existing: AgentRun | None = None,
) -> AsyncIterator[RunHandle]:
    """Bookkeep one execution. On success the caller may set
    `handle.row.status` to a non-`running` terminal value (e.g. `halted`,
    `awaiting_review`); otherwise it defaults to `completed`."""
    row = existing or AgentRun(
        org_id=org_id, pipeline=pipeline, job_id=job_id, status="running", attempt=attempt
    )
    if existing is None:
        db.add(row)
    else:
        row.status = "running"
        row.error = None
        row.finished_at = None
        row.attempt = attempt
    await db.flush()

    handle = RunHandle(row=row)
    t0 = time.monotonic()
    try:
        yield handle
    except Exception as exc:
        row.status = "failed"
        row.error = str(exc)[:2000]
        row.latency_ms = round((time.monotonic() - t0) * 1000, 1)
        row.finished_at = datetime.now(UTC)
        row.cost_usd = await _run_cost_usd(db, job_id)
        await db.commit()
        raise
    else:
        if row.status not in TERMINAL:
            row.status = "completed"
        row.latency_ms = round((time.monotonic() - t0) * 1000, 1)
        row.finished_at = datetime.now(UTC)
        row.cost_usd = await _run_cost_usd(db, job_id)
        await db.commit()


async def resume_run(
    db: AsyncSession,
    run_id: str,
    entrypoint: Callable[..., Any],
    **entrypoint_kwargs: Any,
) -> tuple[AgentRun, Any]:
    """Re-drive `run_id` through `entrypoint`. Raises ValueError if the run is
    unknown or already completed."""
    row = await db.get(AgentRun, run_id)
    if row is None:
        raise ValueError(f"agent_run {run_id} not found")
    if row.status == "completed":
        raise ValueError(f"agent_run {run_id} already completed")

    async with agent_run(
        db,
        pipeline=row.pipeline,
        org_id=row.org_id,
        job_id=row.job_id,
        attempt=row.attempt + 1,
        existing=row,
    ) as handle:
        result = await entrypoint(**entrypoint_kwargs)
        if isinstance(result, dict):
            if result.get("halted"):
                handle.row.status = "halted"
            elif result.get("awaiting_review") or result.get("approval_required"):
                handle.row.status = "awaiting_review"
            handle.row.result_ref = {
                k: result.get(k)
                for k in ("halted", "awaiting_review", "approval_required", "stage")
                if k in result
            }
    return row, result
