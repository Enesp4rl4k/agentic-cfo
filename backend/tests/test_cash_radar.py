"""Plan v9 §K1 — Nakit Radarı: 13 weeks of open invoices against the last proven balance.

Every expected figure is written by hand from the inputs below. The anchor is
Wednesday 2025-01-01, so week 1 is 1-7 January, week 2 is 8-14, week 3 is 15-21,
week 6 is 5-11 February and week 13 ends on 1 April.

The radar claims nothing the documents do not say: no balance without a statement
that proves one, no date for an invoice that gives none, no terms nobody offered.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.models.transaction import Transaction
from app.services.cash_radar import HORIZON_WEEKS, compute_cash_radar
from app.services.ledger import append_job
from app.services.reconciliation import CONFIRMED
from tests.api_helpers import bellek_istemcisi, kullanici

ANCHOR = date(2025, 1, 1)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _sale(uuid: str, amount: int, due: str | None, *, customer: str = "Musteri AS",
          issued: str = "2024-12-20", currency: str = "TRY") -> dict[str, Any]:
    return {"amount_cents": amount, "type": "income", "category": "revenue", "document_id": uuid,
            "description": f"e-Fatura {uuid}: {customer}", "counterparty": customer, "currency": currency,
            "transaction_date": issued, "due_date": date.fromisoformat(due) if due else None}


def _purchase(uuid: str, amount: int, due: str | None, *, vendor: str = "Tedarikci Ltd",
              issued: str = "2024-12-20") -> dict[str, Any]:
    return {"amount_cents": amount, "type": "expense", "category": "cogs", "document_id": uuid,
            "description": f"e-Fatura {uuid}: {vendor}", "counterparty": vendor,
            "transaction_date": issued, "due_date": date.fromisoformat(due) if due else None}


async def _upload(client, org_id: str, *rows: dict[str, Any], meta: dict | None = None,
                  status: JobStatus = JobStatus.COMPLETED) -> str:
    async with client._maker() as db:
        job = AnalysisJob(filename="x.csv", file_path="/x.csv", file_type="csv", org_id=org_id,
                          status=status, result_metadata=meta)
        db.add(job)
        await db.flush()
        for r in rows:
            when, estimated = parse_transaction_date(r["transaction_date"])
            db.add(Transaction(
                job_id=job.id, amount_kurus=r["amount_cents"], currency=r.get("currency", "TRY"),
                type=r["type"], category=r["category"], description=r.get("description"),
                transaction_date=when, date_is_estimated=estimated, document_id=r.get("document_id"),
                due_date=r.get("due_date"), counterparty=r.get("counterparty"),
            ))
        await db.commit()
        await append_job(db, job.id)
        return job.id


def _statement(day: str, cents: int) -> dict:
    """What the worker records for a statement whose balances chain."""
    return {"closing_balance": {"date": day, "balance_cents": cents}}


async def _radar(client, org_id: str, anchor: date = ANCHOR) -> Any:
    async with client._maker() as db:
        return await compute_cash_radar(db, org_id, anchor_date=anchor)


async def test_the_latest_proven_balance_is_the_starting_cash(client):
    _, org_id, _ = await kullanici(client, "bakiye@example.com")
    await _upload(client, org_id, meta=_statement("2024-11-30", 999_00))
    await _upload(client, org_id, meta=_statement("2024-12-31", 100_000_00))
    # A held analysis is not yet the company's: its balance waits with it.
    await _upload(client, org_id, meta=_statement("2025-01-01", 1_00), status=JobStatus.AWAITING_REVIEW)
    await _upload(client, org_id,
                  _sale("R1", 50_000_00, "2025-01-10"),
                  _purchase("P1", 30_000_00, "2025-01-18"))

    radar = await _radar(client, org_id)

    assert radar.starting_cash_cents == 100_000_00
    assert radar.starting_cash_as_of == "2024-12-31"
    assert len(radar.weeks) == HORIZON_WEEKS
    assert (radar.weeks[0].start_date, radar.weeks[0].end_date) == ("2025-01-01", "2025-01-07")
    assert radar.weeks[0].end_balance_cents == 100_000_00
    assert (radar.weeks[1].inflow_cents, radar.weeks[1].end_balance_cents) == (50_000_00, 150_000_00)
    assert (radar.weeks[2].outflow_cents, radar.weeks[2].end_balance_cents) == (30_000_00, 120_000_00)
    assert radar.weeks[-1].end_balance_cents == 120_000_00
    assert radar.shortfall is None
    assert radar.not_included


async def test_without_a_proven_balance_it_shows_movement_and_claims_no_gap(client):
    _, org_id, _ = await kullanici(client, "bakiyesiz@example.com")
    await _upload(client, org_id,
                  _sale("R1", 50_000_00, "2025-01-10"),
                  _purchase("P1", 500_000_00, "2025-01-18"))

    radar = await _radar(client, org_id)

    assert radar.starting_cash_cents is None
    assert radar.starting_cash_as_of is None
    assert radar.weeks[1].end_balance_cents == 50_000_00
    assert radar.weeks[2].end_balance_cents == -450_000_00
    assert radar.shortfall is None


async def test_a_customer_who_pays_late_is_expected_late(client):
    _, org_id, _ = await kullanici(client, "gecikme@example.com")
    await _upload(client, org_id,
                  _sale("PAST", 10_000_00, "2024-11-01", customer="Geciktiren AS", issued="2024-10-01"))
    async with client._maker() as db:
        item = (await db.execute(select(OpenItem).where(OpenItem.document_id == "PAST"))).scalars().one()
        item.status, item.paid_cents = "settled", item.amount_cents
        # Paid 15 November against 1 November: 14 days late.
        db.add(OpenItemMatch(org_id=org_id, open_item_id=item.id, ledger_row_id="row",
                             amount_cents=10_000_00, method="invoice_number", status=CONFIRMED,
                             matched_on=date(2024, 11, 15)))
        await db.commit()
    await _upload(client, org_id, _sale("NEW", 50_000_00, "2025-01-03", customer="Geciktiren AS"))

    radar = await _radar(client, org_id)

    assert radar.weeks[0].inflow_cents == 0
    assert radar.weeks[2].inflow_cents == 50_000_00
    expected = radar.weeks[2].receivables[0]
    assert (expected["due_date"], expected["expected_date"], expected["delay_days"]) == (
        "2025-01-03", "2025-01-17", 14)


async def test_an_invoice_with_no_due_date_is_counted_not_placed(client):
    _, org_id, _ = await kullanici(client, "vadesiz@example.com")
    await _upload(client, org_id,
                  _sale("R1", 25_000_00, None),
                  _purchase("P1", 7_000_00, None))

    radar = await _radar(client, org_id)

    assert (radar.undated_receivables_cents, radar.undated_payables_cents) == (25_000_00, 7_000_00)
    assert all(w.inflow_cents == 0 and w.outflow_cents == 0 for w in radar.weeks)


async def test_an_overdue_receivable_is_reported_and_an_overdue_payable_is_owed_now(client):
    _, org_id, _ = await kullanici(client, "gecmis@example.com")
    await _upload(client, org_id,
                  _sale("R1", 40_000_00, "2024-12-15", customer="Eski Musteri"),
                  _purchase("P1", 15_000_00, "2024-12-20"))

    radar = await _radar(client, org_id)

    assert [(r["counterparty"], r["amount_cents"]) for r in radar.overdue_receivables] == [
        ("Eski Musteri", 40_000_00)]
    assert all(w.inflow_cents == 0 for w in radar.weeks)
    assert radar.overdue_payables_cents == 15_000_00
    assert radar.weeks[0].outflow_cents == 15_000_00
    assert radar.weeks[0].payables[0]["is_overdue"] is True


async def test_a_gap_names_its_week_its_cause_and_real_amounts(client):
    _, org_id, _ = await kullanici(client, "acik@example.com")
    await _upload(client, org_id, meta=_statement("2024-12-31", 30_000_00))
    await _upload(client, org_id,
                  _sale("R1", 20_000_00, "2025-01-04"),                         # week 1: 50,000
                  _purchase("P1", 120_000_00, "2025-01-18", vendor="Ana Tedarikci AS"),  # week 3: -70,000
                  _sale("R2", 45_000_00, "2025-02-10", customer="Buyuk Musteri"))  # week 6: -25,000

    radar = await _radar(client, org_id)
    gap = radar.shortfall

    assert gap is not None
    assert (gap.week, gap.week_start, gap.week_end) == (3, "2025-01-15", "2025-01-21")
    assert gap.shortfall_cents == 70_000_00
    assert "Ana Tedarikci AS" in gap.driver and "₺120,000.00" in gap.driver
    assert [(a["type"], a["amount_cents"]) for a in gap.actions] == [
        ("early_collection", 45_000_00), ("defer_payment", 120_000_00), ("financing", 70_000_00)]
    # No discount rate, no extra days: nobody offered them.
    assert not any("%" in a["detail"] or "gün" in a["detail"] for a in gap.actions)
    assert radar.weeks[5].end_balance_cents == -25_000_00


async def test_a_foreign_currency_invoice_is_counted_never_converted(client):
    _, org_id, _ = await kullanici(client, "doviz@example.com")
    await _upload(client, org_id, _sale("USD1", 1_000_00, "2025-01-10", currency="USD"))

    radar = await _radar(client, org_id)

    assert radar.other_currency_items == 1
    assert all(w.inflow_cents == 0 for w in radar.weeks)


async def test_the_horizon_ends_on_the_last_day_of_week_thirteen(client):
    _, org_id, _ = await kullanici(client, "ufuk@example.com")
    await _upload(client, org_id,
                  _sale("IN", 10_000_00, "2025-04-01"),
                  _sale("OUT", 3_000_00, "2025-04-02"))

    radar = await _radar(client, org_id)

    assert radar.weeks[-1].end_date == "2025-04-01"
    assert radar.weeks[-1].inflow_cents == 10_000_00
    assert radar.beyond_horizon_cents == 3_000_00


async def test_the_radar_endpoint(client):
    headers, org_id, _ = await kullanici(client, "api-radar@example.com")
    await _upload(client, org_id, meta=_statement("2024-12-31", 50_000_00))

    response = await client.get("/api/v1/ledger/cash-radar?anchor_date=2025-01-01", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["starting_cash_cents"] == 50_000_00
    assert body["data"]["anchor_date"] == "2025-01-01"
    assert len(body["data"]["weeks"]) == HORIZON_WEEKS

    bad = await client.get("/api/v1/ledger/cash-radar?anchor_date=invalid-date", headers=headers)
    assert bad.status_code == 400


async def test_a_bank_statement_with_a_balance_column_proves_its_closing_balance(client, monkeypatch, tmp_path: Path):
    """The balance crosses the parser, LangGraph state and the worker: only a real run proves it."""
    import app.database as database
    from app.worker import run_cfo_analysis

    monkeypatch.setattr(database, "get_session_factory", lambda eng=None: client._maker)
    monkeypatch.setattr(database, "session_factory", lambda: client._maker)
    monkeypatch.setattr(database, "engine", lambda: None)
    monkeypatch.setattr("app.worker.spawn_auto_chain", lambda *a: None)
    monkeypatch.setattr("app.worker._job_side_effects", lambda *a, **k: None)

    _, org_id, _ = await kullanici(client, "ekstre@example.com")
    path = tmp_path / "banka.csv"
    path.write_text(
        "Tarih;Açıklama;Tutar;Bakiye\n"
        "02.04.2025;GELEN EFT ABC;10.000,00;60.000,00\n"
        "05.04.2025;KIRA ODEMESI;-4.000,00;56.000,00\n"
        "09.04.2025;GELEN EFT XYZ;1.500,50;57.500,50\n",
        encoding="utf-8",
    )
    async with client._maker() as db:
        job = AnalysisJob(filename="banka.csv", file_path=str(path), file_type="csv", org_id=org_id,
                          status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = job.id

    out = await run_cfo_analysis({}, job_id)
    assert out.get("ok") is True, out
    async with client._maker() as db:
        meta = (await db.get(AnalysisJob, job_id)).result_metadata
    assert meta["closing_balance"] == {"date": "2025-04-09", "balance_cents": 57_500_50}
