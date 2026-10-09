"""
Distributed Lock module using Redis with local asyncio.Lock fallback.

Eliminates race conditions and duplicate executions:
  - Double analysis runs when a user clicks twice
  - Concurrent data ingestion updates on the same organization
  - Webhook delivery double processing

Guarantees:
  - Mutex (mutual exclusion): only one holder per resource
  - Deadlock-free: automatic expiration via TTL
  - Safe release: atomic Lua script ensures workers only release their own lock
  - Fallback: in-memory asyncio locks when Redis is unavailable
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

# Atomic release script: only delete the key if value matches our token
_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

# Fallback local asyncio locks per resource key
_local_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_local_dict_lock = asyncio.Lock()


class LockAcquisitionError(Exception):
    """Raised when a lock cannot be acquired within the timeout."""


@asynccontextmanager
async def distributed_lock(
    resource_key: str,
    *,
    ttl_seconds: int = 60,
    timeout_seconds: float = 5.0,
    retry_delay_seconds: float = 0.1,
) -> AsyncIterator[bool]:
    """
    Acquire a distributed lock on `resource_key`.

    Usage:
        async with distributed_lock("analysis:job-123", ttl_seconds=300):
            # Critical section — only one worker runs this at a time
            await run_pipeline()

    Raises:
        LockAcquisitionError: If the lock cannot be acquired within timeout_seconds.
    """
    key = f"lock:{resource_key}"
    token = str(uuid.uuid4())
    redis = await get_redis()

    if redis is not None:
        # ── Redis distributed lock ────────────────────────────────────────────
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        acquired = False

        while loop.time() < deadline:
            try:
                # SET key token NX EX ttl
                ok = await redis.set(key, token, ex=ttl_seconds, nx=True)
                if ok:
                    acquired = True
                    break
            except Exception as exc:
                logger.warning("Redis lock error on %s: %s — falling back to local lock", key, exc)
                break

            await asyncio.sleep(retry_delay_seconds)

        if not acquired and redis is not None:
            # Check if redis was working and we genuinely timed out
            try:
                existing = await redis.get(key)
                if existing:
                    logger.info("Distributed lock conflict on %s (held by another worker)", key)
                    raise LockAcquisitionError(f"Could not acquire lock for '{resource_key}' within {timeout_seconds}s")
            except LockAcquisitionError:
                raise
            except Exception:
                pass  # Fall through to local lock if redis fails

        if acquired:
            try:
                logger.debug("Acquired distributed lock: %s (token=%s)", key, token)
                yield True
            finally:
                try:
                    await redis.eval(_RELEASE_LUA, 1, key, token)
                    logger.debug("Released distributed lock: %s", key)
                except Exception as exc:
                    logger.warning("Failed to release Redis lock %s: %s", key, exc)
            return

    # ── Local asyncio.Lock fallback (Redis unavailable / testing) ─────────────
    async with _local_dict_lock:
        lock = _local_locks[resource_key]

    try:
        await asyncio.wait_for(lock.acquire(), timeout=timeout_seconds)
    except TimeoutError:
        logger.info("Local lock timeout on %s", resource_key)
        raise LockAcquisitionError(f"Could not acquire local lock for '{resource_key}' within {timeout_seconds}s")

    try:
        logger.debug("Acquired local lock: %s", resource_key)
        yield True
    finally:
        lock.release()
        logger.debug("Released local lock: %s", resource_key)
