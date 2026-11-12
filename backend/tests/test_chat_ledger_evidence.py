"""G9 — the chat's evidence comes from the company ledger, not only the last upload.

The ledger holds every upload; the chat used to see only the chunks of the active
CFO job, so a customer's invoice from an earlier upload was invisible to it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio

from app.models.canonical_transaction import CanonicalTransaction
from app.services.chat_grounding import prepare_grounded_chat
from app.services.rag import retrieve_dual_evidence
from tests.api_helpers import bellek_istemcisi

OLD_JOB = "11111111-1111-1111-1111-111111111111"
NEW_JOB = "22222222-2222-2222-2222-222222222222"
WHEN = datetime(2024, 2, 1, 9, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _row(org: str, n: int, *, counterparty: str, description: str, amount: int = 285_000_00,
         status: str = "active", job: str = OLD_JOB) -> CanonicalTransaction:
    return CanonicalTransaction(
        org_id=org, source_type="upload", source_record_id=f"r-{org[-4:]}-{n}", transaction_date=WHEN,
        amount_cents=amount, currency="TRY", direction="income", category="revenue",
        counterparty=counterparty, description=description, confidence=90,
        source_job_id=job, ledger_status=status,
    )


async def test_a_row_from_an_earlier_upload_is_evidence_for_the_chat(client):
    org = "org-g9-a"
    async with client._maker() as db:
        db.add(_row(org, 1, counterparty="ABC Holding", description="e-Fatura GIB1: ABC Holding"))
        db.add(_row(org, 2, counterparty="Zeta Tekstil", description="e-Fatura GIB2: Zeta Tekstil", amount=1_00))
        await db.commit()

        # The active job is a later upload that has no chunks of its own.
        bundle = await retrieve_dual_evidence(db=db, org_id=org, query="ABC Holding ne kadar borcu var",
                                              job_id=NEW_JOB)

    ledger = [c for c in bundle.citations if c.source_type == "ledger_row"]
    assert len(ledger) == 1
    assert "ABC Holding" in ledger[0].preview
    assert "285000.00" in ledger[0].preview
    assert bundle.found


async def test_rows_that_are_not_counted_are_not_evidence(client):
    org = "org-g9-b"
    async with client._maker() as db:
        db.add(_row(org, 1, counterparty="ABC Holding", description="kopya", status="possible_duplicate"))
        db.add(_row(org, 2, counterparty="ABC Holding", description="dislandi", status="excluded"))
        await db.commit()
        bundle = await retrieve_dual_evidence(db=db, org_id=org, query="ABC Holding", job_id=None)
    assert [c for c in bundle.citations if c.source_type == "ledger_row"] == []


async def test_another_companys_rows_are_never_evidence(client):
    async with client._maker() as db:
        db.add(_row("org-g9-c1", 1, counterparty="ABC Holding", description="gizli fatura"))
        await db.commit()
        bundle = await retrieve_dual_evidence(db=db, org_id="org-g9-c2", query="ABC Holding", job_id=None)
    assert [c for c in bundle.citations if c.source_type == "ledger_row"] == []


async def test_a_question_matching_nothing_in_the_ledger_finds_nothing(client):
    org = "org-g9-d"
    async with client._maker() as db:
        db.add(_row(org, 1, counterparty="ABC Holding", description="e-Fatura GIB1: ABC Holding"))
        await db.commit()
        bundle = await retrieve_dual_evidence(db=db, org_id=org, query="kira odemesi ne zaman", job_id=None)
    assert [c for c in bundle.citations if c.source_type == "ledger_row"] == []


async def test_turkish_letters_do_not_hide_a_match(client):
    org = "org-g9-e"
    async with client._maker() as db:
        db.add(_row(org, 1, counterparty="Şahin Gıda Ltd", description="Şahin Gıda fatura"))
        await db.commit()
        bundle = await retrieve_dual_evidence(db=db, org_id=org, query="sahin gida alacagi", job_id=None)
    assert any(c.source_type == "ledger_row" for c in bundle.citations)


async def test_the_chat_pack_reports_ledger_evidence(client):
    org = "org-g9-f"
    async with client._maker() as db:
        db.add(_row(org, 1, counterparty="ABC Holding", description="e-Fatura GIB1: ABC Holding"))
        await db.commit()
        pack = await prepare_grounded_chat(db=db, org_id=org, question="ABC Holding borcu", base_system_prompt="x",
                                           job_id=NEW_JOB)
    assert pack.evidence_found
    assert pack.to_meta()["evidence_ledger_count"] == 1
    assert "ABC Holding" in pack.system_prompt
