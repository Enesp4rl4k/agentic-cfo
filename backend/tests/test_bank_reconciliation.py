"""Plan v9 §K1 — a bank line settles an invoice; the same money is not revenue twice.

An invoice is revenue when issued, its bank receipt is the cash arriving weeks
later. Both in the ledger counted as revenue twice. The amounts here are written
by hand; nothing is taken from the matcher's output.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item import OpenItem
from app.models.transaction import Transaction
from app.services.ledger import append_job, ledger_summary
from tests.api_helpers import bellek_istemcisi, kullanici


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _sale(uuid: str, *, amount: int = 285_000_00, no: str = "GIB2024000000001", customer: str = "ABC Holding",
          issued: str = "2024-01-02", due: str | None = "2024-02-01") -> dict[str, Any]:
    return {"amount_cents": amount, "type": "income", "category": "revenue", "document_id": uuid,
            "description": f"e-Fatura {no}: {customer}", "counterparty": customer,
            "transaction_date": issued, "due_date": date.fromisoformat(due) if due else None}


def _purchase(uuid: str, *, amount: int = 12_000_00, no: str = "AWS2024000000009", vendor: str = "Turkcell Superonline",
              issued: str = "2024-01-10", due: str | None = "2024-01-25") -> dict[str, Any]:
    return {"amount_cents": amount, "type": "expense", "category": "cogs", "document_id": uuid,
            "description": f"e-Fatura {no}: {vendor}", "counterparty": vendor,
            "transaction_date": issued, "due_date": date.fromisoformat(due) if due else None}


def _bank(description: str, amount: int = 285_000_00, day: str = "2024-02-16", kind: str = "income") -> dict[str, Any]:
    return {"amount_cents": amount, "type": kind, "category": "revenue" if kind == "income" else "other_expense",
            "description": description, "transaction_date": day}


async def _upload(client, org_id: str, *rows: dict[str, Any]) -> dict:
    async with client._maker() as db:
        job = AnalysisJob(filename="x", file_path="/x", file_type="csv", org_id=org_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        for r in rows:
            when, estimated = parse_transaction_date(r["transaction_date"])
            db.add(Transaction(
                job_id=job.id, amount_kurus=r["amount_cents"], currency=r.get("currency", "TRY"), type=r["type"],
                category=r["category"], description=r.get("description"), transaction_date=when,
                date_is_estimated=estimated, document_id=r.get("document_id"), due_date=r.get("due_date"),
                counterparty=r.get("counterparty"), account_code=r.get("account_code"),
            ))
        await db.commit()
        return await append_job(db, job.id)


async def _summary(client, org_id: str) -> dict:
    async with client._maker() as db:
        return await ledger_summary(db, org_id)


async def _item(client, uuid: str) -> OpenItem:
    async with client._maker() as db:
        return (await db.execute(select(OpenItem).where(OpenItem.document_id == uuid))).scalars().one()


async def test_a_receipt_quoting_the_invoice_closes_it_and_is_not_revenue_again(client):
    _, org_id, _ = await kullanici(client, "numara@example.com")
    await _upload(client, org_id, _sale("A"))
    counts = await _upload(client, org_id, _bank("EFT GIB2024000000001 NOLU FATURA ODEMESI"))

    assert counts["settled"] == 1
    item = await _item(client, "A")
    assert (item.status, item.paid_cents) == ("settled", 285_000_00)
    summary = await _summary(client, org_id)
    assert summary["revenue_cents"] == 285_000_00                 # the invoice, once
    assert summary["open_items"]["receivable_cents"] == 0


async def test_the_cash_lands_in_the_month_it_arrived_not_the_invoice_month(client):
    _, org_id, _ = await kullanici(client, "nakit@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("EFT GIB2024000000001"))
    months = {m["month"]: m for m in (await _summary(client, org_id))["months"]}
    assert months["2024-02"]["cash_in_cents"] == 285_000_00
    assert months.get("2024-01", {"cash_in_cents": 0})["cash_in_cents"] == 0


async def test_the_customers_name_and_exact_amount_are_enough_when_only_one_invoice_fits(client):
    _, org_id, _ = await kullanici(client, "isim@example.com")
    await _upload(client, org_id, _sale("A"))
    counts = await _upload(client, org_id, _bank("GELEN HAVALE ABC HOLDING A.S."))
    assert counts["settled"] == 1
    assert (await _item(client, "A")).status == "settled"


async def test_the_same_works_with_the_bank_statement_uploaded_first(client):
    _, org_id, _ = await kullanici(client, "once@example.com")
    await _upload(client, org_id, _bank("EFT GIB2024000000001"))
    counts = await _upload(client, org_id, _sale("A"))
    assert counts["settled"] == 1
    assert (await _summary(client, org_id))["revenue_cents"] == 285_000_00


async def test_a_payment_settles_a_purchase_invoice_too(client):
    _, org_id, _ = await kullanici(client, "alis@example.com")
    await _upload(client, org_id, _purchase("P"))
    await _upload(client, org_id, _bank("TURKCELL SUPERONLINE FATURA", amount=12_000_00, day="2024-01-24", kind="expense"))
    assert (await _item(client, "P")).status == "settled"
    summary = await _summary(client, org_id)
    assert summary["expense_cents"] == 12_000_00
    assert summary["open_items"]["payable_cents"] == 0


async def test_only_the_amount_matching_is_a_question_not_an_answer(client):
    _, org_id, _ = await kullanici(client, "soru@example.com")
    await _upload(client, org_id, _sale("A"))
    counts = await _upload(client, org_id, _bank("GELEN EFT REF 88213"))

    assert counts["settled"] == 0
    assert counts["proposed"] == 1
    assert (await _item(client, "A")).status == "open"
    # Until someone answers, the line is not revenue on top of the invoice.
    assert (await _summary(client, org_id))["revenue_cents"] == 285_000_00


async def test_two_invoices_that_fit_are_never_chosen_between_automatically(client):
    _, org_id, _ = await kullanici(client, "iki@example.com")
    await _upload(client, org_id, _sale("A", no="N1"), _sale("B", no="N2", issued="2024-01-05", due="2024-02-05"))
    counts = await _upload(client, org_id, _bank("HAVALE ABC HOLDING"))
    assert counts["settled"] == 0
    assert counts["proposed"] == 1
    assert {(await _item(client, "A")).status, (await _item(client, "B")).status} == {"open"}


async def test_part_of_an_invoice_is_proposed_and_leaves_the_rest_open(client):
    headers, org_id, _ = await kullanici(client, "kismi@example.com")
    await _upload(client, org_id, _sale("A"))
    counts = await _upload(client, org_id, _bank("GIB2024000000001 ICIN AVANS", amount=100_000_00))
    assert counts["proposed"] == 1

    proposed = (await client.get("/api/v1/ledger/settlements/proposed", headers=headers)).json()["data"]
    res = await client.post(f"/api/v1/ledger/settlements/{proposed[0]['id']}/resolve", headers=headers,
                            json={"action": "confirm"})
    assert res.status_code == 200, res.text
    item = await _item(client, "A")
    assert (item.status, item.paid_cents) == ("open", 100_000_00)
    assert (await _summary(client, org_id))["open_items"]["receivable_cents"] == 185_000_00


async def test_confirming_closes_rejecting_counts_the_line_as_its_own_money(client):
    headers, org_id, _ = await kullanici(client, "karar@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("GELEN EFT REF 1"))
    proposed = (await client.get("/api/v1/ledger/settlements/proposed", headers=headers)).json()["data"]
    assert proposed[0]["item"]["counterparty"] == "ABC Holding"
    assert proposed[0]["row"]["description"] == "GELEN EFT REF 1"

    res = await client.post(f"/api/v1/ledger/settlements/{proposed[0]['id']}/resolve", headers=headers,
                            json={"action": "reject"})
    assert res.status_code == 200, res.text
    assert (await _item(client, "A")).status == "open"
    assert (await _summary(client, org_id))["revenue_cents"] == 570_000_00

    # Said no: the question is not asked again by the next upload.
    await _upload(client, org_id, _bank("BASKA BIR SEY", amount=7_00, day="2024-03-01"))
    assert (await client.get("/api/v1/ledger/settlements/proposed", headers=headers)).json()["data"] == []


async def test_uploading_again_settles_nothing_twice(client):
    _, org_id, _ = await kullanici(client, "tekrar@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("EFT GIB2024000000001"))
    await _upload(client, org_id, _bank("EFT GIB2024000000001"))
    assert (await _item(client, "A")).paid_cents == 285_000_00


async def test_a_payment_before_the_invoice_existed_settles_nothing(client):
    _, org_id, _ = await kullanici(client, "erken@example.com")
    await _upload(client, org_id, _sale("A"))
    counts = await _upload(client, org_id, _bank("ABC HOLDING", day="2023-11-01"))
    assert (counts["settled"], counts["proposed"]) == (0, 0)


async def test_money_in_never_settles_a_payable(client):
    _, org_id, _ = await kullanici(client, "yon@example.com")
    await _upload(client, org_id, _purchase("P"))
    counts = await _upload(client, org_id, _bank("TURKCELL IADE", amount=12_000_00, day="2024-01-24", kind="income"))
    assert (counts["settled"], counts["proposed"]) == (0, 0)


async def test_a_foreign_currency_invoice_is_not_settled_by_lira(client):
    _, org_id, _ = await kullanici(client, "doviz@example.com")
    await _upload(client, org_id, {**_sale("A"), "currency": "USD"})
    counts = await _upload(client, org_id, _bank("EFT GIB2024000000001"))
    assert (counts["settled"], counts["proposed"]) == (0, 0)


async def test_an_invoice_and_its_receipt_a_day_apart_are_not_duplicates(client):
    """Different bases: one is the document, the other the cash."""
    _, org_id, _ = await kullanici(client, "gun@example.com")
    await _upload(client, org_id, _sale("A", due=None))
    counts = await _upload(client, org_id, _bank("EFT GIB2024000000001", day="2024-01-03"))
    assert counts["possible_duplicate"] == 0
    assert counts["settled"] == 1


async def test_a_month_with_books_takes_its_profit_from_the_books(client):
    """The company's posting list is the whole month; a bank line only moves cash."""
    _, org_id, _ = await kullanici(client, "defter@example.com")
    await _upload(client, org_id, {"amount_cents": 500_00, "type": "income", "category": "revenue",
                                   "account_code": "600", "description": "Lisans", "transaction_date": "2024-01-10"})
    await _upload(client, org_id, _bank("GELEN EFT X", amount=500_00, day="2024-01-20"))
    await _upload(client, org_id, _bank("GELEN EFT Y", amount=70_00, day="2024-02-20"))

    summary = await _summary(client, org_id)
    assert summary["revenue_cents"] == 500_00 + 70_00     # January books; February has only the bank
    assert {m["month"]: m["cash_in_cents"] for m in summary["months"]} == {"2024-01": 500_00, "2024-02": 70_00}


