"""Plan v7 §P0 / W1 — an analysis the gate holds still gets its dashboard.

Live audit 2026-10-24: a held run stopped before `report_node`, so it saved no
dashboard; approval continues from the saved results, so after approval there
was still nothing — Feb (loss month), an e-invoice and a broken CSV were all
approved → "completed" → `/dashboard` 404, for good. The approval tests passed
because their fixture *inserted* the dashboard a held run never wrote.

These run the real pipeline on the real files and check the dashboard exists
while held and after approval.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest_asyncio

import app.database as database
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici

CORPUS = Path(__file__).resolve().parent / "fixtures" / "tr_corpus"


@pytest_asyncio.fixture
async def ortam(monkeypatch, tmp_path):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        # The approval's continuation (context, chain) is out of scope here.
        from app.services import review_continuation as rc

        async def devam_yok(job_id: str) -> str:
            return "skipped"

        monkeypatch.setattr(rc, "devami_baslat", devam_yok)
        yield c, tmp_path
        await arka_plan_bitsin()


async def _job(client, tmp_path: Path, org_id: str, source: str) -> str:
    from app.models.analysis_job import AnalysisJob, JobStatus

    dst = tmp_path / source
    shutil.copy(CORPUS / source, dst)
    async with client._maker() as db:
        job = AnalysisJob(filename=source, file_path=str(dst), file_type="csv",
                          org_id=org_id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        return job.id


async def _held_then_approved(client, tmp_path, email: str, source: str) -> None:
    from app.models.analysis_job import AnalysisJob
    from app.worker import run_cfo_analysis

    headers, org_id, _ = await kullanici(client, email)
    job_id = await _job(client, tmp_path, org_id, source)

    out = await run_cfo_analysis({}, job_id)
    assert out.get("ok") is True, out
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        assert job.status == "awaiting_review", f"{source} was expected to be held"

    # Held: the reviewer sees the numbers.
    held = await client.get(f"/api/v1/dashboard/{job_id}", headers=headers)
    assert held.status_code == 200, held.text
    assert (held.json()["data"].get("pnl") or {}).get("revenue") is not None

    approved = await client.post(f"/api/v1/analysis/{job_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text

    after = await client.get(f"/api/v1/dashboard/{job_id}", headers=headers)
    assert after.status_code == 200, after.text
    async with client._maker() as db:
        assert (await db.get(AnalysisJob, job_id)).status == "completed"


async def test_a_run_held_at_the_verifier_has_a_dashboard_before_and_after_approval(ortam):
    client, tmp_path = ortam
    await _held_then_approved(client, tmp_path, "subat@example.com", "technova_subat_2024_zarar.csv")


async def test_a_run_held_at_ingestion_is_still_analysed_for_the_reviewer(ortam):
    client, tmp_path = ortam
    await _held_then_approved(client, tmp_path, "bozuk@example.com", "bozuk_veri.csv")
