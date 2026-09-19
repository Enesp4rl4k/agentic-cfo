"""A trailing semantic rebuild replaced by a newer one ends cancelled, not completed.

The delayed task caught CancelledError and returned, so a superseded rebuild
looked like one that had finished normally — and cancellation, which asyncio's
timeouts and task groups rely on, stopped at it. Found by SonarCloud (S7497).
"""
from __future__ import annotations

import asyncio

import app.services.context_persist as context_persist
import app.worker as worker


async def test_a_superseded_trailing_rebuild_is_cancelled(monkeypatch):
    async def no_arq(org_id, defer_by=None):
        return False

    monkeypatch.setattr(worker, "enqueue_semantic_rebuild_job", no_arq)
    context_persist._trailing_tasks.clear()

    await context_persist.enqueue_trailing_semantic_rebuild("org-cancel-test", delay_sec=30)
    first = context_persist._trailing_tasks["org-cancel-test"]
    await asyncio.sleep(0)  # let it reach the sleep

    await context_persist.enqueue_trailing_semantic_rebuild("org-cancel-test", delay_sec=30)
    second = context_persist._trailing_tasks["org-cancel-test"]
    await asyncio.sleep(0)

    try:
        assert first is not second
        assert first.cancelled()
    finally:
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        context_persist._trailing_tasks.clear()
