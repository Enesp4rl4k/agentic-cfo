"""G2 review — what the shared invoice identity may and may not treat as the same document.

Cases found by reading the first version of `canonical_invoice_id` and the ledger
change that uses it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.main  # noqa: F401
from app.core.invoice_identity import canonical_invoice_id
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.organization import Organization
from app.models.transaction import Transaction
from app.services import ledger
from tests.db_helpers import gecici_oturum


@pytest_asyncio.fixture
async def db():
    async with gecici_oturum() as session:
        yield session


# ── a free-text description is the last place to look for a number ───────────────────────────


def test_a_credit_note_keeps_its_own_number_when_its_description_names_the_original():
    assert (
        canonical_invoice_id(None, "IADE-5", "GIB2024000000042 nolu faturanın iadesi") == "IADE-5"
    )


def test_an_explicit_gib_number_beats_another_one_mentioned_in_the_description():
    assert (
        canonical_invoice_id(None, "GIB2024000000099", "GIB2024000000042 yerine kesildi")
        == "GIB2024000000099"
    )


def test_an_explicit_document_id_beats_the_description():
    assert canonical_invoice_id("INV-77", None, "GIB2024000000042 ile ilgili") == "INV-77"


def test_the_description_is_still_used_when_nothing_explicit_is_given():
    assert canonical_invoice_id(None, None, "e-Fatura GIB2024000000042 nolu") == "GIB2024000000042"


# ── the ledger recognises a document whichever source wrote it first ────────────────────────


async def _org(db) -> str:
    org_id = f"org-g2r-{uuid.uuid4().hex[:8]}"
    db.add(Organization(id=org_id, name="G2 review", slug=f"slug-{org_id}"))
    await db.commit()
    return org_id


async def _upload(db, org_id: str, *, document_id: str, vendor: str, cents: int):
    job = AnalysisJob(
        id=str(uuid.uuid4()), org_id=org_id, status=JobStatus.COMPLETED, filename="f.csv",
        file_path="/tmp/f.csv", file_type="csv",
    )
    db.add(job)
    await db.flush()
    db.add(
        Transaction(
            id=str(uuid.uuid4()), job_id=job.id, transaction_date=datetime.now(UTC) - timedelta(days=3),
            amount_kurus=cents, type="income", currency="TRY", category="revenue", vendor=vendor,
            counterparty=vendor, description=f"Satış {document_id}", document_id=document_id,
            due_date=datetime.now(UTC) + timedelta(days=20), date_is_estimated=False,
        )
    )
    await db.commit()
    return await ledger.append_job(db, job.id)


async def _canonical_count(db, org_id: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(CanonicalTransaction).where(CanonicalTransaction.org_id == org_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_a_row_another_source_already_wrote_is_the_same_document(db):
    """An ERP-written row (its own source_type) must not be written a second time by a file."""
    org_id = await _org(db)
    db.add(
        CanonicalTransaction(
            org_id=org_id, source_type="erp_sync", source_record_id="doc:GIB2024000000050",
            transaction_date=datetime.now(UTC) - timedelta(days=3), amount_cents=1_500_000,
            currency="TRY", direction="income", category="revenue", counterparty="Acme Corp",
            description="Satış GIB2024000000050", ledger_status="active", basis="document",
        )
    )
    await db.commit()

    counts = await _upload(db, org_id, document_id="GIB2024000000050", vendor="Acme Corp", cents=1_500_000)

    assert (counts["new"], counts["already"]) == (0, 1)
    assert await _canonical_count(db, org_id) == 1


@pytest.mark.asyncio
async def test_the_same_invoice_in_lower_case_is_one_document(db):
    org_id = await _org(db)
    await _upload(db, org_id, document_id="inv-2024-77", vendor="Acme Corp", cents=100_000)
    counts = await _upload(db, org_id, document_id="INV-2024-77", vendor="Acme Corp", cents=100_000)
    assert (counts["new"], counts["already"]) == (0, 1)


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="G23: a free-form invoice number is not unique across counterparties; the ledger key has no issuer",
)
async def test_two_suppliers_using_the_same_short_number_are_two_documents(db):
    org_id = await _org(db)
    await _upload(db, org_id, document_id="A-1", vendor="Alfa Ltd", cents=100_000)
    counts = await _upload(db, org_id, document_id="A-1", vendor="Beta Ltd", cents=250_000)
    assert counts["new"] == 1
    assert await _canonical_count(db, org_id) == 2
