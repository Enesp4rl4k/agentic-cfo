"""G22 — a Paraşüt invoice reaches the ledger as an invoice, not as a cash movement.

The pull used to be written as a bank statement (`tarih, açıklama, tutar, tip`):
document number, counterparty and due date were dropped, the invoice became cash,
and the bank receipt weeks later counted the same sale a second time.

The chain under test is the real one: Paraşüt's JSON:API (a MockTransport) → the
sync → the analysis job's file → `run_data_ingestion` → the ledger → a bank
receipt. Paraşüt's contract (`include=contact`, `due_date`, `invoice_no`) is
written from its public shape and not checked against a real account.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item import OpenItem
from app.models.transaction import Transaction
from app.services.erp import parasut_connector as pc
from app.services.ledger import append_job, ledger_summary
from tests.api_helpers import bellek_istemcisi
from tests.test_ingest import _login
from tests.test_parasut import Parasut, _connect


class ParasutWithContacts(Parasut):
    """Invoices that name their contact, as JSON:API does with `include=contact`."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        today = time.strftime("%Y-%m-%d")
        due = (date.today() + timedelta(days=20)).isoformat()
        if request.url.path == "/v4/123456/sales_invoices":
            return httpx.Response(200, json={
                "data": [{
                    "id": "s1", "type": "sales_invoices",
                    "attributes": {"issue_date": today, "due_date": due, "gross_total": "11800.0",
                                   "description": "Danışmanlık", "invoice_no": "A-1"},
                    "relationships": {"contact": {"data": {"id": "c1", "type": "contacts"}}},
                }],
                "included": [{"id": "c1", "type": "contacts", "attributes": {"name": "Acme Ltd"}}],
            })
        if request.url.path == "/v4/123456/purchase_bills":
            return httpx.Response(200, json={"data": [], "included": []})
        return super().__call__(request)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


@pytest.fixture
def parasut(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "parasut_client_id", "platform-client")
    monkeypatch.setattr(s, "parasut_client_secret", "platform-secret")
    fake = ParasutWithContacts()
    monkeypatch.setattr(pc, "_transport", httpx.MockTransport(fake))
    return fake


async def _sync_and_ingest(client, parasut):
    from app.agents.data_ingestion import run_data_ingestion
    from app.agents.state import AgentRunConfig

    h = await _login(client)
    await _connect(client, h, parasut)
    integ = (await client.get("/api/v1/erp/parasut/durum", headers=h)).json()["data"]["baglanti"]["id"]
    res = await client.post("/api/v1/erp/parasut/sync", data={"integration_id": integ}, headers=h)
    assert res.status_code == 200, res.text
    job_id = res.json()["data"]["job_id"]
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        out = await run_data_ingestion(
            {"file_path": job.file_path, "file_type": job.file_type, "job_id": job.id}, AgentRunConfig()
        )
    return job_id, out.patch["transactions"]


async def test_the_ingested_invoice_keeps_its_number_counterparty_and_due_date(client, parasut):
    _, txs = await _sync_and_ingest(client, parasut)
    [tx] = txs
    assert tx["type"] == "income" and tx["amount_cents"] == 1_180_000
    assert tx["document_id"] == "A-1"
    assert tx["counterparty"] == "Acme Ltd"
    assert tx["due_date"] == (date.today() + timedelta(days=20)).isoformat()


async def test_the_sale_is_counted_once_when_the_bank_receipt_arrives(client, parasut):
    job_id, txs = await _sync_and_ingest(client, parasut)

    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        org_id = str(job.org_id)
        job.status = JobStatus.COMPLETED
        for t in txs:  # the worker's own mapping, field for field
            when, estimated = parse_transaction_date(t.get("transaction_date"))
            db.add(Transaction(
                job_id=job_id, amount_kurus=t["amount_cents"], currency=t.get("currency", "TRY"),
                type=t["type"], category=t.get("category", "other_expense"),
                description=t.get("description", ""), vendor=t.get("vendor"), transaction_date=when,
                date_is_estimated=estimated, document_id=t.get("document_id"),
                due_date=date.fromisoformat(t["due_date"]) if t.get("due_date") else None,
                counterparty=t.get("counterparty"), account_code=t.get("account_code"),
            ))
        await db.commit()
        await append_job(db, job_id)

    # The customer pays two weeks later (a receipt within 3 days would only be held as a
    # possible duplicate, which hides the problem rather than solving it).
    async with client._maker() as db:
        bank = AnalysisJob(filename="b.csv", file_path="/b.csv", file_type="csv", org_id=org_id,
                           status=JobStatus.COMPLETED)
        db.add(bank)
        await db.flush()
        when, estimated = parse_transaction_date((date.today() + timedelta(days=15)).isoformat())
        db.add(Transaction(job_id=bank.id, amount_kurus=1_180_000, currency="TRY", type="income",
                           category="revenue", description="GELEN EFT ACME LTD", transaction_date=when,
                           date_is_estimated=estimated))
        await db.commit()
        await append_job(db, bank.id)

    async with client._maker() as db:
        summary = await ledger_summary(db, org_id)
        items = (await db.execute(select(OpenItem).where(OpenItem.org_id == org_id))).scalars().all()

    assert summary["revenue_cents"] == 1_180_000          # once, not 2 x 11.800
    assert [(i.document_id, i.status) for i in items] == [("A-1", "settled")]


def test_an_invoice_without_a_readable_contact_is_still_reported_not_hidden():
    from app.services.erp.parasut_connector import islem_from_fatura

    item = {"id": "s9", "attributes": {"issue_date": "2025-02-01", "gross_total": "100", "invoice_no": "Z-9"}}
    tx = islem_from_fatura(item, "income")
    assert tx is not None
    assert tx["document_id"] == "Z-9"
    assert not tx.get("counterparty")


# ── what must not change ─────────────────────────────────────────────────────────────────────


def test_a_pull_without_invoice_numbers_is_still_a_plain_statement():
    from app.services.ingest.ekle import islemler_csv

    text = islemler_csv([{"date": "2025-02-01", "amount_cents": 100, "type": "income", "description": "x"}]).decode()
    assert text.splitlines()[0] == "tarih,açıklama,tutar,tip"


def test_a_bank_statement_is_read_exactly_as_before():
    from app.agents.data_ingestion import _try_parse_csv

    rows = _try_parse_csv("tarih,açıklama,tutar\n2025-02-01,EFT GELEN,100.00\n")
    assert rows and "document_id" not in rows[0] and "due_date" not in rows[0]


def test_an_invoice_list_row_without_a_counterparty_has_an_identity_but_no_open_item_to_open():
    from app.agents.data_ingestion import _try_parse_csv

    rows = _try_parse_csv("tarih,açıklama,tutar,tip,fatura no\n2025-02-01,Satış,100.00,income,Z-9\n")
    assert rows[0]["document_id"] == "Z-9"
    assert "counterparty" not in rows[0]


async def test_the_sync_says_when_an_invoice_has_no_readable_counterparty(client, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "parasut_client_id", "platform-client")
    monkeypatch.setattr(s, "parasut_client_secret", "platform-secret")
    monkeypatch.setattr(pc, "_transport", httpx.MockTransport(Parasut()))   # its invoice has a number, no contact

    h = await _login(client)
    await _connect(client, h, Parasut())
    integ = (await client.get("/api/v1/erp/parasut/durum", headers=h)).json()["data"]["baglanti"]["id"]
    res = await client.post("/api/v1/erp/parasut/sync", data={"integration_id": integ}, headers=h)
    assert res.status_code == 200, res.text
    assert "çift sayılabilir" in res.json()["data"]["uyari"]
