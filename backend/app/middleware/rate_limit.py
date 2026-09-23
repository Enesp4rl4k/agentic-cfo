"""
Rate Limiting Middleware — sliding window, in-memory (per-process).

Sprint M3 upgrade:
  - X-RateLimit-Reset header (Unix timestamp of window reset)
  - Plan-based endpoint multipliers (expensive endpoints cost more)
  - Upgrade prompt URL in 429 response
  - cache_service integration hook (TCMB caching)

Limits are applied per IP address (or user_id when JWT is present).
Uses a sliding window counter backed by a simple dict + deque.

Limits (configurable via environment):
  /api/v1/upload        → 10 requests / minute
  /api/v1/analysis/*    → 20 requests / minute
  /api/v1/auth/login    → 5 requests / minute  (brute-force protection)
  /api/v1/auth/register → 5 requests / minute
  /api/v1/chat          → 30 requests / minute
  Everything else       → 120 requests / minute

Expensive endpoint multipliers (cost more against plan limit):
  /api/v1/analytics/advanced-anomaly  → 0.2x (5x cost)
  /api/v1/analytics/forecast-v2       → 0.2x (5x cost)
  /api/v1/reports/pdf                 → 0.1x (10x cost)
  /api/v1/negotiation/debate          → 0.1x (10x cost)

For multi-process deployments (e.g. gunicorn workers), replace the
in-memory deque with Redis ZADD/ZRANGEBYSCORE pattern.

HTTP 429 response includes:
  Retry-After:             <seconds>
  X-RateLimit-Limit:       <limit>
  X-RateLimit-Remaining:   <remaining>
  X-RateLimit-Reset:       <unix_timestamp>
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


# ── Route-specific limits (requests per window_seconds) ───────────────────────

_ROUTE_LIMITS: list[tuple[str, int, int]] = [
    # (path_prefix, max_requests, window_seconds)
    ("/api/v1/auth/login",    5,   60),
    ("/api/v1/auth/register", 5,   60),
    ("/api/v1/upload",        10,  60),
    ("/api/v1/chat",          30,  60),
    ("/api/v1/analysis",      20,  60),
    ("/api/v1",               120, 60),   # default API limit
]

# Expensive endpoints: count as multiple requests against the per-user limit
# Multiplier < 1.0 means each call consumes 1/multiplier "slots"
_ENDPOINT_COST: dict[str, float] = {
    "/api/v1/analytics/advanced-anomaly": 5.0,   # 5x cost
    "/api/v1/analytics/forecast-v2":      5.0,
    "/api/v1/reports/pdf":                10.0,  # 10x cost
    "/api/v1/negotiation/debate":         10.0,
    "/api/v1/analytics/monte-carlo":      5.0,
}

# Paths that are never rate-limited
_EXEMPT_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}


def _get_limit(path: str) -> tuple[int, int]:
    """Return (max_requests, window_seconds) for the given path."""
    for prefix, limit, window in _ROUTE_LIMITS:
        if path.startswith(prefix):
            return limit, window
    return 120, 60  # fallback


# ── In-memory counter ──────────────────────────────────────────────────────────

# key → deque of timestamps (sliding window)
# For Redis-backed multi-process: replace with redis.zrangebyscore / zadd
_counters: dict[str, deque[float]] = defaultdict(deque)


def _get_client_key(request: Request) -> str:
    """
    Identify client by user_id (from JWT) or IP address.
    User-based limiting is more accurate and prevents shared-IP false positives.
    """
    # Try to extract user_id from JWT (best-effort, no DB hit)
    try:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            from app.services.auth import decode_token
            payload = decode_token(auth[7:])
            uid = payload.get("sub")
            if uid:
                return f"user:{uid}"
    except Exception:
        pass

    # Fall back to IP
    forwarded = request.headers.get("X-Forwarded-For")
    ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else "unknown"
    )
    return f"ip:{ip}"


def _check_rate_limit(key: str, max_requests: int, window: int) -> tuple[bool, int, int]:
    """
    Sliding window check — in-process fallback.

    Returns (allowed, remaining, retry_after_seconds).

    Contract shared with `_check_rate_limit_redis`: `remaining` counts the
    current request against itself, and a denied request appends nothing.
    The two never mix for one key (the Redis path is tried first for the
    whole request), so monotonic (process-local) and wall (broker) clocks
    cannot interleave in one window.
    """
    now = time.monotonic()
    window_start = now - window

    bucket = _counters[key]

    # Evict entries outside the window
    while bucket and bucket[0] < window_start:
        bucket.popleft()

    count = len(bucket)
    remaining = max(0, max_requests - count - 1)

    if count >= max_requests:
        retry_after = int(window - (now - bucket[0])) + 1
        return False, 0, retry_after

    bucket.append(now)
    return True, remaining, 0


# ── Shared (multi-process) sliding window ─────────────────────────────────────

# One atomic script: prune the window, decide, record. A check-then-write
# over the network would let N workers all read "under the limit" before any
# of them writes — the same check-then-act race the DB claim closes, at the
# request layer. Denied requests are NOT recorded (matches the local path).
_REDIS_WINDOW_LUA = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = window
  if oldest[2] then
    retry = math.ceil(window - (now - tonumber(oldest[2])))
  end
  if retry < 1 then retry = 1 end
  return {0, 0, retry}
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window + 1)
return {1, limit - count - 1, 0}
"""


