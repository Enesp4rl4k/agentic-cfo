"""A decision is readable only by the roles that may see the thing it is about, on every path that returns it."""
from __future__ import annotations

import pytest_asyncio

from app.api.access import READ_ROLES, may_read_decision_kind, readable_decision_kinds
from app.models.decision import DECISION_READ, Decision, DecisionKind, ReadClass, read_class
from app.models.organization import OrgMembership
from app.models.user import User
from app.services.decisions import record_decision
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici

API = "/api/v1/decision-records"
ROLES = ["owner", "admin", "cfo", "smmm", "analyst", "viewer"]


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _member(client, email: str, org_id: str, role: str) -> dict[str, str]:
    """A second user in `org_id` with `role` (membership and column), signed in."""
    from app.services.auth import create_access_token, hash_password

    async with client._maker() as db:
        user = User(email=email, hashed_password=hash_password(PAROLA), full_name="T", role=role, org_id=org_id)
        db.add(user)
        await db.flush()
        db.add(OrgMembership(org_id=org_id, user_id=user.id, role=role))
        await db.commit()
    token = create_access_token(user.id, email, role, token_version=0)   # login is rate-limited to 5 a minute
    return {"Authorization": f"Bearer {token}"}


async def _seed_every_kind(client, org_id: str, user_id: str) -> dict[str, str]:
    """One decision per kind, target `t-<kind>`; returns kind -> decision id."""
    ids: dict[str, str] = {}
    async with client._maker() as db:
        for kind in DecisionKind:
            row = await record_decision(db, org_id=org_id, kind=kind, target_type="thing", target_id=f"t-{kind.value}",
                                        outcome="x", decided_via="human", decided_by=user_id)
            ids[kind.value] = row.id
        await db.commit()
    return ids


def test_every_kind_has_a_read_class_and_every_class_has_roles() -> None:
    assert set(DECISION_READ) == set(DecisionKind), "a new decision kind needs an entry in DECISION_READ"
    assert set(READ_ROLES) == set(ReadClass)


def test_an_unknown_kind_fails_closed() -> None:
    assert read_class("kind-from-the-future") is ReadClass.DECIDER
    assert not may_read_decision_kind("cfo", "kind-from-the-future")
    assert not may_read_decision_kind("viewer", "kind-from-the-future")
    assert may_read_decision_kind("owner", "kind-from-the-future")
    assert may_read_decision_kind(None, "settlement_match") is False
    assert readable_decision_kinds("owner") is None and "security_setting_change" not in (readable_decision_kinds("cfo") or ())


async def test_the_reviewers_reproduction_a_viewer_cannot_read_the_ip_whitelist_record(client):
    owner, org_id, _ = await kullanici(client, "okuma-sahip@example.com")
    assert (await client.put("/api/v1/security/ip-whitelist", headers=owner,
                             json={"cidrs": ["203.0.113.42/32"], "enabled": True})).status_code == 200
    by_object = f"{API}?target_type=organization_ip_whitelist&target_id={org_id}"
    got = (await client.get(by_object, headers=owner)).json()["data"]
    assert [d["kind"] for d in got] == ["security_setting_change"] and "203.0.113.42/32" in str(got)
    for role in ("admin", "cfo", "smmm", "analyst", "viewer"):
        h = await _member(client, f"okuma-{role}@example.com", org_id, role)
        res = await client.get(by_object, headers=h)
        if role == "admin":
            assert len(res.json()["data"]) == 1                     # a decider may read it
            continue
        assert res.status_code == 200 and res.json()["data"] == [], role
        assert "203.0.113.42" not in res.text, role
        assert (await client.get(f"{API}?kind=security_setting_change&target_type=x&target_id={org_id}", headers=h)).status_code == 403
        company = await client.get(API, headers=h)
        assert "203.0.113.42" not in company.text, role


async def test_matrix_role_by_kind_by_path_follows_the_table(client):
    owner, org_id, owner_id = await kullanici(client, "matris@example.com")
    ids = await _seed_every_kind(client, org_id, owner_id)
    # a stored kind this code does not know
    async with client._maker() as db:
        db.add(Decision(org_id=org_id, kind="kind-from-the-future", target_type="thing", target_id="t-future",
                        outcome="x", decided_via="human", decided_by=owner_id, evidence_refs=[]))
        await db.commit()
    for role in ROLES:
        h = owner if role == "owner" else await _member(client, f"matris-{role}@example.com", org_id, role)
        allowed = {k.value for k in DecisionKind if may_read_decision_kind(role, k.value)}
        # path 1: the company-wide log (writers only), kind-filtered rather than all-or-nothing
        company = await client.get(f"{API}?limit=200", headers=h)
        if role in ("owner", "admin", "cfo", "smmm"):
            seen = {d["id"] for d in company.json()["data"]}
            extra = 1 if role in ("owner", "admin") else 0     # the unknown kind: deciders only
            assert {ids[k] for k in allowed} <= seen and len(seen) == len(allowed) + extra, role
        else:
            assert company.status_code == 403, role
        for kind in DecisionKind:
            # path 2: one object's history; path 3: the same with an explicit kind; path 4: kind alone
            obj = f"{API}?target_type=thing&target_id=t-{kind.value}"
            body = (await client.get(obj, headers=h)).json()["data"]
            assert [d["id"] for d in body] == ([ids[kind.value]] if kind.value in allowed else []), (role, kind)
            with_kind = await client.get(f"{obj}&kind={kind.value}", headers=h)
            kind_only = await client.get(f"{API}?kind={kind.value}", headers=h)
            if kind.value in allowed:
                assert [d["id"] for d in with_kind.json()["data"]] == [ids[kind.value]], (role, kind)
            else:
                assert with_kind.status_code == 403 and kind_only.status_code == 403, (role, kind)
        future = (await client.get(f"{API}?target_type=thing&target_id=t-future", headers=h)).json()["data"]
        assert bool(future) == (role in ("owner", "admin")), role      # unknown kind: deciders only


async def test_another_organisations_object_id_yields_nothing(client):
    _, org_a, user_a = await kullanici(client, "tenant-a@example.com")
    owner_b, _, _ = await kullanici(client, "tenant-b@example.com")
    ids = await _seed_every_kind(client, org_a, user_a)
    for kind in ("settlement_match", "security_setting_change"):
        res = await client.get(f"{API}?target_type=thing&target_id=t-{kind}", headers=owner_b)
        assert res.status_code == 200 and res.json()["data"] == [], kind
        assert ids[kind] not in res.text
