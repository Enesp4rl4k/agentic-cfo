"""Duplicate detection and currency: the same invoice read twice is one document, whatever way its currency
was learned (stated by the document, or assumed from the confirmed base); a different currency is another
document; an unknown currency falls back to the comparison made before currencies existed."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.currency_totals import same_currency
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.transaction import Transaction
from app.services.ledger import append_job
from tests.test_ledger_category_correction import _org

DAY = datetime(2026, 3, 3, tzinfo=UTC)


async def _read(client, org, uid, *, number="A-1", who="Alfa Gıda A.Ş.", cents=100_000, currency="TRY",
                assumed=False, days=0, document=True) -> dict:
    async with client._maker() as db:
        job = AnalysisJob(id=str(uuid.uuid4()), org_id=org, user_id=uid, status=JobStatus.COMPLETED,
                          filename="f.csv", file_path="/f.csv", file_type="csv")
        db.add(job)
        await db.flush()
        db.add(Transaction(
            id=str(uuid.uuid4()), job_id=job.id, transaction_date=DAY + timedelta(days=days), amount_kurus=cents,
            type="expense", currency=currency, currency_assumed=assumed, category="cogs", vendor=who,
            counterparty=who, description=f"Alış {number}", document_id=number if document else None,
            due_date=(DAY + timedelta(days=20)).date(), date_is_estimated=False))
        await db.commit()
        return await append_job(db, job.id)


def test_same_currency_treats_equal_codes_as_equal_and_unknown_as_not_different():
    assert same_currency("TRY", "try") and same_currency("USD", "USD")
    assert not same_currency("TRY", "USD")
    assert same_currency("", "USD") and same_currency(None, "TRY")        # unknown: fall back, do not split


@pytest.mark.asyncio
async def test_a_stated_currency_and_an_assumed_one_with_the_same_code_are_one_document(client):
    _, org, uid = await _org(client, "dup-assumed@x.com")
    await _read(client, org, uid, currency="TRY", assumed=False)
    counts = await _read(client, org, uid, currency="TRY", assumed=True)          # the document stated none: TRY assumed
    assert counts["new"] == 0 and counts["possible_duplicate"] + counts["already"] == 1
    # the same through the amount-and-date comparison (no document number)
    await _read(client, org, uid, number="D-1", currency="TRY", assumed=False, document=False)
    counts = await _read(client, org, uid, number="D-1", currency="TRY", assumed=True, document=False, days=1)
    assert (counts["new"], counts["possible_duplicate"]) == (0, 1)


@pytest.mark.asyncio
async def test_the_same_amount_in_another_currency_is_another_document(client):
    _, org, uid = await _org(client, "dup-other@x.com")
    await _read(client, org, uid, number="B-1", currency="TRY", document=False)
    counts = await _read(client, org, uid, number="B-1", who="Beta Ltd", currency="USD", document=False, days=1)
    assert (counts["new"], counts["possible_duplicate"]) == (1, 0)             # bank-line style: amount + date window
    counts = await _read(client, org, uid, number="A-1", currency="TRY")
    again = await _read(client, org, uid, number="A-1", who="Alfa Gıdacılık", currency="USD")   # same number, other currency
    assert counts["new"] == 1 and (again["new"], again["possible_duplicate"]) == (1, 0)


@pytest.mark.asyncio
async def test_an_unknown_currency_falls_back_to_the_old_comparison_and_is_held_when_ambiguous(client):
    _, org, uid = await _org(client, "dup-unknown@x.com")
    await _read(client, org, uid, number="C-1", currency="TRY", document=False)
    counts = await _read(client, org, uid, number="C-1", currency="", document=False, days=1)  # no currency known at all
    assert (counts["new"], counts["possible_duplicate"]) == (0, 1)


async def _confirm(client, org, code):
    from app.models.organization import Organization

    async with client._maker() as db:
        row = await db.get(Organization, org)
        row.base_currency, row.base_currency_confirmed_at = code, datetime.now(UTC)
        await db.commit()


@pytest.mark.asyncio
async def test_held_documents_are_counted_in_their_own_currency_never_added_to_the_headline(client):
    from datetime import date

    from app.services.cash_radar import compute_cash_radar

    _, org, uid = await _org(client, "dup-held@x.com")
    await _confirm(client, org, "TRY")
    await _read(client, org, uid, number="H-1", who="Alfa Gıda San. ve Tic. A.Ş.", currency="USD")
    counts = await _read(client, org, uid, number="H-1", who="Alfa Gıda A.Ş.", currency="USD")
    assert counts["possible_duplicate"] == 1
    async with client._maker() as db:
        radar = await compute_cash_radar(db, org, anchor_date=date(2026, 3, 3))
    held = radar.held_documents
    assert held is not None and held.count == 1
    assert (held.payable_cents, held.other_currency_count, held.other_currency_payable_count) == (0, 1, 1)
    await _confirm(client, org, "USD")                    # the same held row under a USD base: now it is headline money
    async with client._maker() as db:
        radar = await compute_cash_radar(db, org, anchor_date=date(2026, 3, 3))
    assert radar.held_documents is not None and radar.held_documents.payable_cents == 100_000
