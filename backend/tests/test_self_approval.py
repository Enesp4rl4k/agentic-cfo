"""The proposer who is also the decider: one honest step, or the other decider decides.

`docs/payment-plan-approval.md`, `app/services/self_approval.py`. The payment-plan change is the one
approve-type decision with a separate proposer today. These tests walk: the only decider (confirms a
sentence, recorded as `self_decided` with it), a second decider and an amount above the company's
materiality threshold (refused), the same with an amount below it (allowed), the threshold the owner
acknowledged or set, a foreign-currency amount (cannot be compared, so counts as material), a rejection
of one's own proposal, and an inactive admin (does not count as a second decider).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select

from app.models.decision import Decision
from app.models.open_item import OpenItem
from app.models.user import User
from app.services.self_approval import ACKNOWLEDGE, BLOCKED, SELF_DECISION_ACK
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici

PLANS = "/api/v1/ledger/plan-changes"
ACK = {"self_decision_ack": SELF_DECISION_ACK}


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def today() -> date:
    return datetime.now(UTC).date()


async def member(client, email: str, org_id: str, role: str, *, active: bool = True) -> dict[str, str]:
    await client.post("/api/v1/auth/register", json={"email": email, "password": PAROLA, "full_name": "T"})
    async with client._maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        user.org_id, user.role = org_id, role
        await db.commit()
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": PAROLA})).json()["data"]["access_token"]
    if not active:
        async with client._maker() as db:
            (await db.execute(select(User).where(User.email == email))).scalar_one().is_active = False
            await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def seed(client, org_id: str, *, amount: int, currency: str = "TRY", tag: str = "a") -> str:
    async with client._maker() as db:
        item = OpenItem(
            org_id=org_id, direction="payable", document_id=f"D-{tag}", counterparty="Tedarikçi AŞ",
            amount_cents=amount, currency=currency, issue_date=today() - timedelta(days=5),
            due_date=today() + timedelta(days=10), status="open",
        )
        db.add(item)
        await db.commit()
        return item.id


async def propose(client, headers, item: str) -> dict:
    r = await client.post(PLANS, headers=headers, json={"open_item_id": item, "to_date": (today() + timedelta(days=40)).isoformat()})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def approvals(client, org_id: str, outcome: str = "approved") -> list[Decision]:
    async with client._maker() as db:
        return list((await db.execute(
            select(Decision).where(Decision.org_id == org_id, Decision.kind == "plan_change", Decision.outcome == outcome)
        )).scalars())


async def test_the_only_decider_confirms_one_sentence_and_it_is_recorded(client):
    owner, org_id, owner_id = await kullanici(client, "tek@example.com", role="owner")
    change = await propose(client, owner, await seed(client, org_id, amount=120_000_00))
    assert change["self_decision"] == ACKNOWLEDGE
    path = f"{PLANS}/{change['id']}/approve"

    # no confirmation, or a different sentence: nothing is decided
    assert (await client.post(path, headers=owner, json={})).status_code == 422
    assert (await client.post(path, headers=owner, json={"self_decision_ack": "tamam"})).status_code == 422
    assert (await approvals(client, org_id)) == []

    done = await client.post(path, headers=owner, json=ACK)
    assert done.status_code == 200 and done.json()["data"]["status"] == "approved"
    [rec] = await approvals(client, org_id)
    assert rec.decided_by == owner_id
    assert rec.after["self_decided"] is True and rec.after["self_decision_ack"] == SELF_DECISION_ACK


async def test_with_a_second_decider_a_large_amount_is_not_the_proposers_to_approve(client):
    owner, org_id, _ = await kullanici(client, "sahip@example.com", role="owner")
    admin = await member(client, "yonetici@example.com", org_id, "admin")
    change = await propose(client, owner, await seed(client, org_id, amount=120_000_00))  # above the fixed 100.000
    assert change["self_decision"] == BLOCKED and "eşiğin üstünde" in change["self_decision_message"]

    refused = await client.post(f"{PLANS}/{change['id']}/approve", headers=owner, json=ACK)
    assert refused.status_code == 403 and "diğer yöneticinin" in refused.json()["error"]
    assert (await approvals(client, org_id)) == []  # nothing recorded, nothing changed

    # the other decider decides: a second pair of eyes, recorded as such
    ok = await client.post(f"{PLANS}/{change['id']}/approve", headers=admin, json={})
    assert ok.status_code == 200
    [rec] = await approvals(client, org_id)
    assert rec.after["self_decided"] is False and "self_decision_ack" not in rec.after


async def test_with_a_second_decider_a_small_amount_may_still_be_decided_alone(client):
    owner, org_id, _ = await kullanici(client, "sahip2@example.com", role="owner")
    await member(client, "yonetici2@example.com", org_id, "admin")
    change = await propose(client, owner, await seed(client, org_id, amount=40_000_00))
    assert change["self_decision"] == ACKNOWLEDGE
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=owner, json={})).status_code == 422
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=owner, json=ACK)).status_code == 200
    [rec] = await approvals(client, org_id)
    assert rec.after["self_decided"] is True


async def test_the_threshold_the_owner_set_decides_what_is_large(client):
    owner, org_id, _ = await kullanici(client, "sahip3@example.com", role="owner")
    await member(client, "yonetici3@example.com", org_id, "admin")
    small = await propose(client, owner, await seed(client, org_id, amount=40_000_00, tag="s"))
    assert small["self_decision"] == ACKNOWLEDGE  # under the fixed 100.000
    set_it = await client.put("/api/v1/org/me/materiality", headers=owner, json={"amount_cents": 10_000_00, "reason": "küçük şirket"})
    assert set_it.status_code == 200
    now = (await client.get(PLANS, headers=owner)).json()["data"]
    assert [c["self_decision"] for c in now] == [BLOCKED]  # 40.000 is large for this company now


async def test_an_amount_in_another_currency_cannot_be_compared_and_counts_as_large(client):
    owner, org_id, _ = await kullanici(client, "sahip4@example.com", role="owner")
    await member(client, "yonetici4@example.com", org_id, "admin")
    change = await propose(client, owner, await seed(client, org_id, amount=500_00, currency="USD"))
    assert change["self_decision"] == BLOCKED


async def test_rejecting_ones_own_proposal_needs_no_second_decider_and_is_recorded(client):
    owner, org_id, owner_id = await kullanici(client, "sahip5@example.com", role="owner")
    await member(client, "yonetici5@example.com", org_id, "admin")
    change = await propose(client, owner, await seed(client, org_id, amount=120_000_00))
    r = await client.post(f"{PLANS}/{change['id']}/reject", headers=owner, json={"note": "vazgeçtim"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "rejected"
    [rec] = await approvals(client, org_id, "rejected")
    assert rec.decided_by == owner_id and rec.after["self_decided"] is True


async def test_an_inactive_admin_is_not_a_second_decider(client):
    owner, org_id, _ = await kullanici(client, "sahip6@example.com", role="owner")
    await member(client, "eski-yonetici@example.com", org_id, "admin", active=False)
    change = await propose(client, owner, await seed(client, org_id, amount=120_000_00))
    assert change["self_decision"] == ACKNOWLEDGE
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=owner, json=ACK)).status_code == 200


async def test_someone_elses_proposal_needs_no_acknowledgement_and_the_list_carries_the_sentence(client):
    owner, org_id, _ = await kullanici(client, "sahip7@example.com", role="owner")
    analyst = await member(client, "analist7@example.com", org_id, "analyst")
    change = await propose(client, analyst, await seed(client, org_id, amount=120_000_00))
    assert change["self_decision"] is None
    listing = (await client.get(PLANS, headers=owner)).json()
    assert listing["meta"]["self_decision_ack"] == SELF_DECISION_ACK
    assert listing["data"][0]["self_decision"] is None
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=owner, json={})).status_code == 200
