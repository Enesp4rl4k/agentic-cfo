"""A statement that prints its balance on some rows is proven segment by segment (PR #126 follow-up).

Figures written by hand. The balance between two printed balances equals the signed rows after the first one up to
and including the second; at least two segments with a non-zero sum tell the sign convention apart. `known` only
with no row outside the chain; otherwise `assumed` with the reason; none discriminating is unproven.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision import Decision, DecisionKind
from app.models.direction_mapping import DirectionMapping
from app.models.held_transaction import HeldTransaction
from app.services import held_direction
from app.services.balance_reverify import snapshot_chain
from app.services.bank_balance import assess, closing_balance, statement_extent
from app.services.cash_radar import compute_cash_radar
from app.services.coverage import extents_for
from app.services.ingest.rows import _try_parse_csv
from app.services.runway import opening_cash_for
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_sign_discriminating import _csv, _pairs

NO_VERDICT: dict[str, Any] = {"balance_check": None, "unaccounted": 0}
ANCHOR = date(2026, 3, 14)
# (day, amount, type, balance): balances only on rows 0, 2, 4, 6. 1.000,00 opening.
SPEC: list[tuple[str, int, str, int | None]] = [
    ("2026-03-02", 100_00, "expense", 900_00),
    ("2026-03-03", 300_00, "income", None),
    ("2026-03-03", 50_00, "expense", 1_150_00),
    ("2026-03-04", 200_00, "income", None),
    ("2026-03-04", 100_00, "expense", 1_250_00),
    ("2026-03-05", 400_00, "expense", None),
    ("2026-03-05", 150_00, "income", 1_000_00),
]


def _rows(spec: list[tuple[str, int, str, int | None]] = SPEC) -> list[dict[str, Any]]:
    return [
        {"transaction_date": d, "amount_cents": a, "type": t, "balance_cents": b, "currency": "TRY",
         "description": f"satır {i}", "file_pos": i, "confidence": 0.95, "category": "other_expense"}
        for i, (d, a, t, b) in enumerate(spec)
    ]


# ── the arithmetic ───────────────────────────────────────────────────────────────────────────────────────────

def test_a_fully_reconciling_daily_balance_statement_is_known_to_its_last_printed_balance() -> None:
    proof = assess(_rows(), NO_VERDICT)
    assert (proof["state"], proof["basis"], proof["reason"]) == ("verified", "known", None)
    assert (proof["segments"], proof["discriminating"], proof["outside"]) == (3, 3, 0)
    assert closing_balance(_rows()) == {"date": "2026-03-05", "balance_cents": 1_000_00}
    assert statement_extent(_rows()) == {"start": "2026-03-02", "end": "2026-03-05", "opening_cents": 1_000_00, "closing_cents": 1_000_00}


def test_a_newest_first_daily_balance_statement_is_the_same_statement() -> None:
    reversed_rows = _rows()[::-1]
    assert assess(reversed_rows, NO_VERDICT)["basis"] == "known"
    assert closing_balance(reversed_rows) == {"date": "2026-03-05", "balance_cents": 1_000_00}


def test_the_closing_balance_the_radar_reads_is_the_last_printed_one_not_the_last_row() -> None:
    rows = _rows() + _rows([("2026-03-06", 70_00, "expense", None)])[:1]
    rows[-1]["file_pos"] = 7
    proof = assess(rows, NO_VERDICT)
    assert (proof["basis"], proof["outside"]) == ("assumed", 1)
    assert proof["reason"] == "1 satır bakiye zincirinin dışında kaldı; bakiye bu satırları doğrulamıyor"
    assert closing_balance(rows) == {"date": "2026-03-05", "balance_cents": 1_000_00}


def test_a_row_before_the_first_printed_balance_makes_it_assumed_and_the_opening_unknown() -> None:
    rows = _rows([("2026-03-01", 100_00, "income", None), *SPEC])
    for i, r in enumerate(rows):
        r["file_pos"] = i
    # The first row's movement is part of the first printed balance, which nothing in the file can place.
    rows[1]["balance_cents"] = 900_00
    proof = assess(rows, NO_VERDICT)
    assert (proof["basis"], proof["outside"]) == ("assumed", 1)
    extent = statement_extent(rows)
    assert extent is not None and "opening_cents" not in extent and extent["start"] == "2026-03-02"


def test_a_footer_line_between_two_real_rows_is_outside_the_chain_never_inside_it() -> None:
    rows = _rows()
    rows.insert(3, {"transaction_date": "2026-03-03", "amount_cents": 9_99, "type": None, "balance_cents": None,
                    "currency": "TRY", "description": "Sayfa toplamı", "file_pos": 99})
    proof = assess(rows, NO_VERDICT)
    assert (proof["basis"], proof["outside"]) == ("assumed", 1)


def test_one_discriminating_segment_is_an_assumption_none_is_unproven() -> None:
    one = _rows([
        ("2026-03-02", 100_00, "expense", 900_00), ("2026-03-03", 100_00, "income", None),
        ("2026-03-03", 100_00, "expense", 900_00), ("2026-03-04", 300_00, "income", None),
        ("2026-03-04", 100_00, "expense", 1_100_00),
    ])
    proof = assess(one, NO_VERDICT)
    assert (proof["basis"], proof["discriminating"]) == ("assumed", 1)
    assert proof["reason"] == "yalnızca 1 bakiye aralığı satır yönlerini bakiyeyle ayırt ediyor"
    zero = _rows([
        ("2026-03-02", 100_00, "expense", 900_00), ("2026-03-03", 100_00, "income", None),
        ("2026-03-03", 100_00, "expense", 900_00), ("2026-03-04", 100_00, "income", None),
        ("2026-03-04", 100_00, "expense", 900_00),
    ])
    proof = assess(zero, NO_VERDICT)
    assert proof["basis"] is None and "ayırt edilemiyor" in proof["reason"]
    assert closing_balance(zero) is None and statement_extent(zero) is None


def test_a_segment_that_does_not_reconcile_proves_nothing() -> None:
    broken = _rows()
    broken[2]["balance_cents"] = 1_149_00
    proof = assess(broken, NO_VERDICT)
    assert proof["basis"] is None and proof["reason"] == "bakiye aralıkları satır tutarlarıyla uyuşmuyor"
    assert closing_balance(broken) is None


def test_the_opposite_convention_does_not_reconcile() -> None:
    flipped = [{**r, "type": "income" if r["type"] == "expense" else "expense"} for r in _rows()]
    assert assess(flipped, NO_VERDICT)["basis"] is None


def test_a_row_inside_the_chain_whose_direction_nobody_placed_blocks_it() -> None:
    rows = _rows()
    rows[1]["type"] = None
    proof = assess(rows, NO_VERDICT)
    assert proof["basis"] is None and proof["reason"] == "zincirin içinde yönü belli olmayan satır var"


def test_the_readers_unverified_verdict_stands_for_three_segments_unless_a_person_has_answered() -> None:
    unverified = {"balance_check": "unverified", "unaccounted": 0}
    assert assess(_rows(), unverified)["reason"] == "okuyucu bakiye zincirini doğrulayamadı"
    assert assess(_rows(), unverified, recheck=True)["basis"] == "known"
    assert assess(_rows(), {"unaccounted": 2})["reason"] == "2 satır hesaba katılamadı"


def test_the_periodic_file_is_not_proven_by_either_order() -> None:
    # +300 / -100 every day, balance falling 200 a day: reads as newest-first with plus = in, but the dates say otherwise.
    rows = _try_parse_csv(_csv(*[
        line for day in range(1, 8) for line in (
            f"{day:02d}.03.2026;Hareket A{day};300,00;;TRY", f"{day:02d}.03.2026;Hareket B{day};-100,00;{10_000 - 200 * day},00;TRY")
    ])) or []
    assert assess(rows, NO_VERDICT)["basis"] != "known"


# ── through the real CSV reader ──────────────────────────────────────────────────────────────────────────────

def _every_third(first_row_prints_balance: bool, count: int = 30) -> str:
    """The reviewer's file: a balance on every third row (plus = out here, minus = in, to make the sign matter)."""
    lines, balance = [], 10_000
    amounts = [150, 90, 40, 220, 60, 75, 310, 25, 130, 80, 45, 190]
    for i in range(count):
        mag = amounts[i % len(amounts)]
        income = i % 2 == 0
        balance += mag if income else -mag
        printed = (i % 3 == 0) if first_row_prints_balance else (i % 3 == 2)
        shown = f"{balance},00" if printed else ""
        lines.append(f"{1 + i // 3:02d}.03.2026;Hareket {i};{mag if income else -mag},00;{shown};TRY")
    return _csv(*lines)


