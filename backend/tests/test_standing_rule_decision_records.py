"""Standing rules and security settings leave a decision: related parties, triggers, IP allow-list, context reset."""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.company_context import CompanyContextSnapshot
from app.models.organization import Organization
from app.models.related_party import RelatedParty
from app.models.trigger import TriggerDefinitionRow
from app.services.decisions import DecisionError
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.decision_helpers import decisions_of, record_fails

API = "/api/v1"
RULE = "automation_rule_change"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


# ── Related parties ──────────────────────────────────────────────────────────

async def _party(client, headers, name="Yılmaz Gayrimenkul") -> dict:
    res = await client.post(f"{API}/related-parties", headers=headers,
                            json={"name": name, "relationship_type": "diger", "tax_id": "1234567890"})
    assert res.status_code == 201, res.text
    return res.json()["data"]


async def test_a_related_party_is_a_standing_rule_with_who_and_what(client):
    headers, org_id, user_id = await kullanici(client, "iliskili@example.com")
    party = await _party(client, headers)
    (d,) = await decisions_of(client, org_id, kind=RULE)
    assert (d.target_type, d.target_id, d.outcome) == ("related_party", party["id"], "enabled")
    assert (d.decided_via, d.decided_by, d.rule_id, d.before) == ("human", user_id, None, None)
    assert d.after == {"name": "Yılmaz Gayrimenkul", "relationship_type": "diger", "active": True,
                       "has_tax_id": True, "acting_role": "owner"}
    assert "1234567890" not in str(d.after)          # the tax number stays on the party only

    patched = await client.patch(f"{API}/related-parties/{party['id']}", headers=headers,
                                 json={"relationship_type": "ortak", "note": "x"})
    assert patched.status_code == 200, patched.text
    changed = (await decisions_of(client, org_id, kind=RULE))[-1]
    assert changed.outcome == "changed" and changed.before["relationship_type"] == "diger"
    assert changed.after["changed"] == ["relationship_type"]

    off = await client.delete(f"{API}/related-parties/{party['id']}", headers=headers)
    assert off.status_code == 200
    assert (await decisions_of(client, org_id, kind=RULE))[-1].outcome == "revoked"
    again = await client.delete(f"{API}/related-parties/{party['id']}", headers=headers)
    assert again.status_code == 200 and len(await decisions_of(client, org_id, kind=RULE)) == 3   # nothing new decided


async def test_a_refused_party_change_and_a_failed_record_leave_no_effect(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "iliskili2@example.com")
    viewer, _, _ = await kullanici(client, "iliskili-izleyici@example.com", role="viewer")
    assert (await client.post(f"{API}/related-parties", headers=viewer, json={"name": "Aile AŞ"})).status_code == 403
    assert (await client.post(f"{API}/related-parties", headers=headers, json={"name": "Aile AŞ", "relationship_type": "yok"})).status_code == 422
    assert await decisions_of(client, org_id) == []

    record_fails(monkeypatch, "app.api.related_party")
    with pytest.raises(DecisionError):
        await client.post(f"{API}/related-parties", headers=headers, json={"name": "Aile Holding"})
    monkeypatch.undo()
    async with client._maker() as db:
        assert (await db.execute(select(RelatedParty))).scalars().all() == []


# ── Triggers ─────────────────────────────────────────────────────────────────

_RULE_BODY = {"name": "Runway alarmla", "events": ["job.completed"], "condition": {"metric": "finance.runway_months", "op": "lt", "value": 3},
              "action_kind": "webhook.call", "action_params": {"url": "https://hooks.example.com/SECRET-TOKEN"}, "cooldown_minutes": 30}


async def test_a_trigger_records_create_change_disable_and_delete_without_its_parameters(client):
    headers, org_id, user_id = await kullanici(client, "tetik@example.com")
    created = await client.post(f"{API}/tetikler", headers=headers, json=_RULE_BODY)
    assert created.status_code == 201, created.text
    tid = created.json()["data"]["id"]
    (d,) = await decisions_of(client, org_id, kind=RULE)
    assert (d.target_type, d.target_id, d.outcome, d.decided_by) == ("trigger", tid, "enabled", user_id)
    assert d.after["action_kind"] == "webhook.call" and d.after["action_param_keys"] == ["url"]
    assert d.after["acting_role"] == "owner" and "SECRET-TOKEN" not in str(d.after)

    assert (await client.patch(f"{API}/tetikler/{tid}", headers=headers, json={"cooldown_minutes": 5})).status_code == 200
    assert (await client.patch(f"{API}/tetikler/{tid}", headers=headers, json={"enabled": False})).status_code == 200
    assert (await client.patch(f"{API}/tetikler/{tid}", headers=headers, json={"enabled": False})).status_code == 200   # no change
    assert (await client.delete(f"{API}/tetikler/{tid}", headers=headers)).status_code == 200
    outcomes = [x.outcome for x in await decisions_of(client, org_id, kind=RULE)]
    assert outcomes == ["enabled", "changed", "disabled", "revoked"]
    last = (await decisions_of(client, org_id, kind=RULE))[-1]
    assert last.before["enabled"] is False and last.after is None


