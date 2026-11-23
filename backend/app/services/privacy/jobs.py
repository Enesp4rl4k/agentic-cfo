"""Jobs of the data-lifecycle work: the erasure executor, the export build and its sweeper, the retention purge.

Registered from `app.scheduler.get_scheduler` through one call, so this module owns its job bodies and the
scheduler file stays out of its way. Every job is idempotent and run in one process at a time (`_exclusive`).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


async def run_due_erasures() -> None:
    """Hourly: run erasure requests whose cooling-off is over, expire stale pending ones."""
    try:
        from app.database import engine, get_session_factory
        from app.services.privacy.erasure_flow import execute_due

        async with get_session_factory(engine())() as db:
            counts = await execute_due(db)
        if any(counts.values()):
            logger.info("erasure executor: %s", counts)
    except Exception as exc:
        logger.error("erasure executor error: %s", exc)


async def run_data_export(ctx: dict[str, Any], export_id: str) -> dict[str, Any]:
    """ARQ maintenance task: build one company export (idempotent: only a `queued` row is claimed)."""
    from app.database import engine, get_session_factory
    from app.services.privacy.export_flow import build_export

    async with get_session_factory(engine())() as db:
        return {"export_id": export_id, "status": await build_export(db, export_id)}


async def run_export_sweeper() -> None:
    """Hourly: build exports the queue did not (a lost message is a delay, never a lost export)."""
    try:
        from app.database import engine, get_session_factory
        from app.services.privacy.export_flow import build_pending

        async with get_session_factory(engine())() as db:
            counts = await build_pending(db)
        if any(counts.values()):
            logger.info("export sweeper: %s", counts)
    except Exception as exc:
        logger.error("export sweeper error: %s", exc)


async def run_retention_job() -> None:
    """Daily: the retention purge. With RETENTION_DRY_RUN (the default) it only counts and records the report."""
    try:
        from app.database import engine, get_session_factory
        from app.services.privacy.retention import run_retention

        async with get_session_factory(engine())() as db:
            report = await run_retention(db)
        logger.info("retention run: dry_run=%s status=%s counts=%s", report["dry_run"], report["status"], report["counts"])
    except Exception as exc:
        logger.error("retention job error: %s", exc)


def register_privacy_jobs(
    scheduler: Any, exclusive: Callable[..., Callable[[], Awaitable[None]]]
) -> None:
    scheduler.add_job(
        exclusive(run_due_erasures, "erasure_executor"), CronTrigger(minute=40),
        id="erasure_executor", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        exclusive(run_export_sweeper, "export_sweeper"), CronTrigger(minute=50),
        id="export_sweeper", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        exclusive(run_retention_job, "retention_purge", ttl=3600), CronTrigger(hour=3, minute=30),
        id="retention_purge", replace_existing=True, max_instances=1,
    )