def test_the_reviewers_every_third_row_file_is_known_when_the_chain_covers_the_whole_file() -> None:
    rows = _try_parse_csv(_every_third(True, 28)) or []
    assert len(rows) == 28
    # 28 rows, balances on 0, 3, ..., 27: the last row prints one, so nothing is left outside.
    assert not any(r.get("outside_chain") or "direction_file" in r for r in rows)
    proof = assess(rows, NO_VERDICT)
    assert (proof["basis"], proof["outside"], proof["segments"]) == ("known", 0, 9)
    assert closing_balance(rows) is not None


def test_the_reviewers_every_third_row_file_with_trailing_rows_is_assumed_and_names_them() -> None:
    rows = _every_third(True, 30)                 # balances on 0..27; rows 28 and 29 print none
    parsed = _try_parse_csv(rows) or []
    held = [r for r in parsed if r.get("outside_chain")]
    assert len(held) == 2 and all(r["type"] is None for r in held)
    proof = assess(parsed, NO_VERDICT)
    assert proof["basis"] == "assumed" and proof["reason"].startswith("2 satır bakiye zincirinin dışında kaldı")
    assert closing_balance(parsed)["balance_cents"] == int(parsed[27]["balance_cents"])  # type: ignore[index]


def test_a_daily_balance_csv_whose_rows_open_with_no_balance_is_assumed_not_known() -> None:
    parsed = _try_parse_csv(_pairs([(100, 100)] * 6 + [(300, 100), (250, 50)])) or []
    proof = assess(parsed, NO_VERDICT)
    assert (proof["basis"], proof["outside"]) == ("assumed", 1)


