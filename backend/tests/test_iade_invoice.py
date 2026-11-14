"""SMMM M2: an IADE (return) invoice reverses what it returns; it is not a sale.

GİB's own sample (IadeFaturasiOrnegi.xml) with the issuer as our company used to
come out as a *sale*: 120 debit, 600 and 391 credit. A return is issued by the
party who returns the goods, so for the issuer it undoes a purchase, and for the
receiver it undoes a sale.

The assumption "the issuer is the one returning" is GİB's rule for iade
invoices, and it is the only thing separating the two readings, so every return
is held for the accountant (confidence below the 0.80 gate) rather than posted.

Fixtures are GİB's published packages (fetched by scripts/fetch_gib_corpus.py,
not committed); the tests skip when they are not there.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.agents.accounting.double_entry import DoubleEntryEngine
from app.agents.data_ingestion import _try_parse_ubl_xml
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item import OpenItem
from app.models.transaction import Transaction
from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser
from app.services.accounting.thp_classifier import THPClassifier
from app.services.ledger import append_job
from tests.api_helpers import kullanici

XML_DIR = (
    Path(__file__).parent / "fixtures" / "gib_corpus" / "ubl_tr" / "UBLTR_1.2.1_Paketi" / "xml"
)
IADE = XML_DIR / "IadeFaturasiOrnegi.xml"
SATIS = XML_DIR / "TicariFaturaOrnegi.xml"

pytestmark = pytest.mark.skipif(not IADE.exists(), reason="GİB corpus not fetched")


@pytest.fixture(scope="module")
def raw() -> str:
    return IADE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parties(raw):
    p = UBLTRInvoiceParser.parse_xml(raw, own_vkn="")
    return p.supplier, p.customer


def _lines(inv):
    return {(e.account_code, "D" if e.debit_amount else "C"): e.debit_amount or e.credit_amount
            for e in inv.suggested_tdhp_entries}


def test_the_sample_really_is_an_iade(raw):
    assert UBLTRInvoiceParser.parse_xml(raw, own_vkn="").invoice_type == "IADE"


def test_issued_by_us_it_undoes_a_purchase_not_a_sale(raw, parties):
    sup, cus = parties
    inv = UBLTRInvoiceParser.parse_xml(raw, own_vkn=sup.vkn_tckn)
    assert inv.is_return and inv.economic_direction == "purchase"
    lines = _lines(inv)
    # Reverse of 770 / 191 debit, 320 credit: payable down, cost and input KDV down.
    assert ("320.01", "D") in lines and ("770.01", "C") in lines and ("191.01", "C") in lines
    assert not any(code.startswith(("120", "600", "391")) for code, _ in lines)
    assert sum(v for (c, s), v in lines.items() if s == "D") == sum(v for (c, s), v in lines.items() if s == "C")
    # The vendor named is the other party, not us.
    assert cus.title in next(e.account_name for e in inv.suggested_tdhp_entries if e.account_code == "320.01")


def test_received_by_us_it_undoes_a_sale(raw, parties):
    _, cus = parties
    inv = UBLTRInvoiceParser.parse_xml(raw, own_vkn=cus.vkn_tckn)
    assert inv.is_return and inv.economic_direction == "sale"
    lines = _lines(inv)
    # Reverse of 120 debit, 600 / 391 credit: receivable down, revenue and output KDV down.
    assert ("120.01", "C") in lines and ("600.01", "D") in lines and ("391.01", "D") in lines
    assert sum(v for (c, s), v in lines.items() if s == "D") == sum(v for (c, s), v in lines.items() if s == "C")


@pytest.mark.skipif(not SATIS.exists(), reason="sample not in corpus")
def test_an_ordinary_sale_is_unchanged():
    raw = SATIS.read_text(encoding="utf-8")
    parties = UBLTRInvoiceParser.parse_xml(raw, own_vkn="")
    inv = UBLTRInvoiceParser.parse_xml(raw, own_vkn=parties.supplier.vkn_tckn)
    assert not inv.is_return and inv.economic_direction == "sale"
    assert ("120.01", "D") in _lines(inv)


def test_the_pipeline_row_is_signed_marked_and_held(raw, parties):
    sup, cus = parties
    (row,) = _try_parse_ubl_xml(raw, own_vkn=sup.vkn_tckn)
    assert row["iade"] is True
    assert row["type"] == "expense" and row["amount_cents"] < 0  # a purchase reduced
    assert row["confidence"] < 0.8  # held for the accountant: the issuer-is-returner reading is an assumption
    assert row["counterparty"] == cus.title  # the party we bought from

    (row2,) = _try_parse_ubl_xml(raw, own_vkn=cus.vkn_tckn)
    assert row2["type"] == "income" and row2["amount_cents"] < 0  # revenue reduced
    assert row2["counterparty"] == sup.title


@pytest.mark.parametrize("typ, kdv_side, main_side", [("expense", "C", "C"), ("income", "D", "D")])
def test_the_engine_books_a_return_the_other_way_round_with_kdv_on_the_right_side(typ, kdv_side, main_side):
    eng, clf = DoubleEntryEngine(), THPClassifier()
    tx = {"id": "t", "amount_kurus": -120_000, "type": typ, "description": "iade fatura",
          "transaction_date": "2026-01-05T00:00:00+00:00", "kdv_kurus": 20_000, "iade": True}
    k = eng.create_entry(tx, clf.classify("iade fatura", 120_000, typ))
    assert k.dengeli
    by = {s.hesap_kodu: ("D" if s.borc else "C", s.borc or s.alacak) for s in k.satirlar}
    kdv_code = "191" if typ == "expense" else "391"
    assert by[kdv_code] == (kdv_side, 20_000)
    main = next(c for c in by if c not in ("102", "191", "391"))
    assert by[main] == (main_side, 100_000)
    assert by["102"][0] != main_side


def test_a_negative_amount_without_the_mark_is_still_not_reversed():
    # An LLM- or CSV-extracted "-500" outflow is an expense, not a reversal.
    eng, clf = DoubleEntryEngine(), THPClassifier()
    tx = {"id": "t", "amount_kurus": -50_000, "type": "expense", "description": "kira",
          "transaction_date": "2026-01-05T00:00:00+00:00"}
    k = eng.create_entry(tx, clf.classify("kira", 50_000, "expense"))
    assert next(s for s in k.satirlar if s.hesap_kodu != "102").borc == 50_000


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
    assert n_items == 1 and items == [("INV-1", 100_000)]