async def test_how_late_a_customer_pays_is_measured_from_their_receipts(client):
    headers, org_id, _ = await kullanici(client, "gecikme@example.com")
    await _upload(client, org_id,
                  _sale("A", no="N1", amount=100_00, due="2024-02-01"),
                  _sale("B", no="N2", amount=200_00, issued="2024-02-01", due="2024-03-01"))
    await _upload(client, org_id, _bank("N1 ODEME", amount=100_00, day="2024-02-16"))   # 15 days late
    await _upload(client, org_id, _bank("N2 ODEME", amount=200_00, day="2024-03-26"))   # 25 days late

    data = (await client.get("/api/v1/ledger/payment-behaviour", headers=headers)).json()["data"]
    assert data == [{"counterparty": "ABC Holding", "direction": "receivable", "settled": 2, "average_delay_days": 20.0}]


async def test_another_companys_proposal_cannot_be_decided(client):
    headers, org_id, _ = await kullanici(client, "bizimki@example.com")
    other, _, _ = await kullanici(client, "digeri@example.com")
    await _upload(client, org_id, _sale("A"))
    await _upload(client, org_id, _bank("GELEN EFT REF 1"))
    proposed = (await client.get("/api/v1/ledger/settlements/proposed", headers=headers)).json()["data"]
    res = await client.post(f"/api/v1/ledger/settlements/{proposed[0]['id']}/resolve", headers=other,
                            json={"action": "confirm"})
    assert res.status_code == 404
    assert (await client.get("/api/v1/ledger/settlements/proposed", headers=other)).json()["data"] == []
