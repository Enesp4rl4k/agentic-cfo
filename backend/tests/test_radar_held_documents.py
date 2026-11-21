"""G23 review B1: documents waiting for a decision are on the radar's reader, not invisible to it.

A held row opens no open item, so the radar's figures leave it out. UNRESOLVED-state tests: the radar's
`not_included` line and structured `held_documents`, and the Monday briefing's headline caveat with its
materiality rule.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest_asyncio
from sqlalchemy import select

from app.config import get_settings
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.transaction import Transaction
from app.services.cash_radar import compute_cash_radar
from app.services.ledger import append_job
from app.services.monday_briefing import assemble_monday_briefing
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_duplicate_resolution_radar import (
    FULL,
    SHORT,
    TODAY,
    _held,
    _radar_out,
    _resolve,
    _upload,
)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _radar(client, org_id):
    async with client._maker() as db:
        return await compute_cash_radar(db, org_id, anchor_date=TODAY.date())


async def _brief(client, org_id, **kw):
    async with client._maker() as db:
        return await assemble_monday_briefing(db, org_id, anchor_date=TODAY.date(), **kw)


async def _held_pair(client, org_id, *, due_in=2, cents=100_000):
    await _upload(client, org_id, who=FULL, cents=cents, due_in=due_in)
    _, counts = await _upload(client, org_id, who=SHORT, cents=cents, due_in=due_in)
    assert counts["possible_duplicate"] == 1


async def _other_payable(client, org_id, cents, due_in=3):
    """An ordinary payable due this week, from another supplier."""
    await _upload(client, org_id, number="Z-9", who="Zeta Ltd", cents=cents, due_in=due_in)


async def test_an_unresolved_queue_is_a_line_on_the_radar_with_amounts_and_weeks(client):
    _, org_id, _ = await kullanici(client, "heldradar@example.com")
    await _held_pair(client, org_id, due_in=2, cents=100_000)

    radar = await _radar(client, org_id)

    assert await _radar_out(client, org_id) == 100_000           # the radar still counts one, not two
    held = radar.held_documents
    assert held is not None and held.count == 1
    assert (held.payable_cents, held.receivable_cents) == (100_000, 0)
    assert [(w.week, w.payable_cents) for w in held.weeks] == [(1, 100_000)]   # where it would land if kept
    assert held.week1_payable_cents == 100_000
    assert (held.payable_basis.known_cents, held.payable_basis.assumed_cents) == (100_000, 0)   # a dated document
    assert held.review_path == "/onay"
    line = next(x for x in radar.not_included if x.startswith("Karar bekleyen"))
    assert "1 belge" in line and "₺1.000,00 ödeme" in line and "karar verene kadar" in line


async def test_an_overdue_held_payable_is_placed_in_week_one_as_assumed(client):
    _, org_id, _ = await kullanici(client, "heldoverdue@example.com")
    await _held_pair(client, org_id, due_in=-5)
    held = (await _radar(client, org_id)).held_documents
    assert held is not None
    assert [(w.week, w.payable_cents) for w in held.weeks] == [(1, 100_000)]
    assert (held.payable_basis.known_cents, held.payable_basis.assumed_cents) == (0, 100_000)


async def test_a_resolved_queue_leaves_the_radar_clean(client):
    headers, org_id, _ = await kullanici(client, "heldgone@example.com")
    await _held_pair(client, org_id)
    await _resolve(client, headers, (await _held(client, org_id)).id, "keep")
    radar = await _radar(client, org_id)
    assert radar.held_documents is None
    assert not any(x.startswith("Karar bekleyen") for x in radar.not_included)
    assert await _radar_out(client, org_id) == 200_000


async def test_the_radar_endpoint_carries_the_line_and_the_link_target(client):
    headers, org_id, _ = await kullanici(client, "heldapi@example.com")
    await _held_pair(client, org_id)
    data = (await client.get(f"/api/v1/ledger/cash-radar?anchor_date={TODAY.date().isoformat()}",
                             headers=headers)).json()["data"]
    assert data["held_documents"]["count"] == 1 and data["held_documents"]["review_path"] == "/onay"
    assert any(x.startswith("Karar bekleyen") for x in data["not_included"])


# ── the briefing's headline ──────────────────────────────────────────────────────────────────


async def test_a_material_queue_is_said_in_the_briefing_headline(client):
    _, org_id, _ = await kullanici(client, "briefmat@example.com")
    await _held_pair(client, org_id, due_in=2, cents=100_000)           # the week has no other outflow: material
    brief = await _brief(client, org_id)
    assert "Karar bekleyen 1 belge (₺1.000,00 ödeme) radara dahil değil" in brief.sentence_radar
    assert "çıkışlar olduğundan düşük görünebilir" in brief.full_text


async def test_the_threshold_is_a_named_setting_a_share_of_the_weeks_outflow(client, monkeypatch):
    _, org_id, _ = await kullanici(client, "briefthr@example.com")
    await _other_payable(client, org_id, 800_000)                       # with the kept ₺1.000,00: outflow ₺9.000,00
    await _held_pair(client, org_id, due_in=2, cents=100_000)           # the held ₺1.000,00 is 11% of it
    assert get_settings().radar_held_material_ratio == 0.10
    assert "Karar bekleyen" in (await _brief(client, org_id)).sentence_radar

    monkeypatch.setattr(get_settings(), "radar_held_material_ratio", 0.50)
    brief = await _brief(client, org_id)
    assert "Karar bekleyen" not in brief.full_text                     # below 50%: only the not_included line
    assert any(x.startswith("Karar bekleyen") for x in (await _radar(client, org_id)).not_included)


async def test_a_small_queue_does_not_crowd_the_headline(client):
    _, org_id, _ = await kullanici(client, "briefsmall@example.com")
    await _other_payable(client, org_id, 5_000_000)
    await _held_pair(client, org_id, due_in=2, cents=100_000)           # 2%
    assert "Karar bekleyen" not in (await _brief(client, org_id)).full_text


async def test_a_queue_that_lands_next_month_is_not_a_this_week_caveat(client):
    _, org_id, _ = await kullanici(client, "briefsoon@example.com")
    await _held_pair(client, org_id, due_in=40)
    assert "Karar bekleyen" not in (await _brief(client, org_id)).full_text


async def test_an_undated_held_payable_counts_as_material_when_the_week_has_no_outflow(client):
    _, org_id, _ = await kullanici(client, "briefundated@example.com")
    await _held_pair(client, org_id, due_in=2)
    async with client._maker() as db:                                     # the held document carries no due date
        for tx in (await db.execute(select(Transaction))).scalars():
            tx.due_date = None
        await db.commit()
    held = (await _radar(client, org_id)).held_documents
    assert held is not None and held.undated_payable_cents == 100_000 and held.weeks == []
    assert "Karar bekleyen 1 belge" in (await _brief(client, org_id)).sentence_radar


async def test_a_held_payable_whose_size_is_unknown_is_never_dropped_from_the_headline(client):
    """Foreign currency is counted, never converted: an amount that cannot be added up is material."""
    _headers, org_id, _ = await kullanici(client, "briefusd@example.com")
    await _other_payable(client, org_id, 50_000_000)                      # a huge week: 100 USD could not matter... in TRY
    async with client._maker() as db:
        for number, who in (("A-1", FULL), ("A-1", SHORT)):
            job = AnalysisJob(id=str(uuid.uuid4()), org_id=org_id, status=JobStatus.COMPLETED, filename="f.csv",
                              file_path="/f.csv", file_type="csv")
            db.add(job)
            await db.flush()
            db.add(Transaction(
                id=str(uuid.uuid4()), job_id=job.id, transaction_date=TODAY - timedelta(days=2),
                amount_kurus=10_000, type="expense", currency="USD", category="cogs", vendor=who, counterparty=who,
                description=f"Alış {number}", document_id=number, due_date=(TODAY + timedelta(days=2)).date(),
                date_is_estimated=False,
            ))
            await db.commit()
            await append_job(db, job.id)
    held = (await _radar(client, org_id)).held_documents
    assert held is not None and (held.other_currency_count, held.other_currency_payable_count) == (1, 1)
    assert held.payable_cents == 0
    brief = await _brief(client, org_id)
    assert "Karar bekleyen 1 belge" in brief.sentence_radar and "döviz belgeleri" in brief.sentence_radar


async def test_a_narrative_cannot_lose_the_caveat(client):
    _, org_id, _ = await kullanici(client, "briefnarr@example.com")
    await _held_pair(client, org_id, due_in=2)
    brief = await _brief(client, org_id, candidate_narrative="Bu hafta radarda sakin bir görünüm var.")
    assert brief.full_text.startswith("Bu hafta radarda sakin")
    assert "Karar bekleyen 1 belge" in brief.full_text


async def test_receivables_held_are_listed_but_never_a_payables_caveat(client):
    _, org_id, _ = await kullanici(client, "heldrec@example.com")
    for who in (FULL, SHORT):
        async with client._maker() as db:
            job = AnalysisJob(id=str(uuid.uuid4()), org_id=org_id, status=JobStatus.COMPLETED, filename="f.csv",
                              file_path="/f.csv", file_type="csv")
            db.add(job)
            await db.flush()
            db.add(Transaction(
                id=str(uuid.uuid4()), job_id=job.id, transaction_date=TODAY - timedelta(days=2),
                amount_kurus=100_000, type="income", currency="TRY", category="revenue", vendor=who,
                counterparty=who, description="Satış", document_id="S-1",
                due_date=(TODAY + timedelta(days=2)).date(), date_is_estimated=False,
            ))
            await db.commit()
            await append_job(db, job.id)
    radar = await _radar(client, org_id)
    held = radar.held_documents
    assert held is not None and (held.payable_cents, held.receivable_cents) == (0, 100_000)
    assert "₺1.000,00 tahsilat" in next(x for x in radar.not_included if x.startswith("Karar bekleyen"))
    assert "Karar bekleyen" not in (await _brief(client, org_id)).full_text
