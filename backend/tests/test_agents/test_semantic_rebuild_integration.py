"""DB-backed tests for semantic rebuild, conflicts, and trailing debounce."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.agent_conflict import AgentConflict
from app.models.canonical_transaction import CanonicalTransaction
from app.models.company_context import CompanyContextSnapshot
from app.models.company_semantic_snapshot import CompanySemanticSnapshotRow
from app.models.organization import Organization
from app.models.sync_run import SyncRun
from app.models.user import User
from app.services.company_context import CompanyContext, save_company_context
from app.services.context_persist import persist_agent_completion
from app.services.semantic.conflicts import list_org_conflicts
from app.services.semantic.rebuild import rebuild_semantic_snapshot
from app.services.semantic.store import get_semantic_snapshot

ORG_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PERIOD_KEY = "2026-08"
TX_DATE = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

try:
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")  # type: ignore[misc]
    def _jsonb_as_text(_type, compiler, **_kw):
        return "TEXT"
except Exception:
    pass


@pytest.fixture
async def db_session(monkeypatch: pytest.MonkeyPatch):
    async def _no_redis():
        return None

    monkeypatch.setattr("app.services.company_context._get_redis", _no_redis)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[
                    Organization.__table__,
                    User.__table__,
                    CompanyContextSnapshot.__table__,
                    CompanySemanticSnapshotRow.__table__,
                    SyncRun.__table__,
                    CanonicalTransaction.__table__,
                    AgentConflict.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_contradiction_org(db: AsyncSession) -> None:
    db.add(
        Organization(
            id=ORG_ID,
            name="Contradiction Org",
            slug=f"contradiction-{uuid4().hex[:8]}",
            base_currency="USD",
            locale="en-US",
            regional_packs=[],
        )
    )
    await db.flush()

    ctx = CompanyContext(org_id=ORG_ID)
    ctx.company_name = "Contradiction Org"
    ctx.reporting_period = PERIOD_KEY
    ctx.last_cfo_result = {
        "pnl": {"revenue_cents": 1_600_000, "net_margin": 0.05, "gross_margin": 0.4},
        "cashflow": {"operating": 10_000},
        "forecast": {"scenarios": {"base": {"runway_months": 3.0}}},
        "anomalies": [],
    }
    ctx.last_cmo_result = {
        "campaigns": {"overall_roas": 4.0},
    }
    await save_company_context(ctx, db)

    db.add(
        CanonicalTransaction(
            org_id=ORG_ID,
            source_type="crm_export",
            source_record_id="in-1",
            transaction_date=TX_DATE,
            amount_cents=1_000_000,
            currency="USD",
            direction="inflow",
            confidence=90,
        )
    )
    db.add(
        CanonicalTransaction(
            org_id=ORG_ID,
            source_type="crm_export",
            source_record_id="out-1",
            transaction_date=TX_DATE,
            amount_cents=200_000,
            currency="USD",
            direction="outflow",
            confidence=90,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_rebuild_writes_snapshot_brief_and_conflicts(db_session: AsyncSession) -> None:
    await _seed_contradiction_org(db_session)

    snap = await rebuild_semantic_snapshot(ORG_ID, db_session, include_brief=True, strict=True)
    assert snap is not None
    mmap = snap.metric_map()
    assert "finance.revenue" in mmap
    assert "finance.canonical_inflow" in mmap
    assert mmap["finance.revenue"].value == 1_600_000
    assert mmap["finance.canonical_inflow"].value == 1_000_000
    assert snap.period.key == PERIOD_KEY
    assert snap.brief is not None
    assert snap.brief.awaiting_review is True

    stored = await get_semantic_snapshot(ORG_ID, PERIOD_KEY, db_session)
    assert stored is not None
    assert stored.period.key == PERIOD_KEY

    listed = await list_org_conflicts(ORG_ID, db_session, status="open")
    topics = {c["topic"] for c in listed}
    assert "revenue_vs_canonical_inflow" in topics

    # Second rebuild is idempotent: same period key, no duplicate open conflicts
    snap2 = await rebuild_semantic_snapshot(ORG_ID, db_session, include_brief=True, strict=True)
    assert snap2 is not None
    listed2 = await list_org_conflicts(ORG_ID, db_session, status="open")
    revenue_conflicts = [c for c in listed2 if c["topic"] == "revenue_vs_canonical_inflow"]
    assert len(revenue_conflicts) == 1

    from sqlalchemy import func, select

    count = await db_session.scalar(
        select(func.count()).select_from(CompanySemanticSnapshotRow).where(
            CompanySemanticSnapshotRow.org_id == ORG_ID,
            CompanySemanticSnapshotRow.period_key == PERIOD_KEY,
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_strict_rebuild_does_not_return_none(db_session: AsyncSession) -> None:
    await _seed_contradiction_org(db_session)
    snap = await rebuild_semantic_snapshot(ORG_ID, db_session, strict=True)
    assert snap is not None


@pytest.mark.asyncio
async def test_trailing_rebuild_includes_both_agent_blobs(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two persist calls 1s apart: trailing job reflects CFO + CMO metrics."""
    from app.services import context_persist

    monkeypatch.setattr(context_persist, "_REBUILD_DEBOUNCE_SEC", 30.0)
    context_persist._last_rebuild_at.clear()
    context_persist._trailing_tasks.clear()

    await _seed_contradiction_org(db_session)
    ctx = CompanyContext(org_id=ORG_ID)
    ctx.reporting_period = PERIOD_KEY
    ctx.last_cfo_result = {
        "pnl": {"revenue_cents": 1_600_000},
        "forecast": {"scenarios": {"base": {"runway_months": 3.0}}},
        "anomalies": [],
    }
    await save_company_context(ctx, db_session)

    enqueued: list[str] = []

    async def fake_enqueue(org_id: str, delay_sec: float | None = None) -> None:
        enqueued.append(org_id)

    monkeypatch.setattr(context_persist, "enqueue_trailing_semantic_rebuild", fake_enqueue)

    with patch(
        "app.services.semantic.rebuild.rebuild_semantic_snapshot",
        new=AsyncMock(return_value=object()),
    ) as rebuild_mock:
        await persist_agent_completion(
            ORG_ID,
            "cfo",
            ctx.last_cfo_result,
            db_session,
            trigger_auto_chain=False,
        )
        await persist_agent_completion(
            ORG_ID,
            "cmo",
            {"campaigns": {"overall_roas": 4.0}},
            db_session,
            trigger_auto_chain=False,
        )
        assert rebuild_mock.await_count == 1
        assert enqueued == [ORG_ID]

    snap_obj = await rebuild_semantic_snapshot(ORG_ID, db_session, include_brief=True, strict=True)
    assert snap_obj is not None
    mmap = snap_obj.metric_map()
    assert "finance.runway_months" in mmap
    assert "growth.overall_roas" in mmap
    assert mmap["growth.overall_roas"].value == 4.0
