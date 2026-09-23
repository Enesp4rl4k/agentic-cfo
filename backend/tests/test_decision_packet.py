"""Decision packet — the four questions asked before anyone signs.

`GET /analysis/{id}/decision-packet` must answer, deterministically:

  1. Ne oldu?          → situation (report numbers, anomaly count, gate)
  2. Hangi seçenekler? → baseline + the preset counterfactuals, each with
                         a *computed* 12-month effect
  3. Veri ne taze?     → freshness chips from real source columns —
                         a stale connector must read "stale", not "fresh"
  4. Geçmişte ne oldu? → this org's precedent + open actions

Plus the contract edges: mid-run jobs have nothing to decide (409),
other tenants' jobs don't exist (404), a missing report degrades to an
empty options list with the freshness strip still present.

No LLM and no API key is needed anywhere in this file — that is itself
the determinism test.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def client():
    """In-memory FastAPI client + clean schema (mirrors test_review_approval)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _user(client, email: str) -> tuple[dict[str, str], str, str]:
    """Register → attach a fresh org (mirrors test_review_approval)."""
    from sqlalchemy import select

    from app.models.organization import Organization
    from app.models.user import User

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPassword123!", "full_name": "T"},
    )
    async with client._maker() as db:  # type: ignore[attr-defined]
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        org = Organization(name=email, slug=email.split("@")[0])
        db.add(org)
        await db.flush()
        user.org_id = org.id
        await db.commit()
        org_id, user_id = org.id, user.id
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPassword123!"},
        )
    ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, org_id, user_id


async def _seed_job(
    client,
    org_id: str,
    *,
    status="awaiting_review",
    awaiting=True,
    with_report=True,
):
    """Job + full report + anomaly + two transactions (10 days old coverage)."""
    from datetime import UTC, datetime, timedelta

    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.anomaly import Anomaly
    from app.models.report import Report, ReportFormat, ReportType
    from app.models.transaction import Transaction

    async with client._maker() as db:  # type: ignore[attr-defined]
        job = AnalysisJob(
            filename="m.csv",
            file_path="/m.csv",
            file_type="csv",
            org_id=org_id,
            status=JobStatus(status),
            awaiting_review=awaiting,
            min_confidence=0.6 if awaiting else None,
        )
        db.add(job)
        await db.flush()

        if with_report:
            db.add(
                Report(
                    job_id=job.id,
                    report_type=ReportType.FULL,
                    report_format=ReportFormat.JSON,
                    # The stored report is LIRA (production shape —
                    # report_agent._fmt divides the pipeline's cents);
                    # load_pnl_cashflow_forecast converts money to kuruş,
                    # so the assertions below still read kuruş.
                    data={
                        "pnl": {
                            "revenue": 12_000_000,
                            "total_opex": 8_000_000,
                            "net_margin": 0.2,
                            "opex": {"salary": 4_000_000, "rent": 1_000_000},
                        },
                        "cashflow": {"net_change": 500_000},
                        "forecast": {
                            "scenarios": {
                                "base": {
                                    "runway_months": 9.5,
                                    "twelve_month_net": 3_000_000,
                                }
                            }
                        },
                    },
                )
            )
            db.add(
                Anomaly(
                    job_id=job.id,
                    anomaly_type="duplicate",
                    severity="high",
                    title="Mükerrer ödeme",
                    description="Aynı tutar iki kez",
                    confidence=0.9,
                )
            )
            old = datetime.now(UTC) - timedelta(days=10)
            for i in range(2):
                db.add(
                    Transaction(
                        job_id=job.id,
                        amount_kurus=100_00,
                        currency="TRY",
                        type="expense",
                        category="rent",
                        description=f"kira {i}",
                        transaction_date=old,
                    )
                )
        await db.commit()
        return job.id


# ── 1. Dört soru ─────────────────────────────────────────────────────────────

