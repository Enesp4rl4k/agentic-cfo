"""
Server-Sent Events (SSE) infrastructure for real-time agent progress.

Architecture:
  - In-process pub/sub via asyncio.Queue (no extra Redis channel needed)
  - SSEManager holds one Queue per job_id
  - ARQ worker calls `publish_step_event()` after each LangGraph node completes
  - FastAPI endpoint GET /api/v1/stream/{job_id} streams events to the browser

Event format (JSON per SSE data line):
  {"event": "step", "job_id": "...", "step": "pnl", "ok": true,
   "detail": "...", "confidence": 0.95, "ts": "2024-01-01T12:00:00Z"}
  {"event": "done", "job_id": "...", "status": "completed"}
  {"event": "error", "job_id": "...", "message": "..."}

Limitations:
  - Queues are in-process — if you run multiple uvicorn workers (not recommended
    for dev), events published in worker process X won't reach clients on worker Y.
  - For multi-process production, replace Queue with Redis pub/sub.
  - Max 50 concurrent SSE connections by default (configurable).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# Max queued events per job before dropping old ones (ring buffer behaviour)
_MAX_QUEUE_SIZE = 100
# How long to wait for next event before sending a keepalive comment
_KEEPALIVE_INTERVAL = 15  # seconds
# Max seconds a client can stay connected (prevents zombie connections)
_MAX_CONNECTION_SECONDS = 600  # 10 minutes


class SSEManager:
    """
    Singleton that manages per-job event queues for SSE delivery.

    Usage:
      # In agent/worker code (publish side):
      await sse_manager.publish(job_id, event_dict)

      # In FastAPI endpoint (subscribe side):
      async for chunk in sse_manager.subscribe(job_id):
          yield chunk
    """

    def __init__(self) -> None:
        # job_id → list of subscriber queues (one per connected client)
        self._queues: dict[str, list[asyncio.Queue[dict | None]]] = {}

    def _get_or_create_job(self, job_id: str) -> list[asyncio.Queue[dict | None]]:
        if job_id not in self._queues:
            self._queues[job_id] = []
        return self._queues[job_id]

    async def publish(self, job_id: str, event: dict) -> None:
        """
        Publish an event to all clients subscribed to job_id.
        If no clients are connected, the event is silently dropped
        (fire-and-forget — pipeline should not block on SSE delivery).
        """
        queues = self._queues.get(job_id, [])
        if not queues:
            return
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event to make room
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def publish_done(self, job_id: str, status: str) -> None:
        """Signal pipeline completion. Clients will close the connection."""
        await self.publish(job_id, {
            "event": "done",
            "job_id": job_id,
            "status": status,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        # Sentinel None → tells subscribe() generator to stop
        queues = self._queues.get(job_id, [])
        for q in queues:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def subscribe(
        self, job_id: str
    ) -> AsyncGenerator[str, None]:
        """
        Async generator that yields SSE-formatted text chunks.

        Each chunk is a valid SSE message ending with double newline:
          data: {"event": "step", ...}\n\n
          : keepalive\n\n
        """
        q: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        queues = self._get_or_create_job(job_id)
        queues.append(q)
        logger.debug("SSE client subscribed to job=%s (total=%d)", job_id, len(queues))

        try:
            deadline = asyncio.get_event_loop().time() + _MAX_CONNECTION_SECONDS
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    # Max connection time reached — send close signal
                    yield "event: close\ndata: {}\n\n"
                    break

                try:
                    event = await asyncio.wait_for(
                        q.get(),
                        timeout=min(_KEEPALIVE_INTERVAL, remaining),
                    )
                except asyncio.TimeoutError:
                    # Send SSE keepalive comment to prevent proxy timeouts
                    yield ": keepalive\n\n"
                    continue

                if event is None:
                    # Sentinel — pipeline finished
                    break

                yield f"data: {json.dumps(event)}\n\n"

                # If this was a done/error event, close connection
                if event.get("event") in ("done", "error"):
                    break

        finally:
            # Clean up subscriber queue
            try:
                queues.remove(q)
            except ValueError:
                pass
            if not queues:
                self._queues.pop(job_id, None)
            logger.debug("SSE client disconnected from job=%s (remaining=%d)", job_id, len(queues))


# Singleton — imported by API routes and agent/worker code
sse_manager = SSEManager()


# ── Convenience helpers for agent code ────────────────────────────────────────

# Ordered pipeline steps for progress calculation
_PIPELINE_STEPS = [
    "data_ingestion", "pnl", "cashflow", "forecast",
    "budget", "tax", "anomaly", "alert", "report",
]

_completed_steps: dict[str, list[str]] = {}  # job_id → completed step names


def _calc_progress_pct(job_id: str, current_step: str | None = None) -> int:
    """Calculate progress percentage based on completed steps."""
    done = _completed_steps.get(job_id, [])
    total = len(_PIPELINE_STEPS)
    count = sum(1 for s in done if s in _PIPELINE_STEPS)
    # Add half-step credit for currently running step
    if current_step and current_step in _PIPELINE_STEPS and current_step not in done:
        count += 0.5
    return min(100, int((count / total) * 100)) if total > 0 else 0


async def publish_step_event(
    job_id: str,
    step: str,
    ok: bool,
    detail: str | None = None,
    confidence: float | None = None,
    duration_ms: float | None = None,
) -> None:
    """
    Publish a step-completed event. Call this from each LangGraph node.

    Example (inside a node function):
        from app.streaming.sse import publish_step_event
        await publish_step_event(job_id, step="pnl", ok=True, confidence=0.95, duration_ms=142)
    """
    # Track completed steps for progress calculation
    if ok:
        if job_id not in _completed_steps:
            _completed_steps[job_id] = []
        if step not in _completed_steps[job_id]:
            _completed_steps[job_id].append(step)

    progress_pct = _calc_progress_pct(job_id)

    await sse_manager.publish(job_id, {
        "event": "step",
        "job_id": job_id,
        "step": step,
        "ok": ok,
        "detail": detail,
        "confidence": confidence,
        "duration_ms": duration_ms,
        "progress_pct": progress_pct,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


async def publish_agent_start_event(
    job_id: str,
    step: str,
    estimated_duration_s: float | None = None,
) -> None:
    """
    Publish an agent-starting event (before the agent runs).
    Lets the frontend show "agent X is running" immediately.
    """
    progress_pct = _calc_progress_pct(job_id, current_step=step)
    await sse_manager.publish(job_id, {
        "event": "agent_start",
        "job_id": job_id,
        "step": step,
        "current_agent": step,
        "progress_pct": progress_pct,
        "estimated_duration_s": estimated_duration_s,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


async def publish_job_done(job_id: str, status: str = "completed") -> None:
    """Publish job completion. Call from worker after pipeline finishes."""
    await sse_manager.publish_done(job_id, status)


async def publish_job_error(job_id: str, message: str) -> None:
    """Publish job failure. Call from worker on exception."""
    await sse_manager.publish(job_id, {
        "event": "error",
        "job_id": job_id,
        "message": message,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    await sse_manager.publish_done(job_id, "failed")
