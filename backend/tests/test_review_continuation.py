"""An approval's continuation survives a restart.

It ran as an in-process task: a restart between the approval's commit and the
task's end lost it silently — the job read "completed" and the command center
never heard of it. The approval now records `review.devam = "bekliyor"`, the
continuation marks it "tamam", and the reaper re-dispatches what is left.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest_asyncio

import app.database as database
import app.worker as worker
from app.services import review_continuation as rc
from tests.api_helpers import bellek_istemcisi, kullanici, ornek_rapor


async def _broker_yok(job_id: str) -> None:
    raise ConnectionError("broker yok")


@pytest_asyncio.fixture
async def client(monkeypatch):
    async with bellek_istemcisi() as c:
        # The continuation opens its own session: point it at this database.
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        # Decided here, not by whatever Redis the machine happens to have: CI
        # has one that refuses slowly, which made this test time out.
        monkeypatch.setattr(rc, "_kuyruga_koy", _broker_yok)
        yield c


@pytest_asyncio.fixture
def calisanlar(monkeypatch) -> list[str]:
    """Stand in for the heavy continuation; record which jobs it ran for."""
    calls: list[str] = []

    async def fake(job_id: str, org_id: str, result: dict[str, Any], db: Any) -> None:
        calls.append(job_id)

    monkeypatch.setattr(worker, "continue_after_completion", fake)
    return calls


async def _held_job(client, org_id: str) -> str:
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.report import Report, ReportFormat, ReportType

    async with client._maker() as db:
        job = AnalysisJob(filename="m.csv", file_path="/m.csv", file_type="csv", org_id=org_id,
                          status=JobStatus.AWAITING_REVIEW, awaiting_review=True, min_confidence=0.6)
        db.add(job)
        await db.flush()
        db.add(Report(job_id=job.id, report_type=ReportType.FULL,
                      report_format=ReportFormat.JSON, data=ornek_rapor()))
        await db.commit()
        return job.id


async def _meta(client, job_id: str) -> dict[str, Any]:
    from app.models.analysis_job import AnalysisJob

    async with client._maker() as db:
        return dict((await db.get(AnalysisJob, job_id)).result_metadata or {})


async def _bekle(kosul, deneme: int = 100) -> None:
    for _ in range(deneme):
        if await kosul():
            return
        await asyncio.sleep(0.02)


async def test_approval_records_the_owed_continuation_and_it_closes(client, calisanlar):
    headers, org_id, _ = await kullanici(client, "onay@example.com")
    job_id = await _held_job(client, org_id)

    r = await client.post(f"/api/v1/analysis/{job_id}/approve", headers=headers)
    assert r.status_code == 200, r.text

    async def kapandi() -> bool:
        return rc.devam_durumu(await _meta(client, job_id)) == rc.TAMAM

    await _bekle(kapandi)
    assert calisanlar == [job_id]
    meta = await _meta(client, job_id)
    assert meta["review"]["devam"] == rc.TAMAM and meta["review"]["devam_at"]


async def test_the_continuation_runs_once_however_often_it_is_dispatched(client, calisanlar):
    headers, org_id, _ = await kullanici(client, "tek@example.com")
    job_id = await _held_job(client, org_id)
    await client.post(f"/api/v1/analysis/{job_id}/approve", headers=headers)

    async def kapandi() -> bool:
        return rc.devam_durumu(await _meta(client, job_id)) == rc.TAMAM

    await _bekle(kapandi)
    await rc.devam_et(job_id)          # the reaper dispatching it again
    assert calisanlar == [job_id]


async def test_the_reaper_finds_an_approval_whose_continuation_was_lost(client, calisanlar):
    """Simulates the restart: approved and marked 'bekliyor', never closed."""
    from sqlalchemy import update

    from app.models.analysis_job import AnalysisJob, JobStatus

    _, org_id, _ = await kullanici(client, "kayip@example.com")
    job_id = await _held_job(client, org_id)
    eski = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    async with client._maker() as db:
        await db.execute(update(AnalysisJob).where(AnalysisJob.id == job_id).values(
            status=JobStatus.COMPLETED, awaiting_review=False,
            result_metadata={"review": {"approved_by": "u", "approved_at": eski, "devam": rc.BEKLIYOR}},
        ))
        await db.commit()

        assert await rc.yarim_kalanlari_bul(db) == [job_id]

    await rc.devam_et(job_id)
    assert calisanlar == [job_id]
    async with client._maker() as db:
        assert await rc.yarim_kalanlari_bul(db) == []


async def test_a_fresh_approval_is_left_to_its_own_run(client, calisanlar):
    """Inside the grace period the reaper does not race the queued run."""
    from sqlalchemy import update

    from app.models.analysis_job import AnalysisJob, JobStatus

    _, org_id, _ = await kullanici(client, "taze@example.com")
    job_id = await _held_job(client, org_id)
    async with client._maker() as db:
        await db.execute(update(AnalysisJob).where(AnalysisJob.id == job_id).values(
            status=JobStatus.COMPLETED, awaiting_review=False,
            result_metadata={"review": {"approved_at": datetime.now(UTC).isoformat(),
                                        "devam": rc.BEKLIYOR}},
        ))
        await db.commit()
        assert await rc.yarim_kalanlari_bul(db) == []


async def test_with_a_broker_the_continuation_is_queued_not_run_here(client, calisanlar, monkeypatch):
    kuyruk: list[str] = []

    async def kuyruga(job_id: str) -> None:
        kuyruk.append(job_id)

    monkeypatch.setattr(rc, "_kuyruga_koy", kuyruga)
    assert await rc.devami_baslat("job-9") == "queued"
    await asyncio.sleep(0.05)
    assert kuyruk == ["job-9"] and calisanlar == []


async def test_without_a_broker_it_runs_here(client, calisanlar):
    assert await rc.devami_baslat("olmayan-is") == "inline"


async def test_a_broker_slow_to_refuse_does_not_hold_the_approval(monkeypatch):
    """CI's Redis refused slowly; the approval must not wait on it."""
    import time

    import app.core.redis_client as redis_client

    async def var() -> object:
        return object()

    async def yavas_havuz():
        await asyncio.sleep(10)

    monkeypatch.setattr(redis_client, "get_redis", var)
    monkeypatch.setattr(worker, "get_arq_pool", yavas_havuz)
    monkeypatch.setattr(rc, "KUYRUK_ZAMAN_ASIMI", 0.1)
    monkeypatch.setattr("app.core.background.spawn", lambda coro, name: coro.close())

    t0 = time.monotonic()
    assert await rc.devami_baslat("job-yavas") == "inline"
    assert time.monotonic() - t0 < 2
