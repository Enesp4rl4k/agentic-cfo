"""A timestamp in Redis that says "this loop ran lately", for `/api/v1/ready`.

The scheduler lives in the worker process; the API cannot ask it whether it is alive. The outbox pass
runs every five minutes from the scheduler (and again whenever a request writes an immediate mail), so
the age of its last beat answers "is anything delivering the outbox". Never raises: no broker, no beat.
"""

from __future__ import annotations

import time

KEY_PREFIX = "ops:heartbeat:"
TTL_SECONDS = 3600


async def beat(name: str) -> None:
    """Record that `name` ran now. Best effort: a broker outage must not fail the caller."""
    from app.core.redis_client import get_redis, mark_unavailable

    client = await get_redis()
    if client is None:
        return
    try:
        await client.set(f"{KEY_PREFIX}{name}", str(int(time.time())), ex=TTL_SECONDS)
    except Exception as exc:
        mark_unavailable(exc)


async def age_seconds(client: object, name: str) -> float | None:
    """Seconds since `name` last beat, or None when it never did (or the key expired)."""
    raw = await client.get(f"{KEY_PREFIX}{name}")  # type: ignore[attr-defined]
    if raw is None:
        return None
    return max(0.0, time.time() - float(raw))
