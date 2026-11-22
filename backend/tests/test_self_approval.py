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
    assert change["self_decision"] == BLOCKED and "üstünde" in change["self_decision_message"]

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
    before = await propose(client, owner, await seed(client, org_id, amount=40_000_00, tag="s"))
    assert before["self_decision"] == ACKNOWLEDGE  # under the fixed 100.000
    set_it = await client.put("/api/v1/org/me/materiality", headers=owner, json={"amount_cents": 10_000_00, "reason": "küçük şirket"})
    assert set_it.status_code == 200
    after = await propose(client, owner, await seed(client, org_id, amount=40_000_00, tag="t"))
    assert after["self_decision"] == BLOCKED  # 40.000 is large for this company now
    # the proposal made before the change is judged against the threshold of its day
    now = {c["id"]: c["self_decision"] for c in (await client.get(PLANS, headers=owner)).json()["data"]}
    assert now[before["id"]] == ACKNOWLEDGE and now[after["id"]] == BLOCKED


async def test_an_admin_cannot_move_the_threshold_to_approve_their_own_proposal(client):
    """The reviewer's sequence: an admin proposes above the threshold, cannot approve, cannot raise the
    threshold either, and a proposal already made stays with the other decider whatever the owner does later."""
    owner, org_id, _ = await kullanici(client, "sahip7b@example.com", role="owner")
    admin = await member(client, "yonetici7b@example.com", org_id, "admin")
    change = await propose(client, admin, await seed(client, org_id, amount=900_000_00, tag="r"))
    assert change["self_decision"] == BLOCKED
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=admin, json=ACK)).status_code == 403

    url = "/api/v1/org/me/materiality"
    for amount in (10**12, 900_000_00):
        r = await client.put(url, headers=admin, json={"amount_cents": amount, "reason": "yükselt"})
        assert r.status_code == 403
    assert (await client.post(f"{url}/acknowledge", headers=admin, json={"amount_cents": 1})).status_code == 403
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=admin, json=ACK)).status_code == 403

    # the owner may change it, inside the bounds; the proposal already made is still the owner's to decide
    assert (await client.put(url, headers=owner, json={"amount_cents": 1_000_000_00, "reason": "büyüdük"})).status_code == 200
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=admin, json=ACK)).status_code == 403
    listing = (await client.get(PLANS, headers=owner)).json()["data"]
    assert listing[0]["threshold_changed_by_proposer"] is False  # the owner moved it, the admin proposed
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=owner, json={})).status_code == 200


async def test_a_proposal_by_the_person_who_changed_the_threshold_is_flagged(client):
    owner, org_id, _ = await kullanici(client, "sahip7c@example.com", role="owner")
    await member(client, "yonetici7c@example.com", org_id, "admin")
    await client.put("/api/v1/org/me/materiality", headers=owner, json={"amount_cents": 50_000_00, "reason": "ayar"})
    mine = await propose(client, owner, await seed(client, org_id, amount=10_000_00, tag="f"))
    assert mine["threshold_changed_by_proposer"] is True


async def test_three_changes_just_under_the_threshold_are_not_three_trivial_ones(client):
    owner, org_id, _ = await kullanici(client, "sahip8b@example.com", role="owner")
    admin = await member(client, "yonetici8b@example.com", org_id, "admin")
    states = []
    for n in range(3):
        change = await propose(client, admin, await seed(client, org_id, amount=99_000_00, tag=f"p{n}"))
        states.append(change["self_decision"])
        if change["self_decision"] == ACKNOWLEDGE:
            assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=admin, json=ACK)).status_code == 200
    assert states == [ACKNOWLEDGE, BLOCKED, BLOCKED]
    assert "son 30 günde kendi onayladığınız değişikliklerin toplamı eşiği aşıyor" in change["self_decision_message"]
    refused = await client.post(f"{PLANS}/{change['id']}/approve", headers=admin, json=ACK)
    assert refused.status_code == 403
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=owner, json={})).status_code == 200


