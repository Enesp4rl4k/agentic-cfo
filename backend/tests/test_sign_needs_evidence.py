# ruff: noqa: F811
"""The sign of an amount decides a direction only with evidence; a row outside the balance chain is held.

Review of PR #124: `sign_is_informative` was a FILE-LEVEL heuristic. One signed amount column with no balance, 27
positive rows and 3 negative ones, was booked as 27 income / 3 expense with no hold: an expense list with a few
reversals came out inverted. One rule now, for mixed, all-positive and all-negative files alike:

  the sign decides only if (a) a balance chain verifies "minus = out, plus = in", (b) a direction column says so
  (handled elsewhere), or (c) this organisation already answered for this file format. Otherwise the whole file
  is asked ONCE, its rows wait, and the answer is remembered per organisation and format.

And a row with no balance among rows that have one is not a link of the chain: it is held, and the statement is
never called "doğrulandı".
"""
from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.decision import Decision, DecisionKind
from app.models.transaction import Transaction
from app.parsers.direction import SIGN_UNCONFIRMED
from app.services.held_direction import apply_to_rows
from app.services.ingest.hold import row_reasons
from app.services.ingest.rows import _try_parse_csv
from tests.api_helpers import kullanici
from tests.test_ingest_no_silent_defaults import (  # noqa: F401  (a fixture, reused below)
    NL,
    _upload,
    ortam,
)

HEADER = "Tarih;Açıklama;Tutar;Para Birimi"


def _csv(header: str, *rows: str) -> str:
    return NL.join([header, *rows]) + NL


def _expense_list(positives: int = 27, negatives: int = 3, month: str = "03") -> str:
    """Amounts written positive for money spent, with a few reversals written negative: no balance column."""
    rows = [f"{d:02d}.{month}.2026;Gider {d};{d * 10},00;TRY" for d in range(1, positives + 1)]
    rows += [f"{positives + d:02d}.{month}.2026;İade {d};-{d * 5},00;TRY" for d in range(1, negatives + 1)]
    return _csv(HEADER, *rows)


def totals(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    inflow = sum(r["amount_cents"] for r in rows if r["type"] == "income")
    outflow = sum(r["amount_cents"] for r in rows if r["type"] == "expense")
    return inflow, outflow, sum(1 for r in rows if r["type"] not in ("income", "expense"))


# ── the reviewer's case ──────────────────────────────────────────────────────────────────────────────────────

def test_27_positive_and_3_negative_rows_with_no_balance_are_held_not_booked_as_27_income() -> None:
    rows = _try_parse_csv(_expense_list()) or []
    assert len(rows) == 30 and totals(rows) == (0, 0, 30)                    # nothing booked
    assert {r["direction_file"]["reason"] for r in rows} == {SIGN_UNCONFIRMED}
    assert len({r["direction_file"]["key"] for r in rows}) == 1 and sum("direction_question" in r for r in rows) == 1
    assert all(row_reasons({**r, "currency": "TRY"}) == ["direction_file_unknown"] for r in rows)


def test_the_question_shows_a_preview_with_a_row_of_each_sign_and_both_readings_totals() -> None:
    rows = _try_parse_csv(_expense_list()) or []
    q = next(r["direction_question"] for r in rows if "direction_question" in r)
    amounts = [s["amount"] for s in q["samples"]]
    assert len(q["samples"]) == 3 and any(a.startswith("-") for a in amounts) and any(not a.startswith("-") for a in amounts)
    plus = sum(d * 1000 for d in range(1, 28))
    minus = sum(d * 500 for d in range(1, 4))
    assert q["totals"]["as_read"] == {"income": plus, "expense": minus}
    assert q["totals"]["inverted"] == {"income": minus, "expense": plus}
    assert q["uniform"] is False and q["negative_rows"] == 3
    assert [(m["label"], m["means"]) for m in q["mapping"]] == [("-", "expense"), ("+", "income")]


def test_the_answer_expense_list_books_27_expenses_and_3_reversals() -> None:
    rows = _try_parse_csv(_expense_list()) or []
    apply_to_rows(rows, "sign_inverted")
    assert totals(rows) == (sum(d * 500 for d in range(1, 4)), sum(d * 1000 for d in range(1, 28)), 0)
    assert sum(r["type"] == "expense" for r in rows) == 27 and sum(r["type"] == "income" for r in rows) == 3


# ── the three cases are one rule ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rows", [
    [f"{d:02d}.03.2026;Satış {d};{d},00;TRY" for d in range(1, 6)],        # no negatives at all
    [f"{d:02d}.03.2026;Ödeme {d};-{d},00;TRY" for d in range(1, 6)],       # every amount negative
])
def test_a_file_with_one_sign_is_asked_by_the_same_rule(rows: list[str]) -> None:
    parsed = _try_parse_csv(_csv(HEADER, *rows)) or []
    assert totals(parsed) == (0, 0, 5) and {r["direction_file"]["reason"] for r in parsed} == {SIGN_UNCONFIRMED}
    assert next(r["direction_question"] for r in parsed if "direction_question" in r)["uniform"] is True


