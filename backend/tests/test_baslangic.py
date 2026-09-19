"""The first-use guide reads each step from the organisation's own data."""
from __future__ import annotations

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


async def _login(client, email: str) -> dict[str, str]:
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": "StrongPassword123!"})
             ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _user(client, email: str, *, with_org: bool = True) -> tuple[dict[str, str], str | None]:
    from app.models.organization import Organization
    from app.models.user import User

    await client.post("/api/v1/auth/register",
                      json={"email": email, "password": "StrongPassword123!", "full_name": "T"})
    org_id = None
    if with_org:
        async with client._maker() as db:
            user = (await db.execute(select(User).where(User.email == email))).scalar_one()
            org = Organization(name="Kobi A.Ş.", slug=email.split("@")[0])
            db.add(org)
            await db.flush()
            user.org_id = org.id
            await db.commit()
            org_id = org.id
    return await _login(client, email), org_id


async def _job(client, org_id: str, **kw) -> str:
    from app.models.analysis_job import AnalysisJob

    async with client._maker() as db:
        job = AnalysisJob(filename="ekstre.csv", file_path="/e.csv", file_type="csv", org_id=org_id, **kw)
        db.add(job)
        await db.commit()
        return job.id


async def test_a_new_user_has_everything_left_to_do(client):
    headers, _ = await _user(client, "yeni@example.com", with_org=False)
    d = (await client.get("/api/v1/baslangic", headers=headers)).json()["data"]
    assert d["firma"] == {"var": False, "ad": None}
    assert d["veri"] == {"analiz_sayisi": 0, "parasut_bagli": False}
    assert d["son_analiz"] is None and d["tamamlanan_analiz"] == 0
    assert d["otomatik"] == {"eposta": False, "parasut_otomatik": False}


async def test_a_held_analysis_is_reported_as_waiting_for_approval(client):
    headers, org_id = await _user(client, "firma@example.com")
    job_id = await _job(client, org_id, status="awaiting_review", awaiting_review=True, min_confidence=0.62)
    d = (await client.get("/api/v1/baslangic", headers=headers)).json()["data"]
    assert d["firma"] == {"var": True, "ad": "Kobi A.Ş."}
    assert d["veri"]["analiz_sayisi"] == 1
    assert d["son_analiz"]["id"] == job_id
    assert d["son_analiz"]["onay_bekliyor"] is True and d["son_analiz"]["guven"] == 0.62
    assert d["tamamlanan_analiz"] == 0


async def test_a_failed_analysis_carries_its_reason(client):
    headers, org_id = await _user(client, "hata@example.com")
    await _job(client, org_id, status="failed", error_message="Tarih sütunu bulunamadı.")
    d = (await client.get("/api/v1/baslangic", headers=headers)).json()["data"]
    assert d["son_analiz"]["durum"] == "failed"
    assert d["son_analiz"]["hata"] == "Tarih sütunu bulunamadı."


async def test_another_organisations_data_is_not_counted(client):
    _, org_a = await _user(client, "a@example.com")
    await _job(client, org_a, status="completed")
    headers_b, _ = await _user(client, "b@example.com")
    d = (await client.get("/api/v1/baslangic", headers=headers_b)).json()["data"]
    assert d["veri"]["analiz_sayisi"] == 0 and d["son_analiz"] is None


async def test_requires_sign_in(client):
    assert (await client.get("/api/v1/baslangic")).status_code == 401
