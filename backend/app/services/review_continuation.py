"""Onaydan sonrası — kaybolmayan devam.

Approving a held analysis runs what the confidence gate held back: company
context, the command-center snapshot, the auto-chain. That ran as an
in-process task (`spawn`), so a restart between the approval's commit and the
task's end lost it with nothing to say so — the job read "completed" and the
command center never heard of it.

Now the approval writes `review.devam = "bekliyor"` in the same UPDATE that
completes the job. The continuation runs on the maintenance queue under a
per-job ARQ id (a second dispatch is a no-op), falls back to an in-process run
when no broker answers, and marks `devam = "tamam"` when it finishes. The
stuck-job reaper re-dispatches any approval still "bekliyor" past a grace
period, so a crash anywhere in between is recovered, broker or not.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

BEKLIYOR = "bekliyor"
TAMAM = "tamam"
# Long enough for a queued run to start and finish on a busy worker, short
# enough that a lost one is recovered by the next reaper pass (every 10 min).
YENIDEN_DENEME_SURESI = timedelta(minutes=15)


def devam_durumu(meta: dict[str, Any] | None) -> str | None:
    return ((meta or {}).get("review") or {}).get("devam")


async def devam_et(job_id: str) -> dict[str, Any]:
    """Run the held continuation for an approved job, once. Idempotent."""
    from sqlalchemy import update

    from app.database import session_factory
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import continue_after_completion, saved_result

    async with session_factory()() as db:
        job = await db.get(AnalysisJob, job_id)
        if job is None or job.status != JobStatus.COMPLETED or not job.org_id:
            return {"ok": False, "neden": "iş yok ya da tamamlanmamış"}
        if devam_durumu(job.result_metadata) == TAMAM:
            return {"ok": True, "neden": "zaten tamam"}

        await continue_after_completion(job_id, str(job.org_id), await saved_result(job_id, db), db)

        meta = dict(job.result_metadata or {})
        review = dict(meta.get("review") or {})
        review.update(devam=TAMAM, devam_at=datetime.now(UTC).isoformat())
        meta["review"] = review
        await db.execute(
            update(AnalysisJob).where(AnalysisJob.id == job_id).values(result_metadata=meta)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    logger.info("Review continuation done job=%s", job_id)
    return {"ok": True}


async def devami_baslat(job_id: str) -> str:
    """Dispatch the continuation: the maintenance queue, else in-process."""
    try:
        from app.config import get_settings
        from app.worker import get_arq_pool

        pool = await get_arq_pool()
        await pool.enqueue_job(
            "run_review_continuation", job_id,
            _queue_name=get_settings().arq_maintenance_queue_name,
            # One run per job however many times it is dispatched (approval,
            # then the reaper) while the first is still queued or running.
            _job_id=f"review-continue:{job_id}",
        )
        return "queued"
    except Exception as exc:
        logger.info("Review continuation inline (no broker) job=%s: %s", job_id, exc)

    from app.core.background import spawn

    spawn(devam_et(job_id), name=f"review-continue-{job_id[:8]}")
    return "inline"


async def yarim_kalanlari_bul(db: Any, now: datetime | None = None) -> list[str]:
    """Approved jobs whose continuation is still 'bekliyor' past the grace period."""
    from sqlalchemy import select

    from app.models.analysis_job import AnalysisJob, JobStatus

    now = now or datetime.now(UTC)
    # JSON-key filters differ between SQLite and Postgres; a bounded window of
    # recently completed jobs filtered here is portable and cheap.
    rows = (await db.execute(
        select(AnalysisJob.id, AnalysisJob.result_metadata)
        .where(AnalysisJob.status == JobStatus.COMPLETED,
               AnalysisJob.updated_at >= now - timedelta(days=7))
        .limit(500)
    )).all()
    yarim: list[str] = []
    for job_id, meta in rows:
        review = (meta or {}).get("review") or {}
        if review.get("devam") != BEKLIYOR:
            continue
        try:
            onay = datetime.fromisoformat(str(review.get("approved_at")))
        except ValueError:
            onay = now - YENIDEN_DENEME_SURESI
        if onay.tzinfo is None:
            onay = onay.replace(tzinfo=UTC)
        if now - onay >= YENIDEN_DENEME_SURESI:
            yarim.append(str(job_id))
    return yarim
