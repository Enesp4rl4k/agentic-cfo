"""A statement held for a person is read again when the person answers (PR #120 review, follow-up 1).

The balance chain of a PDF statement held whole for its direction (or with rows that break the chain) is
"unverified" at ingest. The owner's answers in /bekleyen-kayitlar change the rows; the proof must follow,
in the same transaction, with a decision record that links the answers. Figures written by hand:
100,000.00 opening, then four outflows of 10,000.00 (balances 90,000 .. 60,000).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision import Decision, DecisionKind
from app.models.held_transaction import HeldTransaction
from app.services import held_direction, held_rows
from app.services.balance_reverify import snapshot_chain
from app.services.bank_balance import assess
from app.services.cash_radar import compute_cash_radar
from tests.api_helpers import bellek_istemcisi, kullanici

ANCHOR = date(2026, 3, 14)
DATES = ["2026-03-02", "2026-03-05", "2026-03-09", "2026-03-12"]


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _rows(*spec: tuple[str, int, str | None, int | None]) -> list[dict[str, Any]]:
    return [
        {
            "transaction_date": day, "amount_cents": amount, "type": kind, "balance_cents": balance,
            "currency": "TRY", "description": f"satır {i}", "file_pos": i, "confidence": 0.95, "category": "other_expense",
        }
        for i, (day, amount, kind, balance) in enumerate(spec)
    ]


FOUR = [(d, 10_000_00, None, 100_000_00 - 10_000_00 * (i + 1)) for i, d in enumerate(DATES)]


async def _held_statement(
    client, org_id: str, rows: list[dict[str, Any]], *, held: set[int] | None = None, direction_file: bool = False,
) -> tuple[str, dict[int, str]]:
    """A completed statement job whose rows (all, or those in `held`) wait for a person.

    The job's stored proof and chain are what ingest wrote: `assess` over the rows as read, and
    `snapshot_chain`. Returns (job id, {file position: held row id}).
    """
    waiting = set(range(len(rows))) if held is None else held
    held_payloads = [
        {
            **r, "hold_reasons": ["direction_unknown"] if r["type"] is None else ["confidence_low"],
            **({"direction_file": {"key": "k1", "signature": "sig", "reason": "no_signal", "read": None, "balance": None}}
               if direction_file else {}),
        }
        for i, r in enumerate(rows) if i in waiting
    ]
    counts = {"balance_check": "unverified", "unaccounted": 0, "read": len(rows)}
    async with client._maker() as db:
        job = AnalysisJob(
            filename="ekstre.pdf", file_path="/ekstre.pdf", file_type="pdf", org_id=org_id,
            status=JobStatus.COMPLETED,
            result_metadata={
                "ingest": {**counts, "held": len(held_payloads), "processed": len(rows) - len(held_payloads)},
                "balance_proof": assess(rows, counts),
                "statement_chain": snapshot_chain(rows, held_payloads),
            },
        )
        db.add(job)
        await db.flush()
        ids: dict[int, str] = {}
        for payload in held_payloads:
            h = HeldTransaction(job_id=job.id, org_id=org_id, row_key=f"k{payload['file_pos']}", payload=payload)
            db.add(h)
            await db.flush()
            ids[payload["file_pos"]] = h.id
        await db.commit()
        return job.id, ids


async def _radar(client, org_id: str):
    async with client._maker() as db:
        return await compute_cash_radar(db, org_id, anchor_date=ANCHOR)


async def _meta(client, job_id: str) -> dict[str, Any]:
    async with client._maker() as db:
        return dict((await db.get(AnalysisJob, job_id)).result_metadata)


async def _reverifications(client, job_id: str) -> list[Decision]:
    async with client._maker() as db:
        return list((await db.execute(
            select(Decision).where(Decision.kind == DecisionKind.BALANCE_REVERIFICATION.value, Decision.target_id == job_id)
        )).scalars())


async def test_a_statement_held_whole_for_direction_is_unproven_and_the_radar_says_why(client):
    _, org_id, _ = await kullanici(client, "r0@example.com")
    job_id, _ = await _held_statement(client, org_id, _rows(*FOUR))
    radar = await _radar(client, org_id)
    assert radar.opening_cash is None and radar.starting_cash_cents is None
    assert [(u["filename"], u["reason"]) for u in radar.unproven_statements] == [
        ("ekstre.pdf", "bazı satırların yönü (giriş/çıkış) belli değil")
    ]
    assert radar.runway["status"] == "no_balance" and "ekstre.pdf" in radar.runway["message"]
    assert await _reverifications(client, job_id) == []


async def test_answering_every_row_gives_the_radar_its_opening_balance(client):
    _, org_id, user_id = await kullanici(client, "r1@example.com")
    job_id, ids = await _held_statement(client, org_id, _rows(*FOUR))
    fixes = {rid: {"type": "expense"} for rid in ids.values()}
    async with client._maker() as db:
        out = await held_rows.resolve(db, org_id, user_id=user_id, release=True, ids=list(ids.values()), corrections=fixes)
    assert out["resolved"] == 4 and out["still_waiting"] == 0
    assert [(p["state"], p["basis"]) for p in out["balance_proof"]] == [("verified", "known")]

    radar = await _radar(client, org_id)
    assert (radar.starting_cash_cents, radar.starting_cash_as_of) == (60_000_00, "2026-03-12")
    assert radar.opening_cash.basis == "known" and radar.unproven_statements == []

    # The recomputation is a decision record that links the answers which caused it, and the job links back.
    (decision,) = await _reverifications(client, job_id)
    answers = {e["id"] for e in decision.evidence_refs if e["type"] == "decision"}
    async with client._maker() as db:
        row_decisions = {
            d.id for d in (await db.execute(select(Decision).where(Decision.kind == DecisionKind.HELD_ROW_RESOLUTION.value))).scalars()
        }
    assert len(answers) == 4 and answers <= row_decisions
    assert decision.outcome == "verified" and decision.after["closing_cents"] == 60_000_00
    assert (await _meta(client, job_id))["balance_proof"]["decision_id"] == decision.id


async def test_the_same_answers_read_again_change_nothing_and_write_nothing(client):
    from app.services.balance_reverify import reverify

    _, org_id, user_id = await kullanici(client, "r2@example.com")
    job_id, ids = await _held_statement(client, org_id, _rows(*FOUR))
    async with client._maker() as db:
        await held_rows.resolve(db, org_id, user_id=user_id, release=True, ids=list(ids.values()),
                                corrections={rid: {"type": "expense"} for rid in ids.values()})
    before = await _meta(client, job_id)
    async with client._maker() as db:
        assert await reverify(db, org_id, {job_id: ["x"]}) == []
        await db.commit()
    assert await _meta(client, job_id) == before and len(await _reverifications(client, job_id)) == 1


async def test_a_partial_answer_leaves_the_statement_unverified_and_counts_what_waits(client):
    _, org_id, user_id = await kullanici(client, "r3@example.com")
    job_id, ids = await _held_statement(client, org_id, _rows(*FOUR))
    first = ids[0]
    async with client._maker() as db:
        out = await held_rows.resolve(db, org_id, user_id=user_id, release=True, ids=[first], corrections={first: {"type": "expense"}})
    assert out["resolved"] == 1 and out["still_waiting"] == 3
    (proof,) = out["balance_proof"]
    assert proof["state"] == "unverified" and proof["reason"] == "3 satır bekliyor"
    assert (await _radar(client, org_id)).opening_cash is None
    assert (await _meta(client, job_id))["balance_proof"]["waiting"] == 3
    # The rest of the answers complete the proof.
    rest = [rid for pos, rid in ids.items() if pos]
    async with client._maker() as db:
        out = await held_rows.resolve(db, org_id, user_id=user_id, release=True, ids=rest, corrections={r: {"type": "expense"} for r in rest})
    assert [p["state"] for p in out["balance_proof"]] == ["verified"]
    assert (await _radar(client, org_id)).starting_cash_cents == 60_000_00


async def test_rejecting_a_row_the_chain_needed_leaves_it_unverified_with_the_reason(client):
    _, org_id, user_id = await kullanici(client, "r4@example.com")
    job_id, ids = await _held_statement(client, org_id, _rows(*FOUR))
    keep = [rid for pos, rid in ids.items() if pos != 1]
    async with client._maker() as db:
        await held_rows.resolve(db, org_id, user_id=user_id, release=True, ids=keep, corrections={r: {"type": "expense"} for r in keep})
        out = await held_rows.resolve(db, org_id, user_id=user_id, release=False, ids=[ids[1]], note="not mine")
    (proof,) = out["balance_proof"]
    assert proof["state"] == "unverified"
    assert proof["reason"] == "1 satır reddedildi; bakiye zinciri bu satırlar olmadan kapanmıyor"
    radar = await _radar(client, org_id)
    assert radar.opening_cash is None
    assert [u["reason"] for u in radar.unproven_statements] == [proof["reason"]]
    assert (await _meta(client, job_id))["balance_proof"]["rejected"] == 1


async def test_rejecting_a_stray_line_with_no_balance_does_not_unprove_the_statement(client):
    _, org_id, user_id = await kullanici(client, "r5@example.com")
    rows = _rows(*[(d, 10_000_00, "expense", 100_000_00 - 10_000_00 * (i + 1)) for i, d in enumerate(DATES)])
    rows.append({"transaction_date": None, "amount_cents": None, "type": None, "balance_cents": None, "currency": "TRY",
                 "description": "Genel Müdürlük adres satırı", "file_pos": 4})
    job_id, ids = await _held_statement(client, org_id, rows, held={4})
    assert (await _meta(client, job_id))["balance_proof"]["state"] == "unverified"  # a line with no balance: nothing chains
    async with client._maker() as db:
        out = await held_rows.resolve(db, org_id, user_id=user_id, release=False, ids=[ids[4]])
    assert [(p["state"], p["basis"]) for p in out["balance_proof"]] == [("verified", "known")]
    assert (await _radar(client, org_id)).starting_cash_cents == 60_000_00


async def test_a_direction_answer_for_the_file_reaches_the_radar(client):
    _, org_id, user_id = await kullanici(client, "r6@example.com")
    job_id, _ = await _held_statement(client, org_id, _rows(*FOUR), direction_file=True)
    async with client._maker() as db:
        out = await held_direction.answer_file(db, org_id, user_id, job_id, "k1", "only_expense", remember=False)
    assert out["resolved"] == 4 and [p["state"] for p in out["balance_proof"]] == ["verified"]
    assert (await _radar(client, org_id)).starting_cash_cents == 60_000_00
    (decision,) = await _reverifications(client, job_id)
    assert decision.reason is None and decision.decided_via == "system"


async def test_a_wrong_direction_answer_does_not_prove_the_balance(client):
    _, org_id, user_id = await kullanici(client, "r7@example.com")
    job_id, _ = await _held_statement(client, org_id, _rows(*FOUR), direction_file=True)
    async with client._maker() as db:
        out = await held_direction.answer_file(db, org_id, user_id, job_id, "k1", "only_income", remember=False)
    assert [p["state"] for p in out["balance_proof"]] == ["unverified"]
    assert (await _radar(client, org_id)).opening_cash is None


async def test_rejecting_every_waiting_row_of_the_job_in_bulk_is_one_reading(client):
    _, org_id, user_id = await kullanici(client, "r8@example.com")
    job_id, _ = await _held_statement(client, org_id, _rows(*FOUR))
    async with client._maker() as db:
        out = await held_rows.resolve(db, org_id, user_id=user_id, release=False, job_id=job_id)
    assert out["resolved"] == 4 and [p["state"] for p in out["balance_proof"]] == ["unverified"]
    assert len(await _reverifications(client, job_id)) == 1


async def test_a_currency_confirmation_releases_rows_and_reads_the_statement_again(client):
    """The third resolution path: rows held for the currency only; confirming it books them."""
    headers, org_id, _ = await kullanici(client, "r9@example.com")
    spec = [(d, 10_000_00, "expense", 100_000_00 - 10_000_00 * (i + 1)) for i, d in enumerate(DATES)]
    rows = _rows(*spec)
    for r in rows:
        r["currency"] = ""
    job_id, _ = await _held_statement(client, org_id, rows)
    async with client._maker() as db:
        job = await db.get(AnalysisJob, job_id)
        job.result_metadata = {**job.result_metadata, "balance_proof": assess(rows, {"balance_check": "unverified", "unaccounted": 0})}
        for h in (await db.execute(select(HeldTransaction).where(HeldTransaction.job_id == job_id))).scalars():
            h.payload = {**h.payload, "hold_reasons": ["currency_unknown"], "currency": ""}
        await db.commit()
    res = await client.post("/api/v1/org/base-currency", headers=headers, json={"currency": "TRY"})
    assert res.status_code == 200 and res.json()["data"]["released"]["resolved"] == 4
    assert [p["state"] for p in res.json()["data"]["released"]["balance_proof"]] == ["verified"]
    assert (await _radar(client, org_id)).starting_cash_cents == 60_000_00


async def test_one_or_two_balance_steps_are_weak_evidence_kept_as_an_assumption(client):
    _, org_id, user_id = await kullanici(client, "r10@example.com")
    spec = [(DATES[0], 10_000_00, None, 90_000_00), (DATES[1], 5_000_00, None, 85_000_00)]
    _, ids = await _held_statement(client, org_id, _rows(*spec))
    fixes = {rid: {"type": "expense"} for rid in ids.values()}
    async with client._maker() as db:
        out = await held_rows.resolve(db, org_id, user_id=user_id, release=True, ids=list(ids.values()), corrections=fixes)
    (proof,) = out["balance_proof"]
    assert (proof["state"], proof["basis"], proof["reason"]) == ("weak", "assumed", "yalnızca 1 bakiye adımıyla doğrulandı")
    opening = (await _radar(client, org_id)).opening_cash
    assert opening.balance_cents == 85_000_00 and opening.basis == "assumed"
    assert "yalnızca 1 bakiye adımıyla doğrulandı" in opening.basis_note


def test_ingest_keeps_a_held_statements_chain_and_numbers_its_rows():
    """What the later answer reads: every row's place, the proof as read, and the chain's closing balance."""
    from app.agents.data_ingestion import _uncertain_rows_wait
    from app.agents.state import SkillResult

    rows = _rows(*FOUR)
    rows[1]["type"] = rows[2]["type"] = "expense"
    for r in rows:
        r.pop("file_pos")
    result = _uncertain_rows_wait(SkillResult(
        ok=True, patch={"transactions": rows}, confidence=0.9,
    ))
    patch = result.patch
    assert [r["file_pos"] for r in patch["held_transactions"]] == [0, 3]          # the two with no direction wait
    assert [e["held"] for e in patch["statement_chain"]["rows"]] == [True, False, False, True]
    assert patch["balance_proof"]["state"] == "unverified"                        # unproven until they are answered
    assert patch["statement_closing_balance"] == {"date": "2026-03-12", "balance_cents": 60_000_00}


def test_a_direction_remembered_from_an_earlier_answer_is_a_recheck_not_the_readers_old_verdict():
    rows = [{**r, "type": "expense", "direction_remembered": "only_expense"} for r in _rows(*FOUR)]
    assert assess(rows, {"balance_check": "unverified", "unaccounted": 0})["basis"] == "known"
    plain = [{**r, "type": "expense"} for r in _rows(*FOUR)]
    assert assess(plain, {"balance_check": "unverified", "unaccounted": 0})["basis"] is None


async def test_a_rerun_that_reads_the_statement_before_the_answers_is_read_again_with_them(client):
    """A re-run asks nothing twice, but its ingest proof was written before the earlier answers: the worker
    reads it again (`reverify` with no new answers), idempotently."""
    from app.services.balance_reverify import reverify

    _, org_id, user_id = await kullanici(client, "r11@example.com")
    job_id, ids = await _held_statement(client, org_id, _rows(*FOUR))
    async with client._maker() as db:
        await held_rows.resolve(db, org_id, user_id=user_id, release=True, ids=list(ids.values()),
                                corrections={rid: {"type": "expense"} for rid in ids.values()})
    before = await _meta(client, job_id)
    async with client._maker() as db:  # what a re-run's ingest writes: the proof of rows nobody had answered yet
        job = await db.get(AnalysisJob, job_id)
        job.result_metadata = {**before, "balance_proof": assess(_rows(*FOUR), {"balance_check": "unverified", "unaccounted": 0})}
        await db.commit()
    assert (await _radar(client, org_id)).opening_cash is None
    async with client._maker() as db:
        assert [p["state"] for p in await reverify(db, org_id, {job_id: []})] == ["verified"]
        assert await reverify(db, org_id, {job_id: []}) == []
        await db.commit()
    assert (await _radar(client, org_id)).starting_cash_cents == 60_000_00


def test_a_single_row_has_nothing_to_chain_to_and_never_verifies():
    one = _rows(("2026-03-02", 10_000_00, "expense", 90_000_00))
    assert assess(one, {"balance_check": "unverified"}, recheck=True)["basis"] is None
    assert assess(one, None)["basis"] is None


def test_directions_read_off_the_balance_itself_are_not_independent_evidence_of_it():
    rows = [{**r, "type": "expense", "direction_from_balance": True} for r in _rows(
        ("2026-03-02", 10_000_00, None, 90_000_00), ("2026-03-05", 5_000_00, None, 85_000_00))]
    thin = assess(rows, {"balance_check": "unverified", "unaccounted": 0})
    assert thin["basis"] is None and "yalnızca bakiyeden çıkarıldı" in thin["reason"]
    # Once a person has answered the direction, the same rows are weak evidence, not circular.
    assert assess(rows, {"balance_check": "unverified", "unaccounted": 0}, recheck=True)["basis"] == "assumed"


async def test_rejecting_down_to_a_single_row_leaves_the_statement_unproven(client):
    _, org_id, user_id = await kullanici(client, "r12@example.com")
    job_id, ids = await _held_statement(client, org_id, _rows(*FOUR))
    async with client._maker() as db:
        await held_rows.resolve(db, org_id, user_id=user_id, release=True, ids=[ids[0]], corrections={ids[0]: {"type": "expense"}})
        out = await held_rows.resolve(db, org_id, user_id=user_id, release=False, ids=[ids[1], ids[2], ids[3]])
    assert [p["state"] for p in out["balance_proof"]] == ["unverified"]
    assert (await _radar(client, org_id)).opening_cash is None
    assert (await _meta(client, job_id))["balance_proof"]["rejected"] == 3

