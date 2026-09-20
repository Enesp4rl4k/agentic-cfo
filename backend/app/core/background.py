"""Work that outlives the request that started it.

`asyncio.create_task(...)` with the result thrown away had three problems here:

- The event loop keeps only a weak reference to a task. One nobody holds can be
  garbage-collected before it finishes — an audit row or a whole agent job
  silently never completes.
- An exception in it is reported, at best, as "Task exception was never
  retrieved" when the task is collected — no job, no org, often nothing.
- Handlers passed their own request `db` session into the task. The request
  keeps using that session, and closes it on return, while the task is still
  reading through it; an AsyncSession does not allow concurrent use.

`spawn` holds the task until it ends and logs its failure under its name.
`with_session` gives the work a session of its own.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RUNNING: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, T], *, name: str) -> asyncio.Task[T]:
    """Run `coro` in the background, held until it ends; a failure is logged."""
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _RUNNING.add(task)
    task.add_done_callback(_finished)
    return task


def _finished(task: asyncio.Task[Any]) -> None:
    _RUNNING.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background task %s failed", task.get_name(), exc_info=exc)


async def with_session(work: Callable[[Any], Awaitable[T]]) -> T:
    """Run `work(db)` on a session opened for it, not borrowed from a request."""
    from app.database import session_factory

    async with session_factory()() as db:
        return await work(db)


def running() -> int:
    """How many background tasks are still in flight (for tests and shutdown)."""
    return len(_RUNNING)
