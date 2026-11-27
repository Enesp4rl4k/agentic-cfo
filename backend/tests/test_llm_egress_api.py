"""Yapay zekâya giden veri: the owner's screen and choice (`GET /privacy/overview`, `PUT /privacy/ai-data-mode`)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import database
from app.config import get_settings
from app.models.decision import Decision, DecisionKind
from app.models.llm_call_log import LLMCallLog
from app.models.organization import Organization
from app.models.user import User
from app.platform.llm_egress import dictionary, policy
from tests.api_helpers import kullanici
from tests.test_org_erasure import _membership

URL = "/api/v1/privacy/ai-data-mode"


@pytest.fixture(autouse=True)
def _fresh_caches(client, monkeypatch):
    monkeypatch.setattr(database, "session_factory", lambda: client._maker)
    policy._CHOICES.clear()
    dictionary.forget()
    yield
    policy._CHOICES.clear()
    dictionary.forget()


async def _owner_and_analyst(client):
    owner, org, uid = await kullanici(client, "owner@example.com", role="owner")
    await _membership(client, uid, org, "owner")
    analyst, _, uid_a = await kullanici(client, "an@example.com", attach_org=False, role="analyst")
    async with client._maker() as db:
        (await db.get(User, uid_a)).org_id = org
        await db.commit()
    await _membership(client, uid_a, org, "analyst")
    return owner, analyst, org, uid


async def test_the_owner_sees_mode_provider_categories_and_counters_and_nobody_else_does(client) -> None:
    owner, analyst, org, _ = await _owner_and_analyst(client)
    async with client._maker() as db:
        db.add(LLMCallLog(org_id=org, task_type="deep_analysis", model="deepseek-chat", data_mode="masked", bytes_out=1200,
                          replaced={"counts": {"IBAN": 2}, "flags": [], "sends": 1}))
        db.add(LLMCallLog(org_id=org, task_type="embedding", model="m", data_mode="masked", bytes_out=300))
        db.add(LLMCallLog(org_id=org, task_type="cached", model="m", data_mode=None, bytes_out=0, from_cache=True))
        db.add(LLMCallLog(org_id=org, task_type="chat", model="-", data_mode="masked", bytes_out=0, ok=False,
                          error="egress_refused:dictionary_unavailable"))
        await db.commit()
    view = (await client.get("/api/v1/privacy/overview", headers=owner)).json()["data"]["ai_egress"]
    assert view["mode"] == "masked" and view["source"] == "platform" and view["platform_mode"] == "masked"
    assert view["provider_host"] == "api.deepseek.com" and view["model"] == get_settings().llm_model
    assert view["provider_is_local"] is False and view["allowed_modes"] == ["off", "masked"]
    assert view["usage"] == {"days": 30, "calls": 2, "bytes_out": 1500, "calls_by_mode": {"masked": 2},
                             "refused": {"dictionary_unavailable": 1}, "refused_total": 1}
    assert view["models"] and view["embeddings"] == {"pending_reindex": 0}
    states = {c["key"]: c["state"] for c in view["categories"]}
    assert states["figures"] == "sent" and states["identifiers"] == "replaced" and states["counterparties"] == "replaced"
    assert states["descriptions"] == "partly" and states["document_text"] == "partly"
    assert "payload" not in str(view).lower()
    other = (await client.get("/api/v1/privacy/overview", headers=analyst)).json()["data"]
    assert other["ai_egress"] is None


async def test_choosing_a_mode_is_owner_only_recorded_and_capped_by_the_operator(client, monkeypatch) -> None:
    owner, analyst, org, uid = await _owner_and_analyst(client)
    assert (await client.put(URL, json={"mode": "off"}, headers=analyst)).status_code == 403

    tightened = await client.put(URL, json={"mode": "off"}, headers=owner)
    assert tightened.status_code == 200 and tightened.json()["data"]["mode"] == "off"
    assert tightened.json()["data"]["organisation_choice"] == "off" and tightened.json()["data"]["source"] == "organisation"

    refused = await client.put(URL, json={"mode": "raw"}, headers=owner)          # looser than the operator's `masked`
    assert refused.status_code == 409 and "LLM_DATA_MODE" in str(refused.json())
    assert (await client.put(URL, json={"mode": "banana"}, headers=owner)).status_code == 422

    monkeypatch.setattr(get_settings(), "llm_org_may_relax", True)
    relaxed = await client.put(URL, json={"mode": "raw"}, headers=owner)
    assert relaxed.status_code == 200 and relaxed.json()["data"]["mode"] == "raw"
    assert relaxed.json()["data"]["categories"][0]["state"] == "sent"

    cleared = await client.put(URL, json={"mode": None}, headers=owner)
    assert cleared.json()["data"]["organisation_choice"] is None and cleared.json()["data"]["mode"] == "masked"

    async with client._maker() as db:
        rows = (await db.execute(select(Decision).where(Decision.org_id == org, Decision.kind == DecisionKind.LLM_DATA_MODE_CHANGE)
                                 .order_by(Decision.decided_at))).scalars().all()
        assert [(r.before, r.after) for r in rows] == [
            ({"mode": None}, {"mode": "off"}), ({"mode": "off"}, {"mode": "raw"}), ({"mode": "raw"}, {"mode": None})]
        assert all(r.decided_by == uid and r.decided_via == "human" and r.decided_at for r in rows)  # who, when
        assert (await db.get(Organization, org)).llm_data_mode is None


async def test_the_dictionary_size_is_shown_as_a_count_never_the_names(client) -> None:
    owner, _, org, _ = await _owner_and_analyst(client)
    async with client._maker() as db:
        from app.models.related_party import RelatedParty

        db.add(RelatedParty(org_id=org, name="Gizli Tedarikçi A.Ş.", normalized_name="gizli", relationship_type="diger"))
        await db.commit()
    view = (await client.get("/api/v1/privacy/overview", headers=owner)).json()["data"]["ai_egress"]
    assert view["dictionary"]["known_names"] >= 2 and view["dictionary"]["complete"] is True
    assert "Gizli" not in str(view)
