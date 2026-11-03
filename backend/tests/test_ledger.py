"""Plan v9 §K1 / §V5 F1 — one company ledger; the same money is counted once.

Every upload was an island: the same file analysed twice was two analyses, and
January–March plus February–April said nothing about the months they share.

Expected figures come from `demo/data/logo_tiger_2024.csv` itself, summed here
without the pipeline: the 600 account's credits, and the 193/360/7xx debits.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from app.agents.data_ingestion import _tablo_ekstresi
from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.transaction import Transaction
from app.services.ledger import append_job, backfill, ledger_summary
from tests.api_helpers import bellek_istemcisi, kullanici

DEMO = Path(__file__).resolve().parents[2] / "demo" / "data" / "logo_tiger_2024.csv"


def _kurus(cell: str) -> int:
    return round(float(cell.replace(".", "").replace(",", ".")) * 100) if cell.strip() else 0


def _file_revenue(months: set[str]) -> int:
    """Revenue of these months, read straight from the file."""
    lines = DEMO.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Tarih;"))
    total = 0
    for row in csv.reader(lines[start + 1:], delimiter=";"):
        if len(row) >= 6 and row[2] == "600" and row[0][3:5] in months:
            total += _kurus(row[5])
    return total


def _demo_rows(*months: str) -> list[dict]:
    rows = _tablo_ekstresi(str(DEMO)) or []
    return [r for r in rows if not months or r["transaction_date"][5:7] in months]


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _analysed(client, org_id: str, rows: list[dict[str, Any]]) -> str:
    """A completed analysis of these rows, as the worker saves them."""
    async with client._maker() as db:
        job = AnalysisJob(filename="x.csv", file_path="/x.csv", file_type="csv", org_id=org_id,
                          status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        for r in rows:
            when, estimated = parse_transaction_date(r.get("transaction_date"))
            db.add(Transaction(
                job_id=job.id, amount_kurus=r["amount_cents"], currency="TRY", type=r["type"],
                category=r["category"], description=r.get("description"), vendor=r.get("vendor"),
                transaction_date=when, date_is_estimated=estimated, account_code=r.get("account_code"),
            ))
        await db.commit()
        return job.id


async def _append(client, job_id: str) -> dict:
    async with client._maker() as db:
        return await append_job(db, job_id)


async def _summary(client, org_id: str) -> dict:
    async with client._maker() as db:
        return await ledger_summary(db, org_id)


async def test_the_whole_file_lands_in_the_ledger(client):
    _, org_id, _ = await kullanici(client, "tam@example.com")
    rows = _demo_rows()
    counts = await _append(client, await _analysed(client, org_id, rows))
    assert counts["new"] == len(rows) == 163
    summary = await _summary(client, org_id)
    assert summary["revenue_cents"] == 9_799_500_00
    assert summary["expense_cents"] == 4_585_700_00
    assert summary["period"] == {"start": "2024-01", "end": "2024-12", "months": 12}


async def test_the_same_file_twice_changes_nothing(client):
    _, org_id, _ = await kullanici(client, "iki@example.com")
    await _append(client, await _analysed(client, org_id, _demo_rows()))
    second = await _append(client, await _analysed(client, org_id, _demo_rows()))
    assert second["new"] == 0
    assert second["already"] == 163
    assert (await _summary(client, org_id))["revenue_cents"] == 9_799_500_00


async def test_overlapping_periods_count_the_shared_months_once(client):
    _, org_id, _ = await kullanici(client, "ortusen@example.com")
    await _append(client, await _analysed(client, org_id, _demo_rows("01", "02", "03")))
    await _append(client, await _analysed(client, org_id, _demo_rows("02", "03", "04")))
    assert (await _summary(client, org_id))["revenue_cents"] == _file_revenue({"01", "02", "03", "04"})


async def test_two_identical_payments_in_one_file_are_two_payments(client):
    _, org_id, _ = await kullanici(client, "ozdes@example.com")
    row = {"amount_cents": 100_00, "type": "expense", "category": "other_expense",
           "description": "Kargo", "transaction_date": "2024-01-05"}
    counts = await _append(client, await _analysed(client, org_id, [row, dict(row)]))
    assert counts["new"] == 2
    assert (await _append(client, await _analysed(client, org_id, [row, dict(row)])))["new"] == 0
    assert (await _summary(client, org_id))["expense_cents"] == 200_00


async def test_the_same_money_described_differently_waits_for_a_person(client):
    """A bank line and an invoice for one payment: neither merged nor deleted."""
    _, org_id, _ = await kullanici(client, "benzer@example.com")
    base = {"amount_cents": 28_500_00, "type": "expense", "category": "rent", "transaction_date": "2024-01-08"}
    await _append(client, await _analysed(client, org_id, [{**base, "description": "Ofis kirası Ocak"}]))
    counts = await _append(client, await _analysed(client, org_id, [{**base, "description": "EFT Levent Gayrimenkul"}]))

    assert counts["possible_duplicate"] == 1
    summary = await _summary(client, org_id)
    assert summary["expense_cents"] == 28_500_00     # not counted until decided
    assert summary["possible_duplicates"] == 1


async def test_the_same_money_a_day_apart_also_waits(client):
    """Live: a January file's ₺285.000 sat a day from the ledger's and counted twice."""
    _, org_id, _ = await kullanici(client, "gun@example.com")
    base = {"amount_cents": 285_000_00, "type": "income", "category": "revenue"}
    await _append(client, await _analysed(client, org_id, [
        {**base, "description": "Ocak Lisans Geliri", "transaction_date": "2024-01-02"},
    ]))
    near = await _append(client, await _analysed(client, org_id, [
        {**base, "description": "Lisans Geliri - ABC Holding", "transaction_date": "2024-01-03"},
    ]))
    far = await _append(client, await _analysed(client, org_id, [
        {**base, "description": "Subat Lisans Geliri", "transaction_date": "2024-02-02"},
    ]))
    assert near["possible_duplicate"] == 1
    assert far["possible_duplicate"] == 0
    assert (await _summary(client, org_id))["revenue_cents"] == 570_000_00


async def test_the_summary_says_what_the_last_upload_added(client):
    _, org_id, _ = await kullanici(client, "son@example.com")
    await _append(client, await _analysed(client, org_id, _demo_rows("01")))
    await _append(client, await _analysed(client, org_id, _demo_rows("01")))
    last = (await _summary(client, org_id))["last_upload"]
    assert last["new"] == 0
    assert last["already"] == len(_demo_rows("01"))


async def test_different_amounts_on_a_day_are_not_suspicious(client):
    _, org_id, _ = await kullanici(client, "farkli@example.com")
    base = {"type": "expense", "category": "rent", "transaction_date": "2024-01-08"}
    await _append(client, await _analysed(client, org_id, [{**base, "amount_cents": 100_00, "description": "A"}]))
    counts = await _append(client, await _analysed(client, org_id, [{**base, "amount_cents": 200_00, "description": "B"}]))
    assert counts["possible_duplicate"] == 0


async def test_a_row_with_no_readable_date_stays_out_and_is_counted(client):
    """Its period is unknown: it would land in whatever month today is."""
    _, org_id, _ = await kullanici(client, "tarihsiz@example.com")
    counts = await _append(client, await _analysed(client, org_id, [
        {"amount_cents": 50_00, "type": "income", "category": "revenue", "description": "X", "transaction_date": None},
    ]))
    assert counts["no_date"] == 1
    assert counts["new"] == 0


async def test_rerunning_a_job_changes_a_category_not_the_money(client):
    _, org_id, _ = await kullanici(client, "duzelt@example.com")
    row = {"amount_cents": 40_00, "type": "expense", "category": "other_expense",
           "description": "AWS", "transaction_date": "2024-02-01"}
    await _append(client, await _analysed(client, org_id, [row]))
    again = await _append(client, await _analysed(client, org_id, [{**row, "category": "technology"}]))
    assert again["new"] == 0
    async with client._maker() as db:
        stored = (await db.execute(select(CanonicalTransaction))).scalars().all()
    assert [(r.category, r.amount_cents) for r in stored] == [("technology", 40_00)]


async def test_backfill_twice_writes_nothing_the_second_time(client):
    _, org_id, _ = await kullanici(client, "gecmis@example.com")
    await _analysed(client, org_id, _demo_rows("01"))
    await _analysed(client, org_id, _demo_rows("02"))
    async with client._maker() as db:
        first = await backfill(db)
    async with client._maker() as db:
        second = await backfill(db)
    assert first["jobs"] == 2
    assert first["new"] > 0
    assert second["new"] == 0


async def test_a_held_analysis_stays_out_until_it_is_approved(client):
    _, org_id, _ = await kullanici(client, "bekleyen@example.com")
    job_id = await _analysed(client, org_id, _demo_rows("01"))
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        job.status = JobStatus.AWAITING_REVIEW
        await db.commit()
    assert (await _append(client, job_id))["new"] == 0
    assert (await _summary(client, org_id))["revenue_cents"] == 0


async def test_a_finished_analysis_joins_the_ledger_through_the_worker(client, monkeypatch):
    import app.database as database
    from app.worker import continue_after_completion

    monkeypatch.setattr(database, "get_session_factory", lambda eng=None: client._maker)
    monkeypatch.setattr(database, "session_factory", lambda: client._maker)
    monkeypatch.setattr(database, "engine", lambda: None)
    monkeypatch.setattr("app.worker.spawn_auto_chain", lambda *a: None)
    monkeypatch.setattr("app.worker._job_side_effects", lambda *a, **k: None)

    _, org_id, _ = await kullanici(client, "isci@example.com")
    job_id = await _analysed(client, org_id, _demo_rows("01"))
    async with client._maker() as db:
        await continue_after_completion(job_id, org_id, {"dashboard_json": {"pnl": {}}}, db)

    assert (await _summary(client, org_id))["revenue_cents"] == _file_revenue({"01"})
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
    assert job.result_metadata["ledger"]["new"] > 0


async def test_a_demo_purge_leaves_no_ledger_behind(client):
    from app.services.demo_template import purge_demo_workspace

    _, org_id, _ = await kullanici(client, "misafir@example.com")
    await _append(client, await _analysed(client, org_id, _demo_rows("01")))
    async with client._maker() as db:
        await purge_demo_workspace(db, org_id)
        await db.commit()
        left = (await db.execute(select(CanonicalTransaction))).scalars().all()
    assert left == []


# ── API ───────────────────────────────────────────────────────────────────────


async def test_a_person_decides_a_possible_duplicate(client):
    headers, org_id, _ = await kullanici(client, "karar@example.com")
    base = {"amount_cents": 500_00, "type": "expense", "category": "rent", "transaction_date": "2024-03-01"}
    await _append(client, await _analysed(client, org_id, [{**base, "description": "Kira Mart"}]))
    await _append(client, await _analysed(client, org_id, [{**base, "description": "Havale Mart"}]))

    listed = (await client.get("/api/v1/ledger/possible-duplicates", headers=headers)).json()["data"]
    assert [r["description"] for r in listed] == ["Havale Mart"]
    assert listed[0]["matches"][0]["description"] == "Kira Mart"

    url = f"/api/v1/ledger/rows/{listed[0]['id']}/resolve"
    assert (await client.post(url, headers=headers, json={"action": "exclude"})).status_code == 200
    summary = (await client.get("/api/v1/ledger/summary", headers=headers)).json()["data"]
    assert summary["expense_cents"] == 500_00
    assert summary["possible_duplicates"] == 0
    assert (await client.post(url, headers=headers, json={"action": "keep"})).status_code == 409


async def test_keeping_a_possible_duplicate_counts_it(client):
    headers, org_id, _ = await kullanici(client, "tut@example.com")
    base = {"amount_cents": 500_00, "type": "expense", "category": "rent", "transaction_date": "2024-03-01"}
    await _append(client, await _analysed(client, org_id, [{**base, "description": "Kira Mart"}]))
    await _append(client, await _analysed(client, org_id, [{**base, "description": "Depo Kirası"}]))
    listed = (await client.get("/api/v1/ledger/possible-duplicates", headers=headers)).json()["data"]
    res = await client.post(f"/api/v1/ledger/rows/{listed[0]['id']}/resolve", headers=headers, json={"action": "keep"})
    assert res.status_code == 200, res.text
    assert (await client.get("/api/v1/ledger/summary", headers=headers)).json()["data"]["expense_cents"] == 1000_00


async def test_another_companys_row_cannot_be_decided(client):
    headers, org_id, _ = await kullanici(client, "bizim@example.com")
    other, _, _ = await kullanici(client, "onlar@example.com")
    base = {"amount_cents": 500_00, "type": "expense", "category": "rent", "transaction_date": "2024-03-01"}
    await _append(client, await _analysed(client, org_id, [{**base, "description": "A"}]))
    await _append(client, await _analysed(client, org_id, [{**base, "description": "B"}]))
    listed = (await client.get("/api/v1/ledger/possible-duplicates", headers=headers)).json()["data"]
    res = await client.post(f"/api/v1/ledger/rows/{listed[0]['id']}/resolve", headers=other, json={"action": "exclude"})
    assert res.status_code == 404
    assert (await client.get("/api/v1/ledger/possible-duplicates", headers=other)).json()["data"] == []
