"""
CacheService — Redis-backed multi-namespace cache for Sprint M3.

Namespaces and TTLs
-------------------
analytics:{org_id}:{endpoint_hash}   → 15 minutes
llm:{prompt_hash}                     → 60 minutes
context:{org_id}                      → 5 minutes
benchmark:{sector}                    → 24 hours
tcmb:{date}                           → 6 hours

Features
--------
- get/set with TTL
- One process-wide Redis pool (app.core.redis_client): no TCP handshake
  per cache op — a cache that costs a connection to read is the thing
  it exists to avoid
- invalidate_pattern: Redis SCAN + DEL (safe for large keyspaces)
- make_key: namespace:part1:part2 helper
- llm_cached decorator: auto-cache LLM calls by prompt hash
- Analytics response cache middleware helper
- Dual tier: Redis first, in-memory dict as fallback (and as rescue when
  `volatile-lru` evicts a TTL'd key under memory pressure)

Cache invalidation triggers
---------------------------
- CFO analysis complete → invalidate context:{org_id} + analytics:{org_id}:*
- New connector sync    → invalidate analytics:{org_id}:*

Usage
-----
    cache = get_cache_service()
    value = await cache.get("analytics:org-1:monthly")
    await cache.set("analytics:org-1:monthly", data, ttl=900)
    count = await cache.invalidate_pattern("analytics:org-1:*")

LLM cache decorator:
    @llm_cached(ttl=3600)
    async def my_llm_call(prompt: str) -> str:
        return await openai_call(prompt)
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from app.core.redis_client import get_redis as _shared_get_redis
from app.core.redis_client import mark_unavailable

logger = logging.getLogger(__name__)

# ── TTL constants ──────────────────────────────────────────────────────────────

TTL_ANALYTICS  = 15 * 60      # 15 minutes
TTL_LLM        = 60 * 60      # 60 minutes
TTL_CONTEXT    = 5  * 60      # 5 minutes
TTL_BENCHMARK  = 24 * 60 * 60 # 24 hours
TTL_TCMB       = 6  * 60 * 60 # 6 hours


# ── Redis singleton ────────────────────────────────────────────────────────────

_cache_service_instance: CacheService | None = None


async def _get_redis() -> Any | None:
    """The shared process-wide client, or None when disabled / in cooldown.

    This used to build a fresh `from_url` client per call and close it
    after — every cache read paid a TCP handshake, and `aclose()` on the
    *shared* client (leftover from that design) would have torn down the
    pool the rate limiter and SSE bus are using. The shared gate
    (USE_SQLITE / DISABLE_REDIS) is the same one tests rely on: brokerless
    runs fall back to the memory tier below.
    """
    return await _shared_get_redis()


# ── Key builder ────────────────────────────────────────────────────────────────

def _make_key(namespace: str, *parts: str) -> str:
    return f"cache:{namespace}:{':'.join(str(p) for p in parts)}"


def _hash_prompt(args: tuple, kwargs: dict) -> str:
    """Stable SHA-256 hash of LLM call arguments."""
    payload = json.dumps({"args": list(args), "kwargs": kwargs}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── CacheService ──────────────────────────────────────────────────────────────

class CacheService:
    """
    Dual-tier cache: Redis-backed with local in-memory fallback.
    Falls back gracefully when Redis is unavailable.
    """

    def __init__(self, max_memory_entries: int = 5000) -> None:
        self._memory_cache: dict[str, tuple[float, dict]] = {}
        self._max_memory_entries = max_memory_entries

    def _get_memory(self, key: str) -> dict | None:
        entry = self._memory_cache.get(key)
        if not entry:
            return None
        expires_at, val = entry
        if time.time() > expires_at:
            self._memory_cache.pop(key, None)
            return None
        return val

    def _set_memory(self, key: str, value: dict, ttl: int) -> None:
        if len(self._memory_cache) >= self._max_memory_entries:
            # Evict expired or oldest entry
            now = time.time()
            expired_keys = [k for k, (exp, _) in self._memory_cache.items() if now > exp]
            for k in expired_keys[:100]:
                self._memory_cache.pop(k, None)
            if len(self._memory_cache) >= self._max_memory_entries:
                first_key = next(iter(self._memory_cache))
                self._memory_cache.pop(first_key, None)
        self._memory_cache[key] = (time.time() + ttl, value)

    async def get(self, key: str) -> dict | None:
        """Return cached value or None on miss."""
        try:
            r = await _get_redis()
            if r is not None:
                raw = await r.get(key)
                if raw:
                    return json.loads(raw)
                # Broker miss — including a `volatile-lru` eviction — does
                # not end the lookup: the memory tier answers. Invalidation
                # clears memory first, so this can rescue a live entry but
                # never resurrect a deleted one.
                return self._get_memory(key)
        except Exception as exc:
            logger.debug("CacheService.get (Redis) failed: %s", exc)
            mark_unavailable(exc)

        # In-memory fallback
        return self._get_memory(key)

    async def set(self, key: str, value: dict, ttl: int) -> None:
        """Store value with TTL (seconds). Fire-and-forget."""
        # Always update memory cache as fallback
        self._set_memory(key, value, ttl)
        try:
            r = await _get_redis()
            if r is not None:
                await r.setex(key, ttl, json.dumps(value, default=str))
        except Exception as exc:
            logger.debug("CacheService.set (Redis) failed: %s", exc)
            mark_unavailable(exc)

    async def delete(self, key: str) -> None:
        """Delete a specific key."""
        self._memory_cache.pop(key, None)
        try:
            r = await _get_redis()
            if r is not None:
                await r.delete(key)
        except Exception as exc:
            logger.debug("CacheService.delete failed: %s", exc)
            mark_unavailable(exc)

    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching pattern using SCAN (safe for large keyspaces).
        Returns number of keys deleted.

        Example: await cache.invalidate_pattern("cache:analytics:org-1:*")
        """
        deleted = 0
        # Invalidate in memory
        import fnmatch
        memory_keys = list(self._memory_cache.keys())
        for k in memory_keys:
            if fnmatch.fnmatch(k, pattern):
                self._memory_cache.pop(k, None)
                deleted += 1

        try:
            r = await _get_redis()
            if r is not None:
                async for key in r.scan_iter(match=pattern, count=100):
                    await r.delete(key)
                    deleted += 1
        except Exception as exc:
            logger.debug("CacheService.invalidate_pattern failed: %s", exc)
            mark_unavailable(exc)

        if deleted > 0:
            logger.debug("CacheService: invalidated %d keys matching '%s'", deleted, pattern)
        return deleted

    def make_key(self, namespace: str, *parts: str) -> str:
        return _make_key(namespace, *parts)

    async def get_stats(self, namespace: str | None = None) -> dict[str, Any]:
        """
        Return cache stats for a namespace (admin use only).
        """
        try:
            r = await _get_redis()
            if r is not None:
                pattern = f"cache:{namespace}:*" if namespace else "cache:*"
                key_count = 0
                async for _ in r.scan_iter(match=pattern, count=500):
                    key_count += 1
                    if key_count >= 10000:
                        break

                info = await r.info("memory")

                return {
                    "available": True,
                    "backend": "redis",
                    "namespace": namespace or "all",
                    "key_count": key_count,
                    "memory_used_mb": round(info.get("used_memory", 0) / 1024 / 1024, 1),
                }
        except Exception as exc:
            logger.debug("CacheService.get_stats (Redis) failed: %s", exc)

        return {
            "available": True,
            "backend": "memory",
            "namespace": namespace or "all",
            "key_count": len(self._memory_cache),
            "memory_used_mb": 0.1,
        }

    async def aclose(self) -> None:
        """Close the shared pool (application shutdown).

        Deliberately delegates to `app.core.redis_client`: per-op closes
        were removed above, so this is now the only close — and it must
        close the *shared* client, not a private one nobody else uses.
        """
        from app.core.redis_client import aclose_redis

        await aclose_redis()


