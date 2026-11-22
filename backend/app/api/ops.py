"""Operations endpoints: what is running (`/version`) and whether it can serve (`/ready`).

`/health` (liveness) says the process answers. `/ready` says it is fit to take traffic and whether the
machinery around it works. Two kinds of check, because they call for different reactions:

* required (database, schema at the code's head, Redis in production): a failure answers 503, so a
  proxy or `docker compose` stops sending requests to an API that would fail them.
* advisory (worker alive, scheduler/outbox pass recent, outbox backlog, failed mail): a failure answers
  200 with `status: degraded`. Taking the API out of rotation because the worker is down would turn a
  background fault into an outage; monitoring alerts on `degraded` instead.

Neither endpoint takes a user and neither returns an exception text, a host name or a count that is
per organisation: only fixed codes and platform-wide numbers.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import heartbeat
from app.core.preflight import app_env, code_heads, is_production, schema_state
from app.core.redis_client import redis_enabled
from app.database import get_db
from app.models.outbox_message import FAILED, PENDING, OutboxMessage

router = APIRouter()

CHECK_TIMEOUT_SECONDS = 3.0
# An outbox pass runs every five minutes; two missed passes is a stalled sender.
OUTBOX_PASS_MAX_AGE_SECONDS = 600
# A pending message older than this was due at the sender's last pass at the latest.
OUTBOX_PENDING_MAX_AGE = timedelta(minutes=15)
OUTBOX_FAILED_WINDOW = timedelta(hours=24)
_SCHEMA_TTL_SECONDS = 30.0

_schema_cache: tuple[float, dict[str, Any]] | None = None


def _reset_cache() -> None:
    global _schema_cache
    _schema_cache = None


def _check(ok: bool | None, *, required: bool, code: str, **extra: Any) -> dict[str, Any]:
    return {"ok": ok, "required": required, "code": code, **extra}


async def _bounded(awaitable: Awaitable[dict[str, Any]], *, required: bool, name: str) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(awaitable, CHECK_TIMEOUT_SECONDS)
    except TimeoutError:
        return _check(False, required=required, code=f"{name}_timeout")
    except Exception:
        return _check(False, required=required, code=f"{name}_error")


async def _database(db: AsyncSession) -> dict[str, Any]:
    await db.execute(text("SELECT 1"))
    return _check(True, required=True, code="ok")


async def _migrations(db: AsyncSession) -> dict[str, Any]:
    global _schema_cache
    now = time.monotonic()
    if _schema_cache is not None and now - _schema_cache[0] < _SCHEMA_TTL_SECONDS:
        return _schema_cache[1]
    state = await schema_state(await db.connection())
    if state.status == "skipped":
        result = _check(True, required=True, code="skipped_sqlite")
    else:
        result = _check(
            state.at_head, required=True, code=state.status, current=state.current, head=list(state.heads)
        )
    _schema_cache = (now, result)
    return result


def _redis_client() -> Any:
    import redis.asyncio as aioredis

    return aioredis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=CHECK_TIMEOUT_SECONDS - 1,
        socket_timeout=CHECK_TIMEOUT_SECONDS - 1,
    )


async def _broker_checks(production: bool) -> dict[str, dict[str, Any]]:
    """Redis ping, the two ARQ workers' health keys, and the outbox pass heartbeat, on one connection."""
    if not redis_enabled():
        off = _check(None, required=False, code="redis_disabled")
        return {"redis": off, "worker": off, "scheduler": off}
    client = _redis_client()
    try:
        try:
            await client.ping()
        except Exception:
            down = _check(False, required=True, code="unreachable")
            skipped = _check(None, required=False, code="redis_unreachable")
            return {"redis": down, "worker": skipped, "scheduler": skipped}
        from arq.constants import health_check_key_suffix

        settings = get_settings()
        keys = (settings.arq_analysis_queue_name, settings.arq_maintenance_queue_name)
        alive = [bool(await client.exists(f"{queue}{health_check_key_suffix}")) for queue in keys]
        age = await heartbeat.age_seconds(client, "outbox_pass")
        fresh = age is not None and age <= OUTBOX_PASS_MAX_AGE_SECONDS
        return {
            "redis": _check(True, required=production, code="ok"),
            "worker": _check(
                all(alive), required=False, code="ok" if all(alive) else "worker_not_seen",
                analysis=alive[0], maintenance=alive[1],
            ),
            "scheduler": _check(
                fresh, required=False, code="ok" if fresh else "no_recent_outbox_pass",
                last_pass_seconds_ago=None if age is None else int(age),
            ),
        }
    finally:
        await client.aclose()


async def _outbox(db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    stuck = (
        await db.execute(
            select(func.count()).select_from(OutboxMessage).where(
                OutboxMessage.status == PENDING, OutboxMessage.created_at < now - OUTBOX_PENDING_MAX_AGE
            )
        )
    ).scalar_one()
    failed = (
        await db.execute(
            select(func.count()).select_from(OutboxMessage).where(
                OutboxMessage.status == FAILED, OutboxMessage.created_at > now - OUTBOX_FAILED_WINDOW
            )
        )
    ).scalar_one()
    ok = stuck == 0 and failed == 0
    return _check(ok, required=False, code="ok" if ok else "backlog_or_failures", pending_overdue=stuck, failed_24h=failed)


def summarise(checks: dict[str, dict[str, Any]]) -> tuple[str, int]:
    """(`ready` | `degraded` | `not_ready`, HTTP status). Only a failed required check is a 503."""
    if any(c["ok"] is False and c["required"] for c in checks.values()):
        return "not_ready", 503
    if any(c["ok"] is False for c in checks.values()):
        return "degraded", 200
    return "ready", 200


@router.get("/ready")
async def ready(db: Annotated[AsyncSession, Depends(get_db)]) -> JSONResponse:
    production = is_production(get_settings())
    checks: dict[str, dict[str, Any]] = {
        "database": await _bounded(_database(db), required=True, name="database"),
    }
    if checks["database"]["ok"]:
        checks["migrations"] = await _bounded(_migrations(db), required=True, name="migrations")
        checks["outbox"] = await _bounded(_outbox(db), required=False, name="outbox")
    else:
        checks["migrations"] = _check(None, required=True, code="database_down")
        checks["outbox"] = _check(None, required=False, code="database_down")
    try:
        checks.update(await asyncio.wait_for(_broker_checks(production), CHECK_TIMEOUT_SECONDS + 1))
    except Exception:
        checks["redis"] = _check(False, required=production, code="redis_error")
    status, http = summarise(checks)
    return JSONResponse(status_code=http, content={"data": {"status": status, "checks": checks}, "error": None})


@router.get("/version")
async def version() -> dict[str, Any]:
    """What is running: the commit the image was built from, and the migration head it expects.

    The commit comes from GIT_SHA (a build arg in backend/Dockerfile) or, on the compose stack, from
    IMAGE_TAG. "unknown" says a build that was not told, never a guess."""
    commit = os.environ.get("GIT_SHA") or os.environ.get("IMAGE_TAG") or "unknown"
    return {
        "data": {
            "commit": commit,
            "built_at": os.environ.get("BUILD_TIME") or None,
            "schema_head": list(code_heads()),
            "environment": app_env() or ("production" if is_production(get_settings()) else "development"),
        },
        "error": None,
    }
