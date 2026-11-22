# ruff: noqa: F811
"""Review of #126: a remembered sign answer is applied silently only to the SAME SOURCE.

Generic header words ("Tarih;Açıklama;Tutar") are shared by unrelated sources of one organisation. A bank export
answered "minus = out" must not book a Market expense list with the same header as income. Silent only with the same
header signature AND the same stated account identity; otherwise asked again with the earlier answer shown (one
click, a recorded decision); an explicit standing rule is the only way an identity-less file passes silently.
Also: a verifying chain beats a memory and says so; daily-balance formats verify by segments; the opening row.
"""
from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.decision import Decision, DecisionKind
from app.models.transaction import Transaction
from app.services.ingest.hold import row_reasons
from app.services.ingest.rows import _try_parse_csv
from tests.api_helpers import kullanici
from tests.test_ingest_no_silent_defaults import (  # noqa: F401  (a fixture, reused below)
    NL,
    _upload,
    ortam,
)

HEADER = "Tarih;Açıklama;Tutar;Para Birimi"
ACCOUNT = "AKBANK Hesap No: 1234567"


def _csv(header: str, *rows: str) -> str:
    return NL.join([header, *rows]) + NL


def _bank_export() -> str:
    """Source A: a bank export. 5 collections written positive, 4 payments written negative."""
    return _csv(HEADER, *[f"{d:02d}.03.2026;Tahsilat {d};{d * 100},00;TRY" for d in range(1, 6)],
                *[f"{5 + d:02d}.03.2026;Ödeme {d};-{d * 50},00;TRY" for d in range(1, 5)])


def _market_list(month: str = "04") -> str:
    """Source B: an expense list with the SAME header. 7 purchases written positive, 3 reversals negative."""
    return _csv(HEADER, *[f"{d:02d}.{month}.2026;Market {d};{d * 20},00;TRY" for d in range(1, 8)],
                *[f"{7 + d:02d}.{month}.2026;Iade {d};-{d * 10},00;TRY" for d in range(1, 4)])


@pytest_asyncio.fixture
async def env(ortam):
    yield ortam


async def _questions(client, headers) -> list[dict[str, Any]]:
    return (await client.get("/api/v1/held-rows/file-questions", headers=headers)).json()["data"]["files"]


async def _booked(client, job_id: str) -> list[Transaction]:
    async with client._maker() as db:
        return list((await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars())


async def _answer(client, headers, job_id, key, answer, **extra):
    return await client.post("/api/v1/held-rows/file-direction", headers=headers,
                             json={"job_id": job_id, "file_key": key, "answer": answer, **extra})


async def _decisions(client, kind: DecisionKind) -> list[Decision]:
    async with client._maker() as db:
        return list((await db.execute(select(Decision).where(Decision.kind == kind.value))).scalars())


@pytest.mark.real_currency
async def test_the_reviewers_leak_is_closed_a_second_source_with_the_same_headers_is_asked_with_the_earlier_answer(env, monkeypatch) -> None:
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "ss1@x.com")
    job_a, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_bank_export(), name="banka.csv")
    key_a = (await _questions(client, headers))[0]["file_key"]
    assert (await _answer(client, headers, job_a, key_a, "sign_correct")).json()["data"]["remembered"]

    job_b, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_market_list(), name="market.csv")
    assert await _booked(client, job_b) == []                               # NOT booked as 7 income / 3 expense
    (asked,) = [q for q in await _questions(client, headers) if q["job_id"] == job_b]
    assert asked["reason"] == "sign_unconfirmed" and asked["previous"]["answer"] == "sign_correct"
    assert asked["question"]["previous"]["answer"] == "sign_correct" and asked["previous"]["same_account"] is False

    done = await _answer(client, headers, job_b, asked["file_key"], "sign_inverted", remember=False)   # B is an expense list
    assert done.json()["data"]["resolved"] == 10
    booked = await _booked(client, job_b)
    assert sum(t.type == "expense" for t in booked) == 7 and sum(t.type == "income" for t in booked) == 3


@pytest.mark.real_currency
async def test_confirming_the_earlier_answer_is_one_click_and_a_recorded_decision(env, monkeypatch) -> None:
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "ss2@x.com")
    job_a, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_bank_export(), name="a.csv")
    await _answer(client, headers, job_a, (await _questions(client, headers))[0]["file_key"], "sign_correct")
    job_b, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_bank_export().replace(".03.2026", ".04.2026"), name="b.csv")
    (asked,) = [q for q in await _questions(client, headers) if q["job_id"] == job_b]
    assert (await _answer(client, headers, job_b, asked["file_key"], asked["previous"]["answer"])).status_code == 200
    answers = await _decisions(client, DecisionKind.FILE_DIRECTION_ANSWER)
    assert sorted(d.after["confirmed_previous"] for d in answers) == [False, True]


