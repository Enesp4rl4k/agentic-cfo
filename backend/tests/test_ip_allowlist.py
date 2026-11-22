"""The organisation's IP allow-list is enforced where the organisation is acted in.

The test client's socket peer is 127.0.0.1. A different "client" address is produced the way
production does it: a trusted proxy count of 1 and an X-Forwarded-For header.
"""
from __future__ import annotations

import logging

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import get_settings
from app.core import client_ip as client_ip_module
from app.models.decision import Decision
from app.models.organization import Organization, OrgMembership
from app.services import ip_allowlist
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici

API = "/api/v1"
URL = f"{API}/security/ip-whitelist"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def via(ip: str, headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "X-Forwarded-For": ip}


def trust_one_proxy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxy_count", 1)


# ── parsing ─────────────────────────────────────────────────────────────────

def test_the_list_is_parsed_strictly():
    assert ip_allowlist.normalise(["203.0.113.5", "10.0.0.0/8", "2001:db8::/32", "2001:db8::1", " "]) == [
        "203.0.113.5/32", "10.0.0.0/8", "2001:db8::/32", "2001:db8::1/128",
    ]
    assert ip_allowlist.normalise(["10.0.0.0/8", "10.0.0.0/8"]) == ["10.0.0.0/8"]
    for bad in ("nope", "10.0.0.5/8", "999.1.1.1", "10.0.0.0/33", "0.0.0.0/0", "::/0", "::ffff:10.0.0.1", "10.0.0.1/24/1"):
        with pytest.raises(ip_allowlist.AllowListError):
            ip_allowlist.normalise([bad])
    with pytest.raises(ip_allowlist.AllowListError):
        ip_allowlist.normalise([f"10.0.{i // 250}.{i % 250}" for i in range(51)])


def test_membership_in_the_list():
    stored = "10.0.0.0/8,2001:db8::/32"
    assert ip_allowlist.allows(stored, "10.4.5.6") and ip_allowlist.allows(stored, "2001:db8::7")
    assert ip_allowlist.allows(stored, "::ffff:10.4.5.6")  # an IPv4-mapped client is the IPv4 address
    assert not ip_allowlist.allows(stored, "11.0.0.1") and not ip_allowlist.allows(stored, "2001:db9::1")
    assert not ip_allowlist.allows(stored, "unknown") and not ip_allowlist.allows(stored, "")


# ── saving: never lock the owner out ────────────────────────────────────────

async def test_saving_a_list_without_the_callers_address_needs_confirmation(client):
    headers, org_id, _ = await kullanici(client, "own@example.com")
    refused = await client.put(URL, headers=headers, json={"cidrs": ["203.0.113.5"], "enabled": True})
    assert refused.status_code == 409 and "127.0.0.1" in refused.text and "confirm_lockout" in refused.text
    async with client._maker() as db:
        assert not (await db.get(Organization, org_id)).ip_whitelist_enabled
    ok = await client.put(URL, headers=headers, json={"cidrs": ["203.0.113.5"], "enabled": True, "confirm_lockout": True})
    assert ok.status_code == 200
    # a list that contains the caller needs no confirmation
    headers2, _, _ = await kullanici(client, "own2@example.com")
    assert (await client.put(URL, headers=headers2, json={"cidrs": ["127.0.0.0/8"], "enabled": True})).status_code == 200


async def test_an_enabled_list_must_have_an_entry_and_a_bad_entry_is_a_400(client):
    headers, _, _ = await kullanici(client, "own@example.com")
    assert (await client.put(URL, headers=headers, json={"cidrs": [], "enabled": True})).status_code == 400
    assert (await client.put(URL, headers=headers, json={"cidrs": ["10.0.0.5/8"], "enabled": True})).status_code == 400
    assert (await client.put(URL, headers=headers, json={"cidrs": [], "enabled": False})).status_code == 200


