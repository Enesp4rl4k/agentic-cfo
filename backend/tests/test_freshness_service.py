"""Real freshness — one measured value, three consumers. (P0 · Güven)

The old OKR agent carried per-KR hardcoded `data_freshness_days` (7, 14,
30…) that fed confidence while pretending to be measurements. P0 kills
that fiction:

  - one org-level age computed from real source columns
    (`services.freshness.age_from_items` — worst age among sources),
  - surfaced at `GET /data/freshness` (same columns as the packet strip),
  - consumed by OKR confidence as-is; unknown scores neutral (0.5),
    never "very confident".

No LLM and no API key is needed anywhere in this file.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def client():
    """In-memory FastAPI client + clean schema (mirrors test_decision_packet)."""
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


async def _user(client, email: str, *, attach_org: bool = True):
    """Register → attach a fresh org (mirrors test_decision_packet)."""
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
        user_id = user.id
        await db.commit()
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPassword123!"},
        )
    ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, org_id, user_id


async def _seed_job_with_txns(client, org_id: str, *, txn_days_old: int = 3):
    """Job with fresh transactions (file age 0, coverage = txn_days_old)."""
    from datetime import UTC, datetime, timedelta

    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.transaction import Transaction

    async with client._maker() as db:  # type: ignore[attr-defined]
        job = AnalysisJob(
            filename="m.csv",
            file_path="/m.csv",
            file_type="csv",
            org_id=org_id,
            status=JobStatus("awaiting_review"),
            awaiting_review=True,
            min_confidence=0.6,
        )
        db.add(job)
        await db.flush()
        when = datetime.now(UTC) - timedelta(days=txn_days_old)
        db.add(
            Transaction(
                job_id=job.id,
                amount_kurus=100_00,
                currency="TRY",
                type="expense",
                category="rent",
                description="kira",
                transaction_date=when,
            )
        )
        await db.commit()
        return job.id


# ── Servis: yaş = kaynakların en kötüsü ──────────────────────────────────────

async def test_age_summary_unknown_without_any_source(client):
    """Org with no job and no connector: nothing to be fresh *about*."""
    from app.services.freshness import org_age_summary

    _, org_id, _ = await _user(client, "temiz@example.com")
    async with client._maker() as db:  # type: ignore[attr-defined]
        age = await org_age_summary(db, org_id)
    assert age == {"days": None, "quality": "unknown", "sources": 0}


async def test_age_summary_fresh_sources_are_high(client):
    """Fresh file + fresh coverage + 2-day-old connector → high quality."""
    from datetime import UTC, datetime, timedelta

    from app.models.connector_connection import ConnectorConnection
    from app.services.freshness import org_age_summary

    _, org_id, _ = await _user(client, "taze@example.com")
    await _seed_job_with_txns(client, org_id, txn_days_old=3)
    async with client._maker() as db:  # type: ignore[attr-defined]
        db.add(
            ConnectorConnection(
                org_id=org_id,
                connector="github",
                status="active",
                display_name="GitHub",
                last_sync_at=datetime.now(UTC) - timedelta(days=2),
                last_status="ok",
            )
        )
        await db.commit()
        age = await org_age_summary(db, org_id)
    assert age["days"] is not None and age["days"] <= 7
    assert age["quality"] == "high"
    assert age["sources"] >= 3  # file + coverage + connector


async def test_age_summary_worst_age_wins(client):
    """One 45-day-stale connector → org age ≥45, quality low (part of the
    picture is 45 days old even if the file arrived today)."""
    from datetime import UTC, datetime, timedelta

    from app.models.connector_connection import ConnectorConnection
    from app.services.freshness import org_age_summary

    _, org_id, _ = await _user(client, "eski@example.com")
    await _seed_job_with_txns(client, org_id, txn_days_old=1)
    async with client._maker() as db:  # type: ignore[attr-defined]
        db.add(
            ConnectorConnection(
                org_id=org_id,
                connector="github",
                status="error",
                display_name="GitHub",
                last_sync_at=datetime.now(UTC) - timedelta(days=45),
                last_status="error",
            )
        )
        await db.commit()
        age = await org_age_summary(db, org_id)
    assert age["days"] >= 45
    assert age["quality"] == "low"


async def test_age_summary_never_synced_source_is_a_gap(client):
    """A never-synced connector has no age — a blind spot, not "fresh"."""
    from app.models.connector_connection import ConnectorConnection
    from app.services.freshness import org_age_summary

    _, org_id, _ = await _user(client, "bos@example.com")
    await _seed_job_with_txns(client, org_id, txn_days_old=1)
    async with client._maker() as db:  # type: ignore[attr-defined]
        db.add(
            ConnectorConnection(
                org_id=org_id,
                connector="github",
                status="pending",
                display_name="GitHub",
                last_sync_at=None,
                last_status=None,
            )
        )
        await db.commit()
        age = await org_age_summary(db, org_id)
    assert age["quality"] == "low"
    assert age["days"] is not None  # file/coverage still date the org


# ── Endpoint: GET /data/freshness ────────────────────────────────────────────

async def test_endpoint_rejects_user_without_org(client):
    headers, org_id, _ = await _user(client, "koprusuz@example.com", attach_org=False)
    assert org_id is None
    r = await client.get("/api/v1/data/freshness", headers=headers)
    assert r.status_code == 400
    assert "kuruluş" in r.json()["error"]


async def test_endpoint_returns_items_summary_and_age(client):
    from datetime import UTC, datetime, timedelta

    from app.models.connector_connection import ConnectorConnection

    headers, org_id, _ = await _user(client, "uc@example.com")
    await _seed_job_with_txns(client, org_id, txn_days_old=10)
    async with client._maker() as db:  # type: ignore[attr-defined]
        db.add(
            ConnectorConnection(
                org_id=org_id,
                connector="github",
                status="error",
                display_name="GitHub",
                last_sync_at=datetime.now(UTC) - timedelta(days=45),
                last_status="error",
            )
        )
        await db.commit()

    r = await client.get("/api/v1/data/freshness", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()["data"]

    sources = {i["source"] for i in d["items"]}
    assert "analysis_file" in sources
    assert "coverage" in sources
    assert "connector:github" in sources

    # Stale connector drives the headline + the age.
    assert d["summary"]["worst"] == "stale"
    assert d["summary"]["counts"]["stale"] == 1
    assert d["age"]["days"] >= 45
    assert d["age"]["quality"] == "low"


async def test_endpoint_requires_auth(client):
    r = await client.get("/api/v1/data/freshness")
    assert r.status_code in (401, 403)


# ── OKR: sahte tazelik gitti ─────────────────────────────────────────────────

def _all_krs(objectives):
    return [kr for obj in objectives for kr in obj["key_results"]]


def test_okr_uses_measured_freshness_not_hardcoded():
    from app.agents.ceo.okr_agent import _confidence_from_data_freshness, _infer_okrs

    objs = _infer_okrs(
        None, None, None, "2026-Q3",
        freshness={"days": 45, "quality": "low"},
    )
    krs = _all_krs(objs)
    assert krs
    expected = _confidence_from_data_freshness(
        days_since_update=45, data_quality="low"
    )
    for kr in krs:
        assert kr["data_freshness_days"] == 45       # measured, org-wide
        assert kr["data_freshness_source"] == "org"
        assert kr["confidence"] == expected
        assert kr["confidence"] < 1.0


def test_okr_unknown_freshness_is_neutral_not_perfect():
    """No measurement → None + 0.5. The old code scored unknown as the
    *maximum* confidence (None → 0 days → 1.0) — trust was manufactured."""
    from app.agents.ceo.okr_agent import _infer_okrs

    objs = _infer_okrs(None, None, None, "2026-Q3")
    krs = _all_krs(objs)
    assert krs
    for kr in krs:
        assert kr["data_freshness_days"] is None
        assert kr["data_freshness_source"] == "unknown"
        assert kr["confidence"] == 0.5


def test_okr_no_hardcoded_days_left_in_defaults():
    """The fictional per-KR days (7/5/14/1/3/30) are gone from the schema."""
    from app.agents.ceo.okr_agent import _infer_okrs

    objs = _infer_okrs(None, None, None, "2026-Q3")
    for kr in _all_krs(objs):
        # With no measurement there is exactly one honest value: None.
        assert kr["data_freshness_days"] is None