async def test_a_missing_open_item_is_an_unknown_amount_and_counts_as_large(client):
    owner, org_id, _ = await kullanici(client, "sahip9b@example.com", role="owner")
    await member(client, "yonetici9b@example.com", org_id, "admin")
    item = await seed(client, org_id, amount=1_000_00, tag="m")
    change = await propose(client, owner, item)
    assert change["self_decision"] == ACKNOWLEDGE
    async with client._maker() as db:
        await db.delete(await db.get(OpenItem, item))
        await db.commit()
    now = (await client.get(PLANS, headers=owner)).json()["data"][0]
    assert now["self_decision"] == BLOCKED and "Tutar bilinmiyor" in now["self_decision_message"]
    assert (await client.post(f"{PLANS}/{change['id']}/approve", headers=owner, json=ACK)).status_code == 403


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


async def test_what_was_self_approved_in_another_currency_is_not_added_to_the_total(client):
    from app.services.self_approval import self_approved_total

    _owner, org_id, owner_id = await kullanici(client, "sahip10@example.com", role="owner")
    now = datetime.now(UTC)
    async with client._maker() as db:
        for cur, cents in (("TRY", 40_000_00), ("USD", 900_000_00), ("try", 5_000_00), ("", 7_000_00)):
            db.add(Decision(
                org_id=org_id, kind="plan_change", target_type="payment_plan_change", target_id="x", outcome="approved",
                decided_via="human", decided_by=owner_id, decided_at=now,
                after={"self_decided": True, "amount_cents": cents, "currency": cur},
            ))
        await db.commit()
        assert await self_approved_total(db, org_id, owner_id, "TRY") == 45_000_00
        assert await self_approved_total(db, org_id, owner_id, "USD") == 900_000_00
        assert await self_approved_total(db, org_id, owner_id, "EUR") == 0


async def test_the_self_approval_check_takes_a_lock_on_the_proposers_membership():
    """On Postgres the second of two concurrent self-approvals waits for the first's commit (FOR UPDATE)."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.dialects import postgresql

    from app.models.organization import OrgMembership

    stmt = sa_select(OrgMembership.id).where(OrgMembership.org_id == "o", OrgMembership.user_id == "u").with_for_update()
    assert "FOR UPDATE" in str(stmt.compile(dialect=postgresql.dialect()))


async def test_a_second_self_approval_is_judged_after_the_first_even_when_both_were_loaded_together(client):
    """Two requests, each with its own session, each loaded its proposal before either approved. The second
    re-reads after the first committed, so the cumulative limit holds (3 x 99.000 against 100.000)."""
    from fastapi import HTTPException

    from app.api.plan_changes import DecisionRequest, _apply_decision
    from app.models.payment_plan_change import PaymentPlanChange

    _owner, org_id, _ = await kullanici(client, "sahip11@example.com", role="owner")
    admin = await member(client, "yonetici11@example.com", org_id, "admin")
    ids = [(await propose(client, admin, await seed(client, org_id, amount=99_000_00, tag=f"c{n}")))["id"] for n in range(2)]
    async with client._maker() as db1, client._maker() as db2:
        user1 = (await db1.execute(select(User).where(User.email == "yonetici11@example.com"))).scalar_one()
        user2 = (await db2.execute(select(User).where(User.email == "yonetici11@example.com"))).scalar_one()
        first = (await db1.execute(select(PaymentPlanChange).where(PaymentPlanChange.id == ids[0]))).scalar_one()
        second = (await db2.execute(select(PaymentPlanChange).where(PaymentPlanChange.id == ids[1]))).scalar_one()
        body = DecisionRequest(self_decision_ack=SELF_DECISION_ACK)
        assert (await _apply_decision(db1, first, True, body, user1))["error"] is None
        try:
            await _apply_decision(db2, second, True, body, user2)
            raise AssertionError("the second self-approval must be refused")
        except HTTPException as exc:
            assert exc.status_code == 403
    assert len(await approvals(client, org_id)) == 1
