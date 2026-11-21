"""What follows a completed analysis is owed, recorded, and recovered.

After the worker committed a completed job it ran the follow-up (ledger append,
company view, chain) inline with nothing recorded. A crash or the 600 s job
timeout in between, or a ledger append that failed and was only logged, left
the ledger and the cash radar without the upload while the job read
"completed" — and nothing would ever try again. Approvals already had a durable
continuation; a normal completion now goes through the same record:
`review.devam` is written with the completion, the run marks it done, and the
reaper re-dispatches what is still owed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio

import app.database as database
import app.post_completion as post_completion
from app.services import review_continuation as rc
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici
from tests.test_worker_end_to_end import _boru_hatti, _is


@pytest_asyncio.fixture
async def ortam(monkeypatch, tmp_path):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        yield c, tmp_path
        await arka_plan_bitsin()


async def _meta(client, job_id: str) -> dict[str, Any]:
    from app.models.analysis_job import AnalysisJob

    async with client._maker() as db:
        return dict((await db.get(AnalysisJob, job_id)).result_metadata or {})


async def test_a_completed_run_records_its_continuation_and_closes_it(ortam, monkeypatch):
    from app.worker import run_cfo_analysis

    client, tmp_path = ortam
    _boru_hatti(monkeypatch, awaiting_review=False)
    calls: list[str] = []

    async def fake(job_id: str, org_id: str, result: dict[str, Any], db: Any) -> None:
        calls.append(job_id)

    monkeypatch.setattr(post_completion, "continue_after_completion", fake)
    _, org_id, _ = await kullanici(client, "devam@example.com")
    job_id = await _is(client, tmp_path, org_id)

    assert (await run_cfo_analysis({}, job_id)).get("ok") is True
    assert calls == [job_id]
    review = (await _meta(client, job_id))["review"]
    assert review["devam"] == rc.TAMAM
    assert review["devam_istendi"]


async def test_a_continuation_that_fails_stays_owed_and_the_job_stays_completed(ortam, monkeypatch):
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import run_cfo_analysis

    client, tmp_path = ortam
    _boru_hatti(monkeypatch, awaiting_review=False)

    async def patlayan(*a: Any, **k: Any) -> None:
        raise RuntimeError("defter yazılamadı")

    monkeypatch.setattr(post_completion, "continue_after_completion", patlayan)
    _, org_id, _ = await kullanici(client, "patlayan@example.com")
    job_id = await _is(client, tmp_path, org_id)

    assert (await run_cfo_analysis({}, job_id)).get("ok") is True
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        assert job.status == JobStatus.COMPLETED
    assert rc.devam_durumu(await _meta(client, job_id)) == rc.BEKLIYOR


async def test_a_held_run_owes_nothing_until_it_is_approved(ortam, monkeypatch):
    from app.worker import run_cfo_analysis

    client, tmp_path = ortam
    _boru_hatti(monkeypatch, awaiting_review=True)
    _, org_id, _ = await kullanici(client, "bekleyen@example.com")
    job_id = await _is(client, tmp_path, org_id)

    await run_cfo_analysis({}, job_id)
    assert "review" not in await _meta(client, job_id)


async def test_the_reaper_finds_a_completion_whose_continuation_was_lost(ortam):
    from sqlalchemy import update

    from app.models.analysis_job import AnalysisJob, JobStatus

    client, tmp_path = ortam
    _, org_id, _ = await kullanici(client, "kayip@example.com")
    lost = await _is(client, tmp_path, org_id)
    fresh = await _is(client, tmp_path, org_id)
    now = datetime.now(UTC)
    async with client._maker() as db:
        for job_id, istendi in ((lost, now - timedelta(hours=1)), (fresh, now)):
            await db.execute(update(AnalysisJob).where(AnalysisJob.id == job_id).values(
                status=JobStatus.COMPLETED,
                result_metadata={"review": {"devam": rc.BEKLIYOR, "devam_istendi": istendi.isoformat()}},
            ))
        await db.commit()

    async with client._maker() as db:
        assert await rc.yarim_kalanlari_bul(db, now=now) == [lost]


async def test_a_failed_ledger_append_is_not_reported_as_done(ortam, monkeypatch):
    """It was logged and swallowed; the view was then rebuilt without the upload."""
    import app.services.ledger as ledger

    async def patlayan(*a: Any, **k: Any) -> None:
        raise RuntimeError("defter kilitli")

    monkeypatch.setattr(ledger, "append_job", patlayan)
    client, _ = ortam
    async with client._maker() as db:
        with pytest.raises(RuntimeError, match="defter kilitli"):
            await post_completion.continue_after_completion("job-x", "org-x", {"dashboard_json": {}}, db)
