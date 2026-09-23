"""Forecast backtest — tutmayan tahmini söyleyen kalibrasyon satırı. (P3)

Pinned:

  1. three closed pairs → MAE / sMAPE / band coverage / bias, with the
     lira→kuruş boundary conversion (`report_agent._fmt` stores lira,
     the ledger stores kuruş) checked through hand-computed numbers;
  2. fewer than three pairs → "yeterli veri yok", never a metric on
     noise; an unclosed 365-day window is not a pair;
  3. claims are org-scoped, the route is authenticated, an org-less
     account is refused with the standard error body;
  4. the decision packet carries `calibration`.

No LLM and no API key is needed anywhere in this file.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def client():
    """In-memory FastAPI client + clean schema (mirrors test_decisions)."""
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


async def _user(client, email: str, *, attach_org: bool = True) -> tuple:
    """Register → optionally attach an org → login (mirrors test_decisions)."""
    from sqlalchemy import select

    from app.models.organization import Organization
    from app.models.user import User

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPassword123!", "full_name": "T"},
    )
    async with client._maker() as db:  # type: ignore[attr-defined]
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        org_id = None
        if attach_org:
            org = Organization(name=email, slug=email.split("@")[0])
            db.add(org)
            await db.flush()
            user.org_id = org.id
            org_id = org.id
        await db.commit()
        user_id = user.id
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPassword123!"},
        )
    ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, org_id, user_id


async def _seed_claim(
    client,
    org_id: str,
    *,
    days_ago: int,
    base: float,
    pess: float,
    opt: float,
) -> str:
    """A finished job whose JSON report claims `base` twelve-month net (lira).

    Report timestamps are explicit: the claim's 365-day window opens at
    `days_ago` and closes `WINDOW_DAYS` later.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.report import Report, ReportFormat, ReportType

    when = datetime.now(UTC) - timedelta(days=days_ago)
    async with client._maker() as db:  # type: ignore[attr-defined]
        job = AnalysisJob(
            filename="m.csv",
            file_path="/m.csv",
            file_type="csv",
            org_id=org_id,
            status=JobStatus.COMPLETED,
            created_at=when,
        )
        db.add(job)
        await db.flush()
        db.add(
            Report(
                job_id=job.id,
                report_type=ReportType.FULL,
                report_format=ReportFormat.JSON,
                created_at=when,
                data={
                    "pnl": {"revenue": 12_000_000.0},
                    "cashflow": {"net_change": 500_000.0},
                    "forecast": {
                        "scenarios": {
                            "pessimistic": {"twelve_month_net": pess},
                            "base": {"twelve_month_net": base, "runway_months": 9.5},
                            "optimistic": {"twelve_month_net": opt},
                        }
                    },
                },
            )
        )
        await db.commit()
        return job.id


async def _seed_data_job(
    client, org_id: str, *, txns: tuple[tuple[int, str, int], ...] = ()
) -> str:
    """The newest finished job — realisations are read from ITS rows.

    `txn_days` entries are (days_ago, type, amount_kurus).
    """
    from datetime import UTC, datetime, timedelta

    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.transaction import Transaction

    async with client._maker() as db:  # type: ignore[attr-defined]
        job = AnalysisJob(
            filename="d.csv",
            file_path="/d.csv",
            file_type="csv",
            org_id=org_id,
            status=JobStatus.COMPLETED,
        )
        db.add(job)
        await db.flush()
        now = datetime.now(UTC)
        for days_ago, tx_type, amount in txns:
            db.add(
                Transaction(
                    job_id=job.id,
                    amount_kurus=amount,
                    currency="TRY",
                    type=tx_type,
                    category="revenue" if tx_type == "income" else "rent",
                    description="seed",
                    transaction_date=now - timedelta(days=days_ago),
                )
            )
        await db.commit()
        return job.id


