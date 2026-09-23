"""Every claim must have an expiry — the reaper is what makes it true
(DDIA Ch.1: "a distributed transaction... a lease", and Ch.7: a crashed
worker cannot release its own lock).

Covered here: a dead worker's job fails instead of sitting `analyzing`
forever; an enqueued-but-never-picked-up job fails instead of sitting
`pending` forever; the two flows that are NOT faults — a live lease and a
job nobody enqueued — are left alone; a human at the review gate is never
reaped; a crashed run's ledger row is closed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.agent_run import AgentRun
from app.models.analysis_job import AnalysisJob, JobStatus
from app.services.job_reaper import reap_stuck_jobs


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _job(
    maker,
    *,
    job_id: str = "j1",
    status: JobStatus = JobStatus.ANALYZING,
    locked_by: str | None = "worker:1",
    lease: datetime | None = None,
) -> None:
    async with maker() as db:
        db.add(
            AnalysisJob(
                id=job_id,
                status=status,
                filename="f.csv",
                file_path="/tmp/f.csv",
                file_type="csv",
                locked_by=locked_by,
                lease_expires_at=lease,
            )
        )
        await db.commit()


async def _get(maker, job_id: str = "j1") -> AnalysisJob | None:
    async with maker() as db:
        return await db.get(AnalysisJob, job_id)


async def _reap(maker) -> dict:
    async with maker() as db:
        return await reap_stuck_jobs(db)


class TestExpiredLeases:
    async def test_a_dead_workers_job_is_failed(self, maker):
        await _job(
            maker,
            status=JobStatus.ANALYZING,
            lease=datetime.now(UTC) - timedelta(minutes=1),
        )
        counts = await _reap(maker)
        assert counts["expired_leases"] == 1

        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert "lease expired" in (job.error_message or "").lower()
        assert "re-run" in (job.error_message or "").lower()
        assert job.lease_expires_at is None

    async def test_a_live_lease_is_left_running(self, maker):
        await _job(
            maker,
            status=JobStatus.ANALYZING,
            lease=datetime.now(UTC) + timedelta(minutes=10),
        )
        counts = await _reap(maker)
        assert counts["expired_leases"] == 0

        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.ANALYZING

    async def test_awaiting_review_is_a_person_not_a_fault(self, maker):
        # A human holding the gate is not a stuck job: reaping it would
        # throw away a finished analysis.
        await _job(
            maker,
            status=JobStatus.AWAITING_REVIEW,
            locked_by="worker:1",
            lease=datetime.now(UTC) - timedelta(hours=2),
        )
        counts = await _reap(maker)
        assert counts["expired_leases"] == 0

        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.AWAITING_REVIEW


class TestStalePending:
    async def test_enqueued_but_never_claimed_fails(self, maker):
        # Stamped at dispatch, no worker ever showed up (queue lost /
        # worker down). `stale_pending_minutes` default is 60.
        await _job(
            maker,
            status=JobStatus.PENDING,
            locked_by="enqueue",
            lease=datetime.now(UTC) - timedelta(minutes=61),
        )
        counts = await _reap(maker)
        assert counts["stale_pending"] == 1

        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert "no worker" in (job.error_message or "").lower()

    async def test_a_recently_enqueued_job_keeps_waiting(self, maker):
        await _job(
            maker,
            status=JobStatus.PENDING,
            locked_by="enqueue",
            lease=datetime.now(UTC) + timedelta(minutes=30),
        )
        counts = await _reap(maker)
        assert counts["stale_pending"] == 0
        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.PENDING

    async def test_a_manual_trigger_has_no_lease_and_is_untouched(self, maker):
        # auto-enqueue off: the job waits for a human to press "analyze".
        # No lease → the reaper cannot tell it from a forgotten job, so it
        # deliberately never touches it.
        await _job(
            maker,
            status=JobStatus.PENDING,
            locked_by=None,
            lease=None,
        )
        counts = await _reap(maker)
        assert counts["stale_pending"] == 0
        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.PENDING


class TestStaleLedgerRows:
    async def test_a_run_left_running_by_a_crash_is_failed(self, maker):
        async with maker() as db:
            db.add(
                AgentRun(
                    pipeline="cfo",
                    job_id="j1",
                    status="running",
                    updated_at=datetime.now(UTC) - timedelta(hours=1),
                    created_at=datetime.now(UTC) - timedelta(hours=1),
                )
            )
            await db.commit()

        counts = await _reap(maker)
        assert counts["stale_runs"] == 1

        async with maker() as db:
            run = (
                await db.execute(select(AgentRun).where(AgentRun.job_id == "j1"))
            ).scalar_one()
        assert run.status == "failed"
        assert run.finished_at is not None
        assert "expired" in (run.error or "").lower()

    async def test_a_running_run_young_enough_stays_running(self, maker):
        async with maker() as db:
            db.add(
                AgentRun(
                    pipeline="cfo",
                    job_id="j2",
                    status="running",
                    updated_at=datetime.now(UTC),
                    created_at=datetime.now(UTC),
                )
            )
            await db.commit()

        counts = await _reap(maker)
        assert counts["stale_runs"] == 0
