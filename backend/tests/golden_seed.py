"""Shared demo seed used by the dashboard, clone and reset test suites.

All three suites build the *same* golden organisation — one completed demo job,
its report, the CFO company-context and a semantic snapshot — then drive the
same guest-session and bearer-header helpers.  Keeping a single copy here stops
the three suites from drifting (they are a favourite spot for jscpd/Sonar to
flag as duplicated lines, and for a future edit to fix a bug in one copy but
not the others).
"""
from __future__ import annotations

import json

from httpx import AsyncClient

from app.api.org import _regional_defaults
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.company_semantic_snapshot import CompanySemanticSnapshotRow
from app.models.organization import Organization
from app.models.report import Report, ReportFormat
from app.services.company_context import (
    CompanyContext,
    save_company_context,
)
from app.services.demo_template import DEMO_FILENAME, GOLDEN_SLUG


async def _seed_golden(sessionmaker) -> str:
    """Golden org with one completed demo job + report + context (D2 shape).

    Returns the id of the seeded analysis job.
    """
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
    """Start a demo guest session and return its payload (token + user)."""
    resp = await client.post("/api/v1/demo/guest")
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _auth(data: dict) -> dict:
    """Bearer header for a guest/demo session payload."""
    return {"Authorization": f"Bearer {data['access_token']}"}