async def _check_rate_limit_redis(
    key: str, max_requests: int, window: int
) -> tuple[bool, int, int] | None:
    """Broker-backed sliding window. Returns None when to fall back locally
    (no broker / disabled / outage) — never raises."""
    import uuid as _uuid

    from app.core.redis_client import get_redis, mark_unavailable

    client = await get_redis()
    if client is None:
        return None
    member = f"{time.time_ns()}:{_uuid.uuid4().hex}"  # unique even same-µs hits
    try:
        raw = await client.eval(
            _REDIS_WINDOW_LUA, 1, f"rl:{key}", window, max_requests,
            time.time(), member,
        )
    except Exception as exc:
        mark_unavailable(exc)
        return None
    try:
        allowed = int(raw[0]) == 1
        remaining = int(raw[1])
        retry_after = int(raw[2])
    except (TypeError, ValueError, IndexError):
        return None
    return allowed, remaining, retry_after


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter middleware."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip exempt paths
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        # Only rate-limit API paths
        if not path.startswith("/api/"):
            return await call_next(request)

        max_requests, window = _get_limit(path)

        # Apply endpoint cost multiplier — expensive endpoints count more
        for prefix, multiplier in _ENDPOINT_COST.items():
            if path.startswith(prefix):
                # Reduce effective limit by multiplier
                max_requests = max(1, int(max_requests / multiplier))
                break

        client_key = f"{path[:20]}:{_get_client_key(request)}"

        # Shared window first (one limit across all worker processes); the
        # in-process deque is the fallback when there is no broker — old
        # behaviour, single-process correct.
        verdict = await _check_rate_limit_redis(client_key, max_requests, window)
        if verdict is None:
            allowed, remaining, retry_after = _check_rate_limit(
                client_key, max_requests, window
            )
        else:
            allowed, remaining, retry_after = verdict

        # Compute reset timestamp
        reset_at = int(time.time()) + window

        if not allowed:
            logger.warning(
                "Rate limit exceeded: key=%s path=%s limit=%d",
                client_key, path, max_requests,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error":        "İstek limitine ulaşıldı. Lütfen kısa bir süre bekleyin.",
                    "retry_after":  retry_after,
                    "upgrade_url":  "/billing",
                    "message":      f"{retry_after} saniye sonra tekrar deneyin.",
                },
                headers={
                    "Retry-After":           str(retry_after),
                    "X-RateLimit-Limit":     str(max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset":     str(reset_at),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"]     = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"]     = str(reset_at)
        return response