@pytest.mark.real_currency
async def test_another_account_or_an_identity_on_one_side_only_is_asked_not_applied(env, monkeypatch) -> None:
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "ss3@x.com")
    job_a, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=NL.join([ACCOUNT, _bank_export()]), name="a.csv")
    await _answer(client, headers, job_a, (await _questions(client, headers))[0]["file_key"], "sign_correct")
    job_b, _ = await _upload(client, tmp_path, monkeypatch, [], org_id,
                             content=NL.join(["AKBANK Hesap No: 7654321", _bank_export().replace(".03.2026", ".04.2026")]), name="b.csv")
    job_c, _ = await _upload(client, tmp_path, monkeypatch, [], org_id,
                             content=_bank_export().replace(".03.2026", ".05.2026"), name="c.csv")
    asked = {q["job_id"]: q for q in await _questions(client, headers)}
    assert set(asked) == {job_b, job_c} and all(q["previous"]["answer"] == "sign_correct" for q in asked.values())
    assert await _booked(client, job_b) == [] and await _booked(client, job_c) == []


@pytest.mark.real_currency
async def test_a_standing_rule_is_explicit_recorded_and_revocable(env, monkeypatch) -> None:
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "ss4@x.com")
    job_a, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_market_list(), name="a.csv")
    key = (await _questions(client, headers))[0]["file_key"]
    assert (await _answer(client, headers, job_a, key, "sign_inverted", standing=True)).json()["data"]["remembered"]
    mappings = (await client.get("/api/v1/held-rows/direction-mappings", headers=headers)).json()["data"]["mappings"]
    assert len(mappings) == 1 and mappings[0]["standing"] is True
    job_b, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_market_list("05"), name="b.csv")
    assert await _questions(client, headers) == []                          # the standing rule applies, silently
    assert sum(t.type == "expense" for t in await _booked(client, job_b)) == 7
    assert (await client.delete(f"/api/v1/held-rows/direction-mappings/{mappings[0]['id']}", headers=headers)).status_code == 200
    await _upload(client, tmp_path, monkeypatch, [], org_id, content=_market_list("06"), name="c.csv")
    assert len(await _questions(client, headers)) == 1                      # revoked: asked again
    outcomes = {d.outcome for d in await _decisions(client, DecisionKind.DIRECTION_MAPPING)}
    assert {"remembered", "revoked"} <= outcomes


@pytest.mark.real_currency
async def test_an_answer_without_the_standing_choice_never_becomes_one(env, monkeypatch) -> None:
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "ss5@x.com")
    job_a, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_market_list(), name="a.csv")
    await _answer(client, headers, job_a, (await _questions(client, headers))[0]["file_key"], "sign_inverted")
    await _upload(client, tmp_path, monkeypatch, [], org_id, content=_market_list("05"), name="b.csv")
    (q,) = await _questions(client, headers)
    assert q["previous"]["answer"] == "sign_inverted"                       # asked, with the earlier answer pre-selected


# ── a verifying chain beats a memory, and says so ──────────────────────────────────────────────────────────

def _plain_chain_file(month: str) -> str:
    lines, balance = ["Tarih;Açıklama;Tutar;Bakiye;Para Birimi"], 10_000
    for d in range(1, 8):
        amount = d * 10 if d % 2 else -d * 10
        balance += amount
        lines.append(f"{d:02d}.{month}.2026;Hareket {d};{amount},00;{balance},00;TRY")
    return NL.join([ACCOUNT, *lines]) + NL


@pytest.mark.real_currency
async def test_a_chain_that_verifies_the_plain_signs_beats_a_remembered_inverted_answer_and_flags_it(env, monkeypatch) -> None:
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "ss6@x.com")
    hdr = "Tarih;Açıklama;Tutar;Bakiye;Para Birimi"
    first = [f"{d:02d}.03.2026;Gider {d};{d * 10},00;;TRY" for d in range(1, 8)] + ["08.03.2026;İade;-30,00;4.040,00;TRY"]
    job1, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=NL.join([ACCOUNT, hdr, *first]) + NL, name="a.csv")
    await _answer(client, headers, job1, (await _questions(client, headers))[0]["file_key"], "sign_inverted")

    job2, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_plain_chain_file("04"), name="b.csv")
    assert [q for q in await _questions(client, headers) if q["job_id"] == job2] == []
    booked = await _booked(client, job2)
    assert sum(t.type == "expense" for t in booked) == 3 and sum(t.type == "income" for t in booked) == 4   # by the chain
    overridden = [d for d in await _decisions(client, DecisionKind.DIRECTION_MAPPING) if d.outcome == "overridden"]
    assert len(overridden) == 1 and "balance chain" in (overridden[0].reason or "")
    (mapping,) = (await client.get("/api/v1/held-rows/direction-mappings", headers=headers)).json()["data"]["mappings"]
    assert mapping["flagged_at"] and "balance chain" in mapping["flagged_note"]    # visible where answers are listed


# ── daily-balance formats: segments ──────────────────────────────────────────────────────────────────────────

def _every_third(rows: int = 12, misread: int | None = None) -> str:
    """A balance only on every third row. `misread`: the statement prints a wrong amount for that row (a bank's error)."""
    lines, balance = ["Tarih;Açıklama;Tutar;Bakiye;Para Birimi"], 50_000
    for d in range(1, rows + 1):
        amount = d * 10 if d % 3 else -d * 25
        balance += amount
        shown = f"{balance},00" if d % 3 == 0 else ""
        lines.append(f"{(d - 1) % 28 + 1:02d}.{3 + (d - 1) // 28:02d}.2026;Hareket {d};{amount + (5 if d == misread else 0)},00;{shown};TRY")
    return NL.join(lines) + NL


