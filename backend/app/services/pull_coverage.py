"""What a fetch of ours received, read back from the job's own metadata, never from file content.

`feed.FeedResult.feed_meta()` is written onto a job by `ekle._finansal_ekle` (and the scheduled sync's `_create_job`),
only for a job made by our fetch code. This module reads it and turns it into the same `statement_period` structure a
statement's header gives (`stated_period`), plus `pulled`, which `coverage.apply_period` trusts: a completed pull
states the window it received, a partial one only the span it did. A file's text can never produce `pulled`
(`stated_period` has no such marker), and no route writes a job's metadata from a client's input.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def period_from_feed(meta: Any) -> dict[str, Any] | None:
    """{"start", "end", "pulled"} from a job's `result_metadata`, or None when the job is not a feed's (or says nothing)."""
    feed = meta.get("feed") if isinstance(meta, dict) else None
    cov = feed.get("pull_coverage") if isinstance(feed, dict) and isinstance(feed.get("source"), str) else None
    if not isinstance(cov, dict):
        return None
    try:
        start, end = date.fromisoformat(str(cov["covered_from"])[:10]), date.fromisoformat(str(cov["covered_until"])[:10])
    except (KeyError, ValueError):
        return None
    if start > end or not isinstance(cov.get("complete"), bool):
        return None
    return {"start": start.isoformat(), "end": end.isoformat(), "pulled": "complete" if cov["complete"] else "partial"}


async def attach_pull(patch: dict[str, Any], state: Any) -> dict[str, Any]:
    """The ingestion patch with the pull's coverage as `statement_period`, for a job made by a feed; unchanged otherwise.

    A text-derived period never carries `pulled` (stripped here as well, defence in depth)."""
    period = patch.get("statement_period")
    if isinstance(period, dict) and "pulled" in period:
        patch = {**patch, "statement_period": {k: v for k, v in period.items() if k != "pulled"}}
    job_id = state.get("job_id")
    if not job_id:
        return patch
    from app.database import session_factory
    from app.models.analysis_job import AnalysisJob

    try:
        async with session_factory()() as db:
            job = await db.get(AnalysisJob, str(job_id))
    except Exception:          # no metadata to read: the pull claims nothing, and the file keeps its own rules
        return patch
    found = period_from_feed(job.result_metadata) if job is not None else None
    if found is None:
        return patch
    rows = [r.get("transaction_date") for r in [*(patch.get("transactions") or []), *(patch.get("held_transactions") or [])]]
    days = sorted(str(d)[:10] for d in rows if d)
    if days and (days[0] < found["start"] or days[-1] > found["end"]):
        return patch                      # rows outside what the pull says it received: the claim is not used
    return {**patch, "statement_period": found}
