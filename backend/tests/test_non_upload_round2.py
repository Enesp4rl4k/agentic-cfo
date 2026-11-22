"""#124 review, round 2: direction from evidence only, coverage evidence from a feed, a stated currency never replaced.

1. one negative row must not turn a payroll / Stripe / CRM file's other rows into income;
2. a pull that stopped on 27 March must not leave March "complete" (and a later complete pull does);
3. a currency the source STATED but that cannot be read (`XXX`, `US$1`) is held, never the base currency;
   plus the extra checks: no secret in a held row, tenancy of the sync job, and a dormant schedule reports once.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services.coverage import annotate_series, complete_months, extents_for
from app.services.data_plane.normalization_service import normalize_csv_transactions
from app.services.ingest import feed as F
from app.services.ingest.feed import Feed, mask_secrets, rows_for_pipeline
from app.services.open_banking.akbank import AkbankClient
from tests.test_non_upload_sources import (
    GarantiClient,
    _bank,
    _json,
    akbank_item,
    akbank_payload,
    garanti_item,
    garanti_payload,
)
from tests.test_non_upload_sources import _queued as _queued

HEADER = "date,amount,description,reference,currency\n"


def _csv(*rows: str, header: str = HEADER) -> bytes:
    return (header + "\n".join(rows) + "\n").encode()


# ── 1. direction ────────────────────────────────────────────────────────────────────────────────────────────

def test_one_negative_row_does_not_make_a_payroll_file_income() -> None:
    n = normalize_csv_transactions(
        csv_bytes=_csv("2026-01-05,10000.00,Maaş A,P1,TRY", "2026-01-05,12000.00,Maaş B,P2,TRY", "2026-01-06,-500.00,Avans iadesi,P3,TRY"),
        source="hr_export",
    )
    assert [(r.source_record_id, r.direction, r.amount_cents) for r in n.rows] == [("P1", "expense", 1000000), ("P2", "expense", 1200000)]
    assert [h["reference"] for h in n.held] == ["P3"] and n.held[0]["type"] is None      # the contradicting sign is held
    assert n.outcome()["status"] == F.AWAITING_REVIEW


@pytest.mark.parametrize(("source", "direction"), [("billing_stripe", "income"), ("crm_export", "income"), ("hr_export", "expense")])
def test_a_contract_source_with_a_refund_row_books_the_rest_by_its_contract_and_holds_the_refund(source, direction) -> None:
    n = normalize_csv_transactions(
        csv_bytes=_csv("2026-01-05,100.00,a,R1,TRY", "2026-01-06,200.00,b,R2,TRY", "2026-01-07,-50.00,refund,R3,TRY"), source=source)
    assert {r.direction for r in n.rows} == {direction} and len(n.rows) == 2
    assert [h["reference"] for h in n.held] == ["R3"]


def test_no_evidence_no_booking_the_sign_mix_of_a_file_is_never_evidence() -> None:
    mixed = _csv("2026-01-05,100.00,a,R1,TRY", "2026-01-06,-40.00,b,R2,TRY", "2026-01-07,-10.00,c,R3,TRY", "2026-01-08,-5.00,d,R4,TRY")
    n = normalize_csv_transactions(csv_bytes=mixed)                                 # no source contract, no type column
    assert n.rows == [] and len(n.held) == 4
    n = normalize_csv_transactions(csv_bytes=mixed, source="manual_csv")            # a source that declares nothing
    assert n.rows == []


def test_an_explicit_row_field_is_evidence_and_beats_nothing_else() -> None:
    n = normalize_csv_transactions(
        csv_bytes=_csv("2026-01-05,100.00,a,R1,TRY,income", "2026-01-06,40.00,b,R2,TRY,expense", "2026-01-07,9.00,c,R3,TRY,transfer",
                       header=HEADER.strip() + ",type\n"), source="hr_export")
    assert {r.source_record_id: r.direction for r in n.rows} == {"R1": "income", "R2": "expense"} and [h["reference"] for h in n.held] == ["R3"]


def test_a_signed_contract_is_the_only_way_a_sign_becomes_a_direction() -> None:
    signed = F.direction_by_contract((F.SIGNED, None), F.read_money("-5.00"))
    assert signed == "expense" and F.direction_by_contract((F.SIGNED, None), F.read_money("5.00")) == "income"
    assert F.direction_by_contract(None, F.read_money("5.00")) is None and F.SIGNED not in {k for k, _ in F.SOURCE_DIRECTION.values()}


# ── 2. coverage evidence from a feed ────────────────────────────────────────────────────────────────────────

async def _sync(client, monkeypatch, tmp_path, handler, name: str):
    from app.config import get_settings
    from tests.test_ingest import _login

    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path), raising=False)
    monkeypatch.setattr("app.api.open_banking._get_bank_settings", lambda bank_id: ("id", "secret", True))
    monkeypatch.setattr("app.worker.enqueue_analysis", lambda job_id, budget_input=None: _queued())
    monkeypatch.setattr("app.services.open_banking.get_bank_client", lambda *a, **k: _bank(AkbankClient, handler))
    h = await _login(client, f"{name}@example.com")
    r = await client.post("/api/v1/open-banking/connections/c1/sync", headers=h,
                          json={"bank_id": "akbank", "account_id": "A", "access_token": "tok", "days_back": 30})
    assert r.status_code == 200, r.text
    _sync.headers = h  # type: ignore[attr-defined]
    return r.json()["data"]


async def _extents(client, job_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.agents.data_ingestion import run_data_ingestion
    from app.models.analysis_job import AnalysisJob

    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
    out = await run_data_ingestion({"file_path": job.file_path, "file_type": "csv", "org_id": job.org_id}, None)  # type: ignore[arg-type]
    patch = out.patch
    state = {"transactions": patch["transactions"], "statement_period": patch.get("statement_period"),
             "statement_extent": patch.get("statement_extent"), "ingest_counts": patch.get("ingest_counts"), "file_path": job.file_path}
    return extents_for(state), patch


def _march(days: list[int], *, fail_next: bool = False, nxt: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if "page2" in str(request.url):
            return httpx.Response(500, text="boom")
        items = [akbank_item(transactionId=f"M{d}", bookingDate=f"2026-03-{d:02d}",
                             transactionAmount={"amount": "-100.00", "currency": "TRY"}) for d in days]
        return httpx.Response(200, json=akbank_payload(*items, nxt="https://sandbox.api.akbank.com/page2" if fail_next or nxt else None))
    return handler


def _window(monkeypatch, start: str, end: str) -> None:
    """The sync asks for [start, end]: pin the clock the endpoint reads."""
    import app.api.open_banking as ob

    class _Now:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime.fromisoformat(end + "T12:00:00+00:00")

    monkeypatch.setattr(ob, "datetime", _Now)


async def test_a_pull_that_stopped_on_27_march_does_not_leave_march_complete(client, monkeypatch, tmp_path) -> None:
    _window(monkeypatch, "2026-03-01", "2026-03-31")
    days = list(range(1, 28))
    data = await _sync(client, monkeypatch, tmp_path, _march(days, fail_next=True), "cov1")
    assert data["sync_status"] == F.PARTIAL and data["period_covered"] is False
    extents, patch = await _extents(client, data["job_id"])
    assert extents and extents[0]["end_stated"] and extents[0]["truncated_at"] == "2026-03-27"
    assert complete_months(extents, ["2026-03"]) == {"2026-03": False}      # was {'2026-03': True} through the 5-day tolerance
    series = annotate_series([{"month": "2026-03", "in": 0, "out": 2700, "net": -2700}], patch["transactions"], extents)
    assert series[0]["complete"] is False and series[0]["pull_truncated"] == "Mart çekimi 27 Mart'ta yarıda kaldı"


async def test_a_pull_that_stopped_within_five_days_of_the_month_end_is_still_incomplete(client, monkeypatch, tmp_path) -> None:
    _window(monkeypatch, "2026-03-01", "2026-03-31")
    data = await _sync(client, monkeypatch, tmp_path, _march(list(range(1, 30)), nxt=True), "cov2")
    extents, _ = await _extents(client, data["job_id"])
    assert complete_months(extents, ["2026-03"]) == {"2026-03": False}


async def test_a_completed_pull_states_its_window_and_a_later_repull_completes_the_month(client, monkeypatch, tmp_path) -> None:
    _window(monkeypatch, "2026-03-01", "2026-03-31")
    data = await _sync(client, monkeypatch, tmp_path, _march([3, 9, 20]), "cov3")      # a quiet month: nothing after the 20th
    assert data["sync_status"] == F.SUCCESS and data["period_covered"] is True
    extents, _ = await _extents(client, data["job_id"])
    assert extents[0]["start"] == "2026-03-01" and extents[0]["end"] == "2026-03-31" and "truncated_at" not in extents[0]
    assert complete_months(extents, ["2026-03"]) == {"2026-03": True}                 # stated by the pull, not assumed


async def test_a_repull_after_a_partial_one_completes_the_month(client, monkeypatch, tmp_path) -> None:
    _window(monkeypatch, "2026-03-01", "2026-03-31")
    first = await _sync(client, monkeypatch, tmp_path, _march(list(range(1, 28)), fail_next=True), "cov4")
    e1, _ = await _extents(client, first["job_id"])
    assert complete_months(e1, ["2026-03"]) == {"2026-03": False}
    monkeypatch.setattr("app.services.open_banking.get_bank_client", lambda *a, **k: _bank(AkbankClient, _march(list(range(1, 32)))))
    r = await client.post("/api/v1/open-banking/connections/c1/sync", headers=_sync.headers,  # type: ignore[attr-defined]
                          json={"bank_id": "akbank", "account_id": "A", "access_token": "tok", "days_back": 30})
    second = r.json()["data"]
    assert second["period_covered"] is True
    e2, _ = await _extents(client, second["job_id"])
    assert complete_months(e2, ["2026-03"]) == {"2026-03": True}


def test_a_file_that_states_no_pull_keeps_the_existing_tolerance_rules() -> None:
    from app.services.coverage import apply_period

    ext = apply_period({"start": "2026-03-01", "end": "2026-03-27"}, {"start": "2026-03-01", "end": "2026-03-31"})
    assert ext is not None and "truncated_at" not in ext and complete_months([ext], ["2026-03"]) == {"2026-03": True}


# ── 3. a stated currency is never replaced ──────────────────────────────────────────────────────────────────

async def _confirm_try(client, email: str) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models.organization import Organization

    async with client._maker() as db:
        org = (await db.execute(select(Organization).where(Organization.name == email))).scalar_one()
        org.base_currency, org.base_currency_confirmed_at = "TRY", datetime.now(UTC)
        await db.commit()


@pytest.mark.parametrize("stated", ["XXX", "US$1", "TL?", "12"])
async def test_a_stated_but_unreadable_currency_is_held_not_booked_as_the_base_currency(client, monkeypatch, tmp_path, stated) -> None:
    from app import database
    from app.config import get_settings
    from tests.test_ingest import _login
    from tests.test_non_upload_sources import SECRET

    monkeypatch.setattr(database, "get_session_factory", lambda eng=None: client._maker)
    monkeypatch.setattr(database, "session_factory", lambda: client._maker)
    monkeypatch.setattr(database, "engine", lambda: None)
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path), raising=False)
    monkeypatch.setattr("app.api.open_banking._get_bank_settings", lambda bank_id: ("id", "secret", True))
    monkeypatch.setattr("app.worker.enqueue_analysis", lambda job_id, budget_input=None: _queued())
    payload = garanti_payload(garanti_item(Description="STATED", CurrencyCode=stated), garanti_item(TransactionId="T2", Description="UNSTATED", CurrencyCode=None))
    monkeypatch.setattr("app.services.open_banking.get_bank_client", lambda *a, **k: _bank(GarantiClient, _json(payload)))
    email = "cur@example.com"
    h = await _login(client, email)
    await _confirm_try(client, email)
    r = await client.post("/api/v1/open-banking/connections/c1/sync", headers=h,
                          json={"bank_id": "garanti", "account_id": "A", "access_token": SECRET})
    d = r.json()["data"]
    assert d["held_candidates"] == 1
    from tests.test_non_upload_sources import _ingest_job

    patch = await _ingest_job(client, d["job_id"])
    held = {x["description"].split(" [")[0]: x for x in patch["held_transactions"]}
    booked = {x["description"]: x for x in patch["transactions"]}
    assert "STATED" in held and "currency_unreadable" in held["STATED"]["hold_reasons"] and held["STATED"]["currency"] is None
    assert "STATED" not in booked
    # the accepted policy for a row that stated nothing is unchanged: the document's currency if it names one (a "$" in
    # the file does), else the confirmed base currency, marked assumed
    if stated in ("XXX", "12"):
        assert booked["UNSTATED"]["currency"] == "TRY" and booked["UNSTATED"]["currency_assumed"] is True
    else:
        assert booked["UNSTATED"]["currency"] in ("TRY", "USD")


def test_an_uploaded_csv_with_a_stated_unreadable_currency_is_held_too() -> None:
    from app.agents.data_ingestion import _try_parse_csv
    from app.services.ingest.hold import resolve_currency, split_uncertain

    rows = _try_parse_csv("tarih,açıklama,tutar,tip,currency\n2026-01-05,A,100.00,income,XXX\n2026-01-06,B,100.00,income,\n") or []
    resolve_currency(rows, "", "TRY")
    accepted, held = split_uncertain(rows)
    assert [r["description"] for r in accepted] == ["B"] and "currency_unreadable" in held[0]["hold_reasons"]
    assert "currency_unknown" not in held[0]["hold_reasons"]


# every safety flag a feed row can carry must survive every projection it goes through
FLAG_CASES = {
    F.AMOUNT_MISSING: {"amount": None, "direction": "income", "date": "2026-01-05", "currency": "TRY"},
    F.AMOUNT_UNREADABLE: {"amount": "x1", "direction": "income", "date": "2026-01-05", "currency": "TRY"},
    F.AMOUNT_AMBIGUOUS: {"amount": "1.500", "direction": "income", "date": "2026-01-05", "currency": "TRY"},
    F.AMOUNT_ZERO: {"amount": "0", "direction": "income", "date": "2026-01-05", "currency": "TRY"},
    F.DIRECTION_MISSING: {"amount": "10.00", "direction": None, "date": "2026-01-05", "currency": "TRY"},
    F.DATE_UNREADABLE: {"amount": "10.00", "direction": "income", "date": "31.31.2026", "currency": "TRY"},
    F.CURRENCY_UNREADABLE: {"amount": "10.00", "direction": "income", "date": "2026-01-05", "currency": "XXX"},
}


@pytest.mark.parametrize("flag", sorted(FLAG_CASES))
def test_every_safety_flag_survives_the_projection_to_the_pipeline_csv_and_holds_the_row(flag) -> None:
    from app.agents.data_ingestion import _try_parse_csv
    from app.services.ingest.ekle import islemler_csv
    from app.services.ingest.hold import resolve_currency, split_uncertain

    feed = Feed("probe")
    feed.add(description="PROBE", evidence={"k": "v"}, **FLAG_CASES[flag])
    assert flag in feed.rows[0]["feed_flags"]
    projected = rows_for_pipeline(feed.rows)
    assert all(key in projected[0] for key in F.SAFETY_KEYS if key in feed.rows[0])          # the projection kept them
    text = islemler_csv(projected).decode()
    rows = _try_parse_csv(text) or []
    resolve_currency(rows, "", "TRY")                       # the confirmed base currency is available and must not rescue it
    accepted, held = split_uncertain(rows)
    assert accepted == [] and len(held) == 1, (flag, text)
    if flag == F.CURRENCY_UNREADABLE:
        assert "currency_unreadable" in held[0]["hold_reasons"] and held[0]["currency"] is None


@pytest.mark.parametrize("flag", sorted(FLAG_CASES))
def test_every_safety_flag_survives_the_scheduled_projection_and_holds_the_row(flag) -> None:
    from app.services.scheduled_sync import feed_row_for_csv

    feed = Feed("probe")
    feed.add(description="PROBE", reference="R1", evidence={"k": "v"}, **FLAG_CASES[flag])
    line = feed_row_for_csv(feed.rows[0])
    text = "date,amount,description,type,currency,reference\n" + ",".join(f'"{line[k]}"' for k in
                                                                        ("date", "amount", "description", "type", "currency", "reference")) + "\n"
    n = normalize_csv_transactions(csv_bytes=text.encode())
    assert n.rows == [] and len(n.held) == 1, (flag, text)


# ── the extra checks ────────────────────────────────────────────────────────────────────────────────────────

def test_no_token_authorization_header_or_full_card_number_reaches_a_held_row() -> None:
    feed = Feed("probe")
    row = feed.add(
        amount="abc", direction="income", date="2026-01-05", currency="TRY",
        description="KART 4543 6000 1234 5678 ODEME Bearer abcdefgh12345678",
        evidence={"Amount": "abc", "note": "card 4543600012345678", "Authorization": "Bearer abcdefgh12345678", "access_token": "tok-123456789"},
    )
    shown = json.dumps(row)
    assert "4543" not in shown and "1234 5678" not in shown and "abcdefgh12345678" not in shown and "tok-123456789" not in shown
    assert "5678" in row["description"] and "Amount='abc'" in row["description"]
    assert mask_secrets("plain 1.500,00 and ref 12345678") == "plain 1.500,00 and ref 12345678"


async def test_the_open_banking_sync_job_belongs_to_the_caller_s_organisation(client, monkeypatch, tmp_path) -> None:
    from sqlalchemy import select

    from app.models.analysis_job import AnalysisJob
    from app.models.organization import Organization

    _window(monkeypatch, "2026-03-01", "2026-03-31")
    data = await _sync(client, monkeypatch, tmp_path, _march([3, 9]), "tenant1")
    async with client._maker() as db:
        job = await db.get(AnalysisJob, data["job_id"])
        org = (await db.execute(select(Organization).where(Organization.name == "tenant1@example.com"))).scalar_one()
    assert job.org_id == org.id


async def test_a_dormant_schedule_is_reported_once_not_on_every_tick(client) -> None:
    from sqlalchemy import func, select

    from app.models.in_app_notification import InAppNotification
    from app.models.organization import Organization
    from app.models.sync_run import SyncRun
    from app.models.sync_schedule import SyncSchedule
    from app.services.scheduled_sync import (
        SyncSourceType,
        SyncStatus,
        _load_active_schedules,
        run_due_syncs,
    )
    from tests.test_ingest import _login

    await _login(client, "dormant@example.com")
    from datetime import UTC, datetime

    async with client._maker() as db:
        org = (await db.execute(select(Organization))).scalars().first().id
        db.add(SyncSchedule(org_id=org, source_type=SyncSourceType.OPEN_BANKING.value, frequency="daily",
                            hour_utc=datetime.now(UTC).hour, enabled=True, auto_analyze=True, notify_on_completion=True,
                            source_config="{}"))
        await db.commit()

    async def tick() -> None:
        async with client._maker() as db:
            await run_due_syncs(db, None)

    for _ in range(3):           # three scheduler ticks
        await tick()
    async with client._maker() as db:
        runs = (await db.execute(select(func.count()).select_from(SyncRun))).scalar()
        row = (await db.execute(select(SyncSchedule))).scalars().one()
        notes = (await db.execute(select(func.count()).select_from(InAppNotification))).scalar()
        loaded = (await _load_active_schedules(db))[0]
    assert runs == 1 and notes == 0                                    # one failed run, no alert, however many ticks
    assert row.last_status == SyncStatus.FAILED and "rızası" in (row.last_error or "")
    # even when the schedule is due again (a new day), the same reason is not recorded as a new run
    from app.services.scheduled_sync import ScheduledSyncRunner

    async with client._maker() as db:
        again = await ScheduledSyncRunner().run(loaded, db, None)
        await db.commit()
        assert again.status == SyncStatus.FAILED
        assert (await db.execute(select(func.count()).select_from(SyncRun))).scalar() == 1