def test_a_balance_chain_that_verifies_the_signs_books_without_a_question() -> None:
    lines = ["Tarih;Açıklama;Tutar;Bakiye;Para Birimi"]
    balance = 10_000
    for d in range(1, 31):
        amount = -d if d % 4 else d * 3
        balance += amount
        lines.append(f"{d:02d}.03.2026;Hareket {d};{amount},00;{balance},00;TRY")
    rows = _try_parse_csv(NL.join(lines) + NL) or []
    assert totals(rows)[2] == 0 and not any("direction_file" in r for r in rows)
    assert sum(r["type"] == "expense" for r in rows) == sum(1 for d in range(1, 31) if d % 4)


def test_a_chain_that_shows_the_opposite_of_the_signs_holds_the_file_for_that_reason() -> None:
    lines, balance = ["Tarih;Açıklama;Tutar;Bakiye;Para Birimi"], 10_000
    for d in range(1, 11):
        amount = d * 10 if d % 2 else -d * 10            # in this file the positives REDUCE the balance
        balance -= amount
        lines.append(f"{d:02d}.03.2026;Hareket {d};{amount},00;{balance},00;TRY")
    rows = _try_parse_csv(NL.join(lines) + NL) or []
    assert totals(rows)[:2] == (0, 0) and {r["direction_file"]["reason"] for r in rows} == {"balance_contradicts"}


# ── a row outside the chain ──────────────────────────────────────────────────────────────────────────────────

def _chain_with_a_row_without_balance() -> str:
    rows, balance = [], 10_000
    for d in range(1, 9):
        balance += -50 if d % 2 else 80
        rows.append(f"{d:02d}.02.2026;Hareket {d};{-50 if d % 2 else 80},00;{balance},00;TRY")
    rows.insert(4, "01.02.2026;Düzenleme komisyon;1.250,00;;TRY")
    return _csv("Tarih;Açıklama;Tutar;Bakiye;Para Birimi", *rows)


def test_a_table_row_with_no_balance_among_rows_that_have_one_is_held_outside_the_chain() -> None:
    rows = _try_parse_csv(_chain_with_a_row_without_balance()) or []
    odd = [r for r in rows if r.get("outside_chain")]
    assert [r["description"] for r in odd] == ["Düzenleme komisyon"] and odd[0]["type"] is None   # never income by its sign
    assert row_reasons({**odd[0], "currency": "TRY"}) == ["balance_outside_chain"]
    assert sum(r["type"] in ("income", "expense") for r in rows) == 8                              # the chain's rows book


GARANTI = (
    "GARANTİ BBVA\n"
    "01.02.2026  MAAŞ ÖDEMESİ  -1.000,00  9.000,00\n"
    "02.02.2026  EFT GELEN  2.000,00  11.000,00\n"
    "03.02.2026  FATURA  -500,00  10.500,00\n"
    "04.02.2026  KİRA  -3.000,00  7.500,00\n"
    "05.02.2026  TAHSİLAT  4.000,00  11.500,00\n"
)
FOOTER = "Düzenleme tarihi 01.02.2026 14:30 komisyon 1.250,00\n"


