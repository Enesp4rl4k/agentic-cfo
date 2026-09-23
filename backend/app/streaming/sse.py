"""
Server-Sent Events (SSE) infrastructure for real-time agent progress.

Architecture (DDIA Ch.3/Ch.11 — processes do not share memory):
  - Events are published to a Redis pub/sub channel `sse:job:{job_id}` — the
    ARQ worker publishes, the API process delivers to browsers. Before this
    bridge the queues were process-local `asyncio.Queue`s and a publish in
    the worker reached nobody: the live-progress feature only ever worked
    for inline (same-process) runs.
  - Each subscriber still owns a local queue; a single listener task feeds
    it from the bus. Same-process publishers also deliver directly (no
    broker round-trip), and every event carries an `eid` so the bus echo of
    an already-delivered event is dropped — delivery is exactly-once per
    subscriber regardless of path.
  - With no broker (dev / tests / outage) behaviour is the old one: local
    direct delivery, fire-and-forget.

Event format (JSON per SSE data line):
  {"event": "step", "job_id": "...", "step": "pnl", "ok": true,
   "detail": "...", "confidence": 0.95, "eid": "...", "ts": "..."}
  {"event": "done", "job_id": "...", "status": "completed"}
  {"event": "error", "job_id": "...", "message": "..."}

Limits (enforced, not promised):
  - Max `settings.sse_max_connections` (default 50) live subscriptions per
    worker process; the endpoint answers 429 beyond it (api/stream.py).
  - `_MAX_QUEUE_SIZE` events buffered per subscriber, drop-oldest beyond.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Max queued events per job before dropping old ones (ring buffer behaviour)
_MAX_QUEUE_SIZE = 100
# How long to wait for next event before sending a keepalive comment
_KEEPALIVE_INTERVAL = 15  # seconds
# Max seconds a client can stay connected (prevents zombie connections)
_MAX_CONNECTION_SECONDS = 600  # 10 minutes
# Dedup memory per subscriber: bus echo of an already-delivered event.
_MAX_SEEN = 512
# Redis channel prefix — the listener pattern-subscribes `{prefix}*`
_CHANNEL_PREFIX = "sse:job:"


@dataclass
class _Subscriber:
    """One connected client: its queue plus the event ids it already got."""

    queue: asyncio.Queue[dict | None]
    seen: deque[str] = field(default_factory=lambda: deque(maxlen=_MAX_SEEN))


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
        # job_id → subscribers (one per connected client)
        self._queues: dict[str, list[_Subscriber]] = {}
        self._listener_task: asyncio.Task[Any] | None = None

    def _get_or_create_job(self, job_id: str) -> list[_Subscriber]:
        if job_id not in self._queues:
            self._queues[job_id] = []
        return self._queues[job_id]

    @property
    def connection_count(self) -> int:
        """Live subscriptions in this process — the endpoint's capacity gate."""
        return sum(len(subs) for subs in self._queues.values())

    # ── Delivery ──────────────────────────────────────────────────────────────

    def _deliver_local(self, job_id: str, event: dict) -> None:
        """Hand the event to this process's subscribers, exactly once each.

        Called by the direct publish path and by the bus listener; the `eid`
        recorded on delivery makes the second call a no-op.
        """
        subs = self._queues.get(job_id, [])
        if not subs:
            return
        eid = event.get("eid")
        for sub in subs:
            if isinstance(eid, str):
                if eid in sub.seen:
                    continue
                sub.seen.append(eid)
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event to make room
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def publish(self, job_id: str, event: dict) -> None:
        """
        Publish an event to all clients subscribed to job_id.

        Local subscribers get it immediately; the bus carries it to every
        other process. Fire-and-forget — the pipeline never blocks on SSE
        delivery: a broker outage degrades to local-only, not to an error.
        """
        if not isinstance(event, dict):
            return
        stamped = dict(event)
        stamped.setdefault("eid", uuid.uuid4().hex[:16])

        self._deliver_local(job_id, stamped)

        from app.core.redis_client import get_redis, mark_unavailable

        client = await get_redis()
        if client is None:
            return
        try:
            await client.publish(
                f"{_CHANNEL_PREFIX}{job_id}",
                json.dumps(stamped, default=str),
            )
        except Exception as exc:
            mark_unavailable(exc)

    async def publish_done(self, job_id: str, status: str) -> None:
        """Signal pipeline completion. Clients will close the connection."""
        await self.publish(job_id, {
            "event": "done",
            "job_id": job_id,
            "status": status,
            "ts": datetime.now(UTC).isoformat(),
        })
        # Sentinel None → tells subscribe() generator to stop (cross-process
        # subscribers close on the `done` event itself).
        for sub in self._queues.get(job_id, []):
            try:
                sub.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        # The progress trail is publisher-side bookkeeping; a job that ended
        # must not leave its entry growing in this dict forever.
        _completed_steps.pop(job_id, None)

    # ── Bus listener (cross-process) ─────────────────────────────────────────

    async def _ensure_listener(self) -> None:
        """Start the single bus listener task (lazily, idempotently)."""
        if self._listener_task is not None and not self._listener_task.done():
            return
        from app.core.redis_client import get_redis

        if await get_redis() is None:
            return
        try:
            self._listener_task = asyncio.create_task(
                self._listener_loop(), name="sse-redis-bus"
            )
        except RuntimeError:
            # No running loop (sync context) — next subscribe retries.
            pass

    async def _listener_loop(self) -> None:
        """Pattern-subscribe the bus and route messages to local queues.

        Reconnects with capped backoff: a broker restart must not kill the
        endpoint's existing streams.
        """
        from app.core.redis_client import get_redis, mark_unavailable

        delay = 1.0
        while True:
            pubsub: Any = None
            try:
                client = await get_redis()
                if client is None:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
                pubsub = client.pubsub()
                await pubsub.psubscribe(f"{_CHANNEL_PREFIX}*")
                delay = 1.0
                async for message in pubsub.listen():
                    if message.get("type") != "pmessage":
                        continue
                    channel = str(message.get("channel", ""))
                    if not channel.startswith(_CHANNEL_PREFIX):
                        continue
                    job_id = channel[len(_CHANNEL_PREFIX):]
                    data = message.get("data")
                    if not isinstance(data, str):
                        continue
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        self._deliver_local(job_id, event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                mark_unavailable(exc)
                logger.warning(
                    "SSE bus listener lost — reconnecting in %.0fs: %s", delay, exc
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass

    # ── Subscribe side ───────────────────────────────────────────────────────

    async def subscribe(
        self, job_id: str
    ) -> AsyncGenerator[str, None]:
        """
        Async generator that yields SSE-formatted text chunks.

        Each chunk is a valid SSE message ending with double newline:
          data: {"event": "step", ...}\n\n
          : keepalive\n\n
        """
        sub = _Subscriber(queue=asyncio.Queue(maxsize=_MAX_QUEUE_SIZE))
        queues = self._get_or_create_job(job_id)
        queues.append(sub)
        await self._ensure_listener()
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
                        sub.queue.get(),
                        timeout=min(_KEEPALIVE_INTERVAL, remaining),
                    )
                except TimeoutError:
                    # Send SSE keepalive comment to prevent proxy timeouts
                    yield ": keepalive\n\n"
                    # A stream that outlived a broker outage still deserves
                    # its bus: retry the listener on every keepalive.
                    await self._ensure_listener()
                    continue

                if event is None:
                    # Sentinel — pipeline finished
                    break

                yield f"data: {json.dumps(event, default=str)}\n\n"

                # If this was a done/error event, close connection
                if event.get("event") in ("done", "error"):
                    break

        finally:
            # Clean up subscriber queue
            try:
                queues.remove(sub)
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
    count: float = sum(1 for s in done if s in _PIPELINE_STEPS)
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
        "ts": datetime.now(UTC).isoformat(),
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
        "ts": datetime.now(UTC).isoformat(),
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
        "ts": datetime.now(UTC).isoformat(),
    })
    await sse_manager.publish_done(job_id, "failed")
