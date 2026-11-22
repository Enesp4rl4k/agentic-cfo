"""The briefing path keeps its promises: the e-mail a person releases is true when it goes,
a release is a recorded human decision, and "Yaptım" is a statement, not a proof.

Before: the held e-mail body was frozen at enqueue and sent as current whenever it was
released; `outbox.release` recorded neither who nor when; "Yaptım" read as a fact.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.decision import Decision
from app.models.organization import OrgMembership
from app.models.outbox_message import OutboxMessage
from app.services import briefing_delivery
from app.services.briefing_delivery import enqueue_briefing_emails, release_briefing
from app.services.monday_briefing import (
    OWNER_STATED_DONE_LABEL,
    assemble_monday_briefing,
)
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici
from tests.radar_helpers import statement, upload

ANCHOR = date(2025, 2, 3)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _held_company(client, tag: str) -> tuple[str, str, str]:
    """A company with a statement and an accountant; the briefing is enqueued and held."""
    _, org_id, _ = await kullanici(client, f"{tag}-owner@t.com")
    _, _, smmm_id = await kullanici(client, f"{tag}-smmm@t.com", attach_org=False, role="smmm")
    async with client._maker() as db:
        db.add(OrgMembership(user_id=smmm_id, org_id=org_id, role="smmm"))
        await db.commit()
    await upload(
        client, org_id,
        {"amount_cents": 50_000_00, "transaction_date": "2025-01-31", "type": "income"},
        meta=statement("2025-01-31", 50_000_00),
    )
    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)
        await enqueue_briefing_emails(db, org_id, briefing, anchor_date=ANCHOR)
        await db.commit()
    return org_id, smmm_id, briefing.briefing_id


async def _move_the_cash(client, org_id: str) -> None:
    """A newer statement arrives after the e-mail was written."""
    await upload(
        client, org_id,
        {"amount_cents": 20_000_00, "transaction_date": "2025-02-02", "type": "income"},
        meta=statement("2025-02-02", 70_000_00),
    )


async def _decisions(client, org_id: str) -> list[Decision]:
    async with client._maker() as db:
        rows = await db.execute(
            select(Decision).where(Decision.org_id == org_id).order_by(Decision.decided_at)
        )
        return list(rows.scalars().all())


async def _rows(client, org_id: str) -> list[OutboxMessage]:
    async with client._maker() as db:
        rows = await db.execute(select(OutboxMessage).where(OutboxMessage.org_id == org_id))
        return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_the_body_carries_the_date_of_the_data(client):
    org_id, _, _ = await _held_company(client, "datebody")
    (row,) = await _rows(client, org_id)
    assert "3 Şubat tarihli verilere göre" in row.body


@pytest.mark.asyncio
async def test_holding_records_the_facts_as_a_system_decision(client):
    org_id, _, briefing_id = await _held_company(client, "hold")
    (hold,) = await _decisions(client, org_id)
    assert (hold.kind, hold.outcome, hold.decided_via, hold.decided_by) == (
        "briefing_release", "held", "system", None,
    )
    assert hold.target_id == briefing_id
    facts = hold.after
    assert facts["opening_cash_cents"] == 50_000_00
    assert facts["opening_as_of"] == "2025-01-31"
    assert {"inflow_cents", "outflow_cents", "items_sha", "headline_sha"} <= set(facts)
    assert {"type": "briefing", "id": briefing_id} in hold.evidence_refs
    assert any(r["type"] == "fingerprint" for r in hold.evidence_refs)


@pytest.mark.asyncio
async def test_an_unchanged_release_sends_the_held_text_and_is_a_human_decision(client):
    org_id, smmm_id, briefing_id = await _held_company(client, "same")
    (before,) = await _rows(client, org_id)
    body = before.body
    async with client._maker() as db:
        result = await release_briefing(
            db, org_id=org_id, briefing_id=briefing_id, released_by=smmm_id
        )
        await db.commit()
    assert result["released"] == 1 and result["refreshed"] is False
    (row,) = await _rows(client, org_id)
    assert row.status == "pending" and row.body == body
    hold, release = await _decisions(client, org_id)
    assert (release.outcome, release.decided_via, release.decided_by) == (
        "released", "human", smmm_id,
    )
    assert release.supersedes_id == hold.id
    assert release.decided_at is not None


@pytest.mark.asyncio
async def test_changed_facts_are_not_sent_silently(client):
    org_id, smmm_id, briefing_id = await _held_company(client, "moved")
    await _move_the_cash(client, org_id)
    async with client._maker() as db:
        result = await release_briefing(
            db, org_id=org_id, briefing_id=briefing_id, released_by=smmm_id
        )
        await db.commit()
    assert result["released"] == 0 and result["needs_confirmation"] is True
    changed = {c["field"]: (c["old"], c["new"]) for c in result["changes"]}
    assert changed["opening_cash_cents"] == ("₺50.000,00", "₺70.000,00")
    assert "opening_as_of" in changed
    (row,) = await _rows(client, org_id)
    assert row.status == "held"
    assert [d.outcome for d in await _decisions(client, org_id)] == ["held"]


@pytest.mark.asyncio
async def test_confirming_sends_the_refreshed_text_with_its_date(client):
    org_id, smmm_id, briefing_id = await _held_company(client, "confirm")
    await _move_the_cash(client, org_id)
    async with client._maker() as db:
        first = await release_briefing(
            db, org_id=org_id, briefing_id=briefing_id, released_by=smmm_id
        )
        stale = await release_briefing(
            db, org_id=org_id, briefing_id=briefing_id, released_by=smmm_id,
            confirm_fingerprint="not-what-was-shown",
        )
        assert stale["needs_confirmation"] is True and stale["released"] == 0
        done = await release_briefing(
            db, org_id=org_id, briefing_id=briefing_id, released_by=smmm_id,
            confirm_fingerprint=first["fingerprint"],
        )
        await db.commit()
    assert done["released"] == 1 and done["refreshed"] is True
    (row,) = await _rows(client, org_id)
    assert row.status == "pending"
    assert "70.000,00" in row.body and "50.000,00" not in row.body
    today = datetime.now(UTC).date()
    from app.services.monday_briefing import _tr_date

    assert f"{_tr_date(today.isoformat())} tarihli verilere göre" in row.body
    hold, release = await _decisions(client, org_id)
    assert (release.outcome, release.decided_via, release.decided_by) == (
        "released_refreshed", "human", smmm_id,
    )
    assert release.before["opening_cash_cents"] == 50_000_00
    assert release.after["opening_cash_cents"] == 70_000_00
    assert release.supersedes_id == hold.id


@pytest.mark.asyncio
async def test_the_system_never_releases_as_a_person_nor_confirms_a_change(client):
    org_id, _, briefing_id = await _held_company(client, "system")
    async with client._maker() as db:
        result = await release_briefing(db, org_id=org_id, briefing_id=briefing_id, released_by=None)
        await db.commit()
    assert result["released"] == 1
    _, release = await _decisions(client, org_id)
    assert (release.decided_via, release.decided_by) == ("system", None)

    org2, _, brief2 = await _held_company(client, "system2")
    await _move_the_cash(client, org2)
    async with client._maker() as db:
        changed = await release_briefing(
            db, org_id=org2, briefing_id=brief2, released_by=None, confirm_fingerprint="x"
        )
        await db.commit()
    assert changed["needs_confirmation"] is True
    assert (await _rows(client, org2))[0].status == "held"


@pytest.mark.asyncio
async def test_the_release_route_is_two_steps_when_the_figures_moved(client):
    org_id, smmm_id, briefing_id = await _held_company(client, "route")
    await _move_the_cash(client, org_id)
    async with client._maker() as db:
        from app.models.user import User

        (await db.get(User, smmm_id)).org_id = org_id
        await db.commit()
    token = (
        await client.post("/api/v1/auth/login", json={"email": "route-smmm@t.com", "password": PAROLA})
    ).json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = await client.post(
        "/api/v1/briefing/monday/release", json={"briefing_id": briefing_id}, headers=headers
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["released"] == 0 and data["needs_confirmation"] is True and data["changes"]
    r = await client.post(
        "/api/v1/briefing/monday/release",
        json={"briefing_id": briefing_id, "confirm_fingerprint": data["fingerprint"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["released"] == 1 and r.json()["data"]["refreshed"] is True
    assert (await _rows(client, org_id))[0].status == "pending"


@pytest.mark.asyncio
async def test_yaptim_is_recorded_as_a_human_statement_and_worded_honestly(client):
    headers, org_id, user_id = await kullanici(client, "owner@yaptim.com")
    await upload(
        client, org_id,
        {"amount_cents": 80_000_00, "transaction_date": "2025-01-31", "type": "income"},
        meta=statement("2025-01-31", 80_000_00),
    )
    r = await client.get("/api/v1/briefing/monday?anchor_date=2025-02-01", headers=headers)
    fingerprint = r.json()["data"]["fingerprint"]
    r = await client.post(
        "/api/v1/briefing/monday/respond", headers=headers,
        json={"response": "done", "anchor_date": "2025-02-01", "fingerprint": fingerprint},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["chosen_option_label"] == OWNER_STATED_DONE_LABEL
    assert "bildirdi" in OWNER_STATED_DONE_LABEL
    (statement_row,) = await _decisions(client, org_id)
    assert (statement_row.kind, statement_row.outcome) == ("owner_statement", "reported_done")
    assert (statement_row.decided_via, statement_row.decided_by) == ("human", user_id)
    assert statement_row.after["verification"] == "owner_stated"
    # Answering again supersedes the statement; the record stays a line.
    r = await client.post(
        "/api/v1/briefing/monday/respond", headers=headers,
        json={"response": "deferred", "anchor_date": "2025-02-01", "fingerprint": fingerprint},
    )
    assert r.status_code == 200, r.text
    first, second = await _decisions(client, org_id)
    assert second.outcome == "deferred" and second.supersedes_id == first.id


def test_the_module_exposes_one_release_path():
    assert callable(briefing_delivery.release_briefing)