# ── Singleton factory ─────────────────────────────────────────────────────────

def get_cache_service() -> CacheService:
    global _cache_service_instance
    if _cache_service_instance is None:
        _cache_service_instance = CacheService()
    return _cache_service_instance


# ── LLM cache decorator ───────────────────────────────────────────────────────

def llm_cached(ttl: int = TTL_LLM):
    """
    Decorator that caches async LLM calls in Redis.
    Cache key: SHA-256 hash of all arguments (first 16 chars).

    Usage:
        @llm_cached(ttl=3600)
        async def analyze_pnl(prompt: str, context: dict) -> str:
            return await openai_call(prompt)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache    = get_cache_service()
            prompt_hash = _hash_prompt(args, kwargs)
            cache_key   = _make_key("llm", func.__name__, prompt_hash)

            # Try cache first
            cached = await cache.get(cache_key)
            if cached is not None:
                logger.debug("LLM cache HIT: %s(%s)", func.__name__, prompt_hash)
                return cached.get("result")

            # Miss — call LLM
            result = await func(*args, **kwargs)

            # Store result
            if result is not None:
                await cache.set(cache_key, {"result": result}, ttl)

            return result

        return wrapper
    return decorator


# ── Analytics response cache helper ──────────────────────────────────────────

async def get_cached_analytics(
    org_id: str,
    endpoint: str,
    query_params: dict,
) -> dict | None:
    """
    Get cached analytics response.
    Cache key: org_id:endpoint:sorted_query_params hash
    """
    cache  = get_cache_service()
    params_str = json.dumps(query_params, sort_keys=True)
    param_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
    key    = _make_key("analytics", org_id, endpoint.replace("/", "_"), param_hash)
    return await cache.get(key)


async def set_cached_analytics(
    org_id: str,
    endpoint: str,
    query_params: dict,
    data: dict,
    ttl: int = TTL_ANALYTICS,
) -> None:
    """Cache an analytics response."""
    cache  = get_cache_service()
    params_str = json.dumps(query_params, sort_keys=True)
    param_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
    key    = _make_key("analytics", org_id, endpoint.replace("/", "_"), param_hash)
    await cache.set(key, data, ttl)


async def invalidate_org_analytics(org_id: str) -> int:
    """
    Invalidate all analytics cache entries for an org.
    Called after CFO analysis completes or connector sync.
    """
    cache = get_cache_service()
    count = await cache.invalidate_pattern(f"cache:analytics:{org_id}:*")
    if count:
        logger.info("Analytics cache invalidated: org=%s keys=%d", org_id, count)
    return count
