"""
D2 — golden → konuk klonlama kapıları (DEMO_PLAN §D2).

`scripts/demo_prefill.py` golden org'u (slug=demo-golden) bir kez doldurur;
`/demo/guest` her yeni konuk için bu golden'dan satır kopyası alır. Gates:

1. Golden yokken konuk davranışı değişmez (boş org — D1 davranışı)
2. Golden varken konuk: context + report anında dolu, job id yeniden üretilir,
   context_json içindeki org_id bile konuğa patch'lenir
3. Dashboard sahiplik: konuk klonlanmış job'ını çeker (200), payload id patch'li
4. İki konuk birbirini görmez — yabancı job'a istek 404
5. /demo/status klonlu konukta has_demo=True (QuickDemoBanner hazır göstergesi)
6. İdempotent: aynı org'a ikinci klon denemesi already_cloned
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.org import _regional_defaults
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.company_semantic_snapshot import CompanySemanticSnapshotRow
from app.models.organization import Organization
from app.models.report import Report, ReportFormat
from app.services.company_context import (
    CompanyContext,
    get_company_context,
    save_company_context,
)
from app.services.demo_template import (
    DEMO_FILENAME,
    GOLDEN_SLUG,
    clone_demo_workspace,
)


@pytest_asyncio.fixture
async def test_client(monkeypatch):
    """In-memory DB dependency override + demo_mode on."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(get_settings(), "demo_mode", True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._test_sessionmaker = TestSessionLocal  # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.clear()
    await test_engine.dispose()


async def _seed_golden(sessionmaker) -> str:
    """Build a golden org with one completed demo job + report + context."""
    async with sessionmaker() as db:
        org = Organization(
            name="TechNova Yazılım A.Ş.",
            slug=GOLDEN_SLUG,
            **_regional_defaults("TR"),
        )
        db.add(org)
        await db.flush()

        job = AnalysisJob(
            status=JobStatus.COMPLETED,
            filename=DEMO_FILENAME,
            file_path="golden_demo.csv",
            file_type="csv",
            org_id=str(org.id),
            user_id=None,
        )
        db.add(job)
        await db.flush()

        db.add(
            Report(
                job_id=str(job.id),
                report_type="full",
                report_format=ReportFormat.JSON,
                data={"job_id": str(job.id), "net": 12345},
            )
        )

        ctx = CompanyContext(org_id=str(org.id), company_name="TechNova Yazılım A.Ş.")
        ctx.update_agent_result(
            "cfo", {"job_id": str(job.id), "dashboard": {"net": 12345}}
        )
        ctx.set_active_job("cfo", str(job.id))
        await save_company_context(ctx, db)

        db.add(
            CompanySemanticSnapshotRow(
                org_id=str(org.id),
                period_key="2024",
                metrics_json="[]",
                drivers_json="[]",
                evidence_json="[]",
                source_job_ids=json.dumps([str(job.id)]),
            )
        )
        await db.commit()
        return str(job.id)


async def _guest(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/demo/guest")
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _auth(data: dict) -> dict:
    return {"Authorization": f"Bearer {data['access_token']}"}


async def _context(client: AsyncClient, data: dict) -> dict:
    resp = await client.get("/api/v1/context/me", headers=_auth(data))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


@pytest.mark.asyncio
async def test_guest_without_golden_starts_empty(test_client):
    """No golden in the DB → the guest keeps the plain D1 behaviour."""
    data = await _guest(test_client)

    ctx = await _context(test_client, data)
    assert not ctx.get("last_cfo_result")

    status = await test_client.get(
        "/api/v1/demo/status", headers=_auth(data)
    )
    assert status.status_code == 200
    assert status.json()["data"]["has_demo"] is False


@pytest.mark.asyncio
async def test_guest_clones_golden_workspace(test_client):
    """The visitor lands on a full context instantly — ids fully re-homed."""
    golden_job_id = await _seed_golden(test_client._test_sessionmaker)
    data = await _guest(test_client)

    ctx = await _context(test_client, data)
    assert ctx.get("last_cfo_result"), "cloned context must carry the CFO result"

    cloned_job_id = ctx.get("active_cfo_job_id")
    assert cloned_job_id
    assert cloned_job_id != golden_job_id, "clones must not share the job id"
    assert ctx["last_cfo_result"]["job_id"] == cloned_job_id
    # context_json embeds org_id — it must read the guest's org, not golden's
    assert ctx["org_id"] == data["user"]["org_id"]


@pytest.mark.asyncio
async def test_guest_dashboard_serves_cloned_report(test_client):
    """The cloned job passes the ownership check and the payload is patched."""
    await _seed_golden(test_client._test_sessionmaker)
    data = await _guest(test_client)

    ctx = await _context(test_client, data)
    job_id = ctx["active_cfo_job_id"]

    dash = await test_client.get(
        f"/api/v1/dashboard/{job_id}", headers=_auth(data)
    )
    assert dash.status_code == 200, dash.text
    payload = dash.json()["data"]
    assert payload["net"] == 12345
    assert payload["job_id"] == job_id, "data.job_id must point at the clone"


@pytest.mark.asyncio
async def test_two_guests_get_isolated_clones(test_client):
    """Tenant isolation: distinct jobs; a foreign dashboard reads as 404."""
    await _seed_golden(test_client._test_sessionmaker)
    a = await _guest(test_client)
    b = await _guest(test_client)

    ctx_a = await _context(test_client, a)
    ctx_b = await _context(test_client, b)
    job_a = ctx_a["active_cfo_job_id"]
    job_b = ctx_b["active_cfo_job_id"]
    assert job_a and job_b and job_a != job_b

    # B asks for A's dashboard → refused (404, never 403 per access.py)
    foreign = await test_client.get(
        f"/api/v1/dashboard/{job_a}", headers=_auth(b)
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_cloned_guest_status_reports_demo_ready(test_client):
    """/demo/status has_demo=True → QuickDemoBanner shows the ready state."""
    await _seed_golden(test_client._test_sessionmaker)
    data = await _guest(test_client)

    status = await test_client.get("/api/v1/demo/status", headers=_auth(data))
    assert status.status_code == 200
    body = status.json()["data"]
    assert body["has_demo"] is True
    assert body["status"] == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_clone_is_idempotent(test_client):
    """A second clone attempt for the same org is a no-op."""
    await _seed_golden(test_client._test_sessionmaker)
    data = await _guest(test_client)
    org_id = data["user"]["org_id"]

    async with test_client._test_sessionmaker() as db:
        second = await clone_demo_workspace(db, org_id)
    assert second.cloned is False
    assert second.reason == "already_cloned"

    ctx = await _context(test_client, data)
    assert second.job_id == ctx["active_cfo_job_id"]


@pytest.mark.asyncio
async def test_context_persists_without_redis_in_clone_path(test_client):
    """Clone writes through save path consumers read: get_company_context hits
    the DB row (no Redis in tests) and still returns the CFO payload."""
    await _seed_golden(test_client._test_sessionmaker)
    data = await _guest(test_client)

    async with test_client._test_sessionmaker() as db:
        ctx = await get_company_context(data["user"]["org_id"], db)
    assert ctx.last_cfo_result is not None
    assert ctx.last_cfo_result["dashboard"]["net"] == 12345
