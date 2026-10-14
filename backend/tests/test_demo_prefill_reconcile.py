"""
D2 gate — demo_prefill uzlaşması (DEMO_PLAN §D2).

Context yazımları tüm-satır read-modify-write; zincirin başındaki kopyayı
geç kaydeden bir yazar ezme yapabiliyor (gözlemlendi: --force sonrası golden
satırında eski boş cto kalırken job gerçek sonucu 3.5 tutuyordu → sayfa
0.0/10 gösteriyordu). `_reconcile_suite_context` job'lardan (otoriter)
yeniden uygular:

1. En yeni TAMAMLANAN job'un sonucu stale result'ın üzerine yazılır;
   başarısız (FAILED) en-yeni job yok sayılır.
2. Job'sız alanlara (ör. zincir-üretimi coo) dokunulmaz; context'in diğer
   alanları (ceo) korunur.
3. Uygulanan result job_id taşıyorsa doğrulama bunu eşleştirir; taşımayan
   (chro/risk/audit — production'da state job_id gömmez) sadece varlık
   kontrolüyle doğrulanır.
"""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.org import _regional_defaults
from app.database import Base
from app.models.agent_job import AgentJob, AgentJobStatus
from app.models.organization import Organization
from app.services.company_context import (
    CompanyContext,
    get_company_context,
    save_company_context,
)

_PREFILL = Path(__file__).resolve().parents[1] / "scripts" / "demo_prefill.py"
_T0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=UTC)


def _load_prefill():
    """Import the script by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("demo_prefill_reconcile", _PREFILL)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _job(org_id: str, agent: str, *, created: datetime, status, result, jid: str):
    return AgentJob(
        id=jid,
        agent_type=agent,
        user_id=None,
        org_id=org_id,
        status=status,
        input_data={"company_name": "Örnek A.Ş."},
        result_json=result,
        progress=100 if status == AgentJobStatus.COMPLETED else 40,
        created_at=created,
        updated_at=created,
    )


async def _seed_org(db) -> str:
    """Context with stale cto + chain-written ceo/coo (no cmo/risk/… yet)."""
    org = Organization(
        name="Örnek A.Ş.",
        slug="demo-reconcile-test",
        **_regional_defaults("TR"),
    )
    db.add(org)
    await db.flush()
    org_id = str(org.id)

    ctx = CompanyContext(org_id=org_id, company_name="Örnek A.Ş.")
    ctx.update_agent_result(
        "cto",
        {"job_id": "cto-job-stale", "cto_summary": {"overall_health_score": 0.0}},
    )
    ctx.update_agent_result("ceo", {"stale": True, "auto_generated": True})
    ctx.update_agent_result("coo", {"auto_generated": True, "source_job": "auto-x"})
    await save_company_context(ctx, db)
    await db.commit()
    return org_id


async def _seed_suite_jobs(db, org_id: str) -> None:
    """Completed jobs for every suite agent except coo (job-less scenario)."""
    # chro/risk/audit results carry no job_id — mirrors production state shape
    db.add(_job(org_id, "cmo", created=_T0 + timedelta(minutes=1),
                status=AgentJobStatus.COMPLETED,
                result={"job_id": "cmo-1", "campaigns": {"total_spend_cents": 1}},
                jid="cmo-1"))
    db.add(_job(org_id, "chro", created=_T0 + timedelta(minutes=1),
                status=AgentJobStatus.COMPLETED,
                result={"headcount": {"total": 5}}, jid="chro-1"))
    db.add(_job(org_id, "risk", created=_T0 + timedelta(minutes=1),
                status=AgentJobStatus.COMPLETED,
                result={"risk_summary": {"open_kris": 3}}, jid="risk-1"))
    db.add(_job(org_id, "audit", created=_T0 + timedelta(minutes=1),
                status=AgentJobStatus.COMPLETED,
                result={"findings": {"total": 5}}, jid="audit-1"))
    await db.commit()


@pytest.mark.asyncio
async def test_reconcile_rewrites_stale_result_from_newest_completed_job(db):
    mod = _load_prefill()
    org_id = await _seed_org(db)
    await _seed_suite_jobs(db, org_id)

    # old completed (stale) → new completed (real run) → FAILED newest (ignored)
    db.add(_job(org_id, "cto", created=_T0, status=AgentJobStatus.COMPLETED,
                result={"job_id": "cto-old",
                        "cto_summary": {"overall_health_score": 0.0}},
                jid="cto-old"))
    db.add(_job(org_id, "cto", created=_T0 + timedelta(minutes=5),
                status=AgentJobStatus.COMPLETED,
                result={"job_id": "cto-new",
                        "cto_summary": {"overall_health_score": 3.5}},
                jid="cto-new"))
    db.add(_job(org_id, "cto", created=_T0 + timedelta(minutes=9),
                status=AgentJobStatus.FAILED,
                result={"job_id": "cto-failed"}, jid="cto-failed"))
    await db.commit()

    applied = await mod._reconcile_suite_context(db, org_id)

    db.expire_all()
    ctx = await get_company_context(org_id, db)
    assert applied["cto"] == "cto-new"
    assert ctx.last_cto_result["job_id"] == "cto-new"
    assert ctx.last_cto_result["cto_summary"]["overall_health_score"] == 3.5
    # coo has no job in agent_jobs → untouched (auto-chain result stays)
    assert applied["coo"] is None
    assert ctx.last_coo_result == {"auto_generated": True, "source_job": "auto-x"}
    # untouched fields preserved on the whole-row write
    assert ctx.last_ceo_result == {"stale": True, "auto_generated": True}
    assert ctx.last_chro_result == {"headcount": {"total": 5}}
    assert ctx.last_risk_result == {"risk_summary": {"open_kris": 3}}
    assert mod._verify_suite_context(ctx, applied) is True


@pytest.mark.asyncio
async def test_reconcile_keeps_matching_job_and_flags_drift(db):
    mod = _load_prefill()
    org_id = await _seed_org(db)
    await _seed_suite_jobs(db, org_id)

    # context already matches the only completed cto job → no rewrite needed
    # (production shape: the state's embedded job_id == the AgentJob row id)
    db.add(_job(org_id, "cto", created=_T0, status=AgentJobStatus.COMPLETED,
                result={"job_id": "cto-job-stale",
                        "cto_summary": {"overall_health_score": 0.0}},
                jid="cto-job-stale"))
    await db.commit()

    applied = await mod._reconcile_suite_context(db, org_id)
    db.expire_all()
    ctx = await get_company_context(org_id, db)

    assert applied["cto"] == "cto-job-stale"
    assert ctx.last_cto_result["job_id"] == "cto-job-stale"
    assert mod._verify_suite_context(ctx, applied) is True

    # verification catches drift: a result pointing at another job fails
    ctx.last_cto_result = {"job_id": "someone-elses", "cto_summary": {}}
    assert mod._verify_suite_context(ctx, {"cto": "cto-job-stale"}) is False
    # …and a missing result fails too
    ctx.last_chro_result = None
    assert mod._verify_suite_context(ctx, {"chro": "chro-1"}) is False
