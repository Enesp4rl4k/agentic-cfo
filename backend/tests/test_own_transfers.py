"""Transfers between the company's own accounts (PR #128 note): proposed by evidence, counted out only when confirmed.

Figures written by hand: bank A and bank B (two different stated IBANs, so two KNOWN accounts), a 10.000,00
transfer from A to B on 10 February, and ordinary payments around it.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from app.agents.cashflow_agent import _classify_cashflow
from app.models.decision import Decision, DecisionKind
from app.services import materiality
from app.services.company_view import ledger_view
from app.services.own_transfers import propose
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import statement_meta as _stmt
from tests.radar_helpers import upload
from tests.test_payment_plan_changes import member

IBAN_A = "iban:TR330006100519786457841326"
IBAN_B = "iban:TR560006200000000000123456"
ACCOUNTS = [
    {"name": "banka-a.csv", "job_ids": ["ja"], "identity": IBAN_A, "currency": "TRY", "known": True},
    {"name": "banka-b.csv", "job_ids": ["jb"], "identity": IBAN_B, "currency": "TRY", "known": True},
]
DAY = date(2026, 2, 10)


def _row(id_: str, job: str, direction: str, desc: str, *, cents: int = 10_000_00, when: date = DAY, cur: str = "TRY") -> dict[str, Any]:
    return {"id": id_, "job_id": job, "direction": direction, "description": desc, "amount_cents": cents, "date": when, "currency": cur}


OUT = _row("o1", "ja", "expense", "FAST TR560006200000000000123456 kira")
IN = _row("i1", "jb", "income", "Gelen FAST")


# ── the matcher ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_leg_that_names_the_other_accounts_iban_is_proposed() -> None:
    (p,) = propose([OUT, IN], ACCOUNTS)
    assert (p["out_id"], p["in_id"], p["amount_cents"], p["days_apart"]) == ("o1", "i1", 10_000_00, 0)
    assert p["evidence"] == ["counterpart_account"] and p["out"]["account"] == "banka-a.csv" and p["in"]["account"] == "banka-b.csv"


def test_own_account_wording_is_evidence_too_and_the_date_window_is_three_days() -> None:
    out = _row("o1", "ja", "expense", "Hesaplar arası virman")
    inc = _row("i1", "jb", "income", "Virman", when=DAY + timedelta(days=3))
    (p,) = propose([out, inc], ACCOUNTS)
    assert p["evidence"] == ["transfer_wording"] and p["days_apart"] == 3
    assert propose([out, {**inc, "date": DAY + timedelta(days=4)}], ACCOUNTS) == []


def test_the_same_amount_on_two_accounts_with_no_evidence_is_not_a_transfer() -> None:
    assert propose([_row("o1", "ja", "expense", "Tedarikçi ödemesi"), _row("i1", "jb", "income", "Müşteri tahsilatı")], ACCOUNTS) == []


def test_a_description_naming_a_fragment_of_an_account_number_is_no_evidence() -> None:
    assert propose([_row("o1", "ja", "expense", "ref 123456"), IN], ACCOUNTS) == []
    acct = [{**ACCOUNTS[0]}, {**ACCOUNTS[1], "identity": "acct:98765432"}]
    assert propose([_row("o1", "ja", "expense", "no 98765432 aidat"), IN], acct)
    assert propose([_row("o1", "ja", "expense", "no 598765432 aidat"), IN], acct) == []


def test_an_ambiguous_pairing_is_never_proposed() -> None:
    twin = _row("i2", "jb", "income", "Gelen FAST", when=DAY + timedelta(days=1))
    assert propose([OUT, IN, twin], ACCOUNTS) == []                    # two candidate arrivals for one departure
    twin_out = _row("o2", "ja", "expense", "FAST TR560006200000000000123456 kira")
    assert propose([OUT, twin_out, IN], ACCOUNTS) == []                # two departures for one arrival


def test_only_two_known_distinct_accounts_with_one_currency_and_the_exact_amount() -> None:
    assert propose([OUT, {**IN, "job_id": "ja"}], ACCOUNTS) == []      # both legs on the same account
    unsure = [ACCOUNTS[0], {**ACCOUNTS[1], "known": False}]
    assert propose([OUT, IN], unsure) == []                            # an account nothing separates from another
    assert propose([OUT, {**IN, "job_id": "elsewhere"}], ACCOUNTS) == []   # a statement that is no known account
    assert propose([OUT, {**IN, "amount_cents": 10_000_01}], ACCOUNTS) == []
    assert propose([OUT, {**IN, "currency": "USD"}], ACCOUNTS) == []
    assert propose([OUT, {**IN, "direction": "expense"}], ACCOUNTS) == []   # same direction on both: not a transfer


# ── through the real ledger ──────────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _two_banks(client, org_id: str) -> None:
    await upload(
        client, org_id,
        {"transaction_date": "2026-02-10", "amount_cents": 10_000_00, "type": "expense", "description": "FAST TR560006200000000000123456 kira"},
        {"transaction_date": "2026-02-12", "amount_cents": 20_000_00, "type": "expense", "description": "Tedarikçi"},
        filename="banka-a.csv", meta=_stmt("2026-02-01", "2026-02-28", 90_000_00, 60_000_00, identity=IBAN_A),
    )
    await upload(
        client, org_id,
        {"transaction_date": "2026-02-11", "amount_cents": 10_000_00, "type": "income", "description": "Gelen FAST"},
        {"transaction_date": "2026-02-14", "amount_cents": 5_000_00, "type": "income", "description": "Tahsilat"},
        filename="banka-b.csv", meta=_stmt("2026-02-01", "2026-02-28", 20_000_00, 35_000_00, identity=IBAN_B),
    )


async def _proposals(client, headers) -> list[dict[str, Any]]:
    res = await client.get("/api/v1/held-rows/transfer-proposals", headers=headers)
    assert res.status_code == 200
    return list(res.json()["data"]["proposals"])


async def _cash(client, org_id: str):
    async with client._maker() as db:
        view = await ledger_view(db, org_id)
        assert view is not None
        return view.cash


async def test_a_proposal_changes_nothing_until_a_person_confirms_it(client) -> None:
    headers, org_id, _ = await kullanici(client, "tr1@example.com")
    await _two_banks(client, org_id)
    (proposal,) = await _proposals(client, headers)
    assert proposal["amount_cents"] == 10_000_00 and proposal["evidence"] == ["counterpart_account"]
    assert proposal["out"]["account"] == "banka-a.csv" and proposal["in"]["account"] == "banka-b.csv"
    assert len(await _cash(client, org_id)) == 4                       # nothing excluded by merely being proposed
    series = _classify_cashflow(await _cash(client, org_id), "TRY")["monthly_series"]
    assert (series[0]["in"], series[0]["out"]) == (15_000_00, 30_000_00)


async def test_a_confirmed_transfer_leaves_burn_cash_flow_and_the_materiality_basis(client) -> None:
    headers, org_id, _ = await kullanici(client, "tr2@example.com")
    await _two_banks(client, org_id)
    (proposal,) = await _proposals(client, headers)
    before = materiality.monthly_out_series(await _cash(client, org_id))
    res = await client.post("/api/v1/held-rows/transfer-proposals/answer", headers=headers, json={
        "out_id": proposal["out_id"], "in_id": proposal["in_id"], "answer": "confirm", "note": "aynı para"})
    assert res.status_code == 200 and res.json()["data"]["changed"] is True
    cash = await _cash(client, org_id)
    assert sorted(r["amount_cents"] for r in cash) == [5_000_00, 20_000_00]
    after_cashflow = _classify_cashflow(cash, "TRY")["monthly_series"]
    assert (after_cashflow[0]["in"], after_cashflow[0]["out"]) == (5_000_00, 20_000_00)
    # One definition: the materiality basis reads the same rows as the cash-flow step (the runway's series).
    after = materiality.monthly_out_series(cash)
    assert [(m["in"], m["out"]) for m in after] == [(m["in"], m["out"]) for m in after_cashflow]
    assert before[0]["out"] - after[0]["out"] == 10_000_00 and before[0]["in"] - after[0]["in"] == 10_000_00
    assert await _proposals(client, headers) == []                     # answered: not proposed again
    async with client._maker() as db:
        (decision,) = (await db.execute(select(Decision).where(Decision.kind == DecisionKind.OWN_TRANSFER.value))).scalars()
    assert decision.outcome == "confirm" and decision.decided_by and decision.reason == "aynı para"
    assert {e["id"] for e in decision.evidence_refs} == {proposal["out_id"], proposal["in_id"]}


async def test_rejecting_keeps_both_legs_and_a_later_answer_supersedes_the_earlier(client) -> None:
    headers, org_id, _ = await kullanici(client, "tr3@example.com")
    await _two_banks(client, org_id)
    (proposal,) = await _proposals(client, headers)
    body = {"out_id": proposal["out_id"], "in_id": proposal["in_id"]}
    assert (await client.post("/api/v1/held-rows/transfer-proposals/answer", headers=headers, json={**body, "answer": "reject"})).status_code == 200
    assert len(await _cash(client, org_id)) == 4 and await _proposals(client, headers) == []
    assert (await client.post("/api/v1/held-rows/transfer-proposals/answer", headers=headers, json={**body, "answer": "confirm"})).status_code == 200
    assert len(await _cash(client, org_id)) == 2
    again = await client.post("/api/v1/held-rows/transfer-proposals/answer", headers=headers, json={**body, "answer": "confirm"})
    assert again.json()["data"]["changed"] is False
    assert (await client.post("/api/v1/held-rows/transfer-proposals/answer", headers=headers, json={**body, "answer": "reject"})).status_code == 200
    assert len(await _cash(client, org_id)) == 4                       # undone: both legs count again
    async with client._maker() as db:
        chain = list((await db.execute(select(Decision).where(Decision.kind == DecisionKind.OWN_TRANSFER.value))).scalars())
    assert [d.outcome for d in sorted(chain, key=lambda d: d.decided_at)] == ["reject", "confirm", "reject"]


async def test_only_a_proposed_pair_can_be_answered_and_only_by_a_decider_in_the_same_organisation(client) -> None:
    headers, org_id, _ = await kullanici(client, "tr4@example.com")
    await _two_banks(client, org_id)
    (proposal,) = await _proposals(client, headers)
    from app.models.canonical_transaction import CanonicalTransaction

    async with client._maker() as db:
        other_id = (await db.execute(select(CanonicalTransaction.id).where(
            CanonicalTransaction.org_id == org_id, CanonicalTransaction.amount_cents == 20_000_00))).scalar_one()
    arbitrary = await client.post("/api/v1/held-rows/transfer-proposals/answer", headers=headers, json={
        "out_id": other_id, "in_id": proposal["in_id"], "answer": "confirm"})
    assert arbitrary.status_code == 422 and len(await _cash(client, org_id)) == 4   # two rows cannot be excluded by naming them
    body = {"out_id": proposal["out_id"], "in_id": proposal["in_id"], "answer": "confirm"}
    for role in ("viewer", "analyst"):
        h = await member(client, f"{role}@example.com", org_id, role)
        assert (await client.post("/api/v1/held-rows/transfer-proposals/answer", headers=h, json=body)).status_code == 403
        assert (await client.get("/api/v1/held-rows/transfer-proposals", headers=h)).status_code == 200
    stranger, _, _ = await kullanici(client, "tr5@example.com")
    assert (await client.post("/api/v1/held-rows/transfer-proposals/answer", headers=stranger, json=body)).status_code == 422
    assert (await client.post("/api/v1/held-rows/transfer-proposals/answer", headers=headers, json={**body, "answer": "maybe"})).status_code == 422
    assert await _proposals(client, stranger) == []