async def test_activation_is_refused_behind_a_proxy_without_trusted_proxy_settings(client, monkeypatch):
    headers, _, _ = await kullanici(client, "own@example.com")
    refused = await client.put(
        URL, headers=via("198.51.100.7", headers), json={"cidrs": ["198.51.100.7"], "enabled": True}
    )
    assert refused.status_code == 409 and "TRUSTED_PROXY" in refused.text
    trust_one_proxy(monkeypatch)
    ok = await client.put(URL, headers=via("198.51.100.7", headers), json={"cidrs": ["198.51.100.7"], "enabled": True})
    assert ok.status_code == 200


# ── enforcement ─────────────────────────────────────────────────────────────

async def test_requests_from_outside_the_list_are_refused_and_inside_pass(client, monkeypatch):
    headers, _org_id, _ = await kullanici(client, "own@example.com")
    assert (await client.put(URL, headers=headers, json={"cidrs": ["127.0.0.1"], "enabled": True})).status_code == 200
    trust_one_proxy(monkeypatch)
    refused = await client.get(URL, headers=via("198.51.100.7", headers))
    assert refused.status_code == 403 and "IP" in refused.text
    assert (await client.get(URL, headers=via("127.0.0.1", headers))).status_code == 200
    # a spoofed first X-Forwarded-For value does not help: the proxy-appended hop decides
    assert (await client.get(URL, headers=via("127.0.0.1, 198.51.100.7", headers))).status_code == 403


async def test_an_api_key_is_held_to_the_list_too(client, monkeypatch):
    headers, _, _ = await kullanici(client, "own@example.com")
    key = (await client.post(f"{API}/auth/api-key", headers=headers)).json()["data"]["api_key"]
    await client.put(URL, headers=headers, json={"cidrs": ["127.0.0.1"], "enabled": True})
    trust_one_proxy(monkeypatch)
    assert (await client.get(URL, headers={"X-API-Key": key, "X-Forwarded-For": "198.51.100.7"})).status_code == 403
    assert (await client.get(URL, headers={"X-API-Key": key, "X-Forwarded-For": "127.0.0.1"})).status_code == 200


async def test_a_disabled_or_empty_list_restricts_nobody(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "own@example.com")
    trust_one_proxy(monkeypatch)
    assert (await client.get(URL, headers=via("198.51.100.7", headers))).status_code == 200
    async with client._maker() as db:
        org = await db.get(Organization, org_id)
        org.ip_whitelist_enabled, org.ip_whitelist = True, ""
        await db.commit()
    assert (await client.get(URL, headers=via("198.51.100.7", headers))).status_code == 200


async def test_a_user_with_two_organisations_can_still_reach_the_other(client, monkeypatch):
    headers, org_a, user_id = await kullanici(client, "own@example.com")
    async with client._maker() as db:
        org_b = Organization(name="B", slug="b-org")
        db.add(org_b)
        await db.flush()
        db.add(OrgMembership(org_id=org_a, user_id=user_id, role="owner"))
        db.add(OrgMembership(org_id=org_b.id, user_id=user_id, role="owner"))
        await db.commit()
        b_id = org_b.id
    await client.put(URL, headers=headers, json={"cidrs": ["127.0.0.1"], "enabled": True})  # restricts org A
    trust_one_proxy(monkeypatch)
    out = via("198.51.100.7", headers)
    assert (await client.get(f"{API}/security/ip-whitelist", headers=out)).status_code == 403  # acting in A
    assert (await client.get(f"{API}/org/memberships", headers=out)).status_code == 200
    assert (await client.post(f"{API}/org/switch", headers=out, json={"org_id": b_id})).status_code == 200
    assert (await client.get(f"{API}/org/memberships", headers=out)).status_code == 200
    # ... and from outside the list the way back into A is refused
    assert (await client.post(f"{API}/org/switch", headers=out, json={"org_id": org_a})).status_code == 403
    assert (await client.post(f"{API}/org/switch", headers=via("127.0.0.1", headers), json={"org_id": org_a})).status_code == 200