async def test_packet_answers_all_four_questions(client):
    headers, org_id, _ = await _user(client, "paket@example.com")
    job_id = await _seed_job(client, org_id)

    r = await client.get(f"/api/v1/analysis/{job_id}/decision-packet", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()["data"]

    # 2. Seçenekler: baseline + en az bir preset, baseline referans = 0
    opts = d["options"]
    assert len(opts) >= 2, "baseline + at least one preset"
    assert opts[0]["id"] == "baseline"
    assert opts[0]["baseline"] is True
    assert opts[0]["base_net_impact"] == 0
    assert opts[0]["runway_after"] == 9.5
    presets = [o for o in opts if not o["baseline"]]
    assert all("base_net_impact" in o and "assumptions" in o for o in presets)

    # 1. Durum: raporun kendi rakamları + anomal sayısı + gate
    s = d["situation"]
    assert s["revenue_12m"] == 12_000_000_00
    assert s["top_opex_category"] == "salary"
    assert s["runway_months"] == 9.5
    assert s["anomaly_count"] == 1
    assert d["gate"]["held_for_review"] is True
    assert d["gate"]["reason"]  # neden insan kontrolünde — açıkça yazıyor

    # 3. Tazelik: gerçek kaynak sütunlarından, yaş sayısal
    states = {f["source"]: f for f in d["freshness"]}
    assert "analysis_file" in states and "coverage" in states
    assert states["coverage"]["age_days"] == 10  # transaction_date = 10 gün önce
    assert states["coverage"]["state"] == "aging"
    assert all(f["state"] in {"fresh", "aging", "stale", "never", "unknown"} for f in d["freshness"])

    # 4. Emsal: bu org'un kayıtları (kayıt yok → boş ama yapı var)
    assert d["precedent"] == {"decisions": [], "pending_actions": 0}

    # Kanıt: best-effort string (chunk yokken "")
    assert isinstance(d["evidence"], str)


# ── 3. Tazelik: bayat connector gerçekten bayat ─────────────────────────────

async def test_stale_connector_reads_stale_not_fresh(client):
    from datetime import UTC, datetime, timedelta

    from app.models.connector_connection import ConnectorConnection

    headers, org_id, _ = await _user(client, "bayat@example.com")
    job_id = await _seed_job(client, org_id)

    async with client._maker() as db:  # type: ignore[attr-defined]
        db.add(
            ConnectorConnection(
                org_id=org_id,
                connector="github",
                status="active",
                last_sync_at=datetime.now(UTC) - timedelta(days=45),
            )
        )
        await db.commit()

    r = await client.get(f"/api/v1/analysis/{job_id}/decision-packet", headers=headers)
    assert r.status_code == 200
    conn_items = [f for f in r.json()["data"]["freshness"] if f["source"] == "connector:github"]
    assert len(conn_items) == 1
    assert conn_items[0]["state"] == "stale"
    assert conn_items[0]["age_days"] >= 45


# ── Henüz karar verilemez / yetki kenarları ─────────────────────────────────

async def test_running_job_is_409(client):
    headers, org_id, _ = await _user(client, "calisiyor@example.com")
    job_id = await _seed_job(client, org_id, status="analyzing", awaiting=False)

    r = await client.get(f"/api/v1/analysis/{job_id}/decision-packet", headers=headers)
    assert r.status_code == 409


async def test_other_tenants_job_is_404(client):
    _, org_a, _ = await _user(client, "a@example.com")
    other_headers, _, _ = await _user(client, "b@example.com")
    job_id = await _seed_job(client, org_a)

    r = await client.get(f"/api/v1/analysis/{job_id}/decision-packet", headers=other_headers)
    assert r.status_code == 404


async def test_missing_job_is_404(client):
    headers, _, _ = await _user(client, "yok@example.com")
    r = await client.get("/api/v1/analysis/does-not-exist/decision-packet", headers=headers)
    assert r.status_code == 404


# ── Bozuk/eksik veri: düşmez, dürüst kalır ─────────────────────────────────

async def test_no_report_degrades_to_empty_options(client):
    headers, org_id, _ = await _user(client, "raporyok@example.com")
    job_id = await _seed_job(client, org_id, awaiting=False, with_report=False)

    r = await client.get(f"/api/v1/analysis/{job_id}/decision-packet", headers=headers)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["options"] == []          # seçenek yoksa uydurmuyor
    assert d["freshness"]              # ama tazelik şeridi yine dürüst
    assert d["gate"]["held_for_review"] is False
    assert d["gate"]["reason"] is None


# ── Parite: paket ile simulate endpoint'i aynı sayıyı okuyor ───────────────

async def test_packet_and_scenarios_endpoint_agree(client):
    headers, org_id, _ = await _user(client, "parite@example.com")
    job_id = await _seed_job(client, org_id)

    packet = await client.get(
        f"/api/v1/analysis/{job_id}/decision-packet", headers=headers
    )
    scenarios = await client.get(
        f"/api/v1/counterfactual/scenarios/{job_id}", headers=headers
    )
    assert scenarios.status_code == 200, scenarios.text

    packet_presets = [
        (o["label"], o["base_net_impact"])
        for o in packet.json()["data"]["options"]
        if not o["baseline"]
    ]
    endpoint_presets = [
        (s["label"], s["base_net_impact"])
        for s in scenarios.json()["data"]["scenarios"]
    ]
    # Aynı paylaşılan preset kurucusu → aynı etiketler ve aynı sonuçlar.
    assert packet_presets == endpoint_presets
    assert len(packet_presets) >= 1


# ── Birim sınırı: saklanan rapor lira, bu yol kuruş ─────────────────────────

async def test_loader_normalizes_report_lira_to_kurus(client):
    """The stored report is lira (`report_agent._fmt` divides the pipeline's
    cents); every consumer of this loader — the panel's fmtTL, the engine's
    own /100, the ledger snapshot — reads kuruş. Ratios and month counts
    must not move."""
    from app.services.decision_packet import load_pnl_cashflow_forecast

    _headers, org_id, _ = await _user(client, "birim@example.com")
    job_id = await _seed_job(client, org_id)

    async with client._maker() as db:  # type: ignore[attr-defined]
        pnl, cashflow, forecast = await load_pnl_cashflow_forecast(db, job_id)

    # Para: lira tohumu ×100 = kuruş (aynı değerler, doğru birim)
    assert pnl["revenue"] == 1_200_000_000           # 12_000_000_00
    assert pnl["total_opex"] == 800_000_000          # 8_000_000_00
    assert pnl["opex"]["salary"] == 400_000_000      # 4_000_000_00
    assert cashflow["net_change"] == 50_000_000      # 500_000_00
    base = forecast["scenarios"]["base"]
    assert base["twelve_month_net"] == 300_000_000   # 3_000_000_00

    # Para değil: oran ve ay sayıları dokunulmaz
    assert pnl["net_margin"] == 0.2
    assert base["runway_months"] == 9.5
