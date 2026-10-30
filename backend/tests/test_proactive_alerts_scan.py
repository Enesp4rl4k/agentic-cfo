"""The hourly proactive scan reaches real organisations and keeps its alerts (plan v6 §S0).

Before: the active-org query was raw SQL in Postgres-only syntax swallowed by
`except: pass` (so on SQLite no org was ever scanned), it read only agent_jobs
(so a CFO-only org was never scanned), and alerts were inserted into a table no
model created (so on SQLite every alert vanished into another `except`).
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.orchestration.proactive_alerts import AlertEvent, ProactiveAlertOrchestrator
from app.database import Base
from tests.db_helpers import gecici_motor


@pytest_asyncio.fixture
async def db():
    import app.models  # noqa: F401  — every table, as create_all in dev builds it

    engine = gecici_motor(echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _analysis(db, org_id: str, *, hours_ago: float) -> None:
    from app.models.analysis_job import AnalysisJob

    db.add(AnalysisJob(
        filename="x.csv", file_path="/tmp/x.csv", file_type="csv", org_id=org_id,
        status="completed", created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    ))
    await db.commit()


async def _agent_job(db, org_id: str, *, hours_ago: float) -> None:
    from app.models.agent_job import AgentJob

    db.add(AgentJob(
        agent_type="cto", org_id=org_id, status="completed",
        created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    ))
    await db.commit()


async def test_active_orgs_include_cfo_only_and_agent_job_orgs(db):
    await _analysis(db, "org-cfo-only", hours_ago=2)
    await _agent_job(db, "org-agents", hours_ago=5)
    await _analysis(db, "org-stale", hours_ago=48)

    orgs = await ProactiveAlertOrchestrator(db=db)._get_active_orgs()

    assert orgs == ["org-agents", "org-cfo-only"]


def _alert(alert_id: str = "a1") -> AlertEvent:
    return AlertEvent(
        alert_id=alert_id, org_id="org-1", trigger="kri_breach", severity="high",
        title="Gider / Gelir kırmızı", body="Faaliyet gideri gelirin %112'si",
        metadata={"kri": "Gider / Gelir"}, channels=["in_app"], created_at=time.time(),
    )


async def test_alert_is_persisted_and_idempotent(db):
    from sqlalchemy import select

    from app.models.proactive_alert import ProactiveAlert

    orch = ProactiveAlertOrchestrator(db=db)
    await orch._save_alert(_alert())
    await orch._save_alert(_alert())  # redelivery of the same alert

    rows = (await db.execute(select(ProactiveAlert))).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "Gider / Gelir kırmızı"
    assert rows[0].metadata_json == '{"kri": "Gider / Gelir"}'
