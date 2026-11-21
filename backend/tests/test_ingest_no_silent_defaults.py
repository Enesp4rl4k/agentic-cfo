"""Missing or uncertain data is said and asked about, never filled with a default.

Audit 2026-11-21, path document -> transaction -> ledger:
  1. an extracted row with no confidence was given 0.8 and passed the gate unreviewed;
  2. a row with no currency became "USD" in the worker;
  3. one weak row held the whole upload;
  4. rows with no readable date were dropped from the ledger and only counted.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.agents.data_ingestion as di
import app.database as database
from app.agents.data_ingestion import run_data_ingestion
from app.core.row_confidence import label, needs_review, parse_confidence
from app.services.ingest.hold import resolve_currency, split_uncertain
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici


def _row(**kw: Any) -> dict[str, Any]:
    return {
        "amount_cents": 150000, "currency": "TRY", "type": "expense", "category": "utilities",
        "description": "Elektrik", "transaction_date": "2026-03-15", "confidence": 0.95, **kw,
    }


# ── confidence is a score or unknown, nothing in between ─────────────────────

def test_unknown_confidence_is_a_state_not_a_number():
    assert parse_confidence(None) is None
    assert parse_confidence("") is None
    assert parse_confidence("abc") is None
    assert parse_confidence(95) is None          # not guessed to be a percentage
    assert parse_confidence(True) is None
    assert parse_confidence(0.0) == 0.0          # a measured zero is not unknown
    assert parse_confidence("0.9") == 0.9


def test_unknown_always_needs_review_and_never_reads_as_a_percentage():
    assert needs_review(None) is True
    assert needs_review(0.79) is True
    assert needs_review(0.80) is False
    assert "%" not in label(None)
    assert label(0.8) == "%80"


# ── 3. only uncertain rows wait; a document is never split ───────────────────

def test_only_uncertain_rows_are_held():
    rows = [_row(), _row(confidence=None), _row(confidence=0.5), _row(currency=None), _row(type=None)]
    accepted, held = split_uncertain(rows)
    assert len(accepted) == 1
    assert [h["hold_reasons"] for h in held] == [
        ["confidence_unknown"], ["confidence_low"], ["currency_unknown"], ["direction_unknown"],
    ]


def test_the_rows_of_one_document_move_together():
    rows = [
        _row(document_id="F1", confidence=0.95),
        _row(document_id="F1", confidence=None),
        _row(document_id="F2", confidence=0.95),
    ]
    accepted, held = split_uncertain(rows)
    assert [r["document_id"] for r in accepted] == ["F2"]
    assert {h["document_id"] for h in held} == {"F1"}
    assert "document_held_together" in held[0]["hold_reasons"] + held[1]["hold_reasons"]


# ── 2. currency: stated, else the organisation's (marked), else held ─────────

def test_currency_stated_by_the_document_is_not_an_assumption():
    rows = [_row(currency=None)]
    resolve_currency(rows, "Hesap hareketleri USD hesabi", "TRY")
    assert rows[0]["currency"] == "USD" and "currency_assumed" not in rows[0]


def test_currency_falls_back_to_the_base_currency_and_says_so():
    rows = [_row(currency=None)]
    resolve_currency(rows, "Fatura odemesi 1500", "TRY")
    assert rows[0]["currency"] == "TRY" and rows[0]["currency_assumed"] is True


def test_currency_with_nothing_to_go_on_holds_the_row():
    rows = [_row(currency=None)]
    resolve_currency(rows, "Fatura odemesi 1500", None)
    accepted, held = split_uncertain(rows)
    assert not accepted and held[0]["hold_reasons"] == ["currency_unknown"]


def test_a_turkish_looking_document_has_not_stated_a_currency():
    from app.services.ingest.cells import _detect_currency

    assert _detect_currency("HESAP BANKA FATURA TARİH TUTAR") is None
    assert _detect_currency("Tutar (₺)") == "TRY"


# ── 1. the audit scenario: an extracted row without confidence is held ───────

@pytest.fixture
def llm_file(tmp_path: Path) -> str:
    f = tmp_path / "belge.txt"
    f.write_text("Fatura odemesi 1500 TL " + chr(10), encoding="utf-8")   # no delimiter: no table, no bank
    return str(f)


async def _ingest(monkeypatch, llm_file: str, rows: list[dict[str, Any]], base: str | None = "TRY"):
    async def fake_llm(raw_text: str, settings: Any) -> list[dict[str, Any]]:
        return rows

    async def fake_base(org_id: str | None) -> str | None:
        return base

    monkeypatch.setattr(di, "_extract_transactions_with_llm", fake_llm)
    monkeypatch.setattr(di, "_read_csv", lambda p: Path(p).read_text(encoding="utf-8"))
    monkeypatch.setattr("app.services.org_identity.own_base_currency", fake_base)
    return await run_data_ingestion({"file_path": llm_file, "file_type": "csv", "org_id": "o1"}, None)  # type: ignore[arg-type]


async def test_extracted_row_without_confidence_is_held_for_review(monkeypatch, llm_file):
    out = await _ingest(monkeypatch, llm_file, [
        {"date": "15.03.2026", "amount": 1500, "type": "expense", "description": "A", "confidence": 0.95},
        {"date": "16.03.2026", "amount": 700, "type": "expense", "description": "B"},   # unscored
    ])
    assert out.ok
    kept, held = out.patch["transactions"], out.patch["held_transactions"]
    assert [t["description"] for t in kept] == ["A"]
    assert [t["description"] for t in held] == ["B"]
    assert held[0]["confidence"] is None and held[0]["hold_reasons"] == ["confidence_unknown"]
    # The upload is not held as a whole: one row proceeds, one waits.
    assert out.needs_review is False
    assert out.detail.startswith("1 kayıt işlendi, 1 kayıt incelemenizi bekliyor")


async def test_every_row_unscored_holds_the_upload_and_analyses_nothing(monkeypatch, llm_file):
    out = await _ingest(monkeypatch, llm_file, [
        {"date": "15.03.2026", "amount": 1500, "type": "expense", "description": "A"},
    ])
    assert out.needs_review is True and out.patch["transactions"] == []
    assert out.detail.startswith("0 kayıt işlendi, 1 kayıt incelemenizi bekliyor")


async def test_llm_row_currency_comes_from_the_document_or_the_base_and_is_marked(monkeypatch, llm_file):
    out = await _ingest(monkeypatch, llm_file, [
        {"date": "15.03.2026", "amount": 1500, "type": "expense", "description": "A", "confidence": 0.9},
    ])
    row = out.patch["transactions"][0]
    assert row["currency"] == "TRY" and "currency_assumed" not in row   # "TL" is in the document


async def test_llm_row_without_direction_is_not_booked_as_an_expense(monkeypatch, llm_file):
    out = await _ingest(monkeypatch, llm_file, [
        {"date": "15.03.2026", "amount": 1500, "description": "A", "confidence": 0.9},
        {"date": "15.03.2026", "amount": 10, "type": "expense", "description": "B", "confidence": 0.9},
    ])
    assert [h["hold_reasons"] for h in out.patch["held_transactions"]] == [["direction_unknown"]]


# ── end to end: the worker, the status, the radar, the release ───────────────

@pytest_asyncio.fixture
async def ortam(monkeypatch, tmp_path):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        from app.services import review_continuation as rc

        async def devam_yok(job_id: str) -> str:
            return "skipped"

        monkeypatch.setattr(rc, "devami_baslat", devam_yok)
        yield c, tmp_path
        await arka_plan_bitsin()


async def _run_job(client, tmp_path, monkeypatch, rows, email, content="Fatura odemesi 1500 TL " + chr(10)):
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import run_cfo_analysis

    headers, org_id, _ = await kullanici(client, email)
    f = tmp_path / "belge.csv"
    f.write_text(content, encoding="utf-8")

    async def fake_llm(raw_text: str, settings: Any) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(di, "_extract_transactions_with_llm", fake_llm)
    async with client._maker() as db:
        job = AnalysisJob(filename="belge.csv", file_path=str(f), file_type="csv",
                          org_id=org_id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = job.id
    out = await run_cfo_analysis({}, job_id)
    return headers, org_id, job_id, out


async def test_a_weak_row_no_longer_holds_the_upload_and_the_counts_say_so(ortam, monkeypatch):
    from app.models.analysis_job import AnalysisJob
    from app.models.held_transaction import HeldTransaction
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    rows = [
        {"date": "15.03.2026", "amount": 1500, "type": "expense", "description": "A", "confidence": 0.95},
        {"date": "16.03.2026", "amount": 700, "type": "income", "description": "B"},
    ]
    headers, _org_id, job_id, out = await _run_job(client, tmp_path, monkeypatch, rows, "a@x.com")
    assert out.get("ok") is True, out

    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        # Ingestion itself is not what holds the run (a 2-row file leaves later steps unsure).
        ingestion = next(lg for lg in job.logs if lg["step"] == "data_ingestion")
        assert ingestion["confidence"] == pytest.approx(0.95)
        assert ingestion["detail"].startswith("1 kayıt işlendi, 1 kayıt incelemenizi bekliyor")
        txs = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars().all()
        held = (await db.execute(select(HeldTransaction).where(HeldTransaction.job_id == job_id))).scalars().all()
    assert len(txs) == 1 and len(held) == 1
    assert held[0].payload["description"] == "B" and held[0].status == "pending"
    assert float(txs[0].confidence) == pytest.approx(0.95)

    status = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    assert status["ingest"]["processed"] == 1 and status["ingest"]["held"] == 1
    assert "1 kayıt işlendi; 1 kayıt incelemenizi bekliyor" in status["ingest"]["summary"]


async def test_undated_rows_are_counted_with_the_reason_and_stay_listed(ortam, monkeypatch):
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    nl = chr(10)
    lines = ["tarih,aciklama,tutar"] + [f"{i:02d}.03.2026,Gider {i},{100 + i}" for i in range(1, 10)]
    lines.append("belli degil,Tarihsiz gider,50")
    headers, _org_id, job_id, _ = await _run_job(
        client, tmp_path, monkeypatch, [], "u@x.com", content=nl.join(lines) + nl
    )
    status = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    assert status["ingest"]["undated"] == 1
    assert "tarihi okunamadığı için deftere ve toplamlara alınmadı" in status["ingest"]["summary"]
    async with client._maker() as db:
        undated = [t for t in (await db.execute(
            select(Transaction).where(Transaction.job_id == job_id))).scalars() if t.date_is_estimated]
    assert [t.description for t in undated] == ["Tarihsiz gider"]    # listed for review, not lost


async def test_held_rows_are_listed_without_a_made_up_confidence_and_can_be_released(ortam, monkeypatch):
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    rows = [
        {"date": "15.03.2026", "amount": 1500, "type": "expense", "description": "A", "confidence": 0.95},
        {"date": "16.03.2026", "amount": 700, "type": "income", "description": "B"},
    ]
    headers, _org_id, job_id, _ = await _run_job(client, tmp_path, monkeypatch, rows, "b@x.com")

    listed = (await client.get(f"/api/v1/analysis/{job_id}/held", headers=headers)).json()["data"]
    assert listed["count"] == 1
    row = listed["rows"][0]
    assert row["confidence"] is None and "%" not in row["confidence_label"]

    # The radar says M rows are not in it.
    radar = (await client.get("/api/v1/ledger/cash-radar", headers=headers)).json()["data"]
    assert any("1 kayıt" in line for line in radar["not_included"])

    done = (await client.post(f"/api/v1/analysis/{job_id}/held/release", json={}, headers=headers)).json()["data"]
    assert done["resolved"] == 1 and done["still_waiting"] == 0
    async with client._maker() as db:
        txs = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars().all()
    released = next(t for t in txs if t.description == "B")
    assert released.confidence is None                  # still unknown: a human accepted it
    radar = (await client.get("/api/v1/ledger/cash-radar", headers=headers)).json()["data"]
    assert not any("kayıt" in line and "İncelemenizi" in line for line in radar["not_included"])


async def test_a_row_without_currency_is_not_given_usd(ortam, monkeypatch):
    from app.models.held_transaction import HeldTransaction
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    # Nothing states a currency and the organisation has no base to assume.
    async def no_base(org_id: str | None) -> str | None:
        return None

    monkeypatch.setattr("app.services.org_identity.own_base_currency", no_base)
    monkeypatch.setattr(di, "_read_csv", lambda p: "Fatura odemesi 1500")
    rows = [
        {"date": "15.03.2026", "amount": 1500, "type": "expense", "description": "A", "confidence": 0.95},
        {"date": "16.03.2026", "amount": 700, "type": "income", "description": "B", "confidence": 0.95,
         "currency": "EUR"},
    ]
    _headers, _org_id, job_id, _out = await _run_job(client, tmp_path, monkeypatch, rows, "c@x.com")
    async with client._maker() as db:
        txs = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars().all()
        held = (await db.execute(select(HeldTransaction).where(HeldTransaction.job_id == job_id))).scalars().all()
    assert [(t.description, t.currency) for t in txs] == [("B", "EUR")]
    assert held[0].payload["hold_reasons"] == ["currency_unknown"]
    assert "USD" not in {t.currency for t in txs}


async def test_base_currency_is_assumed_and_marked(ortam, monkeypatch):
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    monkeypatch.setattr(di, "_read_csv", lambda p: "Fatura odemesi 1500")
    rows = [{"date": "15.03.2026", "amount": 1500, "type": "expense", "description": "A", "confidence": 0.95}]
    headers, _org_id, job_id, _ = await _run_job(client, tmp_path, monkeypatch, rows, "d@x.com")
    async with client._maker() as db:
        tx = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalar_one()
    assert tx.currency_assumed is True and tx.currency == "USD"   # the org row's own default, said out loud
    listed = (await client.get(f"/api/v1/analysis/{job_id}/transactions", headers=headers)).json()["data"]
    assert listed["transactions"][0]["currency_assumed"] is True
    status = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    assert status["ingest"]["currency_assumed"] == 1


# ── a measured zero is not "unset" ───────────────────────────────────────────

async def test_zero_confidence_is_reported_as_zero_not_unknown(ortam):
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.transaction import Transaction

    client, _ = ortam
    headers, org_id, _ = await kullanici(client, "z@x.com")
    async with client._maker() as db:
        job = AnalysisJob(filename="z.csv", file_path="z", file_type="csv", org_id=org_id,
                          status=JobStatus.COMPLETED, min_confidence=0)
        db.add(job)
        await db.flush()
        db.add(Transaction(job_id=job.id, amount_kurus=100, currency="TRY", type="expense",
                           category="other_expense", transaction_date=__import__("datetime").datetime.now(),
                           confidence=0))
        await db.commit()
        job_id = job.id
    status = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    assert status["min_confidence"] == 0.0
    tx = (await client.get(f"/api/v1/analysis/{job_id}/transactions", headers=headers)).json()["data"]
    assert tx["transactions"][0]["confidence"] == 0.0


# ── the parsers feed the same rule ───────────────────────────────────────────

def test_parser_rows_keep_unknown_as_unknown():
    from datetime import UTC, datetime

    from app.parsers.base import ParsedTransaction
    from app.services.ingest.rows import _statement_to_transactions

    tx = ParsedTransaction(date=datetime.now(UTC), description="llm", amount_cents=100,
                           tx_type="", currency="", confidence=None, date_estimated=True)

    class _S:  # the converter reads only `.transactions`
        transactions = [tx]

    row = _statement_to_transactions(_S())[0]  # type: ignore[arg-type]
    assert row["confidence"] is None
    assert row["currency"] is None
    assert row["transaction_date"] is None          # a placeholder date is not "today"
    accepted, held = split_uncertain([row])
    assert not accepted
    assert set(held[0]["hold_reasons"]) == {"confidence_unknown", "currency_unknown", "direction_unknown"}


def test_rows_in_another_currency_are_never_summed_with_the_main_one():
    rows = [_row(), _row(), _row(currency="USD")]
    accepted, held = split_uncertain(rows)
    assert len(accepted) == 2 and held[0]["hold_reasons"] == ["currency_differs"]
