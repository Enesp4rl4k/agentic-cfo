"""Shared scaffolding for API tests that need a real app on an in-memory DB.

The same client fixture, sign-up helper and sample report were copied into
each new test file, and the copies were enough to fail the pull request's
duplication gate. One definition here; each file keeps a three-line fixture
that names it.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from httpx import ASGITransport, AsyncClient

PAROLA = "StrongPassword123!"


@asynccontextmanager
async def bellek_istemcisi() -> AsyncIterator[AsyncClient]:
    """The app on a fresh in-memory schema; `client._maker` opens sessions on it."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import Base, get_db
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c._maker = maker  # type: ignore[attr-defined]
            yield c
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def kullanici(
    client: AsyncClient, email: str, *, attach_org: bool = True,
) -> tuple[dict[str, str], str | None, str]:
    """Register, optionally attach a fresh organisation, sign in.

    Returns (auth headers, org id or None, user id). The login comes after the
    org is attached so the token carries it.
    """
    from sqlalchemy import select

    from app.models.organization import Organization
    from app.models.user import User

    await client.post("/api/v1/auth/register",
                      json={"email": email, "password": PAROLA, "full_name": "T"})
    async with client._maker() as db:  # type: ignore[attr-defined]
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        org_id: str | None = None
        if attach_org:
            org = Organization(name=email, slug=email.split("@")[0])
            db.add(org)
            await db.flush()
            user.org_id = org.id
            org_id = org.id
        user_id = user.id
        await db.commit()
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": PAROLA})).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, org_id, user_id


def ornek_rapor(*, runway: float = 9.5) -> dict[str, Any]:
    """A stored full report in production shape.

    The stored report is LIRA (report_agent._fmt divides the pipeline's
    cents); load_pnl_cashflow_forecast converts money to kuruş, so assertions
    on derived figures read kuruş.
    """
    return {
        "pnl": {
            "revenue": 12_000_000,
            "total_opex": 8_000_000,
            "net_margin": 0.2,
            "opex": {"salary": 4_000_000, "rent": 1_000_000},
        },
        "cashflow": {"net_change": 500_000},
        "forecast": {
            "scenarios": {
                "base": {"runway_months": runway, "twelve_month_net": 3_000_000},
            }
        },
    }
