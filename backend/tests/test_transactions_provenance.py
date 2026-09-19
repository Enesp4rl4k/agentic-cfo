"""İşlem listesi, bir kaydın neden bekletildiğini söyleyebilmeli.

`date_is_estimated`, the tax the source document stated, and the parser's own
note were all persisted on every transaction and none was returned by
`GET /analysis/{job_id}/transactions`. A reviewer looking at a held row could
not see that its date was invented or what the invoice said about KDV — the
facts that decide whether to approve it. A live e-SMM upload showed `raw_text`
coming back empty for a row that had one.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c._maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _user(client, email: str) -> tuple[dict[str, str], str]:
    from app.models.organization import Organization
    from app.models.user import User

    await client.post("/api/v1/auth/register",
                      json={"email": email, "password": "StrongPassword123!", "full_name": "T"})
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": "StrongPassword123!"})
             ).json()["data"]["access_token"]
    async with client._maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        org = Organization(name=email, slug=email.split("@")[0])
        db.add(org)
        await db.flush()
        user.org_id = org.id
        await db.commit()
        org_id = org.id
    # A fresh login so the token carries the org.
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": "StrongPassword123!"})
             ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, org_id


async def _job_with_rows(client, org_id: str) -> str:
    from app.models.analysis_job import AnalysisJob
    from app.models.transaction import Transaction

    async with client._maker() as db:
        job = AnalysisJob(filename="m.pdf", file_path="/m.pdf", file_type="pdf", org_id=org_id)
        db.add(job)
        await db.flush()
        db.add(Transaction(
            job_id=job.id, amount_kurus=100_000, currency="TRY", type="expense",
            category="other_expense", description="e-SMM CDE1: 9876543210 — Hukuki danışmanlık",
            transaction_date=datetime(2026, 9, 1, tzinfo=UTC),
            kdv_kurus=20_000, stopaj_kurus=20_000,
            raw_text="UUID: x | No: CDE1 | Tür: e-SMM | Stopaj: 200",
        ))
        db.add(Transaction(
            job_id=job.id, amount_kurus=5_000, currency="TRY", type="expense",
            category="other_expense", description="okunamayan tarih",
            transaction_date=datetime(2026, 9, 11, tzinfo=UTC), date_is_estimated=True,
        ))
        await db.commit()
        return job.id


@pytest.mark.asyncio
async def test_the_list_carries_what_the_source_said(client) -> None:
    h, org_id = await _user(client, "prov@example.com")
    job_id = await _job_with_rows(client, org_id)

    resp = await client.get(f"/api/v1/analysis/{job_id}/transactions", headers=h)
    assert resp.status_code == 200, resp.text
    rows = {r["description"]: r for r in resp.json()["data"]["transactions"]}

    smm = rows["e-SMM CDE1: 9876543210 — Hukuki danışmanlık"]
    assert (smm["kdv_cents"], smm["stopaj_cents"]) == (20_000, 20_000)
    assert "Stopaj: 200" in smm["raw_text"]
    assert smm["date_is_estimated"] is False

    guessed = rows["okunamayan tarih"]
    assert guessed["date_is_estimated"] is True
    assert guessed["kdv_cents"] is None, "kaynak söylemediyse boş kalmalı, sıfır değil"


@pytest.mark.asyncio
async def test_another_organisations_job_is_refused(client) -> None:
    _h, owner_org = await _user(client, "owner@example.com")
    job_id = await _job_with_rows(client, owner_org)
    stranger, _ = await _user(client, "stranger@example.com")

    resp = await client.get(f"/api/v1/analysis/{job_id}/transactions", headers=stranger)
    assert resp.status_code in (403, 404)
