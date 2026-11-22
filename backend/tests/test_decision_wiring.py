"""The decision points write their record, in the same transaction, naming who decided.

`tests/test_decision_coverage.py` is the structural net (a deciding route must reach `record_decision`).
This is what lands in the log: kind, target, outcome, the person, and, for a plan change and a
category correction, the before and after.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision import Decision
from app.models.organization import Organization
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.models.transaction import Transaction
from app.platform.authority_matrix import DEFAULT_POLICY_RULES
from app.services.self_approval import SELF_DECISION_ACK
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_payment_plan_changes import member, propose, seed_item

P = "/api/v1"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def records(client, **where) -> list[Decision]:
    async with client._maker() as db:
        rows = (await db.execute(select(Decision).order_by(Decision.decided_at, Decision.id))).scalars().all()
    return [r for r in rows if all(getattr(r, k) == v for k, v in where.items())]


async def test_a_category_correction_is_recorded_with_who_and_what_changed(client):
    owner, org_id, user_id = await kullanici(client, "sahip@example.com")
    async with client._maker() as db:
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv", org_id=org_id,
                          user_id=user_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        tx = Transaction(job_id=job.id, amount_kurus=1000, currency="TRY", type="income", category="revenue",
                         description="Danışmanlık geliri - Kara Holding", vendor="Kara Holding",
                         transaction_date=datetime(2026, 1, 5, tzinfo=UTC))
        db.add(tx)
        await db.commit()
        tx_id, job_id = tx.id, job.id

    r = await client.patch(f"{P}/transactions/{tx_id}/category", headers=owner,
                           json={"category": "other_income", "apply_always": True})
    assert r.status_code == 200, r.text

    [correction] = await records(client, kind="category_correction")
    assert (correction.decided_by, correction.decided_via, correction.outcome) == (user_id, "human", "corrected")
    assert (correction.target_type, correction.target_id) == ("transaction", tx_id)
    assert correction.before == {"category": "revenue"} and correction.after == {"category": "other_income"}
    assert {"type": "analysis_job", "id": job_id} in correction.evidence_refs
    # "Apply always" is a standing rule: its own record, pointing at the correction that taught it.
    [rule] = await records(client, kind="automation_rule_change")
    assert rule.outcome == "enabled" and rule.target_type == "category_rule"
    assert {"type": "decision", "id": correction.id} in rule.evidence_refs


async def test_a_correction_without_apply_always_leaves_one_record_and_no_rule_record(client):
    owner, org_id, user_id = await kullanici(client, "sahip@example.com")
    async with client._maker() as db:
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv", org_id=org_id,
                          user_id=user_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        tx = Transaction(job_id=job.id, amount_kurus=1000, currency="TRY", type="expense", category="rent",
                         description="kira", transaction_date=datetime(2026, 1, 5, tzinfo=UTC))
        db.add(tx)
        await db.commit()
        tx_id = tx.id
    r = await client.patch(f"{P}/transactions/{tx_id}/category", headers=owner, json={"category": "utilities"})
    assert r.status_code == 200
    assert len(await records(client, kind="category_correction")) == 1
    assert await records(client, kind="automation_rule_change") == []


async def test_a_plan_change_leaves_a_record_at_each_step(client):
    owner, org_id, owner_id = await kullanici(client, "sahip@example.com", role="owner")
    analyst = await member(client, "analist@example.com", org_id, "analyst")
    item = await seed_item(client, org_id, days=20)
    target = date.today() + timedelta(days=40)

    created = await propose(client, analyst, item, target, "Nakit sıkışık")
    assert created.status_code == 201, created.text
    change_id = created.json()["data"]["id"]
    [proposed] = await records(client, kind="plan_change")
    assert proposed.outcome == "proposed" and proposed.target_id == change_id
    assert proposed.decided_by != owner_id  # the analyst's, not the owner's
    assert proposed.reason == "Nakit sıkışık"

    r = await client.post(f"{P}/ledger/plan-changes/{change_id}/approve", headers=owner, json={"note": "Tamam"})
    assert r.status_code == 200, r.text
    approved = (await records(client, kind="plan_change", outcome="approved"))[0]
    assert (approved.decided_by, approved.decided_via, approved.reason) == (owner_id, "human", "Tamam")
    assert approved.before == {"status": "pending"}
    assert approved.after == {"from_date": created.json()["data"]["from_date"], "to_date": target.isoformat(),
                              "status": "approved", "self_decided": False}
    assert {"type": "open_item", "id": item} in approved.evidence_refs


async def test_an_owners_own_proposal_is_recorded_as_their_decision(client):
    """An owner or admin holds the authority: their proposal is decided by them, and the log says so."""
    owner, org_id, owner_id = await kullanici(client, "sahip@example.com", role="owner")
    item = await seed_item(client, org_id, days=20)
    created = await propose(client, owner, item, date.today() + timedelta(days=35))
    change_id = created.json()["data"]["id"]
    # the only decider decides their own proposal in one honest step: the sentence is confirmed and recorded
    ack = {"self_decision_ack": SELF_DECISION_ACK}
    assert (await client.post(f"{P}/ledger/plan-changes/{change_id}/approve", headers=owner, json=ack)).status_code == 200

    approvals = await records(client, kind="plan_change", outcome="approved")
    assert len(approvals) == 1
    assert approvals[0].decided_by == owner_id and approvals[0].after["self_decided"] is True
    assert approvals[0].after["self_decision_ack"] == SELF_DECISION_ACK


async def test_a_rejection_and_a_withdrawal_are_recorded(client):
    owner, org_id, owner_id = await kullanici(client, "sahip@example.com", role="owner")
    analyst = await member(client, "analist@example.com", org_id, "analyst")
    first = await seed_item(client, org_id, days=20, suffix="a")
    second = await seed_item(client, org_id, days=25, suffix="b")
    a = (await propose(client, analyst, first, date.today() + timedelta(days=45))).json()["data"]["id"]
    b = (await propose(client, analyst, second, date.today() + timedelta(days=50))).json()["data"]["id"]

    assert (await client.post(f"{P}/ledger/plan-changes/{a}/reject", headers=owner, json={"note": "Hayır"})).status_code == 200
    assert (await client.post(f"{P}/ledger/plan-changes/{b}/withdraw", headers=analyst)).status_code == 200

    [rejected] = await records(client, kind="plan_change", outcome="rejected")
    assert rejected.target_id == a and rejected.decided_by == owner_id and rejected.reason == "Hayır"
    [withdrawn] = await records(client, kind="plan_change", outcome="withdrawn")
    assert withdrawn.target_id == b and withdrawn.decided_by != owner_id


async def test_a_refused_plan_decision_leaves_no_record(client):
    _owner, org_id, _ = await kullanici(client, "sahip@example.com", role="owner")
    analyst = await member(client, "analist@example.com", org_id, "analyst")
    item = await seed_item(client, org_id, days=20)
    change_id = (await propose(client, analyst, item, date.today() + timedelta(days=40))).json()["data"]["id"]
    assert (await client.post(f"{P}/ledger/plan-changes/{change_id}/approve", headers=analyst)).status_code == 403
    assert await records(client, kind="plan_change", outcome="approved") == []


async def test_the_authority_policy_edit_is_recorded(client):
    owner, _, owner_id = await kullanici(client, "sahip@example.com", role="owner")
    r = await client.put(f"{P}/authority/policy", headers=owner, json={"rules": DEFAULT_POLICY_RULES, "note": "Yeni eşikler"})
    assert r.status_code == 200, r.text
    [rec] = await records(client, kind="authority_policy_change")
    assert (rec.decided_by, rec.outcome, rec.reason) == (owner_id, "activated", "Yeni eşikler")
    assert rec.target_id == r.json()["data"]["id"] and rec.after["version"] == 1


async def test_an_accountants_answer_and_the_month_close_are_recorded(client):
    smmm, org_id, smmm_id = await kullanici(client, "musavir@example.com", role="smmm")
    async with client._maker() as db:
        (await db.get(Organization, org_id)).regional_packs = ["tr"]  # the accountant's portal is the Turkey pack
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv", org_id=org_id,
                          user_id=smmm_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        row = SMMMOnayKaydi(job_id=job.id, org_id=org_id, kayit_id="k1", orijinal_kayit={},
                            durum=OnayDurumu.BEKLIYOR)
        db.add(row)
        await db.commit()
        row_id = row.id

    assert (await client.post(f"{P}/smmm/onay/{row_id}/onayla", headers=smmm, json={"onay_notu": "Uygun"})).status_code == 200
    [onay] = await records(client, kind="smmm_onay")
    assert (onay.decided_by, onay.outcome, onay.target_id, onay.reason) == (smmm_id, "approved", row_id, "Uygun")
    assert onay.after["durum"] == "onaylandi"

    donem = (datetime.now(UTC).replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    r = await client.post(f"{P}/smmm/donem-kilitleri", headers=smmm, json={"donem": donem})
    assert r.status_code == 200, r.text
    [close] = await records(client, kind="month_close")
    assert (close.decided_by, close.outcome, close.target_id) == (smmm_id, "closed", donem)


async def test_inviting_and_removing_a_member_are_recorded(client):
    owner, org_id, owner_id = await kullanici(client, "sahip@example.com", role="owner")
    r = await client.post(f"{P}/org/invite", headers=owner, json={"email": "yeni@example.com", "role": "cfo"})
    assert r.status_code == 201, r.text
    [invited] = await records(client, kind="member_change", outcome="invited")
    assert invited.decided_by == owner_id and invited.after == {"role": "cfo", "email": "yeni@example.com"}

    colleague = await member(client, "izleyici@example.com", org_id, "viewer")
    async with client._maker() as db:
        from app.models.user import User

        victim = (await db.execute(select(User).where(User.email == "izleyici@example.com"))).scalar_one().id
    assert (await client.delete(f"{P}/org/members/{victim}", headers=owner)).status_code == 200
    [removed] = await records(client, kind="member_change", outcome="removed")
    assert removed.decided_by == owner_id and removed.before == {"role": "viewer"}
    assert {"type": "user", "id": victim} in removed.evidence_refs
