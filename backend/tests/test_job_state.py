"""The claim is the idempotency mechanism (DDIA Ch.7 concurrency, Ch.11).

Duplicate deliveries are allowed to exist everywhere — double-click, HTTP
retry, inline + queued racing — and exactly one of them runs, because the
*database* decides with one atomic UPDATE whose rowcount is the answer.
Terminal transitions guard the same way: outputs and status are one
transaction, and a job a reaper already failed is never overwritten.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.report import Report
from app.models.transaction import Transaction
from app.services.job_state import (
    claim_for_analysis,
    fail_job,
    finish_job,
    mark_enqueue_lease,
    purge_job_outputs,
)


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _add_job(
    maker, job_id: str = "j1", status: JobStatus = JobStatus.PENDING
) -> None:
    async with maker() as db:
        db.add(
            AnalysisJob(
                id=job_id,
                status=status,
                filename="f.csv",
                file_path="/tmp/f.csv",
                file_type="csv",
            )
        )
        await db.commit()


async def _get(maker, job_id: str = "j1") -> AnalysisJob | None:
    async with maker() as db:
        return await db.get(AnalysisJob, job_id)


# ── claim_for_analysis ────────────────────────────────────────────────────────


class TestClaim:
    async def test_first_claim_wins_and_the_duplicate_gets_nothing(self, maker):
        await _add_job(maker)
        async with maker() as worker1:
            claimed = await claim_for_analysis(worker1, "j1", worker_id="w1")
        assert claimed is not None
        assert claimed.status == JobStatus.ANALYZING

        # Second delivery of the same job — the state it must NOT be able
        # to claim from is 'analyzing' (someone holds it), and 'pending'
        # is long gone.
        async with maker() as worker2:
            duplicate = await claim_for_analysis(worker2, "j1", worker_id="w2")
        assert duplicate is None

        job = await _get(maker)
        assert job is not None
        assert job.locked_by == "w1"  # the first claimer holds it, not w2

    async def test_a_claim_carries_an_expiry(self, maker):
        await _add_job(maker)
        async with maker() as db:
            await claim_for_analysis(db, "j1", worker_id="w1", lease_seconds=900)
        job = await _get(maker)
        assert job is not None
        assert job.lease_expires_at is not None
        # SQLite hands datetimes back without tzinfo; the value was written
        # as UTC, so pin it before comparing (Postgres round-trips it).
        lease = job.lease_expires_at
        if lease.tzinfo is None:
            lease = lease.replace(tzinfo=UTC)
        assert lease > datetime.now(UTC)

    async def test_terminal_states_are_not_claimable(self, maker):
        await _add_job(maker, status=JobStatus.COMPLETED)
        async with maker() as db:
            assert await claim_for_analysis(db, "j1") is None

    async def test_a_failed_job_can_be_re_run(self, maker):
        # FAILED is claimable on purpose: the retry path re-runs through the
        # same single-claim gate rather than around it.
        await _add_job(maker, status=JobStatus.FAILED)
        async with maker() as db:
            claimed = await claim_for_analysis(db, "j1", worker_id="w1")
        assert claimed is not None
        assert claimed.status == JobStatus.ANALYZING

    async def test_missing_job_returns_none(self, maker):
        async with maker() as db:
            assert await claim_for_analysis(db, "nope") is None


# ── finish_job / fail_job ─────────────────────────────────────────────────────


class TestTerminalTransitions:
    async def test_finish_does_not_commit_behind_the_callers_back(self, maker):
        """`finish_job` only *positions* the terminal write; the caller's
        commit is what publishes it — that is how outputs and status share
        one transaction."""
        await _add_job(maker)
        async with maker() as db:
            await claim_for_analysis(db, "j1")
            assert await finish_job(db, "j1", status=JobStatus.COMPLETED) is True
            await db.rollback()  # caller aborted after all — nothing may land

        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.ANALYZING  # no commit happened inside

    async def test_second_finish_is_refused_and_the_first_state_stands(self, maker):
        await _add_job(maker)
        async with maker() as db:
            await claim_for_analysis(db, "j1")
            assert await finish_job(db, "j1", status=JobStatus.COMPLETED) is True
            await db.commit()

        async with maker() as late:
            assert (
                await finish_job(late, "j1", status=JobStatus.AWAITING_REVIEW)
            ) is False
            await late.rollback()

        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.COMPLETED  # terminal state is final

    async def test_a_job_the_reaper_took_is_not_overwritten(self, maker):
        """The reaper failed the job mid-run; the late finish must write
        nothing — not results, not a status flip back to completed."""
        await _add_job(maker)
        async with maker() as db:
            await claim_for_analysis(db, "j1", worker_id="w1")

        # Reaper runs in its own transaction:
        async with maker() as reaper:
            await reaper.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id == "j1")
                .values(status=JobStatus.FAILED, lease_expires_at=None)
            )
            await reaper.commit()

        async with maker() as worker:
            await purge_job_outputs(worker, "j1")  # part of the losing txn
            worker.add(
                Transaction(
                    job_id="j1",
                    amount_kurus=100,
                    type="income",
                    category="revenue",
                    transaction_date=datetime.now(UTC),
                )
            )
            won = await finish_job(worker, "j1", status=JobStatus.COMPLETED)
            assert won is False
            await worker.rollback()  # the worker's rule when won is False

        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.FAILED  # the reaper's verdict stands
        async with maker() as db:
            rows = (
                await db.execute(select(Transaction).where(Transaction.job_id == "j1"))
            ).all()
        assert rows == []  # the discarded outputs never landed

    async def test_fail_job_records_the_error(self, maker):
        await _add_job(maker)
        async with maker() as db:
            await claim_for_analysis(db, "j1")
            assert await fail_job(db, "j1", error="boom") is True
            await db.commit()
        job = await _get(maker)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.error_message == "boom"
        assert job.lease_expires_at is None  # the lease is done its job


# ── mark_enqueue_lease ────────────────────────────────────────────────────────


class TestEnqueueLease:
    async def test_enqueued_pending_job_gets_an_expiry(self, maker):
        await _add_job(maker)
        async with maker() as db:
            assert await mark_enqueue_lease(db, "j1") is True
        job = await _get(maker)
        assert job is not None
        assert job.locked_by == "enqueue"
        assert job.lease_expires_at is not None

    async def test_a_claimed_job_keeps_its_holders_lease(self, maker):
        """The stamp only guards unclaimed pending rows — it must not steal
        a lease from the worker actually running the job."""
        await _add_job(maker)
        async with maker() as db:
            await claim_for_analysis(db, "j1", worker_id="w1")
        async with maker() as db2:
            assert await mark_enqueue_lease(db2, "j1") is False
        job = await _get(maker)
        assert job is not None
        assert job.locked_by == "w1"


# ── purge_job_outputs ─────────────────────────────────────────────────────────


class TestPurge:
    async def test_a_rerun_replaces_rather_than_unions(self, maker):
        await _add_job(maker)
        async with maker() as db:
            db.add(
                Transaction(
                    job_id="j1",
                    amount_kurus=100,
                    type="income",
                    category="revenue",
                    transaction_date=datetime.now(UTC),
                )
            )
            db.add(Report(job_id="j1", report_type="pnl", report_format="json"))
            await db.commit()

        async with maker() as db:
            await purge_job_outputs(db, "j1")
            await db.commit()

        async with maker() as db:
            txs = (
                await db.execute(select(Transaction).where(Transaction.job_id == "j1"))
            ).all()
            reports = (
                await db.execute(select(Report).where(Report.job_id == "j1"))
            ).all()
        assert txs == []
        assert reports == []

    async def test_purge_leaves_other_jobs_alone(self, maker):
        await _add_job(maker, "j1")
        await _add_job(maker, "j2")
        async with maker() as db:
            db.add(
                Transaction(
                    job_id="j2",
                    amount_kurus=5,
                    type="expense",
                    category="cost",
                    transaction_date=datetime.now(UTC),
                )
            )
            await db.commit()
        async with maker() as db:
            await purge_job_outputs(db, "j1")
            await db.commit()
        async with maker() as db:
            txs = (
                await db.execute(select(Transaction).where(Transaction.job_id == "j2"))
            ).all()
        assert len(txs) == 1
