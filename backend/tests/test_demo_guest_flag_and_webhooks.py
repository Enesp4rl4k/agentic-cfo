"""Guest-ness is server-set; the WhatsApp webhook has no public default; Slack requests expire.

* `POST /org/create` cannot produce an organisation that passes as a demo guest workspace: the `demo-` prefix is
  reserved and `is_guest_org` reads a flag only /demo/guest sets.
* `GET /demo/status` tells the frontend whether the one-click demo applies (demo mode on AND a guest workspace).
* WhatsApp: no verify token (or no app secret) means 404, never the old public "agentic-cfo-verify".
* Slack: a correctly signed request older than five minutes is refused (replay).
"""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest
import pytest_asyncio

from app.config import get_settings
from app.models.organization import Organization
from app.services.demo_template import GUEST_DESCRIPTION, is_guest_org
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.golden_seed import _auth, _guest

P = "/api/v1"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def test_a_chosen_slug_and_description_do_not_make_a_guest_org():
    imitation = Organization(name="x", slug="demo-0123456789ab", description=GUEST_DESCRIPTION)
    assert is_guest_org(imitation) is False
    imitation.is_demo_guest = True
    assert is_guest_org(imitation) is True


@pytest.mark.asyncio
async def test_org_create_reserves_the_demo_prefix(client):
    headers, _, _ = await kullanici(client, "slug@example.com", attach_org=False)
    refused = await client.post(f"{P}/org/create", headers=headers,
                                json={"name": "Firma", "slug": "demo-0123456789ab", "description": GUEST_DESCRIPTION})
    assert refused.status_code == 422
    derived = await client.post(f"{P}/org/create", headers=headers, json={"name": "Demo 0123456789ab"})
    assert derived.status_code in (200, 201), derived.text
    data = derived.json()["data"] if "data" in derived.json() else derived.json()
    assert not str(data.get("slug", "")).startswith("demo-")


@pytest.mark.asyncio
async def test_demo_status_says_whether_the_banner_applies(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    guest = await _guest(client)
    on = await client.get(f"{P}/demo/status", headers=_auth(guest))
    assert on.json()["data"]["demo_available"] is True
    real, _, _ = await kullanici(client, "real@example.com")
    assert (await client.get(f"{P}/demo/status", headers=real)).json()["data"]["demo_available"] is False
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert (await client.get(f"{P}/demo/status", headers=_auth(guest))).json()["data"]["demo_available"] is False


@pytest.mark.asyncio
async def test_whatsapp_webhook_does_not_exist_without_a_token_and_secret(client, monkeypatch):
    assert get_settings().whatsapp_verify_token == ""  # no public default
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", "")
    probe = {"hub.mode": "subscribe", "hub.verify_token": "agentic-cfo-verify", "hub.challenge": "c"}
    assert (await client.get(f"{P}/webhooks/whatsapp", params=probe)).status_code == 404
    assert (await client.post(f"{P}/webhooks/whatsapp", content=b"{}")).status_code == 404
    monkeypatch.setattr(get_settings(), "whatsapp_verify_token", "vt")
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", "s")
    wrong = await client.get(f"{P}/webhooks/whatsapp", params={**probe, "hub.verify_token": "agentic-cfo-verify"})
    assert wrong.status_code == 403
    right = await client.get(f"{P}/webhooks/whatsapp", params={**probe, "hub.verify_token": "vt"})
    assert right.status_code == 200 and right.text == "c"


@pytest.mark.asyncio
async def test_slack_refuses_a_stale_signed_request(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "slack_signing_secret", "slacksecret")
    body = '{"type": "url_verification", "challenge": "hello"}'

    def post(ts: int):
        sig = "v0=" + hmac.new(b"slacksecret", f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
        return client.post(f"{P}/webhooks/slack", content=body, headers={
            "X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sig, "Content-Type": "application/json"})

    now = int(time.time())
    assert (await post(now)).status_code == 200
    assert (await post(now - 320)).status_code == 403
    assert (await post(now + 320)).status_code == 403