def test_a_footer_like_line_in_a_text_statement_is_held_and_the_statement_is_not_called_verified() -> None:
    from app.parsers.banks.garanti import GarantiParser
    from app.services.ingest.door import read_text_statement
    from app.services.ingest.okuma import reconcile
    from app.services.ingest.summary import ingest_summary

    door = read_text_statement(GarantiParser(), GARANTI + FOOTER, "garanti.txt")
    held = [r for r in door.rows if r.get("outside_chain")]
    assert len(held) == 1 and "komisyon" in held[0]["description"] and held[0]["type"] is None
    assert row_reasons({**held[0], "currency": "TRY"}) == ["balance_outside_chain"]
    assert door.ledger.balance_check == "unverified" and door.ledger.outside_chain == 1
    booked = [r for r in door.rows if r["type"] in ("income", "expense")]
    counts, _ = reconcile(door.ledger.as_dict(), len(booked), len(held))
    summary = ingest_summary(booked, {"new": 1}, counts)
    assert summary["outside_chain"] == 1 and summary["balance_check"] == "unverified"
    assert "1 satır bakiye zincirinin dışında kaldı" in summary["summary"]
    assert "bakiye zinciriyle doğrulandı" not in summary["summary"]


def test_a_text_statement_whose_rows_all_have_balances_is_still_verified() -> None:
    from app.parsers.banks.garanti import GarantiParser
    from app.services.ingest.door import read_text_statement

    door = read_text_statement(GarantiParser(), GARANTI, "garanti.txt")
    assert door.ledger.balance_check == "verified" and door.ledger.outside_chain == 0
    assert all(r["type"] in ("income", "expense") for r in door.rows)


def test_a_text_statement_with_signs_and_no_chain_is_asked_too() -> None:
    from app.parsers.banks.garanti import GarantiParser
    from app.services.ingest.door import read_text_statement

    text = "GARANTİ BBVA\n01.02.2026  KİRA  -3.000,00\n02.02.2026  TAHSİLAT  4.000,00\n03.02.2026  FATURA  -500,00\n"
    door = read_text_statement(GarantiParser(), text, "garanti.txt")
    assert {r["direction_file"]["reason"] for r in door.rows} == {SIGN_UNCONFIRMED} and all(r["type"] is None for r in door.rows)


# ── the answer is remembered for this organisation and format, and recorded ───────────────────────────────────

@pytest_asyncio.fixture
async def env(ortam):
    yield ortam


async def _questions(client, headers) -> list[dict[str, Any]]:
    return (await client.get("/api/v1/held-rows/file-questions", headers=headers)).json()["data"]["files"]


async def _booked(client, job_id: str) -> list[Transaction]:
    async with client._maker() as db:
        return list((await db.execute(select(Transaction).where(Transaction.job_id == job_id))).scalars())


@pytest.mark.real_currency
async def test_one_question_then_the_next_file_of_the_same_format_books_without_asking(env, monkeypatch) -> None:
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "sg1@x.com")
    job1, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_expense_list(), name="mart.csv")
    assert await _booked(client, job1) == []
    asked = await _questions(client, headers)
    assert len(asked) == 1 and asked[0]["reason"] == "sign_unconfirmed" and asked[0]["rows"] == 30
    assert asked[0]["options"] == ["mixed", "sign_correct", "sign_inverted"]
    done = await client.post("/api/v1/held-rows/file-direction", headers=headers, json={
        "job_id": job1, "file_key": asked[0]["file_key"], "answer": "sign_inverted"})
    data = done.json()["data"]
    assert done.status_code == 200 and data["resolved"] == 30 and data["remembered"]
    booked = await _booked(client, job1)
    assert sum(t.type == "expense" for t in booked) == 27 and sum(t.type == "income" for t in booked) == 3

    async with client._maker() as db:      # the file's answer and the format's memory are both decisions
        kinds = {d.kind for d in (await db.execute(select(Decision))).scalars()}
    assert {DecisionKind.FILE_DIRECTION_ANSWER.value, DecisionKind.DIRECTION_MAPPING.value} <= kinds

    job2, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_expense_list(20, 2, "04"), name="nisan.csv")
    assert await _questions(client, headers) == []                         # the memory is applied, nothing is asked
    again = await _booked(client, job2)
    assert sum(t.type == "expense" for t in again) == 20 and sum(t.type == "income" for t in again) == 2
    assert all(t.category for t in again)

    headers2, org2, _ = await kullanici(client, "sg1b@x.com")              # another organisation: asked
    job3, _ = await _upload(client, tmp_path, monkeypatch, [], org2, content=_expense_list(), name="mart.csv")
    assert await _booked(client, job3) == [] and len(await _questions(client, headers2)) == 1


