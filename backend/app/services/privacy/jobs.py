"""Scheduler jobs of the data-lifecycle work: the erasure executor (and, with the retention policy, the purge).

Registered from `app.scheduler.get_scheduler` through one call, so this module owns its job bodies and the
scheduler file stays out of its way. Both jobs are idempotent and run in one process at a time (`_exclusive`).
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


def register_privacy_jobs(
    scheduler: Any, exclusive: Callable[..., Callable[[], Awaitable[None]]]
) -> None:
    scheduler.add_job(
        exclusive(run_due_erasures, "erasure_executor"), CronTrigger(minute=40),
        id="erasure_executor", replace_existing=True, max_instances=1,
    )
