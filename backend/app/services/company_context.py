"""
CompanyContext Service — Unified org-level analysis state.

Architecture:
  - Redis cache (30 min TTL) for fast reads by all agents
  - SQLite/PostgreSQL snapshot for persistence across restarts
  - Falls back gracefully when Redis is unavailable

Every agent result is stored here so the CEO synthesis and
cross-domain correlator always have up-to-date signals.

Usage:
    ctx = await get_company_context(org_id, db)
    ctx.last_cfo_result = {...}
    await save_company_context(ctx, db)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Optional Redis import — falls back silently if not available
try:
    import redis.asyncio as aioredis  # type: ignore[import]
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    logger.debug("redis package not installed — CompanyContext will use DB-only mode")

_redis_client: Any = None
CONTEXT_TTL_SECONDS = 1800  # 30 minutes


async def _get_redis() -> Any | None:
    """Return async Redis client, or None if unavailable."""
    if not _REDIS_AVAILABLE:
        return None
    global _redis_client
    if _redis_client is None:
        try:
            from app.config import get_settings
            settings = get_settings()
            _redis_client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
            )
            await _redis_client.ping()
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — using DB-only context", exc)
            _redis_client = None
    return _redis_client


def _redis_key(org_id: str) -> str:
    return f"company_context:{org_id}"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class CompanyContext:
    """
    Org-level unified state shared by all agents.

    Each agent writes its last result here; the CEO synthesis
    and cross-domain correlator read from here.
    """
    org_id: str

    # Active job tracking
    active_cfo_job_id: str | None = None
    active_cto_job_id: str | None = None
    active_cmo_job_id: str | None = None
    active_coo_job_id: str | None = None
    active_chro_job_id: str | None = None

    # Company metadata
    company_name: str | None = None
    reporting_period: str | None = None

    # Last agent results (JSON-serialisable dicts)
    last_cfo_result:        dict[str, Any] | None = field(default=None)
    last_cto_result:        dict[str, Any] | None = field(default=None)
    last_cmo_result:        dict[str, Any] | None = field(default=None)
    last_coo_result:        dict[str, Any] | None = field(default=None)
    last_chro_result:       dict[str, Any] | None = field(default=None)
    last_risk_result:       dict[str, Any] | None = field(default=None)
    last_audit_result:      dict[str, Any] | None = field(default=None)
    last_compliance_result: dict[str, Any] | None = field(default=None)
    last_ceo_result:        dict[str, Any] | None = field(default=None)

    # Timestamps (ISO strings)
    created_at:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # ── Helpers ───────────────────────────────────────────────────────────────

    def update_agent_result(self, agent: str, result: dict[str, Any]) -> None:
        """Write agent result and touch updated_at."""
        mapping = {
            "cfo":        "last_cfo_result",
            "cto":        "last_cto_result",
            "cmo":        "last_cmo_result",
            "coo":        "last_coo_result",
            "chro":       "last_chro_result",
            "risk":       "last_risk_result",
            "audit":      "last_audit_result",
            "compliance": "last_compliance_result",
            "ceo":        "last_ceo_result",
        }
        attr = mapping.get(agent.lower())
        if attr:
            setattr(self, attr, result)
            self.updated_at = datetime.now(timezone.utc).isoformat()
        else:
            logger.warning("update_agent_result: unknown agent '%s'", agent)

    def set_active_job(self, agent: str, job_id: str) -> None:
        """Track the currently running job for an agent."""
        mapping = {
            "cfo":  "active_cfo_job_id",
            "cto":  "active_cto_job_id",
            "cmo":  "active_cmo_job_id",
            "coo":  "active_coo_job_id",
            "chro": "active_chro_job_id",
        }
        attr = mapping.get(agent.lower())
        if attr:
            setattr(self, attr, job_id)

    def has_required_data(self, agent: str) -> bool:
        """
        Returns True if the context contains enough data to run the given agent.
        Used by auto_chain to decide whether to enqueue follow-on agents.
        """
        requirements: dict[str, list[str]] = {
            "risk":       ["last_cfo_result"],
            "audit":      ["last_cfo_result"],
            "compliance": ["last_cfo_result"],
            "ceo":        ["last_cfo_result"],
        }
        required_fields = requirements.get(agent.lower(), [])
        return all(getattr(self, f, None) is not None for f in required_fields)

    def agent_summary(self) -> dict[str, Any]:
        """Return a lightweight summary of which agents have run."""
        agents = ["cfo", "cto", "cmo", "coo", "chro", "risk", "audit", "compliance", "ceo"]
        return {
            a: {
                "has_result": getattr(self, f"last_{a}_result", None) is not None,
                "updated_at": self.updated_at,
            }
            for a in agents
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompanyContext":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


# ── Storage helpers ───────────────────────────────────────────────────────────

async def get_company_context(
    org_id: str,
    db: Any = None,  # AsyncSession | None
) -> CompanyContext:
    """
    Load CompanyContext for the given org.
    Priority: Redis → DB snapshot → new empty context.
    """
    # 1. Try Redis
    redis = await _get_redis()
    if redis:
        try:
            raw = await redis.get(_redis_key(org_id))
            if raw:
                return CompanyContext.from_dict(json.loads(raw))
        except Exception as exc:
            logger.warning("Redis read failed: %s", exc)

    # 2. Try DB snapshot
    if db is not None:
        try:
            from app.models.company_context import CompanyContextSnapshot
            from sqlalchemy import select
            result = await db.execute(
                select(CompanyContextSnapshot).where(
                    CompanyContextSnapshot.org_id == org_id
                )
            )
            snapshot = result.scalar_one_or_none()
            if snapshot:
                ctx = CompanyContext.from_dict(json.loads(snapshot.context_json))
                # Warm Redis cache
                if redis:
                    try:
                        await redis.setex(
                            _redis_key(org_id),
                            CONTEXT_TTL_SECONDS,
                            json.dumps(ctx.to_dict()),
                        )
                    except Exception:
                        pass
                return ctx
        except Exception as exc:
            logger.warning("DB context read failed: %s", exc)

    # 3. Return empty context
    logger.info("No context found for org=%s — returning empty", org_id)
    return CompanyContext(org_id=org_id)


# ── Payload size guard constants ──────────────────────────────────────────────

# Each agent result is trimmed if the full context exceeds this threshold.
# Prevents unbounded growth when many agents accumulate large result dicts.
_MAX_CONTEXT_BYTES      = 512 * 1024   # 512 KB — warn threshold
_CRITICAL_CONTEXT_BYTES = 2 * 1024 * 1024  # 2 MB — trim threshold

# Keys trimmed when context exceeds critical size (keep metadata, drop large payloads)
_TRIM_FIELDS: list[str] = [
    "last_cfo_result",
    "last_cto_result",
    "last_cmo_result",
    "last_coo_result",
    "last_chro_result",
    "last_risk_result",
    "last_audit_result",
    "last_compliance_result",
    "last_ceo_result",
]

# Maximum characters kept per trimmed agent result (keeps metadata, drops large arrays)
_AGENT_RESULT_MAX_CHARS = 20_000


def _trim_context_payload(data: dict[str, Any]) -> dict[str, Any]:
    """
    Trim large agent results to prevent unbounded payload growth.

    Strategy: keep all metadata fields intact; for each agent result,
    stringify and truncate if it exceeds _AGENT_RESULT_MAX_CHARS.
    This preserves scalar metrics while dropping large arrays (transactions, etc.).
    """
    trimmed = dict(data)
    for field_name in _TRIM_FIELDS:
        value = trimmed.get(field_name)
        if value is None:
            continue
        serialized = json.dumps(value)
        if len(serialized) > _AGENT_RESULT_MAX_CHARS:
            # Keep top-level scalar keys, drop nested arrays/large objects
            if isinstance(value, dict):
                lightweight: dict[str, Any] = {}
                for k, v in value.items():
                    if isinstance(v, (str, int, float, bool)) or v is None:
                        lightweight[k] = v
                    elif isinstance(v, dict) and len(json.dumps(v)) < 2000:
                        lightweight[k] = v
                    else:
                        lightweight[k] = f"[trimmed — {len(json.dumps(v))} chars]"
                trimmed[field_name] = lightweight
                logger.debug(
                    "Context payload: trimmed %s from %d to %d chars",
                    field_name, len(serialized), len(json.dumps(lightweight))
                )
    return trimmed


async def save_company_context(
    ctx: CompanyContext,
    db: Any = None,  # AsyncSession | None
) -> None:
    """
    Persist CompanyContext to Redis (with TTL) and DB snapshot.

    Includes payload size guard:
    - Warns when context exceeds 512 KB (unbounded growth risk)
    - Trims large agent result fields when context exceeds 2 MB
    """
    ctx.updated_at = datetime.now(timezone.utc).isoformat()
    raw_data = ctx.to_dict()
    raw_payload = json.dumps(raw_data)
    raw_size = len(raw_payload.encode("utf-8"))

    # ── Payload size guard ────────────────────────────────────────────────────
    if raw_size >= _CRITICAL_CONTEXT_BYTES:
        logger.warning(
            "CompanyContext payload for org=%s is %d bytes (>2 MB) — trimming large fields",
            ctx.org_id, raw_size,
        )
        trimmed_data = _trim_context_payload(raw_data)
        payload = json.dumps(trimmed_data)
        trimmed_size = len(payload.encode("utf-8"))
        logger.info(
            "CompanyContext trimmed: %d → %d bytes for org=%s",
            raw_size, trimmed_size, ctx.org_id,
        )
    elif raw_size >= _MAX_CONTEXT_BYTES:
        logger.warning(
            "CompanyContext payload for org=%s is %d bytes (>512 KB) — consider cleanup",
            ctx.org_id, raw_size,
        )
        payload = raw_payload
    else:
        payload = raw_payload

    # 1. Write to Redis
    redis = await _get_redis()
    if redis:
        try:
            await redis.setex(_redis_key(ctx.org_id), CONTEXT_TTL_SECONDS, payload)
        except Exception as exc:
            logger.warning("Redis write failed: %s", exc)

    # 2. Write to DB (upsert)
    if db is not None:
        try:
            from app.models.company_context import CompanyContextSnapshot
            from sqlalchemy import select
            result = await db.execute(
                select(CompanyContextSnapshot).where(
                    CompanyContextSnapshot.org_id == ctx.org_id
                )
            )
            snapshot = result.scalar_one_or_none()
            if snapshot:
                snapshot.context_json = payload
                snapshot.updated_at = datetime.now(timezone.utc)
            else:
                snapshot = CompanyContextSnapshot(
                    org_id=ctx.org_id,
                    context_json=payload,
                )
                db.add(snapshot)
            await db.commit()
        except Exception as exc:
            logger.warning("DB context write failed: %s", exc)


async def invalidate_company_context(org_id: str, db: Any = None) -> None:
    """Delete context from Redis and DB (full reset for this org)."""
    redis = await _get_redis()
    if redis:
        try:
            await redis.delete(_redis_key(org_id))
        except Exception:
            pass

    if db is not None:
        try:
            from app.models.company_context import CompanyContextSnapshot
            from sqlalchemy import select
            result = await db.execute(
                select(CompanyContextSnapshot).where(
                    CompanyContextSnapshot.org_id == org_id
                )
            )
            snapshot = result.scalar_one_or_none()
            if snapshot:
                await db.delete(snapshot)
                await db.commit()
        except Exception as exc:
            logger.warning("DB context delete failed: %s", exc)


# ── Kernel result cache ───────────────────────────────────────────────────────
# DDIA principle: "hot path" kernel reads are cached separately from the
# full CompanyContext, with a shorter TTL (5 min) since kernels are
# computed from CFO data which changes less frequently than real-time state.

KERNEL_CACHE_TTL = 300  # 5 minutes


def _kernel_key(org_id: str, kernel: str) -> str:
    return f"kernel_result:{org_id}:{kernel}"


async def cache_kernel_result(org_id: str, kernel: str, result: dict) -> None:
    """Cache a kernel computation result (CTO/CMO/CHRO/COO/Audit/Compliance)."""
    redis = await _get_redis()
    if not redis:
        return
    try:
        await redis.setex(
            _kernel_key(org_id, kernel),
            KERNEL_CACHE_TTL,
            json.dumps(result),
        )
        logger.debug("Cached kernel=%s for org=%s (TTL=%ds)", kernel, org_id, KERNEL_CACHE_TTL)
    except Exception as exc:
        logger.debug("Kernel cache write failed: %s", exc)


async def get_cached_kernel_result(org_id: str, kernel: str) -> dict | None:
    """
    Read a cached kernel result.
    Returns None if not cached or Redis unavailable.
    """
    redis = await _get_redis()
    if not redis:
        return None
    try:
        raw = await redis.get(_kernel_key(org_id, kernel))
        if raw:
            logger.debug("Cache HIT kernel=%s org=%s", kernel, org_id)
            return json.loads(raw)
    except Exception as exc:
        logger.debug("Kernel cache read failed: %s", exc)
    return None


async def invalidate_kernel_cache(org_id: str, kernel: str | None = None) -> None:
    """
    Invalidate kernel cache for an org.
    If kernel=None, invalidates all kernels for that org.
    """
    redis = await _get_redis()
    if not redis:
        return
    try:
        if kernel:
            await redis.delete(_kernel_key(org_id, kernel))
        else:
            # Delete all kernel keys for this org using SCAN
            pattern = f"kernel_result:{org_id}:*"
            async for key in redis.scan_iter(pattern):
                await redis.delete(key)
    except Exception as exc:
        logger.debug("Kernel cache invalidation failed: %s", exc)


async def get_cache_stats(org_id: str) -> dict:
    """
    Return cache diagnostics for an org.
    Useful for /context/cache-stats endpoint.
    """
    redis = await _get_redis()
    if not redis:
        return {"redis_available": False, "context_cached": False, "kernels_cached": []}

    try:
        context_ttl = await redis.ttl(_redis_key(org_id))
        context_cached = context_ttl > 0

        kernels_cached = []
        pattern = f"kernel_result:{org_id}:*"
        async for key in redis.scan_iter(pattern):
            ttl = await redis.ttl(key)
            kernel_name = key.split(":")[-1]
            kernels_cached.append({"kernel": kernel_name, "ttl_seconds": ttl})

        return {
            "redis_available": True,
            "context_cached": context_cached,
            "context_ttl_seconds": max(0, context_ttl),
            "kernels_cached": kernels_cached,
        }
    except Exception as exc:
        logger.warning("Cache stats error: %s", exc)
        return {"redis_available": False, "error": str(exc)}


# ── CompanyContextService singleton (for WebSocket/streaming contexts) ─────────

class CompanyContextService:
    """
    Thin service wrapper that provides convenient async methods
    for get/save/invalidate without requiring db injection at each call.

    Designed for use in WebSocket handlers and background tasks where
    passing a db session on every call is inconvenient.
    """

    async def get_context(self, org_id: str, db: Any = None) -> dict:
        ctx = await get_company_context(org_id, db)
        return ctx.to_dict()

    async def update_agent(self, org_id: str, agent: str, result: dict, db: Any = None) -> None:
        ctx = await get_company_context(org_id, db)
        ctx.update_agent_result(agent, result)
        await save_company_context(ctx, db)
        # Also cache the kernel result separately
        await cache_kernel_result(org_id, agent, result)

    async def invalidate(self, org_id: str) -> None:
        await invalidate_company_context(org_id)
        await invalidate_kernel_cache(org_id)

    async def cache_stats(self, org_id: str) -> dict:
        return await get_cache_stats(org_id)


_ctx_service: CompanyContextService | None = None


def get_company_context_service() -> CompanyContextService:
    """Global singleton for CompanyContextService."""
    global _ctx_service
    if _ctx_service is None:
        _ctx_service = CompanyContextService()
    return _ctx_service
