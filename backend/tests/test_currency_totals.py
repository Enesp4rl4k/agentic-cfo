"""Totals are per currency: a USD amount is never added to a TRY one, and no rate is invented.

A company with TRY, USD and EUR rows: the headline figures hold the base currency only, every
other currency is its own sub-total, ratios ignore foreign rows, and periods and correction pairs
still add up correctly within each currency.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.agents.cashflow_agent import _classify_cashflow, run_cashflow
from app.agents.orchestrator import _keep_base_currency
from app.agents.pnl_agent import _compute_pnl, run_pnl
from app.core.currency_totals import (
    code_of,
    currency_note,
    foreign_summaries,
    split_by_currency,
    totals_by_currency,
)
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization
from app.models.transaction import Transaction
from app.services.company_view import ledger_view
from app.services.donem_kilidi import kilitle
from app.services.ledger import Period, append_job, company_rows, ledger_summary
from tests.test_ledger_category_correction import _org, _patch

# (date, category, direction, kurus, currency)
MIXED = [
    ((2026, 1, 10), "revenue", "income", 100_000, "TRY"),
    ((2026, 1, 12), "revenue", "income", 5_000_000, "USD"),
    ((2026, 1, 15), "other_expense", "expense", 700_000, "EUR"),
    ((2026, 1, 20), "other_expense", "expense", 30_000, "TRY"),
    ((2026, 2, 10), "other_expense", "expense", 1_240_000, "USD"),
    ((2026, 2, 12), "revenue", "income", 40_000, "TRY"),
]


async def _job(db, org, uid, rows):
    job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                      org_id=org, user_id=uid, status=JobStatus.COMPLETED)
    db.add(job)
    await db.flush()
    ids = []
    for i, (day, cat, typ, kurus, cur) in enumerate(rows):
        t = Transaction(job_id=job.id, amount_kurus=kurus, currency=cur, type=typ, category=cat,
                        description=f"islem {i}", transaction_date=datetime(*day, tzinfo=UTC))
        db.add(t)
        await db.flush()
        ids.append(t.id)
    await db.commit()
    return job.id, ids


async def _confirm(client, org, code):
    async with client._maker() as db:
        row = await db.get(Organization, org)
        row.base_currency, row.base_currency_confirmed_at = code, datetime.now(UTC)
        await db.commit()


async def _mixed_company(client, email, rows=MIXED, base="TRY"):
    h, org, uid = await _org(client, email)
    if base:
        await _confirm(client, org, base)
    async with client._maker() as db:
        job, ids = await _job(db, org, uid, rows)
        await append_job(db, job)
    return h, org, uid, ids


def _by_currency(subtotals, key):
    return {s["currency"]: s[key] for s in subtotals}


# -- the helpers ------------------------------------------------------------------------------

def test_split_by_currency_keeps_the_base_and_groups_the_rest():
    rows = [{"currency": "try", "amount_cents": 1}, {"currency": "USD", "amount_cents": 2},
            {"currency": "USD", "amount_cents": 3}, {"currency": "EUR", "amount_cents": 4}]
    mine, other = split_by_currency(rows, "TRY")
    assert [r["amount_cents"] for r in mine] == [1]
    assert {c: [r["amount_cents"] for r in v] for c, v in other.items()} == {"USD": [2, 3], "EUR": [4]}
    assert totals_by_currency(rows, lambda r: r["amount_cents"]) == {"TRY": 1, "USD": 5, "EUR": 4}


def test_a_pipeline_row_with_no_currency_counts_as_base_but_a_ledger_object_never_does():
    assert code_of({"amount_cents": 1}, "TRY") == "TRY"

    class Row:
        currency = None

    assert code_of(Row(), "TRY") == ""
    mine, other = split_by_currency([Row()], "TRY")
    assert mine == [] and list(other) == [""]


def test_the_note_says_what_was_left_out_and_nothing_when_nothing_was():
    assert currency_note("TRY", []) is None
    note = currency_note("TRY", [{"currency": "USD", "revenue_cents": 0, "expense_cents": 1_240_000}])
    assert note is not None and "12,400.00 USD gider" in note and "çevrilmedi" in note


# -- the ledger summary -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_base_totals_exclude_foreign_amounts_and_subtotals_are_per_currency(client):
    h, *_ = await _mixed_company(client, "kur1@x.com")
    res = await client.get("/api/v1/ledger/summary", headers=h)
    data = res.json()["data"]
    assert data["currency"] == "TRY"
    assert data["revenue_cents"] == 140_000 and data["expense_cents"] == 30_000      # TRY rows only
    subs = {s["currency"]: s for s in data["other_currencies"]}
    assert set(subs) == {"EUR", "USD"}
    assert (subs["USD"]["revenue_cents"], subs["USD"]["expense_cents"]) == (5_000_000, 1_240_000)
    assert (subs["EUR"]["revenue_cents"], subs["EUR"]["expense_cents"]) == (0, 700_000)
    assert data["rows"] == 6
    assert sum(m["cash_in_cents"] for m in data["months"]) == 140_000                # cash months: base only
    assert sum(m["cash_out_cents"] for m in data["months"]) == 30_000


@pytest.mark.asyncio
async def test_a_company_with_only_foreign_documents_has_no_base_total_and_says_so(client):
    h, *_ = await _mixed_company(client, "kur2@x.com", [MIXED[1], MIXED[4]])
    data = (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]
    assert data["revenue_cents"] == 0 and data["expense_cents"] == 0
    assert _by_currency(data["other_currencies"], "revenue_cents") == {"USD": 5_000_000}


@pytest.mark.asyncio
async def test_the_base_currency_is_the_organisations_not_a_guess_from_the_rows(client):
    h, org, *_ = await _mixed_company(client, "kur3@x.com")
    await _confirm(client, org, "USD")
    data = (await client.get("/api/v1/ledger/summary", headers=h)).json()["data"]
    assert data["currency"] == "USD" and data["revenue_cents"] == 5_000_000
    assert _by_currency(data["other_currencies"], "revenue_cents") == {"EUR": 0, "TRY": 140_000}


@pytest.mark.asyncio
async def test_adjacent_periods_add_up_to_their_union_per_currency(client):
    _h, org, *_ = await _mixed_company(client, "kur4@x.com")
    async with client._maker() as db:
        jan = await ledger_summary(db, org, Period("2026-01", "2026-01"))
        feb = await ledger_summary(db, org, Period("2026-02", "2026-02"))
        both = await ledger_summary(db, org, Period("2026-01", "2026-02"))
    for key in ("revenue_cents", "expense_cents"):
        assert jan[key] + feb[key] == both[key]
        for cur in ("USD", "EUR"):
            parts = sum(_by_currency(p["other_currencies"], key).get(cur, 0) for p in (jan, feb))
            assert parts == _by_currency(both["other_currencies"], key)[cur]
    assert (jan["revenue_cents"], feb["revenue_cents"]) == (100_000, 40_000)


@pytest.mark.asyncio
async def test_a_correction_pair_sums_within_its_own_currency(client):
    h, org, uid, ids = await _mixed_company(client, "kur5@x.com")
    async with client._maker() as db:
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
    # The January EUR expense is reclassified in the closed month: a pair booked in February.
    assert (await _patch(client, h, ids[2], "rent")).json()["data"]["ledger"] == "booked_in_open_month"
    async with client._maker() as db:
        view = await company_rows(db, org, Period("2026-01", "2026-02"))
    per: dict[tuple[str, str], int] = {}
    for r in view.profit:
        per[(r.currency, r.category)] = per.get((r.currency, r.category), 0) + r.amount_cents
    assert per[("EUR", "other_expense")] == 0 and per[("EUR", "rent")] == 700_000
    assert ("TRY", "rent") not in per and ("USD", "rent") not in per
    async with client._maker() as db:
        summary = await ledger_summary(db, org, Period("2026-01", "2026-02"))
    assert summary["expense_cents"] == 30_000                               # TRY expense untouched
    assert _by_currency(summary["other_currencies"], "expense_cents")["EUR"] == 700_000


@pytest.mark.asyncio
async def test_a_payment_in_another_currency_is_not_a_duplicate_of_a_lira_one(client):
    _h, org, uid = await _org(client, "kur6@x.com")
    async with client._maker() as db:
        first, _ = await _job(db, org, uid, [((2026, 1, 10), "revenue", "income", 100_000, "TRY")])
        second, _ = await _job(db, org, uid, [((2026, 1, 11), "revenue", "income", 100_000, "USD")])
        await append_job(db, first)
        counts = await append_job(db, second)
    assert counts["possible_duplicate"] == 0 and counts["new"] == 1


# -- what the pipeline reads -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_pipeline_gets_base_rows_and_the_rest_as_subtotals(client):
    _h, org, *_ = await _mixed_company(client, "kur7@x.com")
    async with client._maker() as db:
        view = await ledger_view(db, org)
    assert view is not None
    feed = view.for_pipeline()
    assert {t["currency"] for t in feed["profit"]} == {"TRY"} == {t["currency"] for t in feed["cash"]}
    assert feed["base_currency"] == "TRY"
    assert _by_currency(feed["foreign"], "expense_cents") == {"EUR": 700_000, "USD": 1_240_000}


@pytest.mark.asyncio
async def test_a_foreign_row_changes_the_signature_of_the_view(client):
    _h, org, uid, _ = await _mixed_company(client, "kur8@x.com", MIXED[:1] + MIXED[3:4])
    async with client._maker() as db:
        before = await ledger_view(db, org)
        job, _ids = await _job(db, org, uid, [MIXED[1]])
        await append_job(db, job)
        after = await ledger_view(db, org)
    assert before is not None and after is not None
    assert before.signature != after.signature and before.profit == after.profit


def _row(cur, typ, cat, cents, day="2026-01-10"):
    return {"currency": cur, "type": typ, "category": cat, "amount_cents": cents, "transaction_date": day}


def _rows() -> list[dict[str, Any]]:
    return [
        _row("TRY", "income", "revenue", 1_000_000), _row("TRY", "expense", "cogs", 400_000),
        _row("TRY", "expense", "rent", 100_000),
        _row("USD", "income", "revenue", 9_000_000), _row("USD", "expense", "cogs", 8_000_000),
        _row("EUR", "expense", "rent", 700_000),
    ]


def test_pnl_ratios_are_unaffected_by_foreign_rows_and_the_foreign_money_is_listed():
    mixed = _compute_pnl(_rows(), "TRY")
    only_try = _compute_pnl([r for r in _rows() if r["currency"] == "TRY"], "TRY")
    for key in ("revenue", "cogs", "gross_profit", "gross_margin", "ebitda", "net_income", "net_margin",
                "total_expenses", "transaction_count", "revenue_mom_pct"):
        assert mixed[key] == only_try[key], key
    assert mixed["revenue"] == 1_000_000 and mixed["gross_margin"] == 0.6
    assert mixed["currency"] == "TRY" and only_try["other_currencies"] == []
    assert _by_currency(mixed["other_currencies"], "revenue_cents") == {"EUR": 0, "USD": 9_000_000}
    assert _by_currency(mixed["other_currencies"], "expense_cents") == {"EUR": 700_000, "USD": 8_000_000}
    assert "çevrilmedi" in mixed["currency_note"] and "yalnızca TRY" in mixed["currency_note"]


def test_pnl_trend_and_mom_use_base_rows_only():
    rows = [*_rows(), _row("TRY", "income", "revenue", 2_000_000, "2026-02-10"),
            _row("USD", "income", "revenue", 99_000_000, "2026-02-11")]
    assert _compute_pnl(rows, "TRY")["revenue_mom_pct"] == 100.0                 # 1.0M -> 2.0M lira


def test_cashflow_is_base_only_and_lists_the_rest():
    flow = _classify_cashflow(_rows(), "TRY")
    only_try = _classify_cashflow([r for r in _rows() if r["currency"] == "TRY"], "TRY")
    for key in ("operating", "net_change", "operating_in", "operating_out", "monthly_series"):
        assert flow[key] == only_try[key]
    assert _by_currency(flow["other_currencies"], "cash_out_cents") == {"EUR": 700_000, "USD": 8_000_000}
    assert "çevrilmedi" in flow["currency_note"]


def test_the_pipeline_removes_foreign_rows_before_any_other_step_reads_them():
    patch: dict[str, Any] = {"transactions": _rows()}
    _keep_base_currency({"ledger_view": None, "base_currency": "TRY"}, patch)  # type: ignore[typeddict-item]
    assert {t["currency"] for t in patch["transactions"]} == {"TRY"}
    assert patch["base_currency"] == "TRY"
    assert _by_currency(patch["foreign_totals"], "revenue_cents") == {"EUR": 0, "USD": 9_000_000}
    # An organisation whose base is USD gets the USD rows and the lira as an "other" line.
    patch = {"transactions": _rows()}
    _keep_base_currency({"ledger_view": None, "base_currency": "USD"}, patch)  # type: ignore[typeddict-item]
    assert {t["currency"] for t in patch["transactions"]} == {"USD"}


def test_a_ledger_fed_run_keeps_the_sub_totals_the_ledger_computed():
    foreign = [{"currency": "USD", "revenue_cents": 5, "expense_cents": 0, "cash_in_cents": 5,
                "cash_out_cents": 0, "rows": 1}]
    patch: dict[str, Any] = {"transactions": [r for r in _rows() if r["currency"] == "TRY"]}
    _keep_base_currency({"ledger_view": {"base_currency": "TRY", "foreign": foreign}}, patch)  # type: ignore[typeddict-item]
    assert patch["foreign_totals"] == foreign


async def _narrative(*_a, **_k):
    return "x"


@pytest.mark.asyncio
async def test_the_pnl_and_cashflow_steps_report_the_other_currencies(monkeypatch):
    import app.agents.cashflow_agent as cashflow_mod
    import app.agents.pnl_agent as pnl_mod

    monkeypatch.setattr(pnl_mod, "_generate_cfo_narrative", _narrative)
    monkeypatch.setattr(cashflow_mod, "_generate_cashflow_narrative", _narrative)
    patch: dict[str, Any] = {"transactions": _rows()}
    _keep_base_currency({"ledger_view": None, "base_currency": "TRY"}, patch)  # type: ignore[typeddict-item]
    state: Any = {"job_id": "j", **patch}
    pnl = (await run_pnl(state, None)).patch["pnl"]                              # type: ignore[arg-type]
    flow = (await run_cashflow(state, None)).patch["cashflow"]                   # type: ignore[arg-type]
    assert pnl["revenue"] == 1_000_000 and _by_currency(pnl["other_currencies"], "revenue_cents")["USD"] == 9_000_000
    assert flow["net_change"] == 500_000 and flow["other_currencies"]


@pytest.mark.asyncio
async def test_a_run_with_only_foreign_rows_still_answers_instead_of_halting(monkeypatch):
    import app.agents.pnl_agent as pnl_mod

    monkeypatch.setattr(pnl_mod, "_generate_cfo_narrative", _narrative)
    patch: dict[str, Any] = {"transactions": [r for r in _rows() if r["currency"] == "USD"]}
    _keep_base_currency({"ledger_view": None, "base_currency": "TRY"}, patch)  # type: ignore[typeddict-item]
    state: Any = {"job_id": "j", **patch}
    result = await run_pnl(state, None)                                          # type: ignore[arg-type]
    assert result.ok and result.patch["pnl"]["revenue"] == 0
    assert _by_currency(result.patch["pnl"]["other_currencies"], "revenue_cents") == {"USD": 9_000_000}


def test_foreign_summaries_split_profit_and_cash_views():
    rows = _rows()
    out = foreign_summaries(rows, [r for r in rows if r["type"] == "income"], "TRY")
    usd = next(s for s in out if s["currency"] == "USD")
    assert (usd["revenue_cents"], usd["expense_cents"]) == (9_000_000, 8_000_000)
    assert (usd["cash_in_cents"], usd["cash_out_cents"]) == (9_000_000, 0)


# -- other readers of the same money ----------------------------------------------------------

@pytest.mark.asyncio
async def test_a_decisions_outcome_does_not_add_other_currencies_to_the_realised_net(client):
    from datetime import timedelta

    from app.models.decision_log import DecisionLog
    from tests.test_decisions import _record as record_decision
    from tests.test_decisions import _seed_job
    from tests.test_decisions import _user as make_user

    headers, org_id, _ = await make_user(client, "kur-karar@example.com")
    job1 = await _seed_job(client, org_id)
    decision = await record_decision(client, headers, job1, option_id="baseline")
    job2 = await _seed_job(client, org_id, status="completed",
                           txn_days=((1, "income", 500_000_00), (1, "expense", 200_000_00)))
    async with client._maker() as db:
        db.add(Transaction(job_id=job2, amount_kurus=9_000_000_00, currency="USD", type="income",
                           category="revenue", description="dolar", transaction_date=datetime.now(UTC) - timedelta(days=1)))
        row = await db.get(DecisionLog, decision["id"])
        row.created_at = datetime.now(UTC) - timedelta(days=2)
        await db.commit()
    res = await client.post(f"/api/v1/decisions/{decision['id']}/outcome", json={}, headers=headers)
    actual = res.json()["data"]["actual"]
    assert actual["realized_net_kurus"] == 300_000_00 and actual["currency"] == "TRY"
    assert actual["other_currencies"] == [
        {"currency": "USD", "income_kurus": 9_000_000_00, "expense_kurus": 0, "transactions": 1}]


def test_counterparty_suggestions_rank_on_base_amounts_and_keep_each_currency_apart():
    from app.services.related_party import group_counterparties

    out = group_counterparties(
        [("Alfa Ltd", 2, 100_000, "TRY"), ("Alfa Ltd", 1, 90_000_000, "USD"), ("Beta Ltd", 4, 50_000, "TRY")],
        set(), base="TRY",
    )
    alfa = next(g for g in out if g["vendor"] == "Alfa Ltd")
    assert alfa["total_kurus"] == 100_000                                        # the dollars are not in it
    assert alfa["totals_by_currency"] == {"TRY": 100_000, "USD": 90_000_000}
    assert [g["vendor"] for g in out] == ["Beta Ltd", "Alfa Ltd"]                # by count, then base amount


def test_the_morning_brief_says_what_it_left_out_and_lets_the_figure_through_the_number_check():
    from app.services.morning_brief import MorningFacts, facts_lines

    facts = MorningFacts(
        data_date="2026-02-01", job_count=1, critical_count=0, high_count=0,
        revenue_cents=140_000, expense_cents=30_000, period_start="2026-01", period_end="2026-02",
        period_months=2, other_currencies=(("USD", 5_000_000, 1_240_000),), currency="TRY",
    )
    lines = facts_lines(facts)
    assert any("12.400,00 USD gider" in line and "çevrilmedi" in line for line in lines)
    assert 1_240_000 in facts.allowed_cents() and facts.profit_cents == 110_000   # the dollars are not in the profit


def test_an_amount_with_no_currency_is_the_plain_number_labelled_unknown_never_lira():
    from app.core.currency_totals import fmt_money

    for missing in (None, "", "  "):
        text = fmt_money(123_456, missing)
        assert text == "1.234,56 (para birimi bilinmiyor)"
        assert "₺" not in text and "TRY" not in text
    assert fmt_money(123_456, "try") == "₺1.234,56"
    assert fmt_money(-5_00, "usd") == "-5,00 USD"