def test_the_worker_reads_a_segment_statement_through_the_runway_opening_cash() -> None:
    opening = opening_cash_for({"transactions": _rows(), "ingest_counts": NO_VERDICT}, ANCHOR)
    assert opening is not None and opening["balance_cents"] == 1_000_00 and opening["basis"] == "known"
    (extent,) = extents_for({"transactions": _rows(), "ingest_counts": NO_VERDICT})
    assert (extent["start"], extent["end"], extent["closing_cents"]) == ("2026-03-02", "2026-03-05", 1_000_00)


# ── held rows answered: the statement is read again ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _held_whole(client, org_id: str, *, previous: str | None = None) -> str:
    """A completed daily-balance statement held whole for the sign question (sign_unconfirmed)."""
    rows = [{**r, "read": r["type"], "balance": "expense" if r["type"] == "income" else "income"} for r in _rows()]
    mark = {"key": "k1", "signature": "sig", "header_signature": "sig", "reason": "sign_unconfirmed", "identity": False,
            "account": "", "uniform": False, **({"previous": {"answer": previous}} if previous else {})}
    payloads = [
        {**{k: v for k, v in r.items() if k not in ("read", "balance")}, "type": None, "hold_reasons": ["direction_file_unknown"],
         "direction_file": {**mark, "read": r["read"], "balance": r["balance"]}}
        for r in rows
    ]
    counts = {"balance_check": "unverified", "unaccounted": 0, "read": len(rows)}
    stored = [{**r, "type": None} for r in _rows()]
    async with client._maker() as db:
        job = AnalysisJob(
            filename="gunluk.pdf", file_path="/gunluk.pdf", file_type="pdf", org_id=org_id, status=JobStatus.COMPLETED,
            result_metadata={
                "ingest": {**counts, "held": len(payloads), "processed": 0},
                "balance_proof": assess(stored, counts), "statement_chain": snapshot_chain(stored, payloads),
            },
        )
        db.add(job)
        await db.flush()
        for p in payloads:
            db.add(HeldTransaction(job_id=job.id, org_id=org_id, row_key=f"k{p['file_pos']}", payload=p))
        await db.commit()
        return job.id


async def _meta(client, job_id: str) -> dict[str, Any]:
    async with client._maker() as db:
        return dict((await db.get(AnalysisJob, job_id)).result_metadata)


