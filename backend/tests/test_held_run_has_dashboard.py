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


async def _job(client, tmp_path: Path, org_id: str, source: str, extra_row: str | None = None) -> str:
    from app.models.analysis_job import AnalysisJob, JobStatus

    dst = tmp_path / source
    shutil.copy(CORPUS / source, dst)
    if extra_row:
        dst.write_text(dst.read_text(encoding="utf-8").rstrip(chr(10)) + chr(10) + extra_row + chr(10), encoding="utf-8")
    async with client._maker() as db:
        job = AnalysisJob(filename=source, file_path=str(dst), file_type="csv",
                          org_id=org_id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        return job.id


async def _held_then_approved(client, tmp_path, email: str, source: str, extra_row: str | None = None) -> None:
    from app.models.analysis_job import AnalysisJob
    from app.worker import run_cfo_analysis

    headers, org_id, _ = await kullanici(client, email)
    job_id = await _job(client, tmp_path, org_id, source, extra_row)

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
    """The loss month used to be held by its own forecast ("critical" alert); that is shown now, not held
    (see test_forecast_runway). The hold here is a real integrity one: a row whose date cannot be read
    lowers the file's parse confidence under the gate, so the run is held, analysed, and approvable."""
    client, tmp_path = ortam
    await _held_then_approved(
        client, tmp_path, "subat@example.com", "technova_subat_2024_zarar.csv",
        extra_row='bilinmiyor,Okunamayan satır,"1.000,00",expense,other',
    )


async def test_the_loss_month_alone_is_not_held(ortam):
    """Same file without the unreadable row: negative months and critical alerts do not hold it."""
    from app.models.analysis_job import AnalysisJob
    from app.worker import run_cfo_analysis

    client, tmp_path = ortam
    _, org_id, _ = await kullanici(client, "subat2@example.com")
    job_id = await _job(client, tmp_path, org_id, "technova_subat_2024_zarar.csv")
    assert (await run_cfo_analysis({}, job_id)).get("ok") is True
    async with client._maker() as db:
        assert (await db.get(AnalysisJob, job_id)).status == "completed"


async def test_a_file_whose_every_row_is_unreadable_is_held_row_by_row_for_the_reviewer(ortam):
    """Every date of bozuk_veri.csv is unreadable: nothing is analysed (no figure can honestly
    be drawn), the run is held, and each row waits in the held-rows list with its reason."""
    from sqlalchemy import select

    from app.models.analysis_job import AnalysisJob
    from app.models.transaction import Transaction
    from app.worker import run_cfo_analysis

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "bozuk@example.com")
    job_id = await _job(client, tmp_path, org_id, "bozuk_veri.csv")
    out = await run_cfo_analysis({}, job_id)
    assert out.get("ok") is True, out
    async with client._maker() as db:
        assert (await db.get(AnalysisJob, job_id)).status == "awaiting_review"
        assert (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).first() is None
    rows = (await client.get(f"/api/v1/held-rows?job_id={job_id}", headers=headers)).json()["data"]["rows"]
    assert len(rows) == 4 and all("tarih okunamadı" in r["reason_labels"] for r in rows)
