"""A small company with an outside accountant: owner + smmm, end to end.

Many small companies have no finance person; the accountant (`smmm`, a member of several
organisations) does the month close and receives the briefing. These tests check: `has_smmm` on
`/org/me`; the month close in an owner + smmm company (who may close, who sees it, what is recorded);
the accountant's workload across organisations with no cross-tenant leak (an accountant in two
organisations, another organisation they are not in, and one where they hold another role); and the
owner's recorded choice that the briefing also goes to the accountant (a recipient only; the outbox's
release flow is untouched).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import select

from app.api.auth import create_access_token, hash_password
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.decision import Decision
from app.models.organization import Organization, OrgMembership
from app.models.outbox_message import OutboxMessage
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.models.user import User
from app.services import accountant, briefing_delivery
from tests.api_helpers import PAROLA, bellek_istemcisi

REC = "/api/v1/org/me/briefing-recipients"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def company(client, name: str) -> str:
    async with client._maker() as db:
        org = Organization(name=name, slug=name, regional_packs=["tr"])
        db.add(org)
        await db.commit()
        return org.id


async def person(client, email: str, memberships: dict[str, str], *, acting: str, active: bool = True) -> tuple[dict[str, str], str]:
    """A user with a membership per organisation and a session acting in `acting`."""
    async with client._maker() as db:
        user = User(email=email, hashed_password=hash_password(PAROLA), full_name="T", role=memberships[acting], org_id=acting, is_active=active)
        db.add(user)
        await db.flush()
        for org_id, role in memberships.items():
            db.add(OrgMembership(user_id=user.id, org_id=org_id, role=role))
        await db.commit()
        token = create_access_token(user.id, email, memberships[acting])
        return {"Authorization": f"Bearer {token}"}, user.id


async def queue_entry(client, org_id: str, user_id: str, n: int = 1) -> None:
    async with client._maker() as db:
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv", org_id=org_id, user_id=user_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        for i in range(n):
            db.add(SMMMOnayKaydi(job_id=job.id, org_id=org_id, kayit_id=f"k{i}", orijinal_kayit={}, durum=OnayDurumu.BEKLIYOR))
        await db.commit()


async def switch(client, headers, org_id: str) -> None:
    assert (await client.post("/api/v1/org/switch", headers=headers, json={"org_id": org_id})).status_code == 200


# ── has_smmm ─────────────────────────────────────────────────────────────────

async def test_org_me_says_whether_the_company_has_an_active_accountant(client):
    org = await company(client, "acme")
    owner, _ = await person(client, "sahip@acme.com", {org: "owner"}, acting=org)
    me = (await client.get("/api/v1/org/me", headers=owner)).json()["data"]
    assert me["has_smmm"] is False and me["briefing_to_smmm"] is False and me["profile_defaults"] is None

    await person(client, "musavir@acme.com", {org: "smmm"}, acting=org)
    assert (await client.get("/api/v1/org/me", headers=owner)).json()["data"]["has_smmm"] is True


async def test_an_inactive_accountant_is_not_counted_and_one_in_another_company_is_not_this_ones(client):
    a, b = await company(client, "a"), await company(client, "b")
    owner, _ = await person(client, "sahip@a.com", {a: "owner"}, acting=a)
    await person(client, "pasif@a.com", {a: "smmm"}, acting=a, active=False)
    await person(client, "baska@b.com", {b: "smmm"}, acting=b)
    assert (await client.get("/api/v1/org/me", headers=owner)).json()["data"]["has_smmm"] is False


async def test_the_profile_defaults_ride_on_org_me_once_a_profile_is_confirmed(client):
    org = await company(client, "mikro")
    owner, _ = await person(client, "sahip@mikro.com", {org: "owner"}, acting=org)
    assert (await client.post("/api/v1/org/me/size-profile/confirm", headers=owner, json={"profile": "micro"})).status_code == 200
    d = (await client.get("/api/v1/org/me", headers=owner)).json()["data"]["profile_defaults"]
    assert d == {"one_tap_first": True, "briefing_to_smmm_suggested": True}
    assert (await client.post("/api/v1/org/me/size-profile/confirm", headers=owner, json={"profile": "medium"})).status_code == 200
    d = (await client.get("/api/v1/org/me", headers=owner)).json()["data"]["profile_defaults"]
    assert d == {"one_tap_first": False, "briefing_to_smmm_suggested": False}


# ── month close in an owner + smmm company ───────────────────────────────────

async def test_the_accountant_closes_the_month_the_owner_sees_it_and_it_is_recorded(client):
    org = await company(client, "kapanis")
    owner, _owner_id = await person(client, "sahip@kapanis.com", {org: "owner"}, acting=org)
    smmm, smmm_id = await person(client, "musavir@kapanis.com", {org: "smmm"}, acting=org)

    # the company's decision-maker does not close the books when it has an accountant: it is the accountant's sign-off
    refused = await client.post("/api/v1/smmm/donem-kilitleri", headers=owner, json={"donem": "2026-01"})
    assert refused.status_code == 403

    closed = await client.post("/api/v1/smmm/donem-kilitleri", headers=smmm, json={"donem": "2026-01"})
    assert closed.status_code == 200 and closed.json()["data"]["kilitleyen_user_id"] == smmm_id
    assert (await client.post("/api/v1/smmm/donem-kilitleri", headers=smmm, json={"donem": "2026-01"})).status_code == 409

    seen = (await client.get("/api/v1/smmm/donem-kilitleri", headers=owner)).json()["data"]["donemler"]
    assert [d["donem"] for d in seen] == ["2026-01"]
    async with client._maker() as db:
        [rec] = (await db.execute(select(Decision).where(Decision.org_id == org, Decision.kind == "month_close"))).scalars()
    assert rec.decided_by == smmm_id and rec.outcome == "closed" and rec.target_id == "2026-01"


async def test_a_company_with_only_an_owner_closes_its_own_month(client):
    org = await company(client, "yalniz")
    owner, _owner_id = await person(client, "sahip@yalniz.com", {org: "owner"}, acting=org)
    assert (await client.post("/api/v1/smmm/donem-kilitleri", headers=owner, json={"donem": "2026-01"})).status_code == 200


async def test_the_accountant_does_not_decide_the_companys_commercial_matters(client):
    """SMMM onay on accounting entries is theirs; moving a payment date and the materiality threshold are not."""
    org = await company(client, "ticari")
    await person(client, "sahip@ticari.com", {org: "owner"}, acting=org)
    smmm, _ = await person(client, "musavir@ticari.com", {org: "smmm"}, acting=org)
    assert (await client.put("/api/v1/org/me/materiality", headers=smmm, json={"amount_cents": 1000})).status_code == 403
    assert (await client.put(REC, headers=smmm, json={"send_to_smmm": True})).status_code == 403
    r = await client.post("/api/v1/ledger/plan-changes", headers=smmm, json={"open_item_id": "x", "to_date": "2030-01-01"})
    assert r.status_code == 403


# ── the workload across organisations ────────────────────────────────────────

async def test_the_workload_lists_only_the_organisations_the_caller_is_an_accountant_of(client):
    a, b, c, d = [await company(client, n) for n in ("alfa", "beta", "gama", "delta")]
    smmm, smmm_id = await person(client, "musavir@x.com", {a: "smmm", b: "smmm", d: "analyst"}, acting=a)
    other, other_id = await person(client, "baska@x.com", {c: "smmm"}, acting=c)
    await queue_entry(client, a, smmm_id, 2)
    await queue_entry(client, b, smmm_id, 3)
    await queue_entry(client, c, other_id, 7)  # another accountant's company
    await queue_entry(client, d, smmm_id, 5)  # a company where the caller is only an analyst

    got = (await client.get("/api/v1/smmm/workload", headers=smmm)).json()["data"]
    rows = {r["name"]: r for r in got["organizations"]}
    assert set(rows) == {"alfa", "beta"}
    assert rows["alfa"]["pending_onay"] == 2 and rows["beta"]["pending_onay"] == 3
    assert got["total_waiting"] == 5
    assert "gama" not in str(got) and "delta" not in str(got) and c not in str(got) and d not in str(got)

    # the same answer whichever company the accountant is acting in
    await switch(client, smmm, b)
    again = (await client.get("/api/v1/smmm/workload", headers=smmm)).json()["data"]
    assert {r["name"]: r["pending_onay"] for r in again["organizations"]} == {"alfa": 2, "beta": 3}

    # and the acting company's queue is that company's alone
    queue = (await client.get("/api/v1/smmm/onay/queue", headers=smmm)).json()["data"]
    assert queue["total"] == 3

    # the other accountant sees theirs and nothing of the first
    theirs = (await client.get("/api/v1/smmm/workload", headers=other)).json()["data"]
    assert [r["name"] for r in theirs["organizations"]] == ["gama"] and theirs["organizations"][0]["pending_onay"] == 7


async def test_a_user_who_is_nobodys_accountant_has_an_empty_workload(client):
    org = await company(client, "sade")
    owner, _ = await person(client, "sahip@sade.com", {org: "owner"}, acting=org)
    assert (await client.get("/api/v1/smmm/workload", headers=owner)).json()["data"] == {"organizations": [], "total_waiting": 0}


async def test_the_workload_counts_the_months_to_close_and_the_briefings_held(client):
    org = await company(client, "ay")
    smmm, _smmm_id = await person(client, "musavir@ay.com", {org: "smmm"}, acting=org)
    async with client._maker() as db:
        period = accountant.previous_month()
        year, month = int(period[:4]), int(period[5:7])
        db.add(CanonicalTransaction(
            org_id=org, source_type="bank_statement", source_record_id="r1",
            transaction_date=datetime(year, month, 10, tzinfo=UTC), amount_cents=100, currency="TRY", direction="expense",
        ))
        db.add(OutboxMessage(key="k1", org_id=org, channel="email", recipient="x@x.com", subject="s", body="b",
                             source="monday_briefing", source_ref="b1", status="held"))
        await db.commit()
    row = (await client.get("/api/v1/smmm/workload", headers=smmm)).json()["data"]["organizations"][0]
    assert row["month_to_close"] == period and row["briefings_held"] == 1 and row["waiting"] == 2

    assert (await client.post("/api/v1/smmm/donem-kilitleri", headers=smmm, json={"donem": period})).status_code == 200
    after = (await client.get("/api/v1/smmm/workload", headers=smmm)).json()["data"]["organizations"][0]
    assert after["month_to_close"] is None and after["waiting"] == 1


# ── the briefing to the accountant ───────────────────────────────────────────

async def test_the_owner_chooses_that_the_briefing_also_goes_to_the_accountant(client):
    org = await company(client, "bulten")
    owner, owner_id = await person(client, "sahip@bulten.com", {org: "owner"}, acting=org)

    assert (await client.get(REC, headers=owner)).json()["data"] == {"send_to_smmm": False, "has_smmm": False, "suggested": False}
    # nobody to send to: refused, with the way out
    no = await client.put(REC, headers=owner, json={"send_to_smmm": True})
    assert no.status_code == 422 and "davet" in no.json()["error"]

    await person(client, "musavir@bulten.com", {org: "smmm"}, acting=org)
    async with client._maker() as db:
        assert "musavir@bulten.com" not in await briefing_delivery.recipients(db, org)

    r = await client.put(REC, headers=owner, json={"send_to_smmm": True})
    assert r.status_code == 200 and r.json()["data"]["send_to_smmm"] is True
    async with client._maker() as db:
        assert "musavir@bulten.com" in await briefing_delivery.recipients(db, org)
        assert "sahip@bulten.com" in await briefing_delivery.recipients(db, org)
        [rec] = (await db.execute(select(Decision).where(Decision.org_id == org, Decision.kind == "briefing_recipients"))).scalars()
        assert rec.decided_by == owner_id and rec.outcome == "smmm_added" and rec.before == {"send_to_smmm": False}
        # naming a recipient sends nothing and queues nothing
        assert (await db.execute(select(OutboxMessage))).first() is None

    assert (await client.put(REC, headers=owner, json={"send_to_smmm": False})).status_code == 200
    async with client._maker() as db:
        assert "musavir@bulten.com" not in await briefing_delivery.recipients(db, org)
