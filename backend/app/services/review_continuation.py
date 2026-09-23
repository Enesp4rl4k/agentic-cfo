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
CALISIYOR = "calisiyor"
TAMAM = "tamam"
# Long enough for a queued run to start and finish on a busy worker, short
# enough that a lost one is recovered by the next reaper pass (every 10 min).
YENIDEN_DENEME_SURESI = timedelta(minutes=15)


def devam_durumu(meta: dict[str, Any] | None) -> str | None:
    return ((meta or {}).get("review") or {}).get("devam")


async def _devam_yaz(db: Any, job: Any, **alanlar: Any) -> bool:
    """Write review fields only if nobody wrote the row since it was read.

    Compare-and-set on `updated_at`: portable across SQLite and Postgres, and no
    migration for a JSON-held state. Returns whether this caller's write won.
    """
    from sqlalchemy import update

    from app.models.analysis_job import AnalysisJob

    meta = dict(job.result_metadata or {})
    review = dict(meta.get("review") or {})
    review.update(alanlar)
    meta["review"] = review
    sonuc = await db.execute(
        update(AnalysisJob)
        .where(AnalysisJob.id == job.id, AnalysisJob.updated_at == job.updated_at)
        .values(result_metadata=meta, updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return bool(sonuc.rowcount == 1)


def _eski_mi(zaman: str | None, now: datetime) -> bool:
    try:
        t = datetime.fromisoformat(str(zaman))
    except ValueError:
        return True
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return now - t >= YENIDEN_DENEME_SURESI


async def devam_et(job_id: str) -> dict[str, Any]:
    """Run the held continuation for an approved job, once.

    Two dispatches can overlap (the in-process fallback and the reaper, or two
    reapers): each first claims the row with a compare-and-set to "calisiyor",
    and only the one whose write wins runs. A claim older than the grace period
    is a crashed run and may be taken over. A failure puts the row back to
    "bekliyor" for the reaper.
    """
    from app.database import session_factory
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import continue_after_completion, saved_result

    now = datetime.now(UTC)
    async with session_factory()() as db:
        job = await db.get(AnalysisJob, job_id)
        if job is None or job.status != JobStatus.COMPLETED or not job.org_id:
            return {"ok": False, "neden": "iş yok ya da tamamlanmamış"}
        review = (job.result_metadata or {}).get("review") or {}
        durum = review.get("devam")
        if durum == TAMAM:
            return {"ok": True, "neden": "zaten tamam"}
        if durum == CALISIYOR and not _eski_mi(review.get("devam_basladi"), now):
            return {"ok": True, "neden": "başka bir çalıştırma sürüyor"}
        if not await _devam_yaz(db, job, devam=CALISIYOR, devam_basladi=now.isoformat()):
            return {"ok": True, "neden": "başka bir çalıştırma sahiplendi"}

        await db.refresh(job)
        try:
            await continue_after_completion(job_id, str(job.org_id), await saved_result(job_id, db), db)
        except Exception:
            await db.refresh(job)
            await _devam_yaz(db, job, devam=BEKLIYOR)
            raise
        await db.refresh(job)
        await _devam_yaz(db, job, devam=TAMAM, devam_at=datetime.now(UTC).isoformat())
    logger.info("Review continuation done job=%s", job_id)
    return {"ok": True}


# How long an approval may wait on the broker before running the continuation
# itself. The approval is a button press; a broker that is slow to refuse
# (connect timeouts) must not hold it.
KUYRUK_ZAMAN_ASIMI = 3.0


async def _kuyruga_koy(job_id: str) -> None:
    """Queue the continuation on the maintenance queue, or raise."""
    import asyncio

    from app.config import get_settings
    from app.core.redis_client import get_redis
    from app.worker import get_arq_pool

    # The shared client is None when Redis is disabled or was just found
    # unreachable (its cooldown): no point waiting on a connect that will fail.
    if await get_redis() is None:
        raise ConnectionError("broker yok ya da erişilemiyor")
    pool = await asyncio.wait_for(get_arq_pool(), KUYRUK_ZAMAN_ASIMI)
    await asyncio.wait_for(
        pool.enqueue_job(
            "run_review_continuation", job_id,
            _queue_name=get_settings().arq_maintenance_queue_name,
            # One run per job however many times it is dispatched (approval,
            # then the reaper) while the first is still queued or running.
            _job_id=f"review-continue:{job_id}",
        ),
        KUYRUK_ZAMAN_ASIMI,
    )


async def devami_baslat(job_id: str) -> str:
    """Dispatch the continuation: the maintenance queue, else in-process."""
    try:
        await _kuyruga_koy(job_id)
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
        durum = review.get("devam")
        # Owed and never started, or started by a run that died mid-way.
        if (durum == BEKLIYOR and _eski_mi(review.get("approved_at"), now)) or (
            durum == CALISIYOR and _eski_mi(review.get("devam_basladi"), now)
        ):
            yarim.append(str(job_id))
    return yarim
