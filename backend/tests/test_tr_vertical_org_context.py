"""The TR autopilot uses what this organisation's accountant taught the agent.

`/muhasebe/analiz` passed the organisation's learned rules and its measured trust
history to the accounting agent; the autopilot (`/muhasebe/tr-vertical`) and its
resume (`POST /runs/{id}/resume`) did neither, so the same company was classified
one way by hand and another by the autopilot, and the trust it had earned was
unused on the path that runs unattended.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents.state import AgentRunConfig
from app.agents.tr_vertical import run_tr_vertical
from app.models.agent_run import AgentRun
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.accounting.ogrenilmis_kural import KurumKurali, anahtar_uret, ogren
from app.services.accounting.org_context import yukle
from tests.api_helpers import kullanici

_CFG = AgentRunConfig(require_review=False, auto_proceed_min_confidence=0.0)
CSV = "date,description,amount,type,category\n2024-01-05,Reklam gideri Meta,-5000,expense,marketing\n"
KURAL = {anahtar_uret("Reklam gideri Meta"): KurumKurali(anahtar_uret("Reklam gideri Meta"), "760", None, 2)}


@pytest.fixture
def _csv(tmp_path):
    f = tmp_path / "tr.csv"
    f.write_text(CSV, encoding="utf-8")
    return str(f)


async def _entry(_csv, **kw):
    res = await run_tr_vertical(
        job_id="trv-ctx", file_path=_csv, file_type="csv", company_name="X", period="2024-01",
        run_config=_CFG, **kw,
    )
    assert res.accounting_journal, res.errors
    return res.accounting_journal[0]


async def test_the_autopilot_uses_a_learned_rule(_csv):
    e = await _entry(_csv, kurum_kurallari=KURAL)
    assert e["thp_hesap_kodu"] == "760" and e["guven"]["seviye"] == "ogrenilmis"


async def test_the_autopilot_uses_the_organisations_measured_trust(_csv):
    # 30 of 30 of its own decisions at this level: trust comes from that record.
    e = await _entry(_csv, kurum_kurallari=KURAL, guven_gecmisi={"ogrenilmis": (30, 30)})
    assert e["guven"]["kaynak"] == "kurum" and e["confidence"] > 0.8


async def test_without_either_the_autopilot_is_unchanged(_csv):
    e = await _entry(_csv)
    assert e["guven"]["seviye"] != "ogrenilmis"


# ── the shared loader ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_loader_returns_rules_and_history_for_one_organisation(client):
    _h, org, uid = await kullanici(client, "ctx@x.com", role="owner")
    async with client._maker() as db:
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                          org_id=org, user_id=uid, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        db.add(SMMMOnayKaydi(
            job_id=job.id, org_id=org, kayit_id="k", durum=OnayDurumu.ONAYLANDI,
            orijinal_kayit={"guven": {"seviye": "kural"}},
        ))
        for _ in range(2):
            await ogren(db, org, "Reklam gideri Meta", None, "760")
        await db.commit()

    async with client._maker() as db:
        ctx = await yukle(db, org)
        empty = await yukle(db, None)
    assert ctx["guven_gecmisi"] == {"kural": (1, 1)}
    assert [k.hesap_kodu for k in ctx["kurum_kurallari"].values()] == ["760"]
    assert empty == {"guven_gecmisi": {}, "kurum_kurallari": {}}


# ── both entry points pass it ────────────────────────────────────────────────

async def _seed(client, email):
    h, org, uid = await kullanici(client, email, role="owner")
    async with client._maker() as db:
        (await db.get(Organization, org)).regional_packs = ["tr"]
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                          org_id=org, user_id=uid, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        for _ in range(2):
            await ogren(db, org, "Reklam gideri Meta", None, "760")
        await db.commit()
        return h, org, job.id


def _spy(monkeypatch, store):
    from app.agents.tr_vertical import TRVerticalResult

    async def fake(**kw):
        store.update(kw)
        return TRVerticalResult(job_id=kw["job_id"], stage="done")

    monkeypatch.setattr("app.agents.tr_vertical.run_tr_vertical", fake)


@pytest.mark.asyncio
async def test_the_autopilot_route_loads_the_organisations_context(client, monkeypatch):
    h, _org, job_id = await _seed(client, "r1@x.com")
    seen: dict = {}
    _spy(monkeypatch, seen)
    r = await client.post("/api/v1/muhasebe/tr-vertical", json={"job_id": job_id}, headers=h)
    assert r.status_code == 201, r.text
    assert [k.hesap_kodu for k in seen["kurum_kurallari"].values()] == ["760"]
    assert "guven_gecmisi" in seen


@pytest.mark.asyncio
async def test_resume_loads_the_organisations_context_too(client, monkeypatch):
    h, org, job_id = await _seed(client, "r2@x.com")
    async with client._maker() as db:
        run = AgentRun(pipeline="tr_vertical", org_id=org, job_id=job_id, status="failed",
                       started_at=datetime.now(UTC))
        db.add(run)
        await db.commit()
        run_id = run.id
    seen: dict = {}

    async def fake_resume(db, rid, entrypoint, **kw):
        from app.agents.tr_vertical import TRVerticalResult

        seen.update(kw)
        return None, TRVerticalResult(job_id=kw["job_id"], stage="done")

    monkeypatch.setattr("app.agents.run_ledger.resume_run", fake_resume)
    r = await client.post(f"/api/v1/runs/{run_id}/resume", headers=h)
    assert r.status_code in (200, 201), r.text
    assert [k.hesap_kodu for k in seen["kurum_kurallari"].values()] == ["760"]
    assert "guven_gecmisi" in seen
