"""Plan v9 §K1 — what a company is owed and owes, from the invoices it holds.

`PaymentDueDate` was never read, so no cash plan could rest on a real date.
Expected values below are read from GİB's own UBL-TR package (ubl_tr/…/xml):

    TemelFaturaOrnegi   issued 2009-01-05, due 2009-01-20, note "BBB Bank Otomatik Ödeme"
    TicariFaturaOrnegi  issued 2009-01-05, due 2008-11-25: due BEFORE issue, not believed
    ISTISNA-1           issued 2010-05-31, due 2010-07-15, note "%50 Peşin, %50 ..."
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agents.data_ingestion import _try_parse_ubl_xml
from app.config import get_settings
from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item import OpenItem
from app.models.transaction import Transaction
from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser
from app.services.ledger import append_job, ledger_summary
from tests.api_helpers import bellek_istemcisi, kullanici

PKG = Path(__file__).resolve().parent / "fixtures" / "gib_corpus" / "ubl_tr" / "UBLTR_1.2.1_Paketi" / "xml"
NEEDS_PKG = pytest.mark.skipif(not PKG.exists(), reason="GİB UBL-TR paketi yok")

BIZ, THEM = "1111111111", "2222222222"


def _invoice(*, uuid: str = "F47AC10B-58CC-4372-A567-0E02B2C3D479", supplier: str = BIZ, customer: str = THEM,
             issued: str = "2024-03-01", terms: str = "", payable: str = "1180.00") -> str:
    """Trimmed from TemelFaturaOrnegi.xml: the elements the parser reads."""
    def party(vkn: str, name: str) -> str:
        return (f'<cac:Party><cac:PartyIdentification><cbc:ID schemeID="VKN">{vkn}</cbc:ID></cac:PartyIdentification>'
                f"<cac:PartyName><cbc:Name>{name}</cbc:Name></cac:PartyName></cac:Party>")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
 <cbc:ProfileID>TICARIFATURA</cbc:ProfileID><cbc:ID>GIB2024000000001</cbc:ID><cbc:UUID>{uuid}</cbc:UUID>
 <cbc:IssueDate>{issued}</cbc:IssueDate><cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
 <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>
 <cac:AccountingSupplierParty>{party(supplier, "Satici AS")}</cac:AccountingSupplierParty>
 <cac:AccountingCustomerParty>{party(customer, "Alici Ltd")}</cac:AccountingCustomerParty>
 {terms}
 <cac:TaxTotal><cbc:TaxAmount currencyID="TRY">180.00</cbc:TaxAmount><cac:TaxSubtotal>
 <cbc:TaxableAmount currencyID="TRY">1000.00</cbc:TaxableAmount><cbc:TaxAmount currencyID="TRY">180.00</cbc:TaxAmount>
 <cbc:Percent>18</cbc:Percent><cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name>
 <cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
 <cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="TRY">1000.00</cbc:LineExtensionAmount>
 <cbc:TaxExclusiveAmount currencyID="TRY">1000.00</cbc:TaxExclusiveAmount>
 <cbc:TaxInclusiveAmount currencyID="TRY">1180.00</cbc:TaxInclusiveAmount>
 <cbc:PayableAmount currencyID="TRY">{payable}</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>"""


def _due(date: str, note: str = "") -> str:
    return f"<cac:PaymentTerms><cbc:Note>{note}</cbc:Note><cbc:PaymentDueDate>{date}</cbc:PaymentDueDate></cac:PaymentTerms>"


# ── reading the document ──────────────────────────────────────────────────────


def test_the_due_date_and_its_note_are_read():
    inv = UBLTRInvoiceParser.parse_xml(_invoice(terms=_due("2024-04-15", "45 gun vade")), own_vkn=BIZ)
    assert inv.payment_due_date.isoformat() == "2024-04-15"
    assert inv.payment_note == "45 gun vade"


def test_no_terms_means_no_due_date_not_a_guess():
    inv = UBLTRInvoiceParser.parse_xml(_invoice(), own_vkn=BIZ)
    assert inv.payment_due_date is None


def test_a_due_date_before_the_invoice_is_not_believed():
    inv = UBLTRInvoiceParser.parse_xml(_invoice(terms=_due("2024-01-15")), own_vkn=BIZ)
    assert inv.payment_due_date is None
    assert "2024-01-15" in inv.payment_note


@NEEDS_PKG
def test_gibs_own_samples_read_as_written():
    temel = UBLTRInvoiceParser.parse_xml((PKG / "TemelFaturaOrnegi.xml").read_bytes())
    assert temel.payment_due_date.isoformat() == "2009-01-20"
    assert "Otomatik" in temel.payment_note
    istisna = UBLTRInvoiceParser.parse_xml((PKG / "ISTISNA-1.xml").read_bytes())
    assert istisna.payment_due_date.isoformat() == "2010-07-15"
    assert istisna.payment_note.startswith("%50")


@NEEDS_PKG
def test_gibs_sample_with_a_due_date_before_issue_is_not_believed():
    ticari = UBLTRInvoiceParser.parse_xml((PKG / "TicariFaturaOrnegi.xml").read_bytes())
    assert ticari.payment_due_date is None
    assert "2008-11-25" in ticari.payment_note


# ── becoming open items ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "gib_vkn", BIZ)
    async with bellek_istemcisi() as c:
        yield c