@pytest.mark.real_currency
async def test_a_remembered_inverted_answer_meets_a_chain_that_agrees_and_the_balance_books_the_file(env, monkeypatch) -> None:
    client, tmp_path = env
    headers, org_id, _ = await kullanici(client, "sg2@x.com")
    hdr = "Tarih;Açıklama;Tutar;Bakiye;Para Birimi"
    first = [f"{d:02d}.03.2026;Gider {d};{d * 10},00;;TRY" for d in range(1, 8)]
    first += ["08.03.2026;İade;-30,00;;TRY", "09.03.2026;İade;-40,00;4.040,00;TRY"]
    job1, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_csv(hdr, *first), name="a.csv")
    asked = (await _questions(client, headers))[0]
    assert asked["reason"] == "sign_unconfirmed"            # one balance is not a chain: it proves nothing about the signs
    await client.post("/api/v1/held-rows/file-direction", headers=headers,
                      json={"job_id": job1, "file_key": asked["file_key"], "answer": "sign_inverted"})

    balance, rows = 10_000, []
    for d in range(1, 8):                                   # positives reduce the balance: the chain says what was remembered
        balance -= d * 10
        rows.append(f"{d:02d}.04.2026;Gider {d};{d * 10},00;{balance},00;TRY")
    balance += 30
    rows.append(f"08.04.2026;İade;-30,00;{balance},00;TRY")
    job2, _ = await _upload(client, tmp_path, monkeypatch, [], org_id, content=_csv(hdr, *rows), name="b.csv")
    assert [q for q in await _questions(client, headers) if q["job_id"] == job2] == []
    booked = await _booked(client, job2)
    assert sum(t.type == "expense" for t in booked) == 7 and sum(t.type == "income" for t in booked) == 1


# ── property: random mixes of signs, random footer-like lines ────────────────────────────────────────────────

@pytest.mark.parametrize("seed", range(40))
def test_no_mix_of_signs_without_evidence_is_ever_booked_and_every_injected_footer_is_held(seed: int) -> None:
    import random

    rng = random.Random(seed)
    n = rng.randint(3, 40)
    signs = [rng.choice((-1, 1)) for _ in range(n)]
    plain = _csv(HEADER, *[f"{1 + i % 28:02d}.03.2026;Hareket {i};{'-' if s < 0 else ''}{10 + i},00;TRY" for i, s in enumerate(signs)])
    rows = _try_parse_csv(plain) or []
    assert len(rows) == n and totals(rows)[:2] == (0, 0)             # whatever the share of each sign: asked, not booked
    assert {r["direction_file"]["reason"] for r in rows} == {SIGN_UNCONFIRMED}

    balance, chain = 10_000, []
    for i, s in enumerate(signs):
        balance += s * (10 + i)
        chain.append(f"{1 + i % 28:02d}.03.2026;Hareket {i};{s * (10 + i)},00;{balance},00;TRY")
    footers = rng.randint(1, 4)
    for k in range(footers):
        chain.insert(rng.randint(1, len(chain) - 1), f"01.03.2026;Düzenleme {k};{100 + k},00;;TRY")
    parsed = _try_parse_csv(_csv("Tarih;Açıklama;Tutar;Bakiye;Para Birimi", *chain)) or []
    held = [r for r in parsed if r.get("outside_chain")]
    assert len(parsed) == n + footers and len(held) == footers and all(r["type"] is None for r in held)
    assert sum(r["type"] in ("income", "expense") for r in parsed) == n  # the verified chain's own rows are booked
