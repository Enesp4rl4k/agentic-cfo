"""A payment plan changes only with a senior executive's approval.

The owner's rule: a member proposes, an owner or an admin decides. These tests walk the role matrix
route by route, the organisation boundary, and what the radar does (and does not do) with a proposal.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select

from app.models.open_item import OpenItem
from app.models.user import User
from app.services.self_approval import SELF_DECISION_ACK
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def today() -> date:
    return datetime.now(UTC).date()


async def member(client, email: str, org_id: str, role: str) -> dict[str, str]:
    """A second person in an existing organisation, signed in with the given role."""
    await client.post("/api/v1/auth/register", json={"email": email, "password": PAROLA, "full_name": "T"})
    async with client._maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        user.org_id = org_id
        user.role = role
        await db.commit()
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": PAROLA})).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def seed_item(client, org_id: str, *, direction: str = "payable", days: int = 20, **over) -> str:
    async with client._maker() as db:
        item = OpenItem(
            org_id=org_id,
            direction=direction,
            document_id=f"D-{direction}-{days}-{over.get('suffix', '')}",
            counterparty="Ana Tedarikci AS",
            amount_cents=120_000_00,
            issue_date=today() - timedelta(days=10),
            due_date=over.get("due", today() + timedelta(days=days)),
            status=over.get("status", "open"),
        )
        db.add(item)
        await db.commit()
        return item.id


async def propose(client, headers, item_id: str, to: date, note: str | None = None):
    return await client.post(
        "/api/v1/ledger/plan-changes",
        headers=headers,
        json={"open_item_id": item_id, "to_date": to.isoformat(), "note": note},
    )


async def radar_week_of(client, headers, item_id: str) -> tuple[int, bool] | None:
    body = (await client.get("/api/v1/ledger/cash-radar", headers=headers)).json()["data"]
    for w in body["weeks"]:
        for p in w["payables"]:
            if p["id"] == item_id:
                return w["week"], p["rescheduled"]
    return None


async def test_a_members_proposal_waits_for_an_owner_or_admin(client):
    owner, org_id, _ = await kullanici(client, "sahip@example.com", role="owner")
    analyst = await member(client, "analist@example.com", org_id, "analyst")
    admin = await member(client, "yonetici@example.com", org_id, "admin")
    item = await seed_item(client, org_id, days=20)
    before = await radar_week_of(client, owner, item)

    created = await propose(client, analyst, item, today() + timedelta(days=50), "tedarikçi anlaştı")
    assert created.status_code == 201
    change_id = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "pending"

    # nothing moved yet
    assert await radar_week_of(client, owner, item) == before
    # the analyst cannot decide, not even their own proposal
    denied = await client.post(f"/api/v1/ledger/plan-changes/{change_id}/approve", headers=analyst, json={})
    assert denied.status_code == 403
    assert await radar_week_of(client, owner, item) == before

    approved = await client.post(f"/api/v1/ledger/plan-changes/{change_id}/approve", headers=admin, json={"note": "uygun"})
    assert approved.status_code == 200
    data = approved.json()["data"]
    assert data["status"] == "approved"
    assert data["decision_note"] == "uygun"
    after = await radar_week_of(client, owner, item)
    assert after is not None and before is not None
    assert after[0] > before[0] and after[1] is True

    # the document's own due date is untouched
    async with client._maker() as db:
        row = (await db.execute(select(OpenItem).where(OpenItem.id == item))).scalar_one()
        assert row.due_date == today() + timedelta(days=20)


async def test_an_owner_or_admin_holds_the_authority_for_their_own_proposal(client):
    owner, org_id, _ = await kullanici(client, "sahip2@example.com", role="owner")
    item = await seed_item(client, org_id, days=10)
    change = (await propose(client, owner, item, today() + timedelta(days=40))).json()["data"]
    done = await client.post(
        f"/api/v1/ledger/plan-changes/{change['id']}/approve", headers=owner,
        json={"self_decision_ack": SELF_DECISION_ACK},
    )
    assert done.status_code == 200
    assert done.json()["data"]["decided_by"] == done.json()["data"]["requested_by"]


async def test_who_may_propose_and_what_may_be_proposed(client):
    owner, org_id, _ = await kullanici(client, "sahip3@example.com", role="owner")
    viewer = await member(client, "izleyici@example.com", org_id, "viewer")
    payable = await seed_item(client, org_id, days=15, suffix="a")
    receivable = await seed_item(client, org_id, direction="receivable", days=15, suffix="b")
    settled = await seed_item(client, org_id, days=15, status="settled", suffix="c")
    undated = await seed_item(client, org_id, days=15, suffix="d")
    async with client._maker() as db:
        row = (await db.execute(select(OpenItem).where(OpenItem.id == undated))).scalar_one()
        row.due_date = None
        await db.commit()

    assert (await propose(client, viewer, payable, today() + timedelta(days=40))).status_code == 403
    assert (await propose(client, owner, receivable, today() + timedelta(days=40))).status_code == 422
    assert (await propose(client, owner, settled, today() + timedelta(days=40))).status_code == 422
    assert (await propose(client, owner, undated, today() + timedelta(days=40))).status_code == 422
    assert (await propose(client, owner, payable, today() - timedelta(days=1))).status_code == 422
    assert (await propose(client, owner, payable, today() + timedelta(days=500))).status_code == 422
    assert (await propose(client, owner, payable, today() + timedelta(days=15))).status_code == 422  # same date
    assert (await propose(client, owner, "no-such-item", today() + timedelta(days=40))).status_code == 404

    assert (await propose(client, owner, payable, today() + timedelta(days=40))).status_code == 201
    # one open proposal per payment
    assert (await propose(client, owner, payable, today() + timedelta(days=45))).status_code == 409


async def test_a_rejection_changes_nothing_and_keeps_its_reason(client):
    owner, org_id, _ = await kullanici(client, "sahip4@example.com", role="owner")
    analyst = await member(client, "analist4@example.com", org_id, "analyst")
    item = await seed_item(client, org_id, days=12)
    before = await radar_week_of(client, owner, item)
    change = (await propose(client, analyst, item, today() + timedelta(days=60))).json()["data"]

    rejected = await client.post(f"/api/v1/ledger/plan-changes/{change['id']}/reject", headers=owner, json={"note": "kredi vadesi"})
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "rejected"
    assert rejected.json()["data"]["decision_note"] == "kredi vadesi"
    assert await radar_week_of(client, owner, item) == before
    # decided once
    again = await client.post(f"/api/v1/ledger/plan-changes/{change['id']}/approve", headers=owner, json={})
    assert again.status_code == 409
    # and a new proposal is possible once the old one is decided
    assert (await propose(client, analyst, item, today() + timedelta(days=30))).status_code == 201


async def test_only_the_proposer_withdraws_and_only_while_it_waits(client):
    owner, org_id, _ = await kullanici(client, "sahip5@example.com", role="owner")
    analyst = await member(client, "analist5@example.com", org_id, "analyst")
    other = await member(client, "analist6@example.com", org_id, "analyst")
    item = await seed_item(client, org_id, days=12)
    change = (await propose(client, analyst, item, today() + timedelta(days=60))).json()["data"]

    assert (await client.post(f"/api/v1/ledger/plan-changes/{change['id']}/withdraw", headers=other)).status_code == 403
    assert (await client.post(f"/api/v1/ledger/plan-changes/{change['id']}/withdraw", headers=analyst)).status_code == 200
    assert (await client.post(f"/api/v1/ledger/plan-changes/{change['id']}/withdraw", headers=analyst)).status_code == 409
    assert (await client.post(f"/api/v1/ledger/plan-changes/{change['id']}/approve", headers=owner, json={})).status_code == 409


async def test_another_organisations_proposals_are_not_there_to_see_or_decide(client):
    owner, org_id, _ = await kullanici(client, "sahip7@example.com", role="owner")
    outsider, _, _ = await kullanici(client, "yabanci@example.com", role="owner")
    item = await seed_item(client, org_id, days=12)
    change = (await propose(client, owner, item, today() + timedelta(days=60))).json()["data"]

    assert (await client.get("/api/v1/ledger/plan-changes", headers=outsider)).json()["data"] == []
    for action in ("approve", "reject", "withdraw"):
        r = await client.post(f"/api/v1/ledger/plan-changes/{change['id']}/{action}", headers=outsider, json={})
        assert r.status_code == 404
    assert (await propose(client, outsider, item, today() + timedelta(days=60))).status_code == 404


async def test_the_list_says_whether_the_caller_may_decide(client):
    owner, org_id, _ = await kullanici(client, "sahip8@example.com", role="owner")
    analyst = await member(client, "analist8@example.com", org_id, "analyst")
    item = await seed_item(client, org_id, days=12)
    await propose(client, analyst, item, today() + timedelta(days=60))

    as_owner = (await client.get("/api/v1/ledger/plan-changes", headers=owner)).json()
    as_analyst = (await client.get("/api/v1/ledger/plan-changes", headers=analyst)).json()
    assert as_owner["meta"]["can_decide"] is True
    assert as_analyst["meta"]["can_decide"] is False
    assert len(as_owner["data"]) == 1
    assert as_owner["data"][0]["counterparty"] == "Ana Tedarikci AS"
    assert (await client.get("/api/v1/ledger/plan-changes?status=nonsense", headers=owner)).status_code == 422