async def _analysed(client, org_id: str, xml: str) -> str:
    rows = _try_parse_ubl_xml(xml)
    assert rows
    async with client._maker() as db:
        job = AnalysisJob(filename="f.xml", file_path="/f.xml", file_type="xml", org_id=org_id,
                          status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        for r in rows:
            when, estimated = parse_transaction_date(r.get("transaction_date"))
            db.add(Transaction(
                job_id=job.id, amount_kurus=r["amount_cents"], currency=r["currency"], type=r["type"],
                category=r["category"], description=r.get("description"), vendor=r.get("vendor"),
                transaction_date=when, date_is_estimated=estimated, confidence=r.get("confidence"),
                document_id=r.get("document_id"),
                due_date=date.fromisoformat(r["due_date"]) if r.get("due_date") else None,
                payment_note=r.get("payment_note"), counterparty=r.get("counterparty"),
            ))
        await db.commit()
        await append_job(db, job.id)
        return job.id


async def _items(client) -> list[OpenItem]:
    async with client._maker() as db:
        return list((await db.execute(select(OpenItem))).scalars())


async def test_a_sale_is_a_receivable_with_its_due_date(client):
    _, org_id, _ = await kullanici(client, "alacak@example.com")
    await _analysed(client, org_id, _invoice(terms=_due("2024-04-15", "45 gun vade")))
    items = await _items(client)
    assert [(i.direction, i.amount_cents, i.counterparty, i.status) for i in items] == [
        ("receivable", 1180_00, "Alici Ltd", "open"),
    ]
    assert items[0].due_date.isoformat() == "2024-04-15"
    assert items[0].payment_note == "45 gun vade"


async def test_a_purchase_is_a_payable(client):
    _, org_id, _ = await kullanici(client, "borc@example.com")
    await _analysed(client, org_id, _invoice(supplier=THEM, customer=BIZ))
    items = await _items(client)
    assert [(i.direction, i.counterparty) for i in items] == [("payable", "Satici AS")]
    assert items[0].due_date is None


async def test_the_same_invoice_twice_is_one_item(client):
    _, org_id, _ = await kullanici(client, "tek@example.com")
    await _analysed(client, org_id, _invoice())
    await _analysed(client, org_id, _invoice())
    assert len(await _items(client)) == 1
    async with client._maker() as db:
        assert (await ledger_summary(db, org_id))["revenue_cents"] == 1180_00


async def test_an_invoice_on_an_unknown_side_opens_nothing(client, monkeypatch):
    """No VKN match: we do not know who owes whom, so no one is said to owe."""
    _, org_id, _ = await kullanici(client, "bilinmez@example.com")
    monkeypatch.setattr(get_settings(), "gib_vkn", "9999999999")
    await _analysed(client, org_id, _invoice())
    assert await _items(client) == []


async def test_the_summary_totals_what_is_open_and_says_what_has_no_date(client):
    _, org_id, _ = await kullanici(client, "toplam@example.com")
    await _analysed(client, org_id, _invoice(uuid="A", terms=_due("2024-04-15")))
    await _analysed(client, org_id, _invoice(uuid="B"))
    await _analysed(client, org_id, _invoice(uuid="C", supplier=THEM, customer=BIZ, terms=_due("2024-05-01")))
    async with client._maker() as db:
        open_items = (await ledger_summary(db, org_id))["open_items"]
    assert open_items == {"receivable_cents": 2360_00, "payable_cents": 1180_00, "no_due_date": 1, "other_currency": 0}


async def test_a_real_invoice_file_through_the_whole_pipeline_opens_an_item(client, monkeypatch, tmp_path):
    """The row crosses LangGraph state and the worker: only a real run proves it."""
    import app.database as database
    from app.worker import run_cfo_analysis

    monkeypatch.setattr(database, "get_session_factory", lambda eng=None: client._maker)
    monkeypatch.setattr(database, "session_factory", lambda: client._maker)
    monkeypatch.setattr(database, "engine", lambda: None)
    monkeypatch.setattr("app.post_completion.spawn_auto_chain", lambda *a: None)
    monkeypatch.setattr("app.post_completion._job_side_effects", lambda *a, **k: None)

    _, org_id, _ = await kullanici(client, "uctan@example.com")
    path = tmp_path / "fatura.xml"
    path.write_text(_invoice(terms=_due("2024-04-15", "45 gun vade")), encoding="utf-8")
    async with client._maker() as db:
        job = AnalysisJob(filename="fatura.xml", file_path=str(path), file_type="xml", org_id=org_id,
                          status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = job.id

    out = await run_cfo_analysis({}, job_id)
    assert out.get("ok") is True, out
    async with client._maker() as db:
        tx = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars().one()
        status = (await db.get(AnalysisJob, job_id)).status
    assert tx.due_date == date(2024, 4, 15)
    assert tx.document_id == "F47AC10B-58CC-4372-A567-0E02B2C3D479"
    assert status == JobStatus.COMPLETED
    items = await _items(client)
    assert [(i.direction, i.due_date) for i in items] == [("receivable", date(2024, 4, 15))]


async def test_open_items_are_listed_by_due_date_for_this_company_only(client):
    headers, org_id, _ = await kullanici(client, "liste@example.com")
    other, _, _ = await kullanici(client, "baskasi@example.com")
    await _analysed(client, org_id, _invoice(uuid="A", terms=_due("2024-05-01")))
    await _analysed(client, org_id, _invoice(uuid="B", terms=_due("2024-04-01")))
    await _analysed(client, org_id, _invoice(uuid="C"))

    data = (await client.get("/api/v1/ledger/open-items", headers=headers)).json()["data"]
    assert [i["due_date"] for i in data] == ["2024-04-01", "2024-05-01", None]
    assert (await client.get("/api/v1/ledger/open-items", headers=other)).json()["data"] == []
