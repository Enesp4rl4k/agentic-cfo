"""Kurumsallaşma Endeksi — scoring from real platform signals."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 — model registration
from app.database import Base
from app.models.agent_run import AgentRun
from app.models.analysis_job import AnalysisJob
from app.models.authority_policy import AuthorityPolicy
from app.models.defensibility_packet import DefensibilityPacket
from app.models.report import Report, ReportFormat
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.institutionalization import WEIGHTS, compute_index

ORG = "org-fam"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_empty_org_scores_low_with_recommendations(db):
    res = await compute_index(ORG, db)
    assert res["overall_score"] < 40
    assert res["grade"] in {"D", "E"}
    assert len(res["recommendations"]) >= 3
    assert {d["key"] for d in res["dimensions"]} == set(WEIGHTS)
    # weakest-first ordering
    weakest = min(res["dimensions"], key=lambda d: d["score"])["key"]
    assert res["recommendations"][0]["dimension"] == weakest


@pytest.mark.asyncio
async def test_signals_raise_the_relevant_dimensions(db):
    # analysis history across 8 distinct months
    for m in range(1, 9):
        db.add(AnalysisJob(
            filename=f"{m}.csv", file_path="/x", file_type="csv", org_id=ORG,
            created_at=datetime(2026, m, 10, tzinfo=UTC),
        ))
    await db.flush()
    jobs = (await db.execute(
        __import__("sqlalchemy").select(AnalysisJob).where(AnalysisJob.org_id == ORG)
    )).scalars().all()

    # a custom authority policy with two roles
    db.add(AuthorityPolicy(
        org_id=ORG, version=1, active=True,
        rules=[
            {"id": "a", "domain": "spending", "when": {"amount_kurus_lt": 100},
             "decision": "require_approvals", "approvals": [{"role": "finance", "count": 1}]},
            {"id": "b", "domain": "*", "when": {},
             "decision": "require_approvals", "approvals": [{"role": "owner", "count": 1}]},
        ],
    ))
    # journal report for one job — balanced, high confidence
    db.add(Report(
        job_id=jobs[0].id, report_type="tr_muhasebe_journal", report_format=ReportFormat.JSON,
        data={"dengeli": True, "ortalama_confidence": 0.92,
              "yevmiye_kayitlari": [
                  {"thp_hesap_kodu": "600", "authority": {"outcome": "auto_approve", "matched_rule_id": "b"}},
              ]},
    ))
    # run ledger + a finalized defensibility packet
    db.add(AgentRun(org_id=ORG, pipeline="tr_vertical", job_id=jobs[0].id, status="completed"))
    db.add(DefensibilityPacket(org_id=ORG, job_id=jobs[0].id, period="2026-01", status="finalized"))
    # SMMM review — two approvers, all actioned quickly
    now = datetime.now(UTC)
    db.add(SMMMOnayKaydi(job_id=jobs[0].id, org_id=ORG, kayit_id="k1",
                         durum=OnayDurumu.ONAYLANDI, onaylayan_user_id="u1",
                         created_at=now - timedelta(hours=5), onay_zamani=now - timedelta(hours=3)))
    db.add(SMMMOnayKaydi(job_id=jobs[0].id, org_id=ORG, kayit_id="k2",
                         durum=OnayDurumu.DUZELTILDI, onaylayan_user_id="u2",
                         created_at=now - timedelta(hours=4), onay_zamani=now - timedelta(hours=2)))
    await db.commit()

    res = await compute_index(ORG, db)
    dims = {d["key"]: d["score"] for d in res["dimensions"]}
    assert dims["delegated_authority"] >= 60          # custom policy + 2 roles
    assert dims["process_cadence"] >= 60              # 8/12 months
    assert dims["human_oversight"] >= 70              # all actioned, fast
    assert dims["decision_traceability"] > 15         # run + finalized packet
    assert dims["key_person_risk"] >= 45              # two approvers
    assert res["overall_score"] > (await compute_index("org-empty", db))["overall_score"]


@pytest.mark.asyncio
async def test_single_approver_flags_key_person_risk(db):
    db.add(AnalysisJob(filename="j.csv", file_path="/x", file_type="csv", org_id=ORG))
    await db.flush()
    for i in range(5):
        db.add(SMMMOnayKaydi(job_id="j", org_id=ORG, kayit_id=f"k{i}",
                             durum=OnayDurumu.ONAYLANDI, onaylayan_user_id="only-boss"))
    await db.commit()
    res = await compute_index(ORG, db)
    kpr = next(d for d in res["dimensions"] if d["key"] == "key_person_risk")
    assert kpr["score"] <= 55
    assert any("yedek onaylayıcı" in r["text"] for r in res["recommendations"])