async def _starting(client, org_id: str):
    async with client._maker() as db:
        return await compute_cash_radar(db, org_id, anchor_date=ANCHOR)


async def test_a_daily_balance_statement_held_whole_for_its_sign_feeds_the_radar_once_answered(client) -> None:
    _, org_id, user_id = await kullanici(client, "seg1@example.com")
    job_id = await _held_whole(client, org_id)
    before = await _starting(client, org_id)
    assert before.opening_cash is None and before.unproven_statements
    async with client._maker() as db:
        out = await held_direction.answer_file(db, org_id, user_id, job_id, "k1", "sign_correct", remember=False)
    assert out["resolved"] == 7 and [(p["state"], p["basis"]) for p in out["balance_proof"]] == [("verified", "known")]
    radar = await _starting(client, org_id)
    assert (radar.starting_cash_cents, radar.starting_cash_as_of) == (1_000_00, "2026-03-05")
    assert radar.opening_cash.basis == "known"
    meta = await _meta(client, job_id)
    assert meta["closing_balance"] == {"date": "2026-03-05", "balance_cents": 1_000_00}
    assert meta["statement_extent"]["opening_cents"] == 1_000_00
    async with client._maker() as db:
        (decision,) = (await db.execute(select(Decision).where(Decision.kind == DecisionKind.BALANCE_REVERIFICATION.value))).scalars()
    assert decision.outcome == "verified" and decision.after["closing_cents"] == 1_000_00


async def test_the_opposite_sign_answer_does_not_prove_a_daily_balance_statement(client) -> None:
    _, org_id, user_id = await kullanici(client, "seg2@example.com")
    job_id = await _held_whole(client, org_id)
    async with client._maker() as db:
        out = await held_direction.answer_file(db, org_id, user_id, job_id, "k1", "sign_inverted", remember=False)
    assert [p["state"] for p in out["balance_proof"]] == ["unverified"]
    assert (await _starting(client, org_id)).opening_cash is None


async def test_confirming_the_previous_answer_proves_it_the_same_way_and_says_so(client) -> None:
    _, org_id, user_id = await kullanici(client, "seg3@example.com")
    job_id = await _held_whole(client, org_id, previous="sign_correct")
    async with client._maker() as db:
        out = await held_direction.answer_file(db, org_id, user_id, job_id, "k1", "sign_correct", remember=False)
    assert [p["basis"] for p in out["balance_proof"]] == ["known"]
    async with client._maker() as db:
        (decision,) = (await db.execute(select(Decision).where(Decision.kind == DecisionKind.FILE_DIRECTION_ANSWER.value))).scalars()
    assert decision.after["confirmed_previous"] is True and decision.after["balance_reverifications"]
    assert (await _starting(client, org_id)).starting_cash_cents == 1_000_00


async def test_a_standing_rule_settles_the_next_file_and_its_balance_is_proven_without_a_question(client) -> None:
    _, org_id, user_id = await kullanici(client, "seg4@example.com")
    async with client._maker() as db:
        db.add(DirectionMapping(
            org_id=org_id, signature="sig", header_signature="sig", reason="sign_unconfirmed", answer="sign_correct",
            columns="Tarih, Tutar", created_by=user_id, identity="", standing=True,
        ))
        await db.commit()
    rows = [{**r, "type": None, "direction_file": {
        "key": "k2", "signature": "sig", "header_signature": "sig", "reason": "sign_unconfirmed", "identity": False,
        "account": "", "uniform": False, "read": r["type"], "balance": "expense" if r["type"] == "income" else "income"}}
        for r in _rows()]
    async with client._maker() as db:
        assert await held_direction.apply_remembered(db, org_id, rows) == 7
    assert all(r["direction_remembered"] == "sign_correct" and "direction_file" not in r for r in rows)
    proof = assess(rows, {"balance_check": "unverified", "unaccounted": 0})
    assert proof["basis"] == "known"
    # The same rows with no standing answer would not have passed a reader that could not verify them.
    plain = [{k: v for k, v in r.items() if k != "direction_remembered"} for r in rows]
    assert assess(plain, {"balance_check": "unverified", "unaccounted": 0})["basis"] is None
