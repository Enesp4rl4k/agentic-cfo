"""The worker takes a real job from pending to a terminal state.

Every analysis on the worker path failed with MissingGreenlet: a rollback,
added to close the read transaction before the pipeline, expired the job's
attributes, and the next `job.file_path` tried to lazy-load outside the async
context. Nothing ran `run_cfo_analysis` to completion on a real job, so no
test saw it — a live run of the e-Defter package through /baglan did.

The pipeline itself is stood in (it has its own tests); everything around it —
claim, the read transaction, persistence, the terminal write — is real.
"""
from __future__ import annotations

from typing import Any

import pytest_asyncio
from sqlalchemy import select

import app.database as database
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici


@pytest_asyncio.fixture
async def ortam(monkeypatch, tmp_path):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        yield c, tmp_path
        await arka_plan_bitsin()


def _boru_hatti(monkeypatch, *, awaiting_review: bool) -> list[dict[str, Any]]:
    """Stand-in pipeline; records what the worker handed it."""
    alinan: list[dict[str, Any]] = []

    async def sahte(**kw: Any) -> dict[str, Any]:
        alinan.append(kw)
        return {
            "transactions": [{"amount_cents": 1_000_00, "type": "income", "category": "revenue",
                              "description": "Tahsilat", "transaction_date": "2026-08-01"}],
            "dashboard_json": {"pnl": {"revenue": 1000}},
            "anomalies": [],
            "logs": [],
            "awaiting_review": awaiting_review,
            "min_confidence": 0.6 if awaiting_review else 0.95,
        }

    monkeypatch.setattr("app.agents.orchestrator.run_cfo_pipeline", sahte)
    return alinan


async def _is(client, tmp_path, org_id: str) -> str:
    from app.models.analysis_job import AnalysisJob, JobStatus

    dosya = tmp_path / "ekstre.csv"
    dosya.write_text("tarih,aciklama,tutar\n2026-08-01,Tahsilat,1000\n", encoding="utf-8")
    async with client._maker() as db:
        job = AnalysisJob(filename="ekstre.csv", file_path=str(dosya), file_type="csv",
                          org_id=org_id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        return job.id


async def test_a_pending_job_reaches_a_terminal_state(ortam, monkeypatch):
    from app.models.analysis_job import AnalysisJob
    from app.models.transaction import Transaction
    from app.worker import run_cfo_analysis

    client, tmp_path = ortam
    alinan = _boru_hatti(monkeypatch, awaiting_review=True)
    _, org_id, _ = await kullanici(client, "isci@example.com")
    job_id = await _is(client, tmp_path, org_id)

    sonuc = await run_cfo_analysis({}, job_id)

    assert sonuc.get("ok") is True, sonuc
    assert alinan and alinan[0]["file_path"].endswith("ekstre.csv")
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        assert job.status == "awaiting_review" and job.awaiting_review is True
        satirlar = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars().all()
        assert len(satirlar) == 1


async def test_the_extra_documents_reach_the_pipeline(ortam, monkeypatch):
    from app.models.data_source import DataSource, DataSourceDomain, DataSourceType
    from app.worker import run_cfo_analysis

    client, tmp_path = ortam
    alinan = _boru_hatti(monkeypatch, awaiting_review=True)
    _, org_id, _ = await kullanici(client, "ek@example.com")
    job_id = await _is(client, tmp_path, org_id)
    ek = tmp_path / "ikinci.xml"
    ek.write_text("<Invoice/>", encoding="utf-8")
    async with client._maker() as db:
        db.add(DataSource(job_id=job_id, domain=DataSourceDomain.CFO,
                          source_type=DataSourceType.FINANCIAL_DOCUMENT,
                          filename="ikinci.xml", file_path=str(ek), file_size_bytes=10))
        await db.commit()

    await run_cfo_analysis({}, job_id)
    assert alinan[0]["ek_belgeler"] == [{"path": str(ek), "type": "xml", "ad": "ikinci.xml"}]
