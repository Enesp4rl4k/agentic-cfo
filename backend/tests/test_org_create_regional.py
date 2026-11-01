"""A company created at sign-up is a Turkish one, with the Turkish pack on.

Every organisation used to be created as US/USD with no regional pack: a firm
that had just signed up got 404 from e-Fatura and muhasebe and US tax rates.
"""
from __future__ import annotations

import pytest_asyncio

from tests.api_helpers import bellek_istemcisi


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _headers(client, email: str) -> dict[str, str]:
    await client.post("/api/v1/auth/register",
                      json={"email": email, "password": "StrongPassword123!", "full_name": "T"})
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": "StrongPassword123!"})
             ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_a_new_company_is_turkish_by_default(client):
    headers = await _headers(client, "kobi@example.com")
    r = await client.post("/api/v1/org/create", json={"name": "Kobi A.Ş."}, headers=headers)
    assert r.status_code == 201, r.text
    from app.models.organization import Organization
    async with client._maker() as db:
        org = await db.get(Organization, r.json()["data"]["org_id"])
        assert (org.country_code, org.base_currency, org.locale) == ("TR", "TRY", "tr-TR")
        assert org.regional_packs == ["tr"]
    rates = (await client.get("/api/v1/org/me/tax-rates", headers=headers)).json()["data"]
    assert rates["country_code"] == "TR"


async def test_another_country_can_be_asked_for(client):
    headers = await _headers(client, "us@example.com")
    r = await client.post("/api/v1/org/create", json={"name": "Acme Inc", "country_code": "us"}, headers=headers)
    from app.models.organization import Organization
    async with client._maker() as db:
        org = await db.get(Organization, r.json()["data"]["org_id"])
        assert (org.country_code, org.regional_packs) == ("US", [])
