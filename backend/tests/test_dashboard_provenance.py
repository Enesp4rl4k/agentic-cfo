"""1.3 / U7: the dashboard endpoint labels how each section was produced.

`GET /dashboard/{job_id}` stamps a `provenance` map (real / rule_based /
manual / estimated) so the pnl / tax / budget / forecast metric cards can
badge themselves as "Gerçek" vs "Tahmin" (DESIGN.md: "distinguish real,
estimated and benchmark data close to the metric"). The stamp is applied at
read time, so stored reports — golden demo replays included — are labelled
without a data migration.

Harness mirrors test_demo_clone: demo guest is the lightest proven path
through `load_owned_job` (no password auth needed).
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
    save_company_context,
)
from app.services.demo_template import DEMO_FILENAME, GOLDEN_SLUG


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
    """Golden org with one completed demo job + report (same shape as D2)."""
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


@pytest.mark.asyncio
async def test_dashboard_labels_section_provenance(test_client):
    """pnl / tax / budget / forecast carry their production basis on the wire."""
    await _seed_golden(test_client._test_sessionmaker)
    data = await _guest(test_client)

    ctx = await test_client.get("/api/v1/context/me", headers=_auth(data))
    assert ctx.status_code == 200, ctx.text
    job_id = ctx.json()["data"]["active_cfo_job_id"]
    assert job_id

    dash = await test_client.get(
        f"/api/v1/dashboard/{job_id}", headers=_auth(data)
    )
    assert dash.status_code == 200, dash.text
    prov = dash.json()["data"]["provenance"]

    # Measured from the parsed file / pasted transactions → "Gerçek" class.
    assert prov["pnl"]["data_source"] == "real"
    assert prov["pnl"]["synthetic"] is False
    assert prov["kpis"]["data_source"] == "real"

    # Deterministic rules over real data → still non-synthetic, basis says so.
    assert prov["tax"]["data_source"] == "rule_based"
    assert prov["tax"]["synthetic"] is False
    assert "rule" in prov["tax"]["basis"]

    # The budget plan is user-entered → non-synthetic, honestly labelled.
    assert prov["budget"]["data_source"] == "manual"
    assert prov["budget"]["synthetic"] is False

    # Extrapolation is the one synthetic class — the UI must not call it real.
    assert prov["forecast"]["data_source"] == "estimated"
    assert prov["forecast"]["synthetic"] is True

    # Every explanation is reachable, never empty (DESIGN.md).
    for block in prov.values():
        assert block["basis"]
