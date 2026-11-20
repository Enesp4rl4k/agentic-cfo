"""Metamorphic invariance tests on the company ledger.

Plan v10 §13.1 #3 & §13.4 (E2) / Plan v11 Faz 1.3:
A ledger is sound if its state is invariant under metamorphic transformations:
1. Idempotency (x + x == x): Re-analysing or re-appending the exact same file produces 0 new lines
   and causes 0 drift in revenue, expense, and open item totals.
2. Permutation invariance: Shuffling the arrival order of transactions within a batch produces
   identical ledger summaries and open item balances.
3. Partition invariance (Chunking): Splitting a dataset into multiple subsets and appending each
   yields identical totals as appending the entire dataset in a single upload.
"""

from __future__ import annotations

import random
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item import OpenItem
from app.models.transaction import Transaction
from app.services.ledger import append_job, ledger_summary
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.fixtures.stress_corpus import generate_stress_corpus


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _upload_batch(
    client, org_id: str, rows: list[dict[str, Any]], filename: str = "batch.csv"
) -> dict[str, int]:
    async with client._maker() as db:
        job = AnalysisJob(
            filename=filename,
            file_path=f"/{filename}",
            file_type="csv",
            org_id=org_id,
            status=JobStatus.COMPLETED,
        )
        db.add(job)
        await db.flush()
        for r in rows:
            when, estimated = parse_transaction_date(r["transaction_date"])
            db.add(
                Transaction(
                    job_id=job.id,
                    amount_kurus=r["amount_cents"],
                    currency=r.get("currency", "TRY"),
                    type=r["type"],
                    category=r["category"],
                    description=r.get("description"),
                    transaction_date=when,
                    date_is_estimated=estimated,
                    document_id=r.get("document_id"),
                    due_date=r.get("due_date"),
                    counterparty=r.get("counterparty"),
                    account_code=r.get("account_code"),
                )
            )
        await db.commit()
        return await append_job(db, job.id)


async def _get_open_items_total(client, org_id: str) -> tuple[int, int]:
    """Return (receivable_cents, payable_cents)."""
    async with client._maker() as db:
        items = list(
            (await db.execute(select(OpenItem).where(OpenItem.org_id == org_id))).scalars()
        )
        receivables = sum(
            i.amount_cents for i in items if i.direction == "receivable" and i.currency == "TRY"
        )
        payables = sum(
            i.amount_cents for i in items if i.direction == "payable" and i.currency == "TRY"
        )
        return receivables, payables


async def test_metamorphic_idempotency_double_upload_changes_nothing(client):
    """Uploading the exact same stress dataset twice adds 0 rows and causes 0 financial drift."""
    _, org_id, _ = await kullanici(client, "idempotent@example.com")
    bundle = generate_stress_corpus(seed=101)

    # First upload
    first_counts = await _upload_batch(client, org_id, bundle.all_rows, filename="first.csv")
    assert first_counts["new"] > 0
    first_summary = await ledger_summary(await client._maker().__aenter__(), org_id)
    first_open_rec, first_open_pay = await _get_open_items_total(client, org_id)

    # Second upload of identical transactions
    second_counts = await _upload_batch(
        client, org_id, bundle.all_rows, filename="second_duplicate.csv"
    )
    assert second_counts["new"] == 0
    assert second_counts["already"] == len(bundle.all_rows)

    second_summary = await ledger_summary(await client._maker().__aenter__(), org_id)
    second_open_rec, second_open_pay = await _get_open_items_total(client, org_id)

    assert second_summary["revenue_cents"] == first_summary["revenue_cents"]
    assert second_summary["expense_cents"] == first_summary["expense_cents"]
    assert second_open_rec == first_open_rec
    assert second_open_pay == first_open_pay


async def test_metamorphic_permutation_invariance_order_does_not_matter(client):
    """Shuffling rows within an ingestion batch yields identical financial figures."""
    _, org_a, _ = await kullanici(client, "order_a@example.com")
    _, org_b, _ = await kullanici(client, "order_b@example.com")

    bundle = generate_stress_corpus(seed=202)
    original_rows = list(bundle.all_rows)

    shuffled_rows = list(bundle.all_rows)
    rng = random.Random(999)
    rng.shuffle(shuffled_rows)

    # Ingest original order into Org A
    await _upload_batch(client, org_a, original_rows, filename="ordered.csv")
    summary_a = await ledger_summary(await client._maker().__aenter__(), org_a)
    open_rec_a, open_pay_a = await _get_open_items_total(client, org_a)

    # Ingest shuffled order into Org B
    await _upload_batch(client, org_b, shuffled_rows, filename="shuffled.csv")
    summary_b = await ledger_summary(await client._maker().__aenter__(), org_b)
    open_rec_b, open_pay_b = await _get_open_items_total(client, org_b)

    assert summary_a["revenue_cents"] == summary_b["revenue_cents"]
    assert summary_a["expense_cents"] == summary_b["expense_cents"]
    assert open_rec_a == open_rec_b
    assert open_pay_a == open_pay_b


async def test_metamorphic_partition_invariance_chunking(client):
    """Uploading transactions in one single file vs splitting into multiple chunks yields identical totals."""
    _, org_single, _ = await kullanici(client, "single@example.com")
    _, org_split, _ = await kullanici(client, "split@example.com")

    bundle = generate_stress_corpus(seed=303)

    # Org Single: All at once
    await _upload_batch(client, org_single, bundle.all_rows, filename="all_at_once.csv")
    summary_single = await ledger_summary(await client._maker().__aenter__(), org_single)
    open_rec_single, open_pay_single = await _get_open_items_total(client, org_single)

    # Org Split: Invoices first, bank lines second
    await _upload_batch(client, org_split, bundle.invoices, filename="invoices_part1.csv")
    await _upload_batch(client, org_split, bundle.bank_lines, filename="bank_part2.csv")
    summary_split = await ledger_summary(await client._maker().__aenter__(), org_split)
    open_rec_split, open_pay_split = await _get_open_items_total(client, org_split)

    assert summary_single["revenue_cents"] == summary_split["revenue_cents"]
    assert summary_single["expense_cents"] == summary_split["expense_cents"]
    assert open_rec_single == open_rec_split
    assert open_pay_single == open_pay_split