def test_a_balance_printed_every_third_row_verifies_by_segments_and_books_by_sign() -> None:
    rows = _try_parse_csv(_every_third()) or []
    assert len(rows) == 12 and not any("direction_file" in r for r in rows)
    placed = [r for r in rows if r["type"] in ("income", "expense")]
    # rows 1-2 come BEFORE the first balance row (which opens the chain): outside it, held; the rest sit in reconciled segments
    assert {r["description"] for r in rows if r.get("outside_chain")} == {"Hareket 1", "Hareket 2"}
    assert len(placed) == 10 and not any(r.get("balance_mismatch") for r in rows)
    assert sum(r["type"] == "expense" for r in placed) == 4                  # d = 3, 6, 9, 12


def test_a_segment_that_does_not_reconcile_is_held_and_named() -> None:
    rows = _try_parse_csv(_every_third(rows=36, misread=20)) or []
    broken = [r for r in rows if r.get("balance_mismatch")]
    assert {r["description"] for r in broken} == {"Hareket 19", "Hareket 20", "Hareket 21"}   # which row is wrong is unknown
    assert sum(r["type"] in ("income", "expense") for r in rows) == 36 - 3 - 2               # the rest of the chain books
    assert all(r["type"] is None and row_reasons({**r, "currency": "TRY"}) == ["balance_mismatch"] for r in broken)


def test_rows_after_the_last_balance_row_are_outside_the_chain() -> None:
    lines = _every_third().rstrip(NL).split(NL)
    lines.append("13.03.2026;Hareket 13;130,00;;TRY")
    rows = _try_parse_csv(NL.join(lines) + NL) or []
    assert {r["description"] for r in rows if r.get("outside_chain")} == {"Hareket 1", "Hareket 2", "Hareket 13"}


# ── the opening row ──────────────────────────────────────────────────────────────────────────────────────────

def _with_first_row(first: str) -> str:
    rows, balance = [first], 10_000
    for d in range(2, 8):
        amount = -40 * d if d % 2 else 90
        balance += amount
        rows.append(f"{d:02d}.05.2026;Hareket {d};{amount},00;{balance},00;TRY")
    return _csv("Tarih;Açıklama;Tutar;Bakiye;Para Birimi", *rows)


def test_a_first_row_with_a_balance_and_no_amount_is_the_opening_balance_not_a_money_row() -> None:
    from app.services.ingest.okuma import ReadLedger

    ledger = ReadLedger()
    rows = _try_parse_csv(_with_first_row("01.05.2026;Açılış;;10.000,00;TRY"), ledger=ledger) or []
    assert len(rows) == 6 and not any(r.get("outside_chain") or r.get("balance_mismatch") for r in rows)
    assert ledger.summary_skipped == 1 and ledger.summary_lines[0]["description"] == "Açılış"
    assert all(r["type"] in ("income", "expense") for r in rows)


def test_a_first_row_with_an_amount_and_no_balance_is_outside_the_chain_and_held() -> None:
    rows = _try_parse_csv(_with_first_row("01.05.2026;Komisyon;250,00;;TRY")) or []
    odd = [r for r in rows if r.get("outside_chain")]
    assert [r["description"] for r in odd] == ["Komisyon"] and odd[0]["type"] is None
    assert sum(r["type"] in ("income", "expense") for r in rows) == 6


# ── answering a sign question reads the statement's balance chain again ──────────────────────────────────────

@pytest.mark.real_currency
async def test_a_sign_answer_triggers_the_balance_reverification_and_records_it(env) -> None:
    from app.models.held_transaction import HeldTransaction
    from app.services import held_direction
    from tests.test_balance_reverify import FOUR, _held_statement, _reverifications, _rows

    client, _ = env
    _, org_id, user_id = await kullanici(client, "ss7@x.com")
    job_id, _ids = await _held_statement(client, org_id, _rows(*FOUR), direction_file=True)
    async with client._maker() as db:
        for row in (await db.execute(select(HeldTransaction).where(HeldTransaction.job_id == job_id))).scalars():
            row.payload = {**row.payload, "direction_file": {**row.payload["direction_file"], "reason": "sign_unconfirmed",
                                                               "read": "expense", "balance": "income"}}
        await db.commit()
    async with client._maker() as db:
        out = await held_direction.answer_file(db, org_id, user_id, job_id, "k1", "sign_correct", remember=False)
    assert out["resolved"] == 4 and [p["state"] for p in out["balance_proof"]] == ["verified"]
    (decision,) = await _reverifications(client, job_id)
    assert decision.outcome == "verified" and decision.decided_via == "system"
    answered = await _decisions(client, DecisionKind.FILE_DIRECTION_ANSWER)
    assert len(answered) == 1 and answered[0].after["balance_reverifications"] == [decision.id]
