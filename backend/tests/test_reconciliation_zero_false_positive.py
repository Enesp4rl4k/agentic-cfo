"""Zero false-positive bank reconciliation gate.

Plan v10 §13.1 #2 & §13.4 (E2) / Plan v11 Faz 1.4:
In real-world SME finances, automatic matching must ONLY occur when a human would not hesitate:
- Exact invoice number present and amount matches.
- Counterparty name present, amount matches, and exactly one open item fits.

Everything else (duplicate amounts, partial payments without invoice numbers, payments before invoice window,
currency mismatches) MUST NOT be automatically confirmed.
Tolerance: Exactly 0 false positive automatic matches.
"""

from __future__ import annotations

from typing import Any

import pytest_asyncio
from sqlalchemy import select

from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item_match import OpenItemMatch
from app.models.transaction import Transaction
from app.services.ledger import append_job
from app.services.reconciliation import CONFIRMED, PROPOSED, reconcile_org
from app.services.stress_corpus import generate_stress_corpus
from tests.api_helpers import bellek_istemcisi, kullanici


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _upload(
    client, org_id: str, rows: list[dict[str, Any]], filename: str = "stress.csv"
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


async def test_zero_false_positive_reconciliation_on_stress_corpus(client):
    """Verify that ambiguous bank rows never auto-confirm on messy Turkish SME data."""
    _, org_id, _ = await kullanici(client, "recon_gate@example.com")
    bundle = generate_stress_corpus(seed=404)

    # Ingest invoices first
    await _upload(client, org_id, bundle.invoices, filename="invoices.csv")
    # Ingest bank lines second — append_job triggers reconcile_org automatically
    upload_counts = await _upload(client, org_id, bundle.bank_lines, filename="bank.csv")

    async with client._maker() as db:
        # Fetch all matches and join with canonical transactions
        matches = list(
            (
                await db.execute(select(OpenItemMatch).where(OpenItemMatch.org_id == org_id))
            ).scalars()
        )

        confirmed = [m for m in matches if m.status == CONFIRMED]
        proposed = [m for m in matches if m.status == PROPOSED]

        # 1. Zero False Positive Check:
        # None of the ambiguous bank lines should ever have status == CONFIRMED.
        # Ambiguous lines include:
        # - "MUSTERI HESABINDAN GELEN HAVALE" (Case 3: identical amount for two vendors)
        # - "1.KISMI TAHSILAT" (Case 5: partial payment)
        # - "KİRA ÖDEMESİ" (Case 8: recurring expense without invoice)
        false_positives: list[OpenItemMatch] = []
        for m in confirmed:
            tx = (
                (
                    await db.execute(
                        select(CanonicalTransaction).where(
                            CanonicalTransaction.id == m.ledger_row_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            assert tx is not None
            desc = tx.description or ""
            if "MUSTERI HESABINDAN GELEN HAVALE" in desc or "KISMI" in desc or "KİRA" in desc:
                false_positives.append(m)

        # Plan v10 §13.1 #2 requirement: 0 wrong automatic matches
        assert len(false_positives) == 0, (
            f"Found {len(false_positives)} false positive automatic matches!"
        )

        # 2. Check exact counts against ground truth expectations
        assert len(confirmed) == bundle.expectations.expected_confirmed_matches
        assert len(proposed) == bundle.expectations.expected_proposed_matches
        assert upload_counts["settled"] == bundle.expectations.expected_confirmed_matches
        assert upload_counts["proposed"] == bundle.expectations.expected_proposed_matches

        # 3. Idempotency: Running reconcile_org again on the same state produces 0 new matches
        second_run = await reconcile_org(db, org_id)
        assert second_run["settled"] == 0
        assert second_run["proposed"] == 0
