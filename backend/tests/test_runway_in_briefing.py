"""The measured runway is in the Monday briefing, the radar and the e-mail, from the one computation.

Before: the radar and the briefing read the radar's weeks and carried no runway, so a company in real cash
trouble saw the critical alert on the dashboard and not in the briefing (PR #120 review). Figures written
by hand: a burn of 30,000.00 a month over January-March 2026; the briefing is for the week of 2026-04-06.
"""
from __future__ import annotations

from datetime import date

import pytest_asyncio
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob
from app.models.organization import OrgMembership
from app.models.outbox_message import OutboxMessage
from app.services.briefing_delivery import (
    collect_facts,
    enqueue_briefing_emails,
    facts_fingerprint,
    release_briefing,
)
from app.services.monday_briefing import assemble_monday_briefing
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import BURN, statement_meta, upload

ANCHOR = date(2026, 4, 6)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _company(client, tag: str, closing: int, **meta) -> str:
    _, org_id, _ = await kullanici(client, f"{tag}@example.com")
    await upload(client, org_id, *BURN, filename="ekstre.pdf",
                 meta=statement_meta("2026-01-01", "2026-03-31", 170_000_00, closing, **meta))
    return org_id


async def _briefing(client, org_id: str, narrative: str | None = None):
    async with client._maker() as db:
        return await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR, candidate_narrative=narrative)


async def _edit_statement(client, org_id: str, change) -> None:
    async with client._maker() as db:
        for job in (await db.execute(select(AnalysisJob).where(AnalysisJob.org_id == org_id))).scalars():
            job.result_metadata = change(dict(job.result_metadata))
        await db.commit()


async def test_a_measured_runway_is_in_the_briefing_with_its_basis(client):
    b = await _briefing(client, await _company(client, "k1", 120_000_00))
    assert (b.runway_status, b.runway_months, b.runway_level, b.runway_basis) == ("computed", 4.0, "warning", "known")
    assert b.runway_line.startswith("Uyarı: Nakit pisti yaklaşık 4,0 ay (31 Mart 2026 ekstresindeki kasa ₺120.000,00; ")
    assert "son 3 tam ayın (Ocak–Mart) ortalama net çıkışı ₺30.000,00/ay)" in b.runway_line
    assert b.runway_line in b.full_text and not b.full_text.startswith(b.runway_line)  # said, but not first
    assert "Varsayım" not in b.runway_line


async def test_a_critical_runway_is_the_first_thing_the_briefing_says(client):
    b = await _briefing(client, await _company(client, "k2", 50_000_00))
    assert (b.runway_months, b.runway_level) == (1.7, "critical")
    assert b.runway_line.startswith("KRİTİK: Nakit pisti yaklaşık 1,7 ay")
    assert b.full_text.startswith(b.runway_line)


async def test_an_assumed_basis_is_visibly_marked(client):
    org_id = await _company(client, "k3", 120_000_00, basis="assumed", reason="yalnızca 2 bakiye adımıyla doğrulandı")
    b = await _briefing(client, org_id)
    assert b.runway_basis == "assumed"
    assert "Varsayım:" in b.runway_line
    assert "zayıf kanıta dayanıyor (yalnızca 2 bakiye adımıyla doğrulandı)" in b.runway_line


async def test_an_unknown_balance_says_unknown_and_shows_no_runway_number(client):
    _, org_id, _ = await kullanici(client, "k4@example.com")
    await upload(client, org_id, *BURN)  # rows, but no statement proves a balance
    b = await _briefing(client, org_id)
    assert (b.runway_status, b.runway_months, b.runway_level) == ("no_balance", None, None)
    assert b.runway_line.startswith("Kasa bakiyesi bilinmiyor — nakit pisti hesaplanamadı.")
    assert "ay yeter" not in b.runway_line and "yaklaşık" not in b.runway_line


