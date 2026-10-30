"""
D1 — Guest demo entry gates (DEMO_PLAN §D1).

POST /demo/guest mints an isolated demo org + throwaway user with the same
token shape as /auth/login, so the NextAuth credentials shortcut can sign a
visitor in without signing them up.

Gates:
1. demo_mode off         → 403 (secure default: no open user minting)
2. demo_mode on          → 201 + JWT pair; user is owner of a fresh org
3. returned access token → authenticates /auth/me with org_id set
4. org locale            → tr-TR / TRY / country TR (honest demo defaults)
5. tenant isolation      → guests never share orgs; demo job invisible cross-org
6. /demo/seed            → 401 without token, 200 with guest token
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from tests.db_helpers import gecici_motor


@pytest_asyncio.fixture
async def test_client(monkeypatch):
    """In-memory DB dependency override + demo_mode on.

    Mirrors the harness in test_api_integration.py.
    """
    test_engine = gecici_motor(echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(get_settings(), "demo_mode", True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await test_engine.dispose()


async def _guest(client: AsyncClient) -> dict:
    """POST /demo/guest and return the data payload."""
    resp = await client.post("/api/v1/demo/guest")
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["error"] is None
    return payload["data"]


@pytest.mark.asyncio
async def test_guest_disabled_without_demo_mode(test_client, monkeypatch):
    """Secure default: demo_mode off → no guest minting."""
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    resp = await test_client.post("/api/v1/demo/guest")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_guest_returns_login_shaped_tokens(test_client):
    """Response mirrors /auth/login so the NextAuth SSO shortcut can consume it."""
    data = await _guest(test_client)
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]
    user = data["user"]
    assert user["email"].endswith("@demo.local")
    assert user["role"] == "owner"
    assert user["org_id"]


@pytest.mark.asyncio
async def test_guest_access_token_authenticates(test_client):
    """The minted token opens /auth/me with the guest's org attached."""
    data = await _guest(test_client)
    resp = await test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert resp.status_code == 200
    me = resp.json()["data"]
    assert me["user_id"] == data["user"]["user_id"]
    assert me["org_id"] == data["user"]["org_id"]


@pytest.mark.asyncio
async def test_guest_org_is_tr_try(test_client):
    """Guest orgs carry the honest TR defaults (tr-TR / TRY), not en-US / USD."""
    data = await _guest(test_client)
    resp = await test_client.get(
        "/api/v1/org/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert resp.status_code == 200
    org = resp.json()["data"]
    assert org["locale"] == "tr-TR"
    assert org["base_currency"] == "TRY"
    assert org["country_code"] == "TR"


@pytest.mark.asyncio
async def test_guests_are_isolated(test_client):
    """Two clicks → two independent orgs; demos never share a workspace."""
    a = await _guest(test_client)
    b = await _guest(test_client)
    assert a["user"]["org_id"] != b["user"]["org_id"]
    assert a["user"]["user_id"] != b["user"]["user_id"]


@pytest.mark.asyncio
async def test_seed_requires_token_and_works_for_guest(
    test_client, tmp_path, monkeypatch
):
    """Auth wall on /demo/seed; a guest session may seed its own org only."""
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))

    # No token → 401
    resp = await test_client.post("/api/v1/demo/seed")
    assert resp.status_code == 401

    a = await _guest(test_client)
    headers = {"Authorization": f"Bearer {a['access_token']}"}
    resp = await test_client.post("/api/v1/demo/seed", headers=headers)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["data"]["job_id"]
    assert job_id

    # Cross-org isolation: another guest must not see A's demo job
    b = await _guest(test_client)
    status_resp = await test_client.get(
        "/api/v1/demo/status",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["data"]["has_demo"] is False

    # Idempotent reseed returns the same job
    again = await test_client.post("/api/v1/demo/seed", headers=headers)
    assert again.status_code == 200
    body = again.json()["data"]
    assert body["job_id"] == job_id
    assert body["is_new"] is False