async def _get_backtest(client, headers) -> dict:
    r = await client.get("/api/v1/analytics/forecast-backtest", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ── 1. Üç kapanmış çift → dürüst metrikler ───────────────────────────────────

async def test_three_pairs_yield_honest_metrics(client):
    headers, org_id, _ = await _user(client, "metrik@example.com")

    # Claims in LIRA (report convention), realised rows in KURUŞ.
    #   claim 1: F=100M kr, window days_ago [730,1095) → realised  80M
    #   claim 2: F=200M kr, window days_ago [365, 730) → realised 200M
    #   claim 3: F=300M kr, window days_ago [ 35, 400) → realised 360M
    await _seed_claim(client, org_id, days_ago=1095, base=1_000_000, pess=800_000, opt=1_200_000)
    await _seed_claim(client, org_id, days_ago=730, base=2_000_000, pess=1_800_000, opt=2_500_000)
    await _seed_claim(client, org_id, days_ago=400, base=3_000_000, pess=2_000_000, opt=3_300_000)
    await _seed_data_job(
        client,
        org_id,
        txns=(
            (900, "income", 90_000_000),
            (900, "expense", 10_000_000),
            (500, "income", 250_000_000),
            (500, "expense", 50_000_000),
            (100, "income", 400_000_000),
            (100, "expense", 40_000_000),
        ),
    )

    #   errors: |20M|, 0, |60M|      → MAE   = 26_666_667
    #   signed: +20M, 0, −60M        → bias  = −13_333_333
    #   sMAPE: 20/90, 0, 60/330      → 13.5
    #   band coverage: 80M ∈ [80,120], 200M ∈ [180,250], 360M ∉ [200,330] → 66.7
    data = await _get_backtest(client, headers)
    assert data == {
        "status": "ok",
        "pairs": 3,
        "mae_kurus": 26_666_667,
        "smape_pct": 13.5,
        "coverage_pct": 66.7,
        "bias_kurus": -13_333_333,
    }


# ── 2. Üçten az çift → metrik uydurma ────────────────────────────────────────

async def test_two_pairs_refuse_to_guess(client):
    headers, org_id, _ = await _user(client, "ikili@example.com")
    await _seed_claim(client, org_id, days_ago=1095, base=1_000_000, pess=800_000, opt=1_200_000)
    await _seed_claim(client, org_id, days_ago=730, base=2_000_000, pess=1_800_000, opt=2_500_000)
    await _seed_data_job(client, org_id)

    data = await _get_backtest(client, headers)
    assert data == {"status": "yeterli veri yok", "pairs": 2}


async def test_unclosed_window_is_not_a_pair(client):
    # Three claims, each inside the last 12 months: the window that the
    # forecast covers has not closed yet — zero pairs, not three guesses.
    headers, org_id, _ = await _user(client, "mumlu@example.com")
    await _seed_claim(client, org_id, days_ago=300, base=1_000_000, pess=800_000, opt=1_200_000)
    await _seed_claim(client, org_id, days_ago=200, base=2_000_000, pess=1_800_000, opt=2_500_000)
    await _seed_claim(client, org_id, days_ago=100, base=3_000_000, pess=2_000_000, opt=3_300_000)
    await _seed_data_job(client, org_id)

    data = await _get_backtest(client, headers)
    assert data == {"status": "yeterli veri yok", "pairs": 0}


# ── 3. Kuruluş sınırları ve erişim ───────────────────────────────────────────

async def test_other_orgs_claims_do_not_leak(client):
    headers, org_id, _ = await _user(client, "dar@example.com")
    _, other_org, _ = await _user(client, "baska@example.com")
    await _seed_claim(client, other_org, days_ago=1095, base=1_000_000, pess=800_000, opt=1_200_000)
    await _seed_claim(client, other_org, days_ago=730, base=2_000_000, pess=1_800_000, opt=2_500_000)
    await _seed_claim(client, other_org, days_ago=400, base=3_000_000, pess=2_000_000, opt=3_300_000)
    await _seed_data_job(
        client, other_org, txns=((500, "income", 200_000_000),)
    )

    data = await _get_backtest(client, headers)
    assert data == {"status": "yeterli veri yok", "pairs": 0}


async def test_requires_auth(client):
    r = await client.get("/api/v1/analytics/forecast-backtest")
    assert r.status_code in (401, 403)


async def test_user_without_org_is_refused(client):
    headers, org_id, _ = await _user(client, "kurulusuz@example.com", attach_org=False)
    assert org_id is None
    r = await client.get("/api/v1/analytics/forecast-backtest", headers=headers)
    assert r.status_code == 400
    assert "kuruluş" in r.json()["error"]


# ── 4. Paket calibration satırını taşır ──────────────────────────────────────

async def test_packet_carries_calibration(client):
    headers, org_id, _ = await _user(client, "paket@example.com")
    job_id = await _seed_claim(client, org_id, days_ago=1095, base=1_000_000, pess=800_000, opt=1_200_000)
    await _seed_claim(client, org_id, days_ago=730, base=2_000_000, pess=1_800_000, opt=2_500_000)
    await _seed_claim(client, org_id, days_ago=400, base=3_000_000, pess=2_000_000, opt=3_300_000)
    await _seed_data_job(
        client,
        org_id,
        txns=(
            (900, "income", 90_000_000),
            (900, "expense", 10_000_000),
            (500, "income", 250_000_000),
            (500, "expense", 50_000_000),
            (100, "income", 400_000_000),
            (100, "expense", 40_000_000),
        ),
    )

    r = await client.get(
        f"/api/v1/analysis/{job_id}/decision-packet", headers=headers
    )
    assert r.status_code == 200, r.text
    cal = r.json()["data"]["calibration"]
    assert cal["status"] == "ok"
    assert cal["pairs"] == 3