async def test_a_runway_the_data_cannot_support_says_why_and_shows_no_number(client):
    org_id = await _company(client, "k5", 120_000_00)

    def one_month(meta):  # the statement covers only March: one complete month is not a burn
        return {**meta, "statement_extent": {**meta["statement_extent"], "start": "2026-03-01"}}

    await _edit_statement(client, org_id, one_month)
    b = await _briefing(client, org_id)
    assert b.runway_status == "insufficient_history" and b.runway_months is None
    assert b.runway_line == "Nakit pisti hesaplanamadı: üst üste 1 tam ay var, en az 3 gerekir."


async def test_the_runway_sentence_is_the_templates_never_the_narratives(client):
    org_id = await _company(client, "k6", 120_000_00)
    spoken = "Bu hafta radarda belirgin bir hareket görünmüyor."
    b = await _briefing(client, org_id, narrative=spoken)
    assert b.fallback_used is False and b.full_text.startswith(spoken) and b.runway_line in b.full_text
    # A narrative that invents a runway figure is rejected like any invented number.
    lie = await _briefing(client, org_id, narrative="Nakit pistiniz 99 ay, ₺999.000,00 kasanız var.")
    assert lie.fallback_used is True and "999.000" not in lie.full_text


async def test_the_fingerprint_follows_the_runway(client):
    org_id = await _company(client, "k7", 120_000_00)
    before = await _briefing(client, org_id)

    def weaker(meta):
        proof = {**meta["balance_proof"], "basis": "assumed", "reason": "yalnızca 1 bakiye adımıyla doğrulandı"}
        return {**meta, "balance_proof": proof}

    await _edit_statement(client, org_id, weaker)
    after = await _briefing(client, org_id)
    assert after.runway_line != before.runway_line and after.fingerprint != before.fingerprint


async def test_the_email_carries_the_runway_and_a_critical_one_comes_first(client):
    org_id = await _company(client, "k8", 50_000_00)
    async with client._maker() as db:
        b = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)
        (msg,) = await enqueue_briefing_emails(db, org_id, b, anchor_date=ANCHOR)
        await db.commit()
    parts = msg.body.split("\n\n")
    assert parts[0].startswith("Hafta:") and parts[1] == b.runway_line and parts[2] == b.sentence_radar

    calm = await _company(client, "k9", 400_000_00)
    async with client._maker() as db:
        b2 = await assemble_monday_briefing(db, calm, anchor_date=ANCHOR)
        (msg2,) = await enqueue_briefing_emails(db, calm, b2, anchor_date=ANCHOR)
        await db.commit()
    parts2 = msg2.body.split("\n\n")
    assert parts2[1] == b2.sentence_radar and parts2[parts2.index(b2.sentence_action) + 1] == b2.runway_line


async def test_a_held_email_notices_when_the_runway_moved_before_release(client):
    org_id = await _company(client, "k10", 120_000_00)
    _, _, smmm_id = await kullanici(client, "k10-smmm@example.com", attach_org=False, role="smmm")
    async with client._maker() as db:
        db.add(OrgMembership(user_id=smmm_id, org_id=org_id, role="smmm"))
        await db.commit()
        b = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)
        facts = await collect_facts(db, org_id, b, anchor_date=ANCHOR, data_date=ANCHOR)
        await enqueue_briefing_emails(db, org_id, b, anchor_date=ANCHOR)
        await db.commit()
        rows = (await db.execute(select(OutboxMessage).where(OutboxMessage.org_id == org_id))).scalars().all()
    assert facts["runway_line"] == b.runway_line and [r.status for r in rows] == ["held"]

    # The company's cash is lower when the accountant gets to it.
    await _edit_statement(client, org_id, lambda m: {**m, "closing_balance": {"date": "2026-03-31", "balance_cents": 50_000_00}})
    async with client._maker() as db:
        result = await release_briefing(db, org_id=org_id, briefing_id=b.briefing_id, released_by=smmm_id)
    assert result["released"] == 0 and result["needs_confirmation"] is True
    assert "Nakit pisti" in {c["label"] for c in result["changes"]}
    assert facts_fingerprint(facts) != result["fingerprint"]
