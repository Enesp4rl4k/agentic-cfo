"""An IADE (return) invoice opens no receivable or payable; the invoice it returns does.

Split out of test_iade_invoice.py, whose module-level skip (GİB corpus not fetched) also
skipped this one: it needs no corpus, only the database, so it runs in every job.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.invoice_identity import document_key, open_item_key
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item import OpenItem
from app.models.transaction import Transaction
from app.services.ledger import append_job
from tests.api_helpers import kullanici


@pytest.mark.asyncio
async def test_a_return_opens_no_receivable_or_payable(client):
    _h, org, uid = await kullanici(client, "iade@x.com")
    async with client._maker() as db:
        job = AnalysisJob(filename="a.xml", file_path="/a.xml", file_type="xml",
                          org_id=org, user_id=uid, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        for n, (amt, doc) in enumerate([(100_000, "inv-1"), (-30_000, "iade-1")]):
            db.add(Transaction(
                job_id=job.id, amount_kurus=amt, currency="TRY", type="expense", category="cogs",
                description=f"e-Fatura {doc}", vendor="Tedarikçi A.Ş.", document_id=doc,
                counterparty="Tedarikçi A.Ş.", transaction_date=datetime(2026, 1, 5 + n, tzinfo=UTC),
            ))
        await db.flush()
        await append_job(db, job.id)
        items = (await db.execute(select(OpenItem.document_id, OpenItem.amount_cents))).all()
        n_items = (await db.execute(select(func.count()).select_from(OpenItem))).scalar_one()
    # A free-form number is keyed with its counterparty and side (plan v10 G23), so the
    # open item carries `inv:p:<party>:INV-1`, not the bare number.
    expected = open_item_key(document_key(org, "inv-1", "Tedarikçi A.Ş.", "expense"))
    assert expected.startswith("inv:p:") and expected.endswith(":INV-1")
    assert n_items == 1 and items == [(expected, 100_000)]
