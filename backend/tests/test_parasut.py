"""Paraşüt: connected by logging in, owned by one organisation, and its invoices analysed.

Paraşüt's side is an httpx.MockTransport shaped like its OAuth token endpoint
and JSON:API responses. That shape is Paraşüt's public one as understood here,
not a recording of a real account; these tests pin this system's behaviour
around it — who may connect, what the callback accepts, where the data goes.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.parse

import httpx
import pytest
from sqlalchemy import select

from app.services.erp import parasut_connector as pc
from tests.test_ingest import _login, client  # noqa: F401 — fixture


class Parasut:
    """A fake Paraşüt: token endpoint, /me, and invoice lists."""

    def __init__(self, companies=({"id": "123456", "name": "Kobi A.Ş."},), fail_invoices=False):
        self.companies = list(companies)
        self.fail_invoices = fail_invoices
        self.token_posts: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.path == "/oauth/token":
            form = dict(urllib.parse.parse_qsl(request.content.decode()))
            self.token_posts.append(form)
            if form.get("code") == "kotu":
                return httpx.Response(401, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "ACCESS-TOKEN-PLAIN", "refresh_token": "REFRESH-TOKEN-PLAIN", "expires_in": 7200})
        assert request.headers.get("authorization") == "Bearer ACCESS-TOKEN-PLAIN"
        if url.path == "/v4/me":
            return httpx.Response(200, json={"data": {"id": "1", "type": "users"}, "included": [
                {"id": c["id"], "type": "companies", "attributes": {"name": c["name"]}} for c in self.companies]})
        if self.fail_invoices:
            return httpx.Response(403, json={"errors": [{"title": "Forbidden"}]})
        today = time.strftime("%Y-%m-%d")
        if url.path == "/v4/123456/sales_invoices":
            return httpx.Response(200, json={"data": [
                {"id": "s1", "type": "sales_invoices",
                 "attributes": {"issue_date": today, "gross_total": "11800.0", "description": "Danışmanlık", "invoice_no": "A-1"}},
            ]})
        if url.path == "/v4/123456/purchase_bills":
            return httpx.Response(200, json={"data": [
                {"id": "p1", "type": "purchase_bills",
                 "attributes": {"issue_date": today, "gross_total": "2360.5", "description": "Ofis kirası"}},
                {"id": "p2", "type": "purchase_bills", "attributes": {"issue_date": "2001-01-01", "gross_total": "5"}},
            ]})
        return httpx.Response(404)


@pytest.fixture
def parasut(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "parasut_client_id", "platform-client")
    monkeypatch.setattr(s, "parasut_client_secret", "platform-secret")
    fake = Parasut()
    monkeypatch.setattr(pc, "_transport", httpx.MockTransport(fake))
    return fake


async def _connect(client, h, parasut_fake, code="iyi"):
    url = (await client.post("/api/v1/erp/parasut/baglan", headers=h)).json()["data"]["auth_url"]
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]
    r = await client.get("/api/v1/erp/parasut/callback", params={"code": code, "state": state})
    return url, state, r


def _redirected(r) -> str:
    assert r.status_code == 303
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers["location"]).query)).get("parasut", "")


@pytest.mark.asyncio
async def test_not_offered_until_the_platform_has_a_parasut_application(client):
    h = await _login(client)
    assert (await client.get("/api/v1/erp/parasut/durum", headers=h)).json()["data"]["acik"] is False
    assert (await client.post("/api/v1/erp/parasut/baglan", headers=h)).status_code == 409


@pytest.mark.asyncio
async def test_one_click_connects_and_the_person_never_sees_a_secret(client, parasut):
    h = await _login(client)
    url, state, r = await _connect(client, h, parasut)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert q["client_id"] == "platform-client" and "secret" not in url
    assert q["redirect_uri"].endswith("/api/v1/erp/parasut/callback")
    assert _redirected(r) == "baglandi"

    d = (await client.get("/api/v1/erp/parasut/durum", headers=h)).json()["data"]
    assert d["baglanti"]["status"] == "active" and d["baglanti"]["display_name"] == "Paraşüt · Kobi A.Ş."
    assert parasut.token_posts[0]["client_secret"] == "platform-secret"

    # The same state a second time is refused: it was used.
    r = await client.get("/api/v1/erp/parasut/callback", params={"code": "iyi", "state": state})
    assert _redirected(r) == "hata"


@pytest.mark.asyncio
async def test_tokens_and_config_are_encrypted_at_rest(client, parasut):
    from app.models.erp_integration import ERPIntegration

    h = await _login(client)
    await _connect(client, h, parasut)
    async with client._maker() as db:
        row = (await db.execute(select(ERPIntegration))).scalar_one()
    for blob in (row.access_token_enc, row.refresh_token_enc, row.config_enc):
        assert blob and "TOKEN-PLAIN" not in blob and "123456" not in blob
        with pytest.raises((ValueError, UnicodeDecodeError, json.JSONDecodeError)):
            json.loads(base64.b64decode(blob).decode())


def test_a_legacy_base64_config_is_still_read():
    class Row:
        config_enc = base64.b64encode(json.dumps({"company_id": "42"}).encode()).decode()
    assert pc._config(Row())["company_id"] == "42"


@pytest.mark.asyncio
@pytest.mark.parametrize("bozuk", ["tampered", "expired", "other-org"])
async def test_the_callback_only_accepts_a_state_this_server_signed_for_this_login(client, parasut, bozuk):
    h = await _login(client)
    _url, state, _ = await _connect(client, h, parasut)
    await client.post("/api/v1/erp/parasut/baglan", headers=h)          # a fresh login attempt
    org, user, nonce, exp, sig = state.split(".")
    if bozuk == "tampered":
        forged = f"{org}.{user}.{nonce}.{int(exp) + 9999}.{sig}"
    elif bozuk == "expired":
        forged = pc.state_uret(org, user, nonce, now=time.time() - 3600)
    else:
        forged = pc.state_uret("00000000-0000-0000-0000-000000000000", user, nonce)
    r = await client.get("/api/v1/erp/parasut/callback", params={"code": "iyi", "state": forged})
    assert _redirected(r) == "hata"


@pytest.mark.asyncio
async def test_several_companies_ask_which_one(client, parasut):
    parasut.companies = [{"id": "123456", "name": "Kobi A.Ş."}, {"id": "777", "name": "Kobi Ltd."}]
    h = await _login(client)
    _u, _s, r = await _connect(client, h, parasut)
    assert _redirected(r) == "firma_sec"
    d = (await client.get("/api/v1/erp/parasut/durum", headers=h)).json()["data"]
    assert {f["ad"] for f in d["firmalar"]} == {"Kobi A.Ş.", "Kobi Ltd."}
    assert (await client.post("/api/v1/erp/parasut/firma", json={"company_id": "999"}, headers=h)).status_code == 422
    r = await client.post("/api/v1/erp/parasut/firma", json={"company_id": "123456"}, headers=h)
    assert r.status_code == 200 and r.json()["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_sync_opens_an_analysis_of_the_invoices(client, parasut, monkeypatch):
    from app.agents.data_ingestion import run_data_ingestion
    from app.agents.state import AgentRunConfig
    from app.models.analysis_job import AnalysisJob

    h = await _login(client)
    await _connect(client, h, parasut)
    integ = (await client.get("/api/v1/erp/parasut/durum", headers=h)).json()["data"]["baglanti"]["id"]
    r = await client.post("/api/v1/erp/parasut/sync", data={"integration_id": integ}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["sync_count"] == 2 and d["job_id"]    # the 2001 bill is outside the 90 days

    async with client._maker() as db:
        job = await db.get(AnalysisJob, d["job_id"])
        out = await run_data_ingestion({"file_path": job.file_path, "file_type": job.file_type, "job_id": job.id},
                                       AgentRunConfig())
    assert sorted((t["type"], t["amount_cents"]) for t in out.patch["transactions"]) == [
        ("expense", 236_050), ("income", 1_180_000)]


@pytest.mark.asyncio
async def test_a_failed_pull_is_an_error_not_an_empty_success(client, parasut):
    parasut.fail_invoices = True
    h = await _login(client)
    await _connect(client, h, parasut)
    integ = (await client.get("/api/v1/erp/parasut/durum", headers=h)).json()["data"]["baglanti"]["id"]
    r = await client.post("/api/v1/erp/parasut/sync", data={"integration_id": integ}, headers=h)
    assert r.status_code == 502 and "403" in r.json()["error"]
    b = (await client.get("/api/v1/erp/parasut/durum", headers=h)).json()["data"]["baglanti"]
    assert b["last_sync_status"] == "error" and b["last_sync_count"] is None


@pytest.mark.asyncio
async def test_another_organisation_cannot_sync_or_disconnect_it(client, parasut):
    owner = await _login(client, "a@example.com")
    await _connect(client, owner, parasut)
    integ = (await client.get("/api/v1/erp/parasut/durum", headers=owner)).json()["data"]["baglanti"]["id"]
    stranger = await _login(client, "b@example.com")
    assert (await client.post("/api/v1/erp/parasut/sync", data={"integration_id": integ},
                              headers=stranger)).status_code == 404
    assert (await client.post("/api/v1/erp/parasut/disconnect", params={"integration_id": integ},
                              headers=stranger)).status_code == 404
    b = (await client.get("/api/v1/erp/parasut/durum", headers=owner)).json()["data"]["baglanti"]
    assert b["status"] == "active"


@pytest.mark.asyncio
async def test_a_schedule_cannot_pull_another_organisations_parasut(client, parasut):
    from app.models.organization import Organization
    from app.services.scheduled_sync import ScheduledSyncRunner

    owner = await _login(client, "a@example.com")
    await _connect(client, owner, parasut)
    integ = (await client.get("/api/v1/erp/parasut/durum", headers=owner)).json()["data"]["baglanti"]["id"]
    await _login(client, "b@example.com")
    async with client._maker() as db:
        other = (await db.execute(select(Organization).where(Organization.name == "b@example.com"))).scalar_one()
        data, name = await ScheduledSyncRunner()._pull_parasut({"integration_id": integ}, None, db=db, org_id=other.id)
    assert (data, name) == (b"", "")


# ── Automatic pulls ─────────────────────────────────────────────────────────

async def _connected_row(client, h, parasut):
    from app.models.erp_integration import ERPIntegration

    await _connect(client, h, parasut)
    async with client._maker() as db:
        return (await db.execute(select(ERPIntegration))).scalar_one().id


@pytest.mark.asyncio
async def test_unchanged_invoices_are_not_analysed_again(client, parasut):
    from app.models.analysis_job import AnalysisJob

    h = await _login(client)
    integ = await _connected_row(client, h, parasut)
    first = (await client.post("/api/v1/erp/parasut/sync", data={"integration_id": integ}, headers=h)).json()["data"]
    again = (await client.post("/api/v1/erp/parasut/sync", data={"integration_id": integ}, headers=h)).json()["data"]
    assert first["durum"] == "analiz_baslatildi"
    assert again["durum"] == "degisiklik_yok" and again["job_id"] == first["job_id"]
    async with client._maker() as db:
        assert len((await db.execute(select(AnalysisJob))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_the_person_chooses_how_often(client, parasut):
    h = await _login(client)
    await _connected_row(client, h, parasut)
    r = await client.patch("/api/v1/erp/parasut/otomatik", json={"aralik": "haftalik"}, headers=h)
    assert (r.json()["data"]["auto_sync_enabled"], r.json()["data"]["sync_interval_hours"]) == (True, 168)
    r = await client.patch("/api/v1/erp/parasut/otomatik", json={"aralik": "kapali"}, headers=h)
    assert r.json()["data"]["auto_sync_enabled"] is False
    assert (await client.patch("/api/v1/erp/parasut/otomatik", json={"aralik": "saniyede"}, headers=h)).status_code == 422


@pytest.mark.asyncio
async def test_the_timer_pulls_only_what_is_due_and_says_once_when_it_fails(client, parasut):
    from datetime import UTC, datetime, timedelta

    from app.agents.orchestration.erp_sync_runner import run_scheduled_erp_sync
    from app.models.analysis_job import AnalysisJob
    from app.models.erp_integration import ERPIntegration
    from app.models.in_app_notification import InAppNotification

    h = await _login(client)
    integ = await _connected_row(client, h, parasut)

    async with client._maker() as db:
        out = await run_scheduled_erp_sync(db)                 # never pulled: due
        assert out["results"][0]["durum"] == "analiz_baslatildi"
        out = await run_scheduled_erp_sync(db)                 # pulled a moment ago: not due
        assert out["results"] == []
        job = (await db.execute(select(AnalysisJob))).scalar_one()
        assert job.org_id and job.user_id is None              # filed under the organisation

        row = await db.get(ERPIntegration, integ)
        row.last_sync_at = datetime.now(UTC) - timedelta(days=2)
        await db.commit()
        parasut.fail_invoices = True
        await run_scheduled_erp_sync(db)
        row.last_sync_at = datetime.now(UTC) - timedelta(days=2)
        await db.commit()
        await run_scheduled_erp_sync(db)                       # still broken
        notes = (await db.execute(select(InAppNotification))).scalars().all()
    assert len(notes) == 1 and "Paraşüt" in notes[0].message
