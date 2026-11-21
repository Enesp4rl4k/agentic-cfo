"""The effective base: ONE rule decides the headline currency everywhere.

No fixture defaults the test organisations' currency: `Organization.base_currency` is the real column
default ("USD") and `base_currency_confirmed_at` is empty until a test confirms it, exactly as for a new
company. The four states (confirmed, one currency, several currencies, no data) are read through the real
lookups: ledger summary, company view, pipeline split, cash radar, morning brief, transactions list.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.agents.accounting.currency_merge import merge_runs
from app.agents.accounting.orchestrator import get_muhasebe_agent
from app.agents.currency_split import keep_base_currency
from app.agents.report_agent import _currency_scope
from app.core.currency_totals import (
    AMBIGUOUS,
    CONFIRMED,
    NO_DATA,
    SINGLE_UNCONFIRMED,
    effective_base,
)
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.open_item import OpenItem
from app.models.organization import Organization
from app.models.transaction import Transaction
from app.services.accounting.currency_runs import (
    balance_by_currency,
    entries_of,
    groups_by_currency,
)
from app.services.cash_radar import compute_cash_radar
from app.services.company_view import ledger_view
from app.services.ledger import append_job, effective_base_of
from app.services.morning_brief import build_facts, facts_lines
from tests.test_ledger_category_correction import _org

TODAY = date(2026, 3, 2)


async def _confirm(client, org_id: str, code: str) -> None:
    async with client._maker() as db:
        org = await db.get(Organization, org_id)
        org.base_currency, org.base_currency_confirmed_at = code, datetime.now(UTC)
        await db.commit()


async def _upload(client, org_id: str, user_id: str, rows: list[tuple[int, str, str, int, str]]) -> str:
    """rows: (day of March 2026, category, direction, kurus, currency)."""
    async with client._maker() as db:
        job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv", org_id=org_id,
                          user_id=user_id, status=JobStatus.COMPLETED)
        db.add(job)
        await db.flush()
        for i, (day, cat, typ, kurus, cur) in enumerate(rows):
            db.add(Transaction(job_id=job.id, amount_kurus=kurus, currency=cur, type=typ, category=cat,
                               description=f"islem {i}", transaction_date=datetime(2026, 3, day, tzinfo=UTC)))
        await db.commit()
        await append_job(db, job.id)
        return job.id


TRY_ONLY = [(3, "revenue", "income", 500_000, "TRY"), (5, "other_expense", "expense", 120_000, "TRY")]
MIXED = [
    (3, "revenue", "income", 500_000, "TRY"), (4, "revenue", "income", 400_000, "TRY"),
    (5, "other_expense", "expense", 120_000, "TRY"),
    (6, "revenue", "income", 9_000_000, "USD"), (7, "other_expense", "expense", 1_240_000, "USD"),
]


# -- the pure rule ----------------------------------------------------------------------------

def test_the_rule_has_four_states_and_never_an_empty_headline_over_real_data():
    assert effective_base("TRY", {"TRY": 3, "USD": 1}).state == CONFIRMED
    assert effective_base("EUR", {"TRY": 3}).currency == "EUR"            # confirmed wins over what the rows are
    single = effective_base(None, {"TRY": 4})
    assert (single.state, single.currency, single.run_currency) == (SINGLE_UNCONFIRMED, "TRY", "TRY")
    many = effective_base(None, {"TRY": 3, "USD": 5})
    assert (many.state, many.currency, many.dominant, many.run_currency) == (AMBIGUOUS, None, "USD", "USD")
    assert effective_base(None, {"TRY": 2, "USD": 2}).dominant == "TRY"    # a tie is decided by code, deterministically
    assert effective_base(None, {}).state == NO_DATA and effective_base(None, {"TRY": 0}).state == NO_DATA


# -- 1. confirmed -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirmed_base_is_the_headline_and_the_rest_is_listed_not_converted(client):
    h, org, uid = await _org(client, "eb-confirmed@x.com")
    await _upload(client, org, uid, MIXED)
    await _confirm(client, org, "TRY")
    data = (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]
    assert (data["currency"], data["base_state"], data["base_confirmed"]) == ("TRY", "confirmed", True)
    assert (data["revenue_cents"], data["expense_cents"]) == (900_000, 120_000)
    assert [(o["currency"], o["revenue_cents"], o["expense_cents"]) for o in data["other_currencies"]] == [
        ("USD", 9_000_000, 1_240_000)]


@pytest.mark.asyncio
async def test_a_confirmed_base_other_than_lira_is_the_headline_and_lira_is_listed(client):
    h, org, uid = await _org(client, "eb-eur@x.com")
    await _upload(client, org, uid, [*TRY_ONLY, (8, "revenue", "income", 700_000, "EUR")])
    await _confirm(client, org, "EUR")
    data = (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]
    assert (data["currency"], data["revenue_cents"]) == ("EUR", 700_000)
    assert [o["currency"] for o in data["other_currencies"]] == ["TRY"]
    async with client._maker() as db:
        view = await ledger_view(db, org)
        radar = await compute_cash_radar(db, org, anchor_date=TODAY)
    assert view is not None and {t["currency"] for t in view.for_pipeline()["profit"]} == {"EUR"}
    assert radar.currency == "EUR" and radar.base_state == "confirmed"      # the radar cannot disagree


# -- 2. unconfirmed, one currency: nothing is dropped -----------------------------------------

@pytest.mark.asyncio
async def test_a_new_lira_only_company_sees_its_lira_everywhere_marked_unconfirmed(client):
    h, org, uid = await _org(client, "eb-single@x.com")
    await _upload(client, org, uid, TRY_ONLY)
    data = (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]
    assert (data["currency"], data["base_state"], data["base_confirmed"]) == ("TRY", "single_unconfirmed", False)
    assert (data["revenue_cents"], data["expense_cents"]) == (500_000, 120_000)
    assert data["other_currencies"] == [] and data["confirm_path"]

    async with client._maker() as db:
        view = await ledger_view(db, org)
        radar = await compute_cash_radar(db, org, anchor_date=TODAY)
        facts = await build_facts(db, org, job_count=0, critical_count=0, high_count=0, today=TODAY)
    assert view is not None and len(view.profit) == 2 and view.base_state == "single_unconfirmed"
    assert (radar.currency, radar.base_state) == ("TRY", "single_unconfirmed")
    assert any("henüz onaylanmadı" in line for line in radar.not_included)
    assert (facts.revenue_cents, facts.currency) == (500_000, "TRY")
    assert any("henüz onaylanmadı" in line for line in facts_lines(facts))

    # the pipeline runs on all of it, and says the currency is not confirmed
    patch: dict[str, Any] = {"transactions": list(view.for_pipeline()["profit"])}
    keep_base_currency({"ledger_view": view.for_pipeline(), "base_currency": None}, patch)  # type: ignore[typeddict-item]
    assert len(patch["transactions"]) == 2 and patch["base_state"] == "single_unconfirmed"
    assert "awaiting_review" not in patch


@pytest.mark.asyncio
async def test_a_dollar_only_company_has_a_dollar_headline_not_a_lira_one(client):
    h, org, uid = await _org(client, "eb-usd@x.com")
    await _upload(client, org, uid, [(3, "revenue", "income", 800_000, "USD")])
    data = (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]
    assert (data["currency"], data["revenue_cents"], data["base_state"]) == ("USD", 800_000, "single_unconfirmed")
    async with client._maker() as db:
        assert (await compute_cash_radar(db, org, anchor_date=TODAY)).currency == "USD"


# -- 3. unconfirmed, several currencies: no single headline -----------------------------------

@pytest.mark.asyncio
async def test_several_currencies_and_none_confirmed_show_per_currency_totals_and_ask(client):
    h, org, uid = await _org(client, "eb-many@x.com")
    await _upload(client, org, uid, MIXED)
    data = (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]
    assert (data["currency"], data["base_state"]) == (None, "ambiguous")
    assert (data["revenue_cents"], data["expense_cents"]) == (0, 0)                  # there is no headline
    side_by_side = {o["currency"]: (o["revenue_cents"], o["expense_cents"]) for o in data["currency_totals"]}
    assert side_by_side == {"TRY": (900_000, 120_000), "USD": (9_000_000, 1_240_000)}   # real data is shown

    async with client._maker() as db:
        view = await ledger_view(db, org)
        radar = await compute_cash_radar(db, org, anchor_date=TODAY)
        facts = await build_facts(db, org, job_count=0, critical_count=0, high_count=0, today=TODAY)
    assert view is not None
    assert (view.base_currency, view.base_state) == ("TRY", "ambiguous")             # TRY has 3 rows to USD's 2
    assert any("Şirket para biriminizi seçin" in line for line in radar.not_included)
    assert radar.currency == view.base_currency
    lines = facts_lines(facts)
    assert any("Şirket para biriminizi seçin" in line for line in lines)
    assert any(line.startswith("USD:") for line in lines) and any(line.startswith("TRY:") for line in lines)
    assert facts.revenue_cents is None                                               # no single revenue claimed

    # the pipeline runs on the dominant currency, labels its outputs, and is held for a person
    patch: dict[str, Any] = {"transactions": list(view.for_pipeline()["profit"])}
    keep_base_currency({"ledger_view": view.for_pipeline(), "base_currency": None}, patch)  # type: ignore[typeddict-item]
    assert patch["base_state"] == "ambiguous" and patch["awaiting_review"] is True
    from app.agents.pnl_agent import _compute_pnl

    pnl = _compute_pnl(patch["transactions"], patch["base_currency"], patch["foreign_totals"], patch["base_state"])
    assert "Şirket para biriminizi seçin" in pnl["currency_note"] and pnl["currency"] == "TRY"


@pytest.mark.asyncio
async def test_confirming_the_currency_turns_the_prompt_into_a_headline(client):
    h, org, uid = await _org(client, "eb-confirm-flow@x.com")
    await _upload(client, org, uid, MIXED)
    assert (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]["currency"] is None
    res = await client.post("/api/v1/org/base-currency", headers=h, json={"currency": "USD"})
    assert res.status_code == 200, res.text
    data = (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]
    assert (data["currency"], data["base_state"], data["revenue_cents"]) == ("USD", "confirmed", 9_000_000)


# -- 4. no data -------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_empty_company_gets_the_normal_empty_state(client):
    h, org, _ = await _org(client, "eb-empty@x.com")
    data = (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]
    assert (data["currency"], data["base_state"], data["rows"]) == (None, "no_data", 0)
    assert data["currency_totals"] == [] and data["revenue_cents"] == 0
    async with client._maker() as db:
        assert (await effective_base_of(db, org)).state == NO_DATA
        assert await ledger_view(db, org) is None


# -- the same function in the file-fed pipeline, the transactions list and the left-out count -

def _rows(*specs: tuple[str, int]) -> list[dict[str, Any]]:
    return [{"currency": c, "type": "income", "category": "revenue", "amount_cents": a,
             "transaction_date": "2026-03-03"} for c, a in specs]


def test_a_file_fed_run_decides_with_the_same_rule():
    one: dict[str, Any] = {"transactions": _rows(("TRY", 5), ("TRY", 6))}
    keep_base_currency({"ledger_view": None, "base_currency": None}, one)  # type: ignore[typeddict-item]
    assert (one["base_state"], len(one["transactions"])) == ("single_unconfirmed", 2)

    many: dict[str, Any] = {"transactions": _rows(("TRY", 5), ("USD", 6), ("USD", 7))}
    keep_base_currency({"ledger_view": None, "base_currency": None}, many)  # type: ignore[typeddict-item]
    assert (many["base_state"], many["base_currency"], many["awaiting_review"]) == ("ambiguous", "USD", True)
    assert [f["currency"] for f in many["foreign_totals"]] == ["TRY"]

    confirmed: dict[str, Any] = {"transactions": _rows(("TRY", 5), ("USD", 6))}
    keep_base_currency({"ledger_view": None, "base_currency": "TRY"}, confirmed)  # type: ignore[typeddict-item]
    assert (confirmed["base_state"], len(confirmed["transactions"])) == ("confirmed", 1)
    # the cut-down rows are still carried, to be stored with the job: the list and the journal lose nothing
    assert [t["currency"] for t in confirmed["foreign_transactions"]] == ["USD"]


def test_the_dashboard_says_how_many_rows_were_left_out_and_why():
    scope = _currency_scope({"base_currency": "TRY", "base_state": "confirmed", "foreign_totals": [  # type: ignore[typeddict-item]
        {"currency": "USD", "rows": 9}, {"currency": "EUR", "rows": 3}]})
    assert scope["left_out_rows"] == 12 and "12 dövizli işlem dahil değil" in scope["note"]
    assert _currency_scope({"base_currency": "TRY", "foreign_totals": []})["note"] is None  # type: ignore[typeddict-item]


@pytest.mark.asyncio
async def test_the_transactions_list_has_every_row_in_its_own_currency_and_the_base_block(client):
    h, org, uid = await _org(client, "eb-list@x.com")
    job = await _upload(client, org, uid, MIXED)
    data = (await client.get(f"/api/v1/analysis/{job}/transactions", headers=h)).json()["data"]
    assert data["total"] == 5 and {t["currency"] for t in data["transactions"]} == {"TRY", "USD"}
    assert (data["base"]["state"], data["base"]["currency"]) == ("ambiguous", None)
    await _confirm(client, org, "TRY")
    data = (await client.get(f"/api/v1/analysis/{job}/transactions", headers=h)).json()["data"]
    assert (data["base"]["state"], data["base"]["currency"], data["total"]) == ("confirmed", "TRY", 5)


# -- radar: the open items of another currency are listed with their own totals ---------------

@pytest.mark.asyncio
async def test_the_radar_lists_other_currency_items_with_their_own_totals(client):
    _, org, _uid = await _org(client, "eb-radar@x.com")
    await _confirm(client, org, "TRY")
    async with client._maker() as db:
        for i, (cur, amount) in enumerate([("TRY", 100_000), ("USD", 250_000), ("USD", 50_000)]):
            db.add(OpenItem(
                id=f"oi-{i}", org_id=org, direction="payable", instrument="invoice", document_id=f"D-{i}",
                counterparty="X", amount_cents=amount, paid_cents=0, currency=cur,
                issue_date=TODAY, due_date=TODAY + timedelta(days=3), status="open",
                created_at=datetime.now(UTC)))
        await db.commit()
        radar = await compute_cash_radar(db, org, anchor_date=TODAY)
    assert radar.other_currency_items == 2
    assert radar.other_currency_totals == [{"currency": "USD", "receivable_cents": 0, "payable_cents": 300_000, "count": 2}]
    assert any("USD kalemleri (2" in line and "çevrilmedi" in line for line in radar.not_included)
    assert sum(w.outflow_cents for w in radar.weeks) == 100_000                     # lira only


# -- journals: per currency, balanced per currency, nothing hidden from the accountant ---------

def _journal_tx(i: int, cur: str, kurus: int, typ: str = "expense") -> dict[str, Any]:
    return {"id": f"t{i}", "amount_kurus": kurus, "type": typ, "description": f"islem {i}", "vendor": "X",
            "transaction_date": "2026-03-03T00:00:00+00:00", "date_is_estimated": False, "currency": cur}


@pytest.mark.asyncio
async def test_journals_balance_per_currency_and_foreign_entries_stay_visible():
    txs = [_journal_tx(1, "TRY", 100_000), _journal_tx(2, "TRY", 50_000, "income"),
           _journal_tx(3, "USD", 700_000), _journal_tx(4, "USD", 300_000, "income"), _journal_tx(5, "EUR", 90_000)]
    agent = get_muhasebe_agent(use_llm_fallback=False, regional_packs=["tr"])
    runs = {}
    for cur, group in groups_by_currency(txs, "TRY").items():
        runs[cur] = await agent.run(job_id="j", transactions=group)
    merged = merge_runs(runs, "TRY")

    assert list(runs) == ["TRY", "EUR", "USD"] and merged.birincil_para_birimi == "TRY"
    assert merged.kayit_sayisi == 5 and merged.dengeli is True
    per = merged.para_birimleri
    assert set(per) == {"TRY", "USD", "EUR"}
    for cur, slot in per.items():
        assert slot["toplam_borc"] == slot["toplam_alacak"] and slot["dengeli"], cur   # debit = credit, per currency
    assert per["USD"]["kayit_sayisi"] == 2 and per["TRY"]["kayit_sayisi"] == 2
    assert {e["para_birimi"] for e in merged.yevmiye_kayitlari} == {"TRY", "USD", "EUR"}
    assert {i["para_birimi"] for i in merged.onay_kuyrugu} <= {"TRY", "USD", "EUR"}
    assert set(merged.mizan_para_birimi) == {"TRY", "USD", "EUR"}
    # the trial balance of one currency holds only that currency's money
    usd_total = sum(r["borc"] for r in merged.mizan_para_birimi["USD"].values())
    try_total = sum(r["borc"] for r in merged.mizan_para_birimi["TRY"].values())
    assert usd_total == 1_000_000 and try_total == 150_000 and merged.mizan == merged.mizan_para_birimi["TRY"]

    # statutory outputs: the primary currency, with the left-out count said; the raw journal keeps all
    kept, left = entries_of(merged.yevmiye_kayitlari, merged.birincil_para_birimi)
    assert len(kept) == 2 and left == {"USD": 2, "EUR": 1}
    assert balance_by_currency(merged.yevmiye_kayitlari, "TRY") == per


def test_an_untagged_older_journal_is_read_as_one_currency():
    entries = [{"kayit_id": "a", "satirlar": [{"borc": 5, "alacak": 0}, {"borc": 0, "alacak": 5}]}]
    assert entries_of(entries, "TRY") == (entries, {}) and entries_of(entries, None) == (entries, {})
    assert balance_by_currency(entries, "TRY")["TRY"]["dengeli"] is True
