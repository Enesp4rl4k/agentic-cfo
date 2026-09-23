"""Approving a held analysis completes it and runs what the gate held back.

`POST /analysis/{id}/approve` set the job to PENDING and nothing else. Nothing
re-ran a pending job, so an approved analysis sat "pending" forever, and the
company context, command-center snapshot and auto-chain the gate had held never
ran. Approval now completes the job, records who approved it, and continues
from the saved results.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.database as database
import app.worker as worker
from app.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c._maker = maker  # type: ignore[attr-defined]
        yield c
        # The approval spawns its continuation; let it end inside this test.
        from tests.api_helpers import arka_plan_bitsin

        await arka_plan_bitsin()
    app.dependency_overrides.clear()
    await engine.dispose()


async def _user(client, email: str) -> tuple[dict[str, str], str, str]:
    from app.models.organization import Organization
    from app.models.user import User

    await client.post("/api/v1/auth/register",
                      json={"email": email, "password": "StrongPassword123!", "full_name": "T"})
    async with client._maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        org = Organization(name=email, slug=email.split("@")[0])
        db.add(org)
        await db.flush()
        user.org_id = org.id
        await db.commit()
        org_id, user_id = org.id, user.id
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": "StrongPassword123!"})
             ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, org_id, user_id


async def _held_job(client, org_id: str) -> str:
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.anomaly import Anomaly
    from app.models.report import Report, ReportFormat, ReportType

    async with client._maker() as db:
        job = AnalysisJob(filename="m.csv", file_path="/m.csv", file_type="csv", org_id=org_id,
                          status=JobStatus.AWAITING_REVIEW, awaiting_review=True, min_confidence=0.6)
        db.add(job)
        await db.flush()
        db.add(Report(job_id=job.id, report_type=ReportType.FULL, report_format=ReportFormat.JSON,
                      data={"pnl": {"revenue": 1_000_000}, "cashflow": {"net_change": -5}}))
        db.add(Anomaly(job_id=job.id, anomaly_type="duplicate", severity="high",
                       title="Mükerrer ödeme", description="Aynı tutar iki kez", confidence=0.9))
        await db.commit()
        return job.id


async def test_approval_completes_the_job_and_continues_from_saved_results(client, monkeypatch):
    calls: list[tuple[str, str, dict[str, Any]]] = []

    async def fake_continue(job_id, org_id, result, db):
        calls.append((job_id, org_id, result))

    monkeypatch.setattr(worker, "continue_after_completion", fake_continue)
    # The continuation runs in the background on its own session; in the test
    # that session must be the test database's.
    monkeypatch.setattr(database, "session_factory", lambda: client._maker)
    # No broker, decided by the test: CI's Redis refused slowly and the wait
    # below ran out before the in-process fallback started.
    from app.services import review_continuation as rc

    async def broker_yok(job_id: str) -> None:
        raise ConnectionError("broker yok")

    monkeypatch.setattr(rc, "_kuyruga_koy", broker_yok)
    headers, org_id, user_id = await _user(client, "onay@example.com")
    job_id = await _held_job(client, org_id)

    r = await client.post(f"/api/v1/analysis/{job_id}/approve", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "completed"

    from app.models.analysis_job import AnalysisJob
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        assert job.status == "completed" and job.awaiting_review is False
        assert job.result_metadata["review"]["approved_by"] == user_id

    for _ in range(50):  # let the background task run
        if calls:
            break
        await asyncio.sleep(0.02)
    assert len(calls) == 1
    got_job, got_org, result = calls[0]
    assert (got_job, got_org) == (job_id, org_id)
    assert result["dashboard_json"]["pnl"]["revenue"] == 1_000_000
    assert result["anomalies"][0]["title"] == "Mükerrer ödeme"

    again = await client.post(f"/api/v1/analysis/{job_id}/approve", headers=headers)
    assert again.status_code == 409


async def test_another_org_cannot_approve(client, monkeypatch):
    async def fake_continue(*a, **k):
        raise AssertionError("must not continue")

    monkeypatch.setattr(worker, "continue_after_completion", fake_continue)
    monkeypatch.setattr(database, "session_factory", lambda: client._maker)
    _, org_a, _ = await _user(client, "a@example.com")
    headers_b, _, _ = await _user(client, "b@example.com")
    job_id = await _held_job(client, org_a)

    r = await client.post(f"/api/v1/analysis/{job_id}/approve", headers=headers_b)
    assert r.status_code in (403, 404)