async def test_an_invalid_or_foreign_trigger_change_and_a_failed_record_leave_nothing(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "tetik2@example.com")
    other, other_org, _ = await kullanici(client, "tetik3@example.com")
    bad = await client.post(f"{API}/tetikler", headers=headers, json={**_RULE_BODY, "action_kind": "nonsense"})
    assert bad.status_code == 400
    tid = (await client.post(f"{API}/tetikler", headers=headers, json=_RULE_BODY)).json()["data"]["id"]
    assert (await client.delete(f"{API}/tetikler/{tid}", headers=other)).status_code == 404
    assert len(await decisions_of(client, org_id)) == 1 and await decisions_of(client, other_org) == []

    record_fails(monkeypatch, "app.api.triggers")
    with pytest.raises(DecisionError):
        await client.delete(f"{API}/tetikler/{tid}", headers=headers)
    with pytest.raises(DecisionError):
        await client.post(f"{API}/tetikler", headers=headers, json={**_RULE_BODY, "name": "ikinci"})
    monkeypatch.undo()
    async with client._maker() as db:
        names = [r.name for r in (await db.execute(select(TriggerDefinitionRow))).scalars()]
    assert names == ["Runway alarmla"]                    # the delete did not happen, the create did not either


# ── IP allow-list ────────────────────────────────────────────────────────────

async def test_the_ip_allow_list_records_before_and_after_and_who(client):
    headers, org_id, user_id = await kullanici(client, "ip@example.com", role="owner")
    res = await client.put(f"{API}/security/ip-whitelist", headers=headers,
                           json={"cidrs": ["203.0.113.42", "10.0.0.0/8", "127.0.0.1"], "enabled": True})
    assert res.status_code == 200, res.text
    (d,) = await decisions_of(client, org_id, kind="security_setting_change")
    assert (d.target_type, d.target_id, d.outcome, d.decided_by) == ("organization_ip_whitelist", org_id, "enabled", user_id)
    assert d.before == {"enabled": False, "cidrs": []}
    assert d.after == {"enabled": True, "cidrs": ["203.0.113.42/32", "10.0.0.0/8", "127.0.0.1/32"], "acting_role": "owner"}

    off = await client.put(f"{API}/security/ip-whitelist", headers=headers, json={"cidrs": [], "enabled": False})
    assert off.status_code == 200
    second = (await decisions_of(client, org_id, kind="security_setting_change"))[-1]
    assert second.outcome == "disabled" and second.before["cidrs"] == ["203.0.113.42/32", "10.0.0.0/8", "127.0.0.1/32"]


async def test_a_bad_list_a_non_decider_and_a_failed_record_do_not_change_the_list(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "ip2@example.com")
    analyst, _, _ = await kullanici(client, "ip3@example.com", role="analyst")
    url = f"{API}/security/ip-whitelist"
    assert (await client.put(url, headers=headers, json={"cidrs": ["not-an-ip"], "enabled": True})).status_code == 400
    assert (await client.put(url, headers=headers, json={"cidrs": ["1.1.1.1"] * 51, "enabled": True})).status_code == 422
    assert (await client.put(url, headers=analyst, json={"cidrs": ["1.1.1.1"], "enabled": True})).status_code == 403
    assert await decisions_of(client, org_id) == []

    record_fails(monkeypatch, "app.api.security")
    with pytest.raises(DecisionError):
        await client.put(url, headers=headers, json={"cidrs": ["1.1.1.1", "127.0.0.1"], "enabled": True})
    monkeypatch.undo()
    async with client._maker() as db:
        org = await db.get(Organization, org_id)
        assert not org.ip_whitelist_enabled and not org.ip_whitelist


# ── Context reset ────────────────────────────────────────────────────────────

async def _seed_context(client, org_id: str) -> None:
    async with client._maker() as db:
        db.add(CompanyContextSnapshot(
            org_id=org_id, context_json=json.dumps({"org_id": org_id, "last_cfo_result": {"x": 1}, "reporting_period": "2024-Q1"})))
        await db.commit()


async def test_a_context_reset_records_what_was_wiped_and_by_whom(client):
    headers, org_id, user_id = await kullanici(client, "ctx@example.com")
    await _seed_context(client, org_id)
    res = await client.delete(f"{API}/context/{org_id}", headers=headers)
    assert res.status_code == 200, res.text
    (d,) = await decisions_of(client, org_id, kind="context_reset")
    assert (d.target_type, d.target_id, d.outcome, d.decided_by) == ("company_context", org_id, "reset", user_id)
    assert d.before["agents_with_results"] == ["cfo"] and d.after["agents_with_results"] == []
    assert d.after["acting_role"] == "owner"
    async with client._maker() as db:
        assert (await db.execute(select(CompanyContextSnapshot))).scalars().all() == []


async def test_another_orgs_context_a_non_decider_and_a_failed_record_leave_it_standing(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "ctx2@example.com")
    other, other_org, _ = await kullanici(client, "ctx3@example.com")
    cfo, _, _ = await kullanici(client, "ctx4@example.com", role="cfo")
    await _seed_context(client, org_id)
    assert (await client.delete(f"{API}/context/{org_id}", headers=other)).status_code == 403   # not their organisation
    assert (await client.delete(f"{API}/context/me", headers=cfo)).status_code == 403
    assert await decisions_of(client, org_id) == [] and await decisions_of(client, other_org) == []

    record_fails(monkeypatch, "app.api.context")
    with pytest.raises(DecisionError):
        await client.delete(f"{API}/context/{org_id}", headers=headers)
    monkeypatch.undo()
    async with client._maker() as db:
        assert len((await db.execute(select(CompanyContextSnapshot))).scalars().all()) == 1
