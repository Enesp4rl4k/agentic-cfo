"""Missing or uncertain data is said and asked about, never filled with a default.

Audit 2026-11-21, path document -> transaction -> ledger:
  1. an extracted row with no confidence was given 0.8 and passed the gate unreviewed;
  2. a row with no currency became "USD" in the worker;
  3. one weak row held the whole upload;
  4. rows with no readable date were dropped from the ledger and only counted.
Review of the first fix: a stored base currency is only the column default, so it
may not stand in for a missing one; a person must be able to act on held rows.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.agents.data_ingestion as di
import app.database as database
from app.agents.data_ingestion import run_data_ingestion
from app.core.row_confidence import label, needs_review, parse_confidence
from app.services.ingest.hold import resolve_currency, split_uncertain
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici

# The currency rule is tested against the real organisation lookup, not a TRY stand-in.
pytestmark = pytest.mark.real_currency

NL = chr(10)


def _row(**kw: Any) -> dict[str, Any]:
    return {
        "amount_cents": 150000, "currency": "TRY", "type": "expense", "category": "utilities",
        "description": "Elektrik", "transaction_date": "2026-03-15", "confidence": 0.95, **kw,
    }


def _llm(date: str = "15.03.2026", amount: Any = 1500, **kw: Any) -> dict[str, Any]:
    return {"date": date, "amount": amount, "type": "expense", "description": "A", "confidence": 0.95, **kw}


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


# ── only uncertain rows wait; a document is never split ──────────────────────

def test_only_uncertain_rows_are_held_each_with_its_reason():
    rows = [
        _row(), _row(confidence=None), _row(confidence=0.5), _row(currency=None), _row(type=None),
        _row(amount_cents=None), _row(transaction_date=None),
    ]
    accepted, held = split_uncertain(rows)
    assert len(accepted) == 1
    assert [h["hold_reasons"] for h in held] == [
        ["confidence_unknown"], ["confidence_low"], ["currency_unknown"], ["direction_unknown"],
        ["amount_unreadable"], ["date_unreadable"],
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


def test_a_stated_foreign_currency_is_known_not_uncertain():
    """A row that says USD is USD: admitted with its own currency, not held for differing."""
    accepted, held = split_uncertain([_row(), _row(), _row(currency="USD")])
    assert not held and {r["currency"] for r in accepted} == {"TRY", "USD"}


# ── currency: stated, else the CONFIRMED base, else held ─────────────────────

def test_currency_stated_by_the_document_is_not_an_assumption():
    rows = [_row(currency=None)]
    resolve_currency(rows, "Hesap hareketleri USD hesabi", None)
    assert rows[0]["currency"] == "USD" and "currency_assumed" not in rows[0]


def test_a_confirmed_base_currency_fills_in_and_says_so():
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


# ── the table path never guesses a direction (the resolver is tested in test_statement_direction) ──

def _csv(text: str):
    from app.services.ingest.rows import _try_parse_csv

    return _try_parse_csv(text) or []


def test_csv_direction_comes_from_the_sign_when_a_balance_chain_verifies_it():
    rows = _csv(NL.join(["Tarih,Açıklama,Tutar,Bakiye", '01.03.2026,Satış,"1.000,00","11.000,00"',
                         '02.03.2026,Kira,"-500,00","10.500,00"']))
    assert [r["type"] for r in rows] == ["income", "expense"]
    assert all(r["confidence"] == 0.95 for r in rows)      # derived by a rule: not certain


def test_csv_sign_without_a_balance_chain_is_asked_not_assumed():
    rows = _csv(NL.join(["Tarih,Açıklama,Tutar", '01.03.2026,Satış,"1.000,00"', '02.03.2026,Kira,"-500,00"']))
    assert [r["type"] for r in rows] == [None, None]
    assert {r["direction_file"]["reason"] for r in rows} == {"sign_unconfirmed"}


def test_csv_with_unambiguous_debit_and_credit_columns_reads_the_column():
    rows = _csv(NL.join(["Tarih,Açıklama,Ödeme,Tahsilat", "01.03.2026,Kira,500,", "02.03.2026,Satış,,900"]))
    assert [r["type"] for r in rows] == ["expense", "income"]


def test_csv_with_borc_alacak_and_no_balance_is_asked_not_booked_as_the_customers_view():
    rows = _csv(NL.join(["Tarih,Açıklama,Borç,Alacak", "01.03.2026,Kira,500,", "02.03.2026,Satış,,900"]))
    assert [r["type"] for r in rows] == [None, None]
    assert {r["direction_file"]["reason"] for r in rows} == {"convention_unverified"}


def test_csv_with_one_unsigned_column_cannot_tell_and_says_so():
    rows = _csv(NL.join(["Tarih,Açıklama,Tutar", "01.03.2026,Bir,100", "02.03.2026,İki,200"]))
    assert [r["type"] for r in rows] == [None, None]       # never income by default
    assert all(r["direction_file"]["reason"] == "sign_unconfirmed" for r in rows)
    accepted, held = split_uncertain([{**r, "currency": "TRY"} for r in rows])
    assert not accepted and held[0]["hold_reasons"] == ["direction_file_unknown"]


def test_csv_type_column_still_decides():
    rows = _csv(NL.join(["Tarih,Açıklama,Tutar,Tür", "01.03.2026,Bir,100,gider", "02.03.2026,İki,200,gelir"]))
    assert [r["type"] for r in rows] == ["expense", "income"]


def test_parser_rows_keep_unknown_as_unknown():
    from datetime import UTC, datetime

    from app.parsers.base import ParsedTransaction
    from app.services.ingest.rows import _statement_to_transactions

    tx = ParsedTransaction(date=datetime.now(UTC), description="llm", amount_cents=100,
                           tx_type="", currency="", confidence=None, date_estimated=True)

    class _S:  # the converter reads only `.transactions`
        transactions = [tx]

    row = _statement_to_transactions(_S())[0]  # type: ignore[arg-type]
    assert row["confidence"] is None and row["currency"] is None
    assert row["transaction_date"] is None          # a placeholder date is not "today"
    accepted, held = split_uncertain([row])
    assert not accepted
    assert set(held[0]["hold_reasons"]) == {
        "confidence_unknown", "currency_unknown", "direction_unknown", "date_unreadable",
    }


# ── 1. the audit scenario: an extracted row without confidence is held ───────

@pytest.fixture
def llm_file(tmp_path: Path) -> str:
    f = tmp_path / "belge.txt"
    f.write_text("Fatura odemesi 1500 TL " + NL, encoding="utf-8")   # no delimiter: no table, no bank
    return str(f)


async def _ingest(monkeypatch, llm_file: str, rows: list[dict[str, Any]], base: str | None = None):
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
        _llm(description="A"),
        {"date": "16.03.2026", "amount": 700, "type": "expense", "description": "B"},   # unscored
    ])
    assert out.ok
    kept, held = out.patch["transactions"], out.patch["held_transactions"]
    assert [t["description"] for t in kept] == ["A"]
    assert [t["description"] for t in held] == ["B"]
    assert held[0]["confidence"] is None and held[0]["hold_reasons"] == ["confidence_unknown"]
    assert out.needs_review is False        # one row proceeds, one waits
    assert out.detail.startswith("1 kayıt işlendi, 1 kayıt incelemenizi bekliyor")


async def test_every_row_unscored_holds_the_upload_and_analyses_nothing(monkeypatch, llm_file):
    out = await _ingest(monkeypatch, llm_file, [
        {"date": "15.03.2026", "amount": 1500, "type": "expense", "description": "A"},
    ])
    assert out.needs_review is True and out.patch["transactions"] == []
    assert out.detail.startswith("0 kayıt işlendi, 1 kayıt incelemenizi bekliyor")


async def test_row_currency_comes_from_the_document(monkeypatch, llm_file):
    out = await _ingest(monkeypatch, llm_file, [_llm()])
    row = out.patch["transactions"][0]
    assert row["currency"] == "TRY" and "currency_assumed" not in row   # "TL" is in the document


async def test_row_without_direction_is_not_booked_as_an_expense(monkeypatch, llm_file):
    bad = _llm()
    del bad["type"]
    out = await _ingest(monkeypatch, llm_file, [bad, _llm(description="B")])
    assert [h["hold_reasons"] for h in out.patch["held_transactions"]] == [["direction_unknown"]]


async def test_undated_and_amountless_rows_wait_with_their_reason(monkeypatch, llm_file):
    out = await _ingest(monkeypatch, llm_file, [
        _llm(), _llm(date="", description="C"), _llm(amount="", description="D"),
    ])
    held = {h["description"]: h["hold_reasons"] for h in out.patch["held_transactions"]}
    assert held["C"] == ["confidence_low", "date_unreadable"] or "date_unreadable" in held["C"]
    assert "amount_unreadable" in held["D"]
    assert [t["description"] for t in out.patch["transactions"]] == ["A"]


# ── end to end: an organisation that never set its currency ──────────────────

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


async def _upload(client, tmp_path, monkeypatch, rows, org_id, *, content="Fatura odemesi 1500" + NL, name="belge.csv"):
    """One upload by `org_id`; the file states no currency unless `content` does."""
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import run_cfo_analysis

    f = tmp_path / name
    f.write_text(content, encoding="utf-8")

    async def fake_llm(raw_text: str, settings: Any) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(di, "_extract_transactions_with_llm", fake_llm)
    async with client._maker() as db:
        job = AnalysisJob(filename=name, file_path=str(f), file_type="csv",
                          org_id=org_id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = job.id
    out = await run_cfo_analysis({}, job_id)
    return job_id, out


async def _count(client, model, **where) -> int:
    async with client._maker() as db:
        stmt = select(func.count()).select_from(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        return int((await db.execute(stmt)).scalar() or 0)


GOOD = [_llm(description="A"), _llm(date="16.03.2026", amount=700, description="B", type="income")]


async def test_default_usd_organisation_uploading_a_currencyless_file_holds_every_row(ortam, monkeypatch):
    """The reviewed blocker: nothing is stamped USD, nothing reaches the ledger."""
    from app.models.canonical_transaction import CanonicalTransaction
    from app.models.held_transaction import HeldTransaction
    from app.models.organization import Organization
    from app.models.transaction import Transaction
    from app.services.ledger import append_job

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "usd@x.com")
    async with client._maker() as db:
        org = await db.get(Organization, org_id)
        assert org.base_currency == "USD" and org.base_currency_confirmed_at is None   # the column default
    job_id, out = await _upload(client, tmp_path, monkeypatch, GOOD, org_id)
    assert out.get("ok") is True, out

    assert await _count(client, Transaction, job_id=job_id) == 0
    assert await _count(client, HeldTransaction, job_id=job_id) == 2
    async with client._maker() as db:
        reasons = [h.payload["hold_reasons"] for h in (await db.execute(select(HeldTransaction))).scalars()]
    assert reasons == [["currency_unknown"], ["currency_unknown"]]

    # Even if the job completes and the ledger reads it, there is nothing of these rows to read.
    from app.models.analysis_job import AnalysisJob, JobStatus

    async with client._maker() as db:
        (await db.get(AnalysisJob, job_id)).status = JobStatus.COMPLETED
        await db.commit()
        await append_job(db, job_id)
    assert await _count(client, CanonicalTransaction, org_id=org_id) == 0

    status = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    assert status["ingest"]["processed"] == 0 and status["ingest"]["held"] == 2
    assert "şirketin para birimini onaylarsanız bu kayıtlar serbest bırakılır" in status["ingest"]["summary"]


async def test_confirming_the_company_currency_releases_the_rows_held_for_it(ortam, monkeypatch):
    from app.models.decision import Decision
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "ok@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, GOOD, org_id)
    state = (await client.get("/api/v1/org/base-currency", headers=headers)).json()["data"]
    assert state == {"currency": None, "confirmed": False, "waiting_for_currency": 2}

    done = await client.post("/api/v1/org/base-currency", json={"currency": "try"}, headers=headers)
    assert done.status_code == 200, done.text
    assert done.json()["data"]["released"]["resolved"] == 2, done.json()

    async with client._maker() as db:
        txs = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars().all()
        kinds = [d.kind for d in (await db.execute(select(Decision))).scalars()]
    assert {(t.currency, t.currency_assumed) for t in txs} == {("TRY", True)}   # visible, never silent
    assert kinds.count("held_row_resolution") == 2 and kinds.count("base_currency_confirmation") == 1


async def test_after_confirmation_the_next_currencyless_upload_is_read_in_it_and_marked(ortam, monkeypatch):
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "next@x.com")
    await client.post("/api/v1/org/base-currency", json={"currency": "TRY"}, headers=headers)
    job_id, _ = await _upload(client, tmp_path, monkeypatch, GOOD, org_id)
    async with client._maker() as db:
        txs = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars().all()
    assert len(txs) == 2 and all(t.currency == "TRY" and t.currency_assumed for t in txs)
    listed = (await client.get(f"/api/v1/analysis/{job_id}/transactions", headers=headers)).json()["data"]
    assert all(t["currency_assumed"] for t in listed["transactions"])


async def test_only_a_decider_confirms_the_company_currency(ortam):
    client, _ = ortam
    headers, _, _ = await kullanici(client, "viewer@x.com", role="viewer")
    res = await client.post("/api/v1/org/base-currency", json={"currency": "TRY"}, headers=headers)
    assert res.status_code == 403


async def test_a_row_with_another_row_question_keeps_waiting_after_confirmation(ortam, monkeypatch):
    from app.models.held_transaction import HeldTransaction

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "two@x.com")
    rows = [_llm(description="A"), {"date": "16.03.2026", "amount": 7, "type": "expense", "description": "U"}]
    await _upload(client, tmp_path, monkeypatch, rows, org_id)
    res = await client.post("/api/v1/org/base-currency", json={"currency": "TRY"}, headers=headers)
    assert res.json()["data"]["released"]["resolved"] == 1          # only the row asked about currency alone
    async with client._maker() as db:
        left = (await db.execute(select(HeldTransaction).where(HeldTransaction.status == "pending"))).scalars().all()
    assert [h.payload["description"] for h in left] == ["U"]
    assert left[0].payload["hold_reasons"] == ["confidence_unknown"] and left[0].payload["currency"] == "TRY"


async def test_a_stated_foreign_currency_row_is_admitted_with_its_own_currency(ortam, monkeypatch):
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    _headers, org_id, _ = await kullanici(client, "fx@x.com")
    rows = [_llm(description="A", currency="TRY"), _llm(description="B", currency="USD")]
    job_id, _ = await _upload(client, tmp_path, monkeypatch, rows, org_id)
    async with client._maker() as db:
        txs = (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars().all()
    assert {(t.description, t.currency, t.currency_assumed) for t in txs} == {("A", "TRY", False), ("B", "USD", False)}


# ── a person acts on held rows ───────────────────────────────────────────────

UNSURE = [
    _llm(description="A", currency="TRY"),
    {"date": "16.03.2026", "amount": 700, "type": "income", "description": "B", "currency": "TRY"},   # unscored
    {"date": "", "amount": 300, "type": "expense", "description": "C", "currency": "TRY", "confidence": 0.9},
]


async def _held(client, headers, job_id=None) -> dict[str, dict[str, Any]]:
    url = "/api/v1/held-rows" + (f"?job_id={job_id}" if job_id else "")
    rows = (await client.get(url, headers=headers)).json()["data"]["rows"]
    return {r["description"]: r for r in rows}


async def test_held_rows_say_where_they_came_from_and_why_in_plain_turkish(ortam, monkeypatch):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "list@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, UNSURE, org_id, name="mart.csv")
    held = await _held(client, headers, job_id)
    assert set(held) == {"B", "C"}
    assert held["B"]["source"]["filename"] == "mart.csv"
    assert held["B"]["reason_labels"] == ["güven bilinmiyor"] and held["B"]["confidence"] is None
    assert "%" not in held["B"]["confidence_label"]
    assert "tarih okunamadı" in held["C"]["reason_labels"]       # undated: held, in no total
    status = (await client.get(f"/api/v1/analysis/{job_id}", headers=headers)).json()["data"]
    assert status["ingest"]["processed"] == 1 and status["ingest"]["held"] == 2


async def test_release_as_is_correct_and_release_and_reject_are_recorded_decisions(ortam, monkeypatch):
    from app.models.decision import Decision
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    headers, org_id, user_id = await kullanici(client, "act@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, UNSURE, org_id)
    held = await _held(client, headers)

    # C has no date: it cannot be released as it is.
    blocked = (await client.post("/api/v1/held-rows/release", json={"ids": [held["C"]["id"]]}, headers=headers)).json()["data"]
    assert blocked["resolved"] == 0 and blocked["blocked"][0]["missing"] == ["transaction_date"]
    # B as it is; C corrected.
    ok = await client.post("/api/v1/held-rows/release", json={
        "ids": [held["B"]["id"], held["C"]["id"]],
        "corrections": {held["C"]["id"]: {"transaction_date": "2026-03-17"}},
    }, headers=headers)
    assert ok.json()["data"]["resolved"] == 2
    async with client._maker() as db:
        txs = {t.description: t for t in (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars()}
        decisions = list((await db.execute(select(Decision).order_by(Decision.decided_at))).scalars())
    assert set(txs) == {"A", "B", "C"} and txs["B"].confidence is None and txs["C"].date_is_estimated is False
    outcomes = sorted(d.outcome for d in decisions)
    assert outcomes == ["corrected_released", "released"]
    corrected = next(d for d in decisions if d.outcome == "corrected_released")
    assert corrected.decided_by == user_id and corrected.before["transaction_date"] is None
    assert corrected.after["transaction_date"] == "2026-03-17"


async def test_reject_keeps_the_row_out_and_records_it(ortam, monkeypatch):
    from app.models.decision import Decision
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "rej@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, UNSURE, org_id)
    held = await _held(client, headers)
    res = await client.post("/api/v1/held-rows/reject", json={"ids": [held["B"]["id"]]}, headers=headers)
    assert res.json()["data"]["resolved"] == 1
    assert await _count(client, Transaction, job_id=job_id) == 1
    async with client._maker() as db:
        assert [d.outcome for d in (await db.execute(select(Decision))).scalars()] == ["rejected"]


async def test_two_clicks_resolve_a_row_once(ortam, monkeypatch):
    from app.models.decision import Decision
    from app.models.transaction import Transaction

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "twice@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, UNSURE, org_id)
    held = await _held(client, headers)
    body = {"ids": [held["B"]["id"]]}
    first = (await client.post("/api/v1/held-rows/release", json=body, headers=headers)).json()["data"]
    second = (await client.post("/api/v1/held-rows/release", json=body, headers=headers)).json()["data"]
    assert first["resolved"] == 1 and second["resolved"] == 0
    assert await _count(client, Transaction, job_id=job_id) == 2
    assert await _count(client, Decision) == 1


async def test_bulk_release_by_reason_and_document(ortam, monkeypatch):
    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "bulk@x.com")
    rows = [
        {"date": "16.03.2026", "amount": 7, "type": "expense", "description": f"U{i}", "currency": "TRY"}
        for i in range(3)
    ]
    await _upload(client, tmp_path, monkeypatch, [*rows, _llm(description="A", currency="TRY")], org_id)
    res = await client.post("/api/v1/held-rows/release", json={"reason": "confidence_unknown"}, headers=headers)
    assert res.json()["data"]["resolved"] == 3 and res.json()["data"]["still_waiting"] == 0


async def test_another_organisations_rows_are_invisible_and_untouchable(ortam, monkeypatch):
    client, tmp_path = ortam
    h1, org1, _ = await kullanici(client, "o1@x.com")
    h2, _, _ = await kullanici(client, "o2@x.com")
    await _upload(client, tmp_path, monkeypatch, UNSURE, org1)
    held = await _held(client, h1)
    assert (await client.get("/api/v1/held-rows", headers=h2)).json()["data"]["count"] == 0
    for action in ("release", "reject"):
        res = await client.post(f"/api/v1/held-rows/{action}", json={"ids": [held["B"]["id"]]}, headers=h2)
        assert res.status_code == 404
    # a made-up id is the same answer as another organisation's: 404, never "resolved: 0"
    res = await client.post("/api/v1/held-rows/release", json={"ids": ["no-such-row"]}, headers=h2)
    assert res.status_code == 404
    assert (await client.get("/api/v1/held-rows", headers=h1)).json()["data"]["count"] == 2


# ── a question is asked once ─────────────────────────────────────────────────

async def test_uploading_the_same_file_again_does_not_duplicate_the_pending_rows(ortam, monkeypatch):
    from app.models.held_transaction import HeldTransaction

    client, tmp_path = ortam
    _headers, org_id, _ = await kullanici(client, "again@x.com")
    await _upload(client, tmp_path, monkeypatch, UNSURE, org_id)
    await _upload(client, tmp_path, monkeypatch, UNSURE, org_id)
    assert await _count(client, HeldTransaction, status="pending") == 2


async def test_a_rerun_does_not_ask_again_and_keeps_the_trail(ortam, monkeypatch):
    from app.models.decision import Decision
    from app.models.held_transaction import HeldTransaction
    from app.models.transaction import Transaction
    from app.worker import run_cfo_analysis

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "rerun@x.com")
    job_id, _ = await _upload(client, tmp_path, monkeypatch, UNSURE, org_id)
    held = await _held(client, headers)
    await client.post("/api/v1/held-rows/release", json={"ids": [held["B"]["id"]]}, headers=headers)
    await client.post("/api/v1/held-rows/reject", json={"ids": [held["C"]["id"]]}, headers=headers)

    from app.models.analysis_job import AnalysisJob, JobStatus

    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        job.status = JobStatus.PENDING
        await db.commit()
    await run_cfo_analysis({}, job_id)

    assert await _count(client, HeldTransaction, status="pending") == 0       # not re-asked
    assert await _count(client, HeldTransaction, status="rejected") == 1      # the trail stays
    assert await _count(client, HeldTransaction, status="released") == 1
    assert await _count(client, Decision) == 2
    async with client._maker() as db:
        names = {t.description for t in (await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars()}
    assert names == {"A", "B"}      # the released row is back as they answered; the rejected one is not


# ── the same risk seen from the radar, the briefing and erasure ──────────────

async def test_radar_and_monday_briefing_say_how_many_rows_are_not_included(ortam, monkeypatch):
    from app.services.monday_briefing import assemble_monday_briefing

    client, tmp_path = ortam
    headers, org_id, _ = await kullanici(client, "radar@x.com")
    await _upload(client, tmp_path, monkeypatch, UNSURE, org_id)
    radar = (await client.get("/api/v1/ledger/cash-radar", headers=headers)).json()["data"]
    assert "2 kayıt incelemenizi bekliyor" in radar["not_included"]
    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id)
    assert "2 kayıt incelemenizi bekliyor; bu rakamlara dahil değil" in briefing.full_text


async def test_a_foreign_currency_open_item_stays_out_of_the_radar_and_is_counted(ortam):
    """Documents today's behaviour: other currencies are counted, never added to TRY."""
    from datetime import UTC, date, datetime, timedelta

    from app.models.open_item import OpenItem
    from app.services.cash_radar import compute_cash_radar

    client, _ = ortam
    _, org_id, _ = await kullanici(client, "fx2@x.com")
    due = date.today() + timedelta(days=10)
    async with client._maker() as db:
        for cur in ("TRY", "USD"):
            db.add(OpenItem(org_id=org_id, direction="receivable", instrument="invoice", document_id=f"D-{cur}",
                            amount_cents=100_000, paid_cents=0, currency=cur, issue_date=date.today(), due_date=due,
                            status="open", created_at=datetime.now(UTC)))
        await db.commit()
        radar = await compute_cash_radar(db, org_id)
    assert radar.other_currency_items == 1
    assert sum(w.inflow_cents for w in radar.weeks) == 100_000       # the TRY item only


async def test_erasure_deletes_held_rows_whose_payload_names_people(ortam, monkeypatch):
    """Not in RETAINED: a held row is deleted in anonymise mode as in hard delete."""
    from app.services import org_erasure

    assert "held_transactions" not in org_erasure.RETAINED
    assert "held_transactions" in org_erasure.derive_scope()