async def test_login_is_not_organisation_scoped_and_is_never_refused(client, monkeypatch):
    headers, _, _ = await kullanici(client, "own@example.com")
    await client.put(URL, headers=headers, json={"cidrs": ["127.0.0.1"], "enabled": True})
    trust_one_proxy(monkeypatch)
    login = await client.post(f"{API}/auth/login", json={"email": "own@example.com", "password": PAROLA},
                              headers={"X-Forwarded-For": "198.51.100.7"})
    assert login.status_code == 200


async def test_websockets_are_held_to_the_list(client, monkeypatch):
    from app.api import ws_auth
    from app.services.auth import create_access_token

    headers, _org_id, user_id = await kullanici(client, "own@example.com")
    await client.put(URL, headers=headers, json={"cidrs": ["203.0.113.9", "127.0.0.1"], "enabled": True})
    token = create_access_token(user_id, "own@example.com", "owner", token_version=0)
    monkeypatch.setattr(ws_auth, "session_factory", lambda: client._maker)
    assert await ws_auth.websocket_caller(token, "203.0.113.9") is not None
    assert await ws_auth.websocket_caller(token, "198.51.100.7") is None
    assert await ws_auth.websocket_caller(token, "unknown") is None
    assert await ws_auth.websocket_caller(token) is not None  # no address given: the caller that has none (tests)


# ── break-glass ─────────────────────────────────────────────────────────────

async def test_a_platform_operator_can_clear_a_list_and_it_is_recorded(client, monkeypatch):
    owner, org_id, _ = await kullanici(client, "own@example.com")
    await client.put(URL, headers=owner, json={"cidrs": ["203.0.113.9"], "enabled": True, "confirm_lockout": True})
    operator, _, op_id = await kullanici(client, "ops@example.com", attach_org=False)
    path = f"{API}/platform/orgs/{org_id}/ip-whitelist"
    assert (await client.delete(path, headers=operator)).status_code == 403  # not (yet) an operator
    assert (await client.delete(path, headers=owner)).status_code == 403     # a company owner is not an operator
    monkeypatch.setattr(get_settings(), "platform_operator_emails", "ops@example.com")
    assert (await client.delete(f"{API}/platform/orgs/nope/ip-whitelist", headers=operator)).status_code == 404
    assert (await client.delete(path, headers=operator)).status_code == 200
    async with client._maker() as db:
        org = await db.get(Organization, org_id)
        assert not org.ip_whitelist_enabled and not org.ip_whitelist
        rows = (await db.execute(
            select(Decision).where(Decision.org_id == org_id, Decision.kind == "security_setting_change")
        )).scalars().all()
    last = rows[-1]
    assert last.decided_by == op_id and last.before["cidrs"] == ["203.0.113.9/32"]
    assert last.after["break_glass"] is True and last.after["acting_role"] == "platform_operator"
    assert (await client.get(URL, headers=owner)).status_code == 200


# ── the proxy-misconfiguration watch ────────────────────────────────────────

def test_production_warns_once_when_only_private_peers_are_seen_and_nothing_is_configured(caplog):
    client_ip_module.reset_peer_watch()
    with caplog.at_level(logging.ERROR, logger="app.core.client_ip"):
        fired = [client_ip_module.observe_peer("10.1.2.3", production=True, configured=False) for _ in range(25)]
    assert fired.count(True) == 1 and "TRUSTED_PROXY_COUNT" in caplog.text
    client_ip_module.reset_peer_watch()


def test_the_watch_stays_quiet_when_configured_in_dev_or_after_a_public_peer():
    client_ip_module.reset_peer_watch()
    assert not any(client_ip_module.observe_peer("10.1.2.3", production=True, configured=True) for _ in range(30))
    assert not any(client_ip_module.observe_peer("10.1.2.3", production=False, configured=False) for _ in range(30))
    client_ip_module.observe_peer("93.184.216.34", production=True, configured=False)
    assert not any(client_ip_module.observe_peer("10.1.2.3", production=True, configured=False) for _ in range(30))
    client_ip_module.reset_peer_watch()
